"""
Custom Pipecat Transport for SIP PBX RTP Relay.

SIP PBX의 RTP Relay Worker와 Pipecat Pipeline을 연결하는 Transport.
- Input: RTP Relay에서 수신한 caller 오디오 -> Pipecat InputAudioRawFrame
- Output: Pipecat OutputAudioRawFrame -> RTP Relay를 통해 caller에게 전송
"""

import asyncio
import time
from datetime import datetime
from typing import Optional

import structlog

from pipecat.frames.frames import (
    CancelFrame,
    EndFrame,
    Frame,
    InputAudioRawFrame,
    LLMFullResponseEndFrame,
    LLMFullResponseStartFrame,
    OutputAudioRawFrame,
    StartFrame,
    StartInterruptionFrame,
)
# TTS가 내보내는 오디오 프레임(Notifier는 누적하지만 Output이 처리 안 하면 RTP로 누락됨)
try:
    from pipecat.frames.frames import TTSAudioRawFrame
except ImportError:
    TTSAudioRawFrame = type(None)  # 없으면 무시
from pipecat.processors.frame_processor import FrameDirection, FrameProcessor
from pipecat.transports.base_transport import TransportParams

logger = structlog.get_logger(__name__)

# TTS 완료 시 Notifier/Output이 설정하는 키 (Phase1→Phase2 대기·불일치 경고용)
KEY_LAST_TTS_DURATION_SEC = "last_tts_duration_sec"
KEY_LAST_RTP_SENT_SEC = "last_rtp_sent_sec"
TTS_RTP_MISMATCH_THRESHOLD = 0.10  # 10% 이상 차이 시 경고

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
    
    async def process_frame(self, frame: Frame, direction: FrameDirection):
        await super().process_frame(frame, direction)
        
        if isinstance(frame, StartFrame):
            self._running = True
            self._audio_task = asyncio.create_task(self._read_audio_loop())
            await self.push_frame(frame, direction)
        elif isinstance(frame, (EndFrame, CancelFrame)):
            self._running = False
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
                    await self.push_frame(frame)
        except asyncio.CancelledError:
            pass
        except Exception as e:
            logger.error("pipecat_input_transport_error",
                        call_id=self._rtp_worker.media_session.call_id,
                        error=str(e))
        finally:
            logger.info("pipecat_input_transport_stopped",
                       call_id=self._rtp_worker.media_session.call_id)


class SIPPBXOutputTransport(FrameProcessor):
    """
    Pipecat 파이프라인에서 생성된 TTS 오디오를 RTP Relay를 통해 caller에게 전송하는 Output Transport.
    
    OutputAudioRawFrame을 받아 RTP 패킷으로 변환 후 전송.
    """
    
    def __init__(self, rtp_worker, tts_sync_context=None, **kwargs):
        super().__init__(**kwargs)
        self._rtp_worker = rtp_worker
        self._tts_sync_context = tts_sync_context or {}
        self._first_audio_sent = False  # 통화당 첫 오디오 RTP 전송 시점 로그용
        self._response_bytes = 0  # 현재 응답(Phase) 단위 RTP 전송 바이트 (Phase1 잘림 디버깅)

    async def process_frame(self, frame: Frame, direction: FrameDirection):
        await super().process_frame(frame, direction)

        if isinstance(frame, LLMFullResponseStartFrame):
            self._response_bytes = 0
            await self.push_frame(frame, direction)
            return
        if isinstance(frame, LLMFullResponseEndFrame):
            if self._response_bytes > 0:
                duration_sec = self._response_bytes / (PIPECAT_SAMPLE_RATE * 2)
                duration_sec_rounded = round(duration_sec, 3)
                self._tts_sync_context[KEY_LAST_RTP_SENT_SEC] = duration_sec_rounded
                logger.info("tts_rtp_sent_for_response",
                            call_id=self._rtp_worker.media_session.call_id,
                            call=True,
                            progress="tts",
                            category="tts",
                            bytes_sent=self._response_bytes,
                            duration_sec=duration_sec_rounded,
                            ts_iso=datetime.now().isoformat(timespec="milliseconds"),
                            note="해당 응답(Phase)까지 큐에 넣은 PCM 바이트 합 → duration_sec=bytes/(16k*2). 실제 전송은 발송 루프가 20ms 간격 수행")
                # TTSCompleteNotifier가 설정한 재생 길이와 RTP 전송량 불일치 시 경고 (Phase1 잘림 등 디버깅용)
                last_tts_sec = self._tts_sync_context.get(KEY_LAST_TTS_DURATION_SEC)
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
                                       note="Notifier(음원 길이) vs Output(큐에 넣은 양) 불일치. sample_rate 차이 또는 프레임 누락 가능")
            await self.push_frame(frame, direction)
            return

        # 오디오 프레임: OutputAudioRawFrame, TTSAudioRawFrame + .audio 가 bytes 인 모든 프레임 (TTS가 다른 타입으로 내보내도 RTP 전달)
        audio_data = getattr(frame, "audio", None)
        is_audio_frame = (
            isinstance(frame, OutputAudioRawFrame)
            or (TTSAudioRawFrame is not type(None) and isinstance(frame, TTSAudioRawFrame))
            or (isinstance(audio_data, bytes) and len(audio_data) > 0)
        )
        if is_audio_frame and audio_data and isinstance(audio_data, bytes):
            if not self._first_audio_sent:
                logger.info("tts_first_audio_sent_to_rtp",
                            call_id=self._rtp_worker.media_session.call_id,
                            progress="tts",
                            ts_iso=datetime.now().isoformat(timespec="milliseconds"),
                            note="첫 오디오 RTP 전송(재생 시작) 시점")
                self._first_audio_sent = True
            self._response_bytes += len(audio_data)
            try:
                self._rtp_worker.send_audio_to_caller(
                    audio_data,
                    sample_rate=getattr(frame, "sample_rate", None) or PIPECAT_SAMPLE_RATE,
                )
            except Exception as e:
                logger.error("pipecat_output_send_error",
                           call_id=self._rtp_worker.media_session.call_id,
                           error=str(e))
        elif isinstance(frame, StartInterruptionFrame):
            # Barge-in: TTS 중단
            logger.info("pipecat_tts_interrupted",
                       call_id=self._rtp_worker.media_session.call_id)
            await self.push_frame(frame, direction)
        else:
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
