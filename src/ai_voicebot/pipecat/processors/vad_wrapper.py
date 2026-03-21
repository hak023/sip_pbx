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


class VADWrapperProcessor(FrameProcessor):
    """
    VAD 프로세서 래퍼 - 로깅 및 모니터링 추가
    
    Features:
    - 음성 감지 시작/종료 로깅
    - Barge-in (TTS 중단) 이벤트 로깅
    - VAD 상태 추적
    - 디버깅을 위한 상세 타이밍 정보
    """
    
    def __init__(self, vad_processor, call_id: Optional[str] = None, enable_barge_in: bool = True, **kwargs):
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
        
        # VAD 상태 추적
        self._is_speaking = False
        self._speech_start_time: Optional[float] = None
        self._speech_count = 0
        self._silence_count = 0
        
        # 통계
        self._total_speech_duration = 0.0
        self._total_silence_duration = 0.0
        
        logger.info("vad_wrapper_initialized",
                   call_id=self._call_id,
                   enable_barge_in=self._enable_barge_in)

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
                logger.warning("vad_barge_in_start",
                              call_id=self._call_id,
                              progress="vad",
                              category="vad",
                              note="🛑 Barge-in: 사용자가 TTS 중 말을 시작함 → TTS 중단")
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
        
        # 오디오 프레임 카운트 (디버깅용)
        elif isinstance(frame, InputAudioRawFrame):
            # 첫 10개 프레임만 로깅
            if self._speech_count + self._silence_count < 10:
                logger.debug("vad_audio_frame_received",
                            call_id=self._call_id,
                            audio_len=len(getattr(frame, 'audio', b'')),
                            is_speaking=self._is_speaking)
        
        # 프레임 전달
        await self.push_frame(frame, direction)
    
    async def cleanup(self):
        """정리: 내부 VAD cleanup + Pipecat FrameProcessor __input_frame_task_handler 취소 (dangling task 방지)"""
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


def wrap_vad_with_logging(vad_processor, call_id: Optional[str] = None, enable_barge_in: bool = True):
    """
    VAD 프로세서를 로깅 래퍼로 감싸기
    
    Args:
        vad_processor: Pipecat VAD 프로세서 (예: SileroVADAnalyzer)
        call_id: 통화 ID
        enable_barge_in: Barge-in 활성화 여부
    
    Returns:
        VADWrapperProcessor 인스턴스
    """
    if not _PIPECAT_AVAILABLE:
        logger.warning("pipecat_not_available", note="Pipecat 패키지가 없어 VAD 래퍼를 사용할 수 없습니다")
        return vad_processor
    
    wrapper = VADWrapperProcessor(
        vad_processor=vad_processor,
        call_id=call_id,
        enable_barge_in=enable_barge_in
    )
    
    logger.info("vad_wrapped_for_pipecat",
               call_id=call_id or "unknown")
    
    return wrapper
