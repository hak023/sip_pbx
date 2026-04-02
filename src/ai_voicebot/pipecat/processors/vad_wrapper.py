"""
VAD (Voice Activity Detection) Wrapper Processor

Pipecat VAD 프로세서를 래핑하여 상세 로깅 및 모니터링 기능 추가
"""

import asyncio
import time
from typing import Optional

import structlog

try:
    from pipecat.processors.frame_processor import FrameProcessor, FrameDirection, FrameProcessorSetup
    from pipecat.frames.frames import (
        CancelFrame,
        EndFrame,
        Frame,
        InputAudioRawFrame,
        InterruptionFrame,
        InterruptionTaskFrame,
        StartFrame,
        StartInterruptionFrame,
        UserStartedSpeakingFrame,
        UserStoppedSpeakingFrame,
    )
    try:
        from pipecat.frames.frames import StopInterruptionFrame
    except ImportError:
        StopInterruptionFrame = None  # 일부 pipecat 버전에 없음
    _PIPECAT_AVAILABLE = True
except ImportError:
    _PIPECAT_AVAILABLE = False
    FrameProcessor = object
    FrameDirection = object
    Frame = object
    InterruptionFrame = object
    InterruptionTaskFrame = object
    StopInterruptionFrame = None

logger = structlog.get_logger(__name__)

# STT 무응답 감지: 오디오 수신 후 이 시간(초) 동안 UserStartedSpeakingFrame 없으면 경고
_STT_SILENCE_WATCHDOG_SEC = 20.0
# barge-in이 이 횟수 이상 연속 발생하면 경고 (STT 동결 선행 지표)
_CONSECUTIVE_BARGEIN_ALERT_THRESHOLD = 2


class VADWrapperProcessor(FrameProcessor):
    """
    VAD 프로세서 래퍼 - 로깅 및 모니터링 추가

    Features:
    - 음성 감지 시작/종료 로깅
    - Barge-in (TTS 중단) 이벤트 로깅
    - VAD 상태 추적
    - 디버깅을 위한 상세 타이밍 정보
    - STT 무응답 워치독: 오디오가 오는데 일정 시간 STT 이벤트가 없으면 경고
    - 아웃바운드 전용: TTS 재생 중 STT 입력 억제 (에코 방지)
    """

    def __init__(
        self,
        vad_processor,
        call_id: Optional[str] = None,
        enable_barge_in: bool = True,
        suppress_stt_during_tts: bool = False,
        tts_sync_context: Optional[dict] = None,
        **kwargs,
    ):
        """
        Args:
            vad_processor: 래핑할 Pipecat VAD 프로세서
            call_id: 통화 ID (로깅용)
            enable_barge_in: Barge-in 활성화 여부
        """
        super().__init__(**kwargs)
        self._vad = vad_processor
        self._call_id = call_id or "unknown"
        self._enable_barge_in = enable_barge_in

        # 아웃바운드 TTS 재생 중 STT 입력 억제
        self._suppress_stt_during_tts = suppress_stt_during_tts
        self._tts_sync_context: dict = tts_sync_context or {}
        self._stt_suppressed_frame_count: int = 0  # 억제된 프레임 수 (로깅용)

        # VAD 상태 추적
        self._is_speaking = False
        self._speech_start_time: Optional[float] = None
        self._speech_count = 0
        self._silence_count = 0

        # 통계
        self._total_speech_duration = 0.0
        self._total_silence_duration = 0.0

        # STT 무응답 워치독
        self._last_speech_event_time: Optional[float] = None  # 마지막 UserStartedSpeakingFrame 수신 시각
        self._first_audio_time: Optional[float] = None        # 첫 InputAudioRawFrame 수신 시각
        self._audio_frame_count = 0
        self._stt_watchdog_task: Optional[asyncio.Task] = None
        self._stt_watchdog_alerted = False  # 알림 중복 방지

        # barge-in 연속 카운터
        self._consecutive_bargein_count = 0
        self._last_bargein_time: Optional[float] = None

        logger.info("vad_wrapper_initialized",
                    call_id=self._call_id,
                    enable_barge_in=self._enable_barge_in,
                    suppress_stt_during_tts=self._suppress_stt_during_tts)

    async def setup(self, setup: "FrameProcessorSetup"):
        """파이프라인에서 호출되는 setup. 내부 VAD에도 동일 setup 전달해 TaskManager 초기화.
        내부 VAD가 파이프라인 체인에 없어 setup()을 받지 않으면, process_frame 시
        'TaskManager is still not initialized' 에러가 발생함."""
        await super().setup(setup)
        if self._vad is not None and hasattr(self._vad, "setup") and callable(getattr(self._vad, "setup")):
            await self._vad.setup(setup)
            logger.info("vad_wrapper_inner_setup_done",
                        call_id=self._call_id,
                        note="내부 VAD에 TaskManager 등 setup 전달 — TaskManager is still not initialized 방지")
        # STT 무응답 워치독 시작
        self._stt_watchdog_task = asyncio.create_task(self._stt_silence_watchdog())
    
    async def process_frame(self, frame: Frame, direction: FrameDirection):
        """프레임 처리 및 로깅"""
        await super().process_frame(frame, direction)

        # 바지인 끔 시: Interruption* 프레임을 내부 VAD에 넘기면 안 됨 (내부 VAD가 push_frame으로 하류 전달해 TTS가 끊김).
        # 반드시 _vad.process_frame() 호출 전에 차단하고, 하류로도 보내지 않음.
        _interruption_types = (InterruptionFrame, InterruptionTaskFrame, StartInterruptionFrame)
        if StopInterruptionFrame is not None:
            _interruption_types = _interruption_types + (StopInterruptionFrame,)
        if isinstance(frame, _interruption_types):
            if not self._enable_barge_in:
                logger.info("vad_interruption_absorbed",
                            call_id=self._call_id,
                            frame_type=type(frame).__name__,
                            direction=getattr(direction, "name", str(direction)),
                            note="바지인 끔 — Interruption* 하류/내부 VAD로 전달하지 않음 (TTS 끊김 방지)")
                return
            if self._vad:
                await self._vad.process_frame(frame, direction)
            if isinstance(frame, StartInterruptionFrame):
                now = time.perf_counter()
                # 연속 barge-in 카운터 갱신 (2초 이내 재발생이면 연속으로 간주)
                if self._last_bargein_time is not None and (now - self._last_bargein_time) < 2.0:
                    self._consecutive_bargein_count += 1
                else:
                    self._consecutive_bargein_count = 1
                self._last_bargein_time = now
                # 연속 임계치 초과 시 경고 — STT 동결의 선행 지표
                if self._consecutive_bargein_count >= _CONSECUTIVE_BARGEIN_ALERT_THRESHOLD:
                    logger.warning(
                        "vad_consecutive_bargein_alert",
                        call_id=self._call_id,
                        progress="vad",
                        category="vad",
                        consecutive_count=self._consecutive_bargein_count,
                        note=(
                            f"[STT 위험] barge-in {self._consecutive_bargein_count}회 연속 — "
                            "STT 스트림 동결 선행 지표. vad_speech_started 로그 확인 필요"
                        ),
                    )
                else:
                    logger.warning("vad_barge_in_start",
                                   call_id=self._call_id,
                                   progress="vad",
                                   category="vad",
                                   consecutive_count=self._consecutive_bargein_count,
                                   note="🛑 Barge-in: 사용자가 TTS 중 말을 시작함 → TTS 중단")
                # 연속 barge-in 후 STT 워치독 알림 리셋 (새 경보 허용)
                if self._consecutive_bargein_count >= _CONSECUTIVE_BARGEIN_ALERT_THRESHOLD:
                    self._stt_watchdog_alerted = False
            elif StopInterruptionFrame is not None and isinstance(frame, StopInterruptionFrame):
                logger.info("vad_barge_in_stop",
                            call_id=self._call_id,
                            progress="vad",
                            category="vad",
                            note="▶️ Barge-in 종료: TTS 재개 가능")
            await self.push_frame(frame, direction)
            return

        # StartFrame/EndFrame/CancelFrame: 하류(BargeInSuppress 등)에 먼저 전달 후 VAD 호출.
        # 내부 VAD가 OutputTransportMessageUrgentFrame을 먼저 push하면 "StartFrame not received yet" 발생하므로 선행 push.
        if isinstance(frame, (StartFrame, EndFrame, CancelFrame)):
            await self.push_frame(frame, direction)
            if self._vad:
                await self._vad.process_frame(frame, direction)
            return

        # VAD 프로세서로 전달 (Interruption* 제외)
        if self._vad:
            await self._vad.process_frame(frame, direction)

        # 음성 감지 시작
        if isinstance(frame, UserStartedSpeakingFrame):
            self._is_speaking = True
            self._speech_start_time = time.perf_counter()
            self._speech_count += 1
            self._last_speech_event_time = time.monotonic()
            self._stt_watchdog_alerted = False  # 정상 수신: 알림 리셋
            self._consecutive_bargein_count = 0  # 정상 STT 이벤트 → barge-in 연속 카운터 리셋

            logger.info("vad_speech_started",
                        call_id=self._call_id,
                        progress="stt",
                        category="vad",
                        speech_count=self._speech_count,
                        note="👤 사용자 음성 감지 시작")

        # 음성 감지 종료
        elif isinstance(frame, UserStoppedSpeakingFrame):
            if self._is_speaking and self._speech_start_time:
                duration = time.perf_counter() - self._speech_start_time
                self._total_speech_duration += duration

                logger.info("vad_speech_stopped",
                            call_id=self._call_id,
                            progress="stt",
                            category="vad",
                            speech_duration_ms=round(duration * 1000, 1),
                            total_speech_duration_sec=round(self._total_speech_duration, 2),
                            note="👤 사용자 음성 감지 종료 → STT 처리 시작")

            self._is_speaking = False
            self._speech_start_time = None
            self._silence_count += 1

        # 오디오 프레임 수신 — 워치독 기준 시각 갱신
        elif isinstance(frame, InputAudioRawFrame):
            self._audio_frame_count += 1
            now_m = time.monotonic()
            if self._first_audio_time is None:
                self._first_audio_time = now_m

            # ── 아웃바운드 전용: TTS 재생 중 STT 입력 억제 ──
            # tts_playing 플래그가 True이면 InputAudioRawFrame을 STT로 흘려보내지 않는다.
            # VAD에는 이미 위에서 process_frame으로 전달됐으므로 VAD 상태는 유지된다.
            if self._suppress_stt_during_tts and self._tts_sync_context.get("tts_playing"):
                self._stt_suppressed_frame_count += 1
                if self._stt_suppressed_frame_count <= 3 or self._stt_suppressed_frame_count % 100 == 0:
                    logger.debug(
                        "vad_stt_suppressed_tts_playing",
                        call_id=self._call_id,
                        suppressed_count=self._stt_suppressed_frame_count,
                        note="TTS 재생 중 STT 입력 억제 (에코 방지)",
                    )
                return  # STT(하류)로 전달하지 않음

            if self._stt_suppressed_frame_count > 0:
                logger.info(
                    "vad_stt_suppression_ended",
                    call_id=self._call_id,
                    total_suppressed=self._stt_suppressed_frame_count,
                    note="TTS 재생 종료 → STT 입력 재개",
                )
                self._stt_suppressed_frame_count = 0

            # 첫 10개 프레임만 디버그 로깅
            if self._speech_count + self._silence_count < 10:
                logger.debug("vad_audio_frame_received",
                             call_id=self._call_id,
                             audio_len=len(getattr(frame, 'audio', b'')),
                             is_speaking=self._is_speaking)

        # 프레임 전달
        await self.push_frame(frame, direction)
    
    async def _stt_silence_watchdog(self) -> None:
        """STT 무응답 워치독 — 오디오가 수신되는데 일정 시간 UserStartedSpeakingFrame이 없으면 경고.

        체크 주기: _STT_SILENCE_WATCHDOG_SEC / 2 마다 폴링.
        경보 조건:
          - 오디오 프레임이 최소 50개 이상 수신됨 (통화 활성 상태)
          - (마지막 speech 이벤트 또는 첫 오디오) 이후 _STT_SILENCE_WATCHDOG_SEC 초 경과
          - speech_count == 0 이거나 마지막 speech 이벤트로부터 _STT_SILENCE_WATCHDOG_SEC 초 경과
        """
        check_interval = _STT_SILENCE_WATCHDOG_SEC / 2
        try:
            while True:
                await asyncio.sleep(check_interval)
                # 오디오 미수신이면 통화 미활성 — 체크 불필요
                if self._audio_frame_count < 50:
                    continue
                now_m = time.monotonic()
                # 기준 시각: 마지막 speech 이벤트 or 첫 오디오 수신
                baseline = self._last_speech_event_time or self._first_audio_time
                if baseline is None:
                    continue
                elapsed = now_m - baseline
                if elapsed >= _STT_SILENCE_WATCHDOG_SEC and not self._stt_watchdog_alerted:
                    self._stt_watchdog_alerted = True
                    logger.error(
                        "stt_silence_watchdog_alert",
                        call_id=self._call_id,
                        progress="stt",
                        category="stt",
                        elapsed_sec=round(elapsed, 1),
                        speech_count=self._speech_count,
                        audio_frame_count=self._audio_frame_count,
                        consecutive_bargein_before=self._consecutive_bargein_count,
                        note=(
                            f"[STT 동결 의심] {elapsed:.0f}s 동안 UserStartedSpeakingFrame 없음 — "
                            "Pipecat GoogleSTTService 스트리밍 세션이 끊겼거나 barge-in 연속으로 인한 "
                            "파이프라인 상태 불일치 가능성. 서버 재시작 또는 STT 스트림 재연결 필요."
                        ),
                    )
        except asyncio.CancelledError:
            pass

    async def cleanup(self):
        """정리: 내부 VAD cleanup + Pipecat FrameProcessor __input_frame_task_handler 취소 (dangling task 방지)"""
        # STT 워치독 취소
        if self._stt_watchdog_task and not self._stt_watchdog_task.done():
            self._stt_watchdog_task.cancel()
            try:
                await self._stt_watchdog_task
            except asyncio.CancelledError:
                pass
        self._stt_watchdog_task = None

        # Pipecat FrameProcessor의 입력 큐 핸들러 태스크 취소 (BYE 시 __input_frame_task_handler dangling 방지)
        for attr_name in ("_FrameProcessor__input_frame_task_handler", "__input_frame_task_handler"):
            task = getattr(self, attr_name, None)
            if task is not None and isinstance(task, asyncio.Task) and not task.done():
                try:
                    task.cancel()
                    await task
                except asyncio.CancelledError:
                    pass
                except Exception:
                    pass
                break

        logger.info("vad_wrapper_cleanup",
                    call_id=self._call_id,
                    total_speech_count=self._speech_count,
                    total_silence_count=self._silence_count,
                    total_speech_duration_sec=round(self._total_speech_duration, 2),
                    avg_speech_duration_ms=round((self._total_speech_duration / self._speech_count * 1000) if self._speech_count > 0 else 0, 1))

        if self._vad and hasattr(self._vad, 'cleanup'):
            await self._vad.cleanup()


def wrap_vad_with_logging(
    vad_processor,
    call_id: Optional[str] = None,
    enable_barge_in: bool = True,
    suppress_stt_during_tts: bool = False,
    tts_sync_context: Optional[dict] = None,
):
    """
    VAD 프로세서를 로깅 래퍼로 감싸기

    Args:
        vad_processor: Pipecat VAD 프로세서 (예: SileroVADAnalyzer)
        call_id: 통화 ID
        enable_barge_in: Barge-in 활성화 여부
        suppress_stt_during_tts: TTS 재생 중 STT 입력 억제 (아웃바운드 전용)
        tts_sync_context: tts_playing 플래그를 공유하는 컨텍스트 딕셔너리

    Returns:
        VADWrapperProcessor 인스턴스
    """
    if not _PIPECAT_AVAILABLE:
        logger.warning("pipecat_not_available", note="Pipecat 패키지가 없어 VAD 래퍼를 사용할 수 없습니다")
        return vad_processor

    wrapper = VADWrapperProcessor(
        vad_processor=vad_processor,
        call_id=call_id,
        enable_barge_in=enable_barge_in,
        suppress_stt_during_tts=suppress_stt_during_tts,
        tts_sync_context=tts_sync_context,
    )

    logger.info("vad_wrapped_for_pipecat",
               call_id=call_id or "unknown",
               suppress_stt_during_tts=suppress_stt_during_tts)

    return wrapper
