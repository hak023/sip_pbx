"""
Custom Pipecat Transport for SIP PBX RTP Relay.

SIP PBX의 RTP Relay Worker와 Pipecat Pipeline을 연결하는 Transport.
- Input: RTP Relay에서 수신한 caller 오디오 -> Pipecat InputAudioRawFrame
- Output: Pipecat OutputAudioRawFrame -> RTP Relay를 통해 caller에게 전송
"""

import asyncio
import time
from datetime import datetime
from typing import Optional, Tuple

import structlog

from pipecat.frames.frames import (
    CancelFrame,
    EndFrame,
    Frame,
    InputAudioRawFrame,
    LLMFullResponseEndFrame,
    LLMFullResponseStartFrame,
    StartFrame,
)
from src.ai_voicebot.pipecat.interruption_compat import StartInterruptionFrame
# TTS가 내보내는 오디오 프레임 (GoogleTTSService 등이 출력)
try:
    from pipecat.frames.frames import TTSAudioRawFrame
except ImportError:
    TTSAudioRawFrame = type(None)  # 없으면 무시
try:
    from pipecat.frames.frames import OutputAudioRawFrame
except ImportError:
    OutputAudioRawFrame = type(None)  # 없으면 무시
# TTS 입력 텍스트 프레임 (TTS로 전달되는 텍스트 로깅용)
try:
    from pipecat.frames.frames import TextFrame
except ImportError:
    TextFrame = type(None)
from pipecat.processors.frame_processor import FrameDirection, FrameProcessor
from pipecat.transports.base_transport import TransportParams

logger = structlog.get_logger(__name__)

# TTS 완료 시 Notifier/Output이 설정하는 키 (Phase1→Phase2 대기·불일치 경고용)
KEY_LAST_TTS_DURATION_SEC = "last_tts_duration_sec"
KEY_LAST_TTS_FRAME_COUNT = "last_tts_audio_frame_count"  # Notifier가 EndFrame 시 설정 (mismatch 로그 강화)
KEY_LAST_RTP_SENT_SEC = "last_rtp_sent_sec"
# EndFrame이 잔여 오디오보다 먼저 처리되면 Notifier·Output 프레임 수가 달라질 수 있어
# 과도한 오탐을 줄이기 위해 임계값을 소폭 완화 (실제 끊김은 output_bytes·queue_empty와 병행 확인)
TTS_RTP_MISMATCH_THRESHOLD = 0.18  # 18% 이상 차이 시 경고

# ========== 변수 정의 (로그·동기화 해석용) ==========
# - last_tts_duration_sec (Notifier): 해당 응답(Start~End) 구간에서 TTS가 내보낸 모든 오디오 프레임의
#   재생 길이 합(초). 각 프레임은 len(audio)/(sample_rate*2*channels). "이 응답이 몇 초짜리 음원인가".
# - last_rtp_sent_sec / bytes_sent (Output): 해당 응답 구간에서 send_audio_to_caller()로
#   **발송 큐에 넣은** PCM 바이트 합 → duration_sec = bytes / (16000*2). 실제 전송은
#   _pipecat_outgoing_sender_loop가 20ms 간격으로 수행하므로, 로그 시점에는 아직 일부가 큐에 남아 있을 수 있음.
# - tts_rtp_duration_mismatch: Notifier 누적(음원 길이) vs Output 누적(큐에 넣은 양) 불일치.
#   동일 프레임을 두 프로세서가 보므로 이론상 일치. sample_rate 불일치 시 차이 발생 가능.

# Pipecat 내부 오디오 포맷: 16kHz 16-bit mono PCM
PIPECAT_SAMPLE_RATE = 16000
PIPECAT_NUM_CHANNELS = 1


def infer_tts_rtp_stream_label(text: str) -> Optional[Tuple[str, str]]:
    """
    TTS TextFrame → RTP 추적용 stream_label.
    인사(기상청 AI 비서)·LLM 대기 안내 등 끊김 재현 시 app.log 에서 상관.
    """
    t = (text or "").strip()
    if not t:
        return None
    if "정보를 확인 중" in t:
        return ("llm_wait_notify", t[:220])
    if "잠시만 기다려" in t:
        return ("llm_wait_notify_follow", t[:220])
    if "기상청" in t and ("비서" in t or "AI 통화" in t):
        return ("greeting_kma_opening", t[:220])
    if (
        "어떤 도움" in t
        or "도움이 필요하실까요" in t
        or "무엇을 도와" in t
        or "어떤 도움이 필요" in t
    ):
        return ("greeting_capability_prompt", t[:220])
    return None


class SIPPBXInputTransport(FrameProcessor):
    """
    RTP Relay Worker에서 수신한 caller 오디오를 Pipecat 파이프라인에 주입하는 Input Transport.
    
    RTP Relay의 async audio queue에서 PCM 16kHz 오디오를 읽어
    InputAudioRawFrame으로 변환하여 파이프라인에 push.
    """
    
    def __init__(self, rtp_worker, **kwargs):
        super().__init__(**kwargs)
        self._rtp_worker = rtp_worker
        self._running = False
        self._audio_task: Optional[asyncio.Task] = None
        self._fallback_task: Optional[asyncio.Task] = None
        self._fallback_scheduled = False
        self._first_frame_logged = False
    
    def _start_audio_loop_if_needed(self):
        """Start _read_audio_loop if not already running (idempotent)."""
        if self._audio_task is not None and not self._audio_task.done():
            return
        self._running = True
        self._audio_task = asyncio.create_task(self._read_audio_loop())
        logger.info("input_audio_loop_task_created",
                    call_id=getattr(self._rtp_worker.media_session, "call_id", None),
                    note="_read_audio_loop() 태스크 생성 — get_caller_audio_stream() 소비 시작 예상")

    async def _delayed_start_audio_loop(self, delay: float = 0.05):
        """StartFrame이 하류(BargeInSuppress 등)에 먼저 전달된 뒤 오디오 루프 시작."""
        await asyncio.sleep(delay)
        self._start_audio_loop_if_needed()
    
    def ensure_audio_loop_started(self):
        """외부에서 호출: StartFrame 미수신 시에도 큐 소비를 시작 (STT 백업 방지)."""
        call_id = getattr(self._rtp_worker.media_session, "call_id", None)
        logger.info("input_ensure_audio_loop_called",
                    call_id=call_id,
                    already_running=self._audio_task is not None and not self._audio_task.done(),
                    note="외부 폴백에서 ensure_audio_loop_started() 호출됨")
        self._start_audio_loop_if_needed()
    
    async def _fallback_start_after_delay(self, delay: float = 2.0):
        """Start audio loop after delay if StartFrame was never received (STT queue backup 방지)."""
        try:
            await asyncio.sleep(delay)
        except asyncio.CancelledError:
            return
        if self._audio_task is not None and not self._audio_task.done():
            return
        if self._running:
            return
        logger.warning("pipecat_input_transport_start_fallback",
                      call_id=self._rtp_worker.media_session.call_id,
                      note="StartFrame 미수신 — 폴백으로 오디오 루프 시작 (큐 소비)")
        self._start_audio_loop_if_needed()
    
    async def process_frame(self, frame: Frame, direction: FrameDirection):
        await super().process_frame(frame, direction)
        # 디버깅: 파이프라인에서 Input에 도달하는 첫 프레임 로그 (StartFrame 수신 여부 확인)
        if not self._first_frame_logged:
            self._first_frame_logged = True
            logger.info("input_transport_first_frame",
                        call_id=getattr(self._rtp_worker.media_session, "call_id", None),
                        frame_type=type(frame).__name__,
                        is_start_frame=isinstance(frame, StartFrame),
                        note="[STT 경로] Input Transport에 도달한 첫 프레임 — StartFrame이면 즉시 큐 소비 시작")
        # StartFrame 미수신 시 큐 백업 방지: 첫 프레임 수신 시 폴백 타이머 예약
        if not self._fallback_scheduled:
            self._fallback_scheduled = True
            self._fallback_task = asyncio.create_task(self._fallback_start_after_delay(2.0))

        if isinstance(frame, StartFrame):
            logger.info("input_transport_startframe_received",
                        call_id=getattr(self._rtp_worker.media_session, "call_id", None),
                        note="StartFrame 수신 — 먼저 push 후 오디오 루프 지연 시작 (StartFrame 선행 전달)")
            if self._fallback_task and not self._fallback_task.done():
                self._fallback_task.cancel()
                try:
                    await self._fallback_task
                except asyncio.CancelledError:
                    pass
            self._fallback_task = None
            await self.push_frame(frame, direction)
            asyncio.create_task(self._delayed_start_audio_loop(0.05))
        elif isinstance(frame, (EndFrame, CancelFrame)):
            self._running = False
            if self._fallback_task and not self._fallback_task.done():
                self._fallback_task.cancel()
                try:
                    await self._fallback_task
                except asyncio.CancelledError:
                    pass
            if self._audio_task:
                self._audio_task.cancel()
                try:
                    await self._audio_task
                except asyncio.CancelledError:
                    pass
            await self.push_frame(frame, direction)
        else:
            await self.push_frame(frame, direction)
    
    async def _read_audio_loop(self):
        """RTP Worker의 audio stream에서 PCM 오디오를 읽어 프레임으로 push"""
        logger.info("pipecat_input_transport_started",
                    call_id=self._rtp_worker.media_session.call_id)
        
        frame_count = 0
        try:
            async for pcm_data in self._rtp_worker.get_caller_audio_stream():
                if not self._running:
                    break
                
                if pcm_data:
                    frame = InputAudioRawFrame(
                        audio=pcm_data,
                        sample_rate=PIPECAT_SAMPLE_RATE,
                        num_channels=PIPECAT_NUM_CHANNELS,
                    )
                    frame_count += 1
                    
                    # STT 경로 디버깅: 첫 프레임 시 한 번 (테스트 후 동작 여부 점검용)
                    if frame_count == 1:
                        logger.debug("stt_path_input_first",
                                    call_id=self._rtp_worker.media_session.call_id,
                                    note="[STT 경로] Input → 파이프라인 첫 프레임 (큐 소비 시작)")
                    # STT 디버깅: 첫 10개 프레임과 100개마다 로깅
                    if frame_count <= 10 or frame_count % 100 == 0:
                        logger.debug("input_audio_frame_to_pipeline",
                                    call_id=self._rtp_worker.media_session.call_id,
                                    frame_count=frame_count,
                                    audio_len=len(pcm_data),
                                    note="Input Transport → Pipeline (VAD → STT)")
                    if frame_count > 0 and frame_count % 200 == 0:
                        logger.debug("stt_path_input_to_pipeline",
                                    call_id=self._rtp_worker.media_session.call_id,
                                    frame_count=frame_count,
                                    note="[STT 경로] Input Transport → 파이프라인(VAD→STT) 누적")
                    await self.push_frame(frame)
        except asyncio.CancelledError:
            pass
        except Exception as e:
            logger.error("pipecat_input_transport_error",
                        call_id=self._rtp_worker.media_session.call_id,
                        error=str(e))
        finally:
            try:
                logger.info("pipecat_input_transport_stopped",
                           call_id=self._rtp_worker.media_session.call_id)
                logger.info("stt_path_input_total",
                           call_id=self._rtp_worker.media_session.call_id,
                           total_frames=frame_count,
                           note="[STT 경로] Input Transport 종료 시까지 파이프라인에 넣은 총 프레임 수")
            except (ValueError, OSError):
                pass  # 로그 파일이 이미 닫힌 상태(서버 종료 시)에서 발생 가능


class SIPPBXOutputTransport(FrameProcessor):
    """
    Pipecat 파이프라인에서 생성된 TTS 오디오를 RTP Relay를 통해 caller에게 전송하는 Output Transport.
    
    OutputAudioRawFrame을 받아 RTP 패킷으로 변환 후 전송.
    """
    
    def __init__(self, rtp_worker, tts_sync_context=None, **kwargs):
        super().__init__(**kwargs)
        self._rtp_worker = rtp_worker
        self._tts_sync_context = tts_sync_context or {}
        self._first_audio_sent = False  # 응답마다 첫 오디오 RTP 전송 시점 로그용
        self._session_has_sent_audio = False  # 통화에서 한 번이라도 오디오 전송했으면 True (Phase1 flush 방지)
        self._first_response_endframe_logged = True  # Phase1(첫 응답) EndFrame 시 phase1_rtp_summary 1회 로깅용
        self._response_bytes = 0  # 현재 응답(Phase) 단위 RTP 전송 바이트 (Phase1 잘림 디버깅)
        self._response_duration_sec = 0.0  # 프레임 sample_rate 기준 누적 재생 길이(초) — Notifier와 일치용
        # PCM 큐 참조를 tts_sync_context에 등록: rag_processor에서 실시간 큐 잔량 확인 가능
        # rtp_worker._pipecat_pcm_queue는 enable_pipecat_mode() 이후에 생성되므로 지연 조회
        self._tts_sync_context["_rtp_worker_ref"] = rtp_worker

    async def process_frame(self, frame: Frame, direction: FrameDirection):
        await super().process_frame(frame, direction)

        # TTS 입력 텍스트 로깅 (전체 길이·60자 청크 — 로그 필드 잘림 시에도 추적 가능)
        if TextFrame is not type(None) and isinstance(frame, TextFrame):
            text_content = getattr(frame, "text", None)
            if text_content:
                _t = text_content
                _chunks = [_t[i : i + 60] for i in range(0, min(len(_t), 300), 60)]  # 앞 300자만 청크
                logger.info("tts_text_input",
                            call_id=self._rtp_worker.media_session.call_id,
                            progress="tts",
                            category="tts",
                            direction=str(direction),
                            text_len=len(text_content),
                            text_chunk_0=_chunks[0] if _chunks else "",
                            text_chunk_1=_chunks[1] if len(_chunks) > 1 else "",
                            text_chunk_2=_chunks[2] if len(_chunks) > 2 else "",
                            text_suffix_60=_t[-60:] if len(_t) > 60 else _t,
                            note="TTS로 전달된 텍스트. text_len·text_chunk_*·text_suffix_60 로 잘림 확인")
                _pair = infer_tts_rtp_stream_label(text_content)
                self._rtp_worker.clear_tts_rtp_stream_context()
                if _pair:
                    self._rtp_worker.set_tts_rtp_stream_context(_pair[0], _pair[1])
                    logger.info(
                        "tts_rtp_stream_context_set",
                        call_id=self._rtp_worker.media_session.call_id,
                        progress="rtp_tts_trace",
                        tts_stream_label=_pair[0],
                        tts_stream_text_preview=_pair[1][:120],
                        note="이후 tts_rtp_trace_pcm_enqueued / tts_rtp_trace_udp_sent 로 RTP 송신 상관",
                    )

        if isinstance(frame, LLMFullResponseStartFrame):
            self._response_bytes = 0
            self._response_duration_sec = 0.0
            self._response_audio_frame_count = 0  # 인사말 중간 끊김 추적: 이 응답에서 받은 오디오 프레임 수
            self._first_audio_sent = False  # 응답마다 로그 남기기 위해 리셋
            # (flush 비활성화) 새 TTS 시작 시에도 PCM 큐를 비우지 않음 — 준비된 내용을 순차 재생.
            # _greeting_phase2_no_flush 등은 사용하지 않음. 필요 시 나중에 flush 기능 재도입.
            self._tts_sync_context.pop("_greeting_phase2_no_flush", None)
            # ✅ TTS 활성 플래그 설정 (STT 처리 중 TTS 상태 확인용)
            self._tts_sync_context["_tts_active"] = True
            self._tts_sync_context["_tts_pending_pcm_bytes"] = 0
            await self.push_frame(frame, direction)
            return
        if isinstance(frame, LLMFullResponseEndFrame):
            # EndFrame 수신 시점의 큐 적재량 (원인 파악: Notifier와 순서 비교용)
            call_id = getattr(self._rtp_worker.media_session, "call_id", "")
            # ✅ TTS 활성 플래그 해제
            self._tts_sync_context["_tts_active"] = False
            self._tts_sync_context["_tts_pending_pcm_bytes"] = 0
            response_frames = getattr(self, "_response_audio_frame_count", 0)
            # ✅ 송신 스레드 패킷 수 조회 (응답별 추적용)
            thread_packets_queued = self._rtp_worker.stats.get("rtp_tts_thread_packets_queued", 0)
            logger.info("output_endframe_processed",
                        call=True,
                        call_id=call_id,
                        category="tts",
                        progress="tts",
                        response_bytes=self._response_bytes,
                        response_audio_frame_count=response_frames,
                        thread_packets_queued=thread_packets_queued,
                        ts_iso=datetime.now().isoformat(timespec="milliseconds"),
                        note="Output이 EndFrame 수신 — 이 응답에서 큐에 넣은 PCM 바이트·프레임 수. thread_packets_queued로 송신 완료 여부 추적")
            if self._response_bytes > 0:
                # Notifier와 동일한 기준: 프레임별 sample_rate로 누적한 재생 길이 사용 (일치 시 mismatch 경고 감소)
                duration_sec_rounded = round(self._response_duration_sec, 3)
                if duration_sec_rounded <= 0:
                    duration_sec_rounded = round(
                        self._response_bytes / (PIPECAT_SAMPLE_RATE * 2), 3
                    )
                self._tts_sync_context[KEY_LAST_RTP_SENT_SEC] = duration_sec_rounded
                # Phase1(첫 응답) 검증: 2문장 인사말이 한 TextFrame으로 순차 전송됨. 3초 기준 기대 바이트 ≈ 96000 (16kHz*2)
                is_first_response = getattr(self, "_first_response_endframe_logged", True) is True
                if is_first_response:
                    self._first_response_endframe_logged = False
                    expected_bytes_3s = PIPECAT_SAMPLE_RATE * 2 * 3  # 16kHz 16bit 3초
                    logger.info("phase1_rtp_summary",
                                call_id=call_id,
                                call=True,
                                progress="tts",
                                category="tts",
                                response_bytes=self._response_bytes,
                                duration_sec=duration_sec_rounded,
                                expected_bytes_3s=expected_bytes_3s,
                                note="Phase1(첫 응답) RTP 큐 투입량. 2문장 인사말 1개 TextFrame 순차 재생. 3초면 약 96000바이트 기대")
                logger.info("tts_rtp_sent_for_response",
                            call_id=call_id,
                            call=True,
                            progress="tts",
                            category="tts",
                            bytes_sent=self._response_bytes,
                            duration_sec=duration_sec_rounded,
                            ts_iso=datetime.now().isoformat(timespec="milliseconds"),
                            note="해당 응답(Phase)까지 큐에 넣은 PCM 바이트 합. duration_sec=프레임 sample_rate 기준 누적(Notifier와 동일 기준)")
                # TTSCompleteNotifier가 설정한 재생 길이와 RTP 전송량 불일치 시 경고 (Phase1 잘림 등 디버깅용)
                last_tts_sec = self._tts_sync_context.get(KEY_LAST_TTS_DURATION_SEC)
                last_tts_frames = self._tts_sync_context.get(KEY_LAST_TTS_FRAME_COUNT)
                if last_tts_sec is not None and last_tts_sec > 0:
                    diff_ratio = abs(duration_sec_rounded - last_tts_sec) / last_tts_sec
                    if diff_ratio >= TTS_RTP_MISMATCH_THRESHOLD:
                        logger.warning("tts_rtp_duration_mismatch",
                                       call_id=self._rtp_worker.media_session.call_id,
                                       call=True,
                                       progress="tts",
                                       category="tts",
                                       tts_duration_sec=round(last_tts_sec, 3),
                                       rtp_sent_duration_sec=duration_sec_rounded,
                                       diff_ratio_pct=round(diff_ratio * 100, 1),
                                       notifier_audio_frame_count=last_tts_frames,
                                       output_audio_frame_count=response_frames,
                                       response_bytes=self._response_bytes,
                                       note="Notifier vs Output 불일치. EndFrame·파이프라인 순서로 일부 오디오가 EndFrame 이후에 도착하면 프레임 수만 달라질 수 있음. 바지인 시 더 벌어짐.",
                                       frame_count_gap=(last_tts_frames or 0) - (response_frames or 0))
            await self.push_frame(frame, direction)
            return

        # 오디오 프레임: 모든 오디오 프레임 처리 (InputAudioRawFrame 제외!)
        # InputAudioRawFrame은 caller 음성이므로 다시 caller에게 보내면 안됨 (에코 발생)
        audio_data = getattr(frame, "audio", None)
        
        # ✅ InputAudioRawFrame(발신자 음성)은 제외 → 에코 방지
        is_caller_audio = isinstance(frame, InputAudioRawFrame)
        
        # ✅ 모든 오디오 프레임 수신 로깅 (조건문 진입 전, 유실 추적용)
        if audio_data and isinstance(audio_data, bytes):
            if not hasattr(self, "_output_all_audio_frames_count"):
                self._output_all_audio_frames_count = 0
            self._output_all_audio_frames_count += 1
            logger.debug("output_audio_frame_received",
                        call_id=self._rtp_worker.media_session.call_id,
                        progress="tts",
                        frame_index=self._output_all_audio_frames_count,
                        frame_type=type(frame).__name__,
                        audio_len=len(audio_data),
                        is_caller_audio=is_caller_audio,
                        note="Output이 받은 오디오 프레임 (caller 음성 포함, 유실 추적용)")
        
        # ✅ Notifier와 동일 로직: audio 속성이 있는 모든 프레임 카운트 (InputAudioRawFrame 제외)
        # Google TTS는 TTSAudioRawFrame 외에도 다른 오디오 프레임 타입을 생성할 수 있음
        if not is_caller_audio and audio_data and isinstance(audio_data, bytes):
            self._response_audio_frame_count = getattr(self, "_response_audio_frame_count", 0) + 1
            fc = self._response_audio_frame_count
            
            # ✅ sample_rate를 조건문 밖에서 먼저 정의 (라인 428, 439, 445에서 사용)
            sr = getattr(frame, "sample_rate", None) or PIPECAT_SAMPLE_RATE
            
            # 📌 프레임 타입·길이 추적 (Notifier vs Output 불일치 원인 파악)
            if fc <= 5 or fc % 10 == 0:
                logger.debug("output_audio_frame_detail",
                            call_id=self._rtp_worker.media_session.call_id,
                            frame_index=fc,
                            frame_type=type(frame).__name__,
                            audio_len=len(audio_data),
                            duration_ms=round(len(audio_data) / (sr * 2) * 1000, 2),
                            sample_rate=sr,
                            note="Output 프레임 타입·길이 추적 (Notifier 불일치 원인 파악)")
            
            if not self._first_audio_sent:
                logger.info("tts_first_audio_sent_to_rtp",
                            call_id=self._rtp_worker.media_session.call_id,
                            progress="tts",
                            category="tts",
                            frame_type=type(frame).__name__,
                            audio_len=len(audio_data),
                            ts_iso=datetime.now().isoformat(timespec="milliseconds"),
                            note="이 응답의 첫 오디오 RTP 전송 시점 (응답마다 로깅)")
                self._first_audio_sent = True
                try:
                    from src.common.ai_response_latency_compare import mark_first_audio_and_compare

                    mark_first_audio_and_compare(
                        self._tts_sync_context,
                        call_id=self._rtp_worker.media_session.call_id,
                    )
                except Exception:
                    pass
            if not self._session_has_sent_audio:
                self._session_has_sent_audio = True
            self._response_bytes += len(audio_data)
            
            # 📌 TTS 오디오 청크 상세 로깅 (모든 프레임, 끊김 원인 파악용)
            logger.debug("tts_audio_frame_to_rtp",
                        call_id=self._rtp_worker.media_session.call_id,
                        progress="tts",
                        category="tts",
                        frame_index=fc,
                        frame_type=type(frame).__name__,
                        audio_len=len(audio_data),
                        response_bytes_cumulative=self._response_bytes,
                        sample_rate=sr,
                        note="TTS→RTP 오디오 프레임 (디버그: 끊김 시 누락 프레임 확인)")
            
            # 주요 체크포인트는 info로 기록
            if fc in (10, 30, 50) or (fc > 0 and fc % 20 == 0):
                logger.debug("tts_response_audio_chunk",
                            call_id=self._rtp_worker.media_session.call_id,
                            frame_index=fc,
                            response_bytes_so_far=self._response_bytes,
                            note="응답 내 오디오 청크 누적 — 중간 끊김 시 이 로그가 중간에 멈춤")
            # Notifier와 동일한 재생 길이 계산: bytes / (sample_rate * 2) — mismatch 경고 완화
            self._response_duration_sec += len(audio_data) / (sr * 2)
            # ✅ TTS PCM 송출 바이트 추적 (STT 처리 중 TTS 상태 확인용)
            self._tts_sync_context["_tts_pending_pcm_bytes"] = self._response_bytes
            
            # ✅ PCM 큐 투입 직전 로그 (244ms 갭 원인 추적)
            if not self._first_audio_sent:
                logger.info("output_transport_pcm_queuing_attempt",
                           call_id=self._rtp_worker.media_session.call_id,
                           progress="tts",
                           audio_len=len(audio_data),
                           ts_iso=datetime.now().isoformat(timespec="milliseconds"),
                           note="Output Transport가 PCM 큐에 넣기 직전 (send_audio_to_caller 호출 전)")
            
            # ✅ 모든 send_audio_to_caller() 호출 로깅 (유실 추적용)
            logger.debug("output_sending_audio_to_caller",
                        call_id=self._rtp_worker.media_session.call_id,
                        progress="tts",
                        frame_index=fc,
                        audio_len=len(audio_data),
                        response_bytes_cumulative=self._response_bytes,
                        note="Output → send_audio_to_caller() 호출 (PCM 큐 투입)")
            
            try:
                self._rtp_worker.send_audio_to_caller(
                    audio_data,
                    sample_rate=sr,
                )
            except Exception as e:
                logger.error("pipecat_output_send_error",
                           call_id=self._rtp_worker.media_session.call_id,
                           error=str(e))
        # InputAudioRawFrame(발신자 음성)은 에코 방지를 위해 의도적으로 RTP로 보내지 않음
        elif is_caller_audio:
            pass  # 정상: caller 음성을 caller에게 다시 보내지 않음
        
        # Interruption 계열은 TTS까지 도달해 "Barge-in detected, stopping TTS"를 유발함.
        # 파이프라인 중간 BargeInSuppressProcessor로 막아도, Task 경로 등으로 올 수 있으므로
        # Output에서 한 번 더 흡수하여 RTP/하류로 전달하지 않음.
        if isinstance(frame, StartInterruptionFrame):
            logger.info("output_interruption_frame_absorbed",
                       call_id=self._rtp_worker.media_session.call_id,
                       frame_type="StartInterruptionFrame",
                       note="바지인 차단 (Output 흡수) — 이미 TTS를 통과한 뒤이므로 TTS는 이미 반응했을 수 있음")
            logger.debug("pipecat_interruption_frame_reached_output",
                         call_id=self._rtp_worker.media_session.call_id,
                         frame_type="StartInterruptionFrame",
                         note="Pipecat 경로: Interruption* 가 BargeInSuppress를 거치지 않고 Output까지 도달")
            return
        try:
            from pipecat.frames.frames import InterruptionFrame, InterruptionTaskFrame
            try:
                from pipecat.frames.frames import StopInterruptionFrame
            except ImportError:
                StopInterruptionFrame = None
            _out_interruption_types = (InterruptionFrame, InterruptionTaskFrame)
            if StopInterruptionFrame is not None:
                _out_interruption_types = _out_interruption_types + (StopInterruptionFrame,)
            if isinstance(frame, _out_interruption_types):
                logger.info("output_interruption_frame_absorbed",
                           call_id=self._rtp_worker.media_session.call_id,
                           frame_type=type(frame).__name__,
                           note="바지인 차단 (Output 흡수) — 이미 TTS 통과 후이면 TTS가 Barge-in detected 했을 수 있음")
                logger.debug("pipecat_interruption_frame_reached_output",
                             call_id=self._rtp_worker.media_session.call_id,
                             frame_type=type(frame).__name__,
                             note="Pipecat 경로: Interruption* 가 BargeInSuppress를 거치지 않고 Output까지 도달")
                return
        except ImportError:
            pass
        await self.push_frame(frame, direction)


class SIPPBXTransport:
    """
    SIP PBX RTP Relay Worker와 Pipecat Pipeline을 연결하는 Transport.
    
    Usage:
        transport = SIPPBXTransport(rtp_worker)
        pipeline = Pipeline([
            transport.input(),
            vad,
            stt,
            ...
            tts,
            transport.output(),
        ])
    """
    
    def __init__(self, rtp_worker, params: Optional[TransportParams] = None, tts_sync_context: Optional[dict] = None):
        self._rtp_worker = rtp_worker
        self._params = params or TransportParams()
        self._tts_sync_context = tts_sync_context or {}
        self._input_transport = SIPPBXInputTransport(
            rtp_worker, name="SIPPBXInput"
        )
        self._output_transport = SIPPBXOutputTransport(
            rtp_worker, tts_sync_context=self._tts_sync_context, name="SIPPBXOutput"
        )
    
    def input(self) -> FrameProcessor:
        """Input transport (RTP -> Pipecat)"""
        return self._input_transport
    
    def output(self) -> FrameProcessor:
        """Output transport (Pipecat -> RTP)"""
        return self._output_transport
