"""
Google TTS Service Wrapper for detailed logging.

TextFrame 입력 및 OutputAudioRawFrame 출력을 상세히 로깅하여
TTS 엔진 내부에서 오디오 생성이 중단되거나 지연되는 원인을 파악한다.
"""

import structlog
from datetime import datetime
from pipecat.frames.frames import Frame, TextFrame
from pipecat.processors.frame_processor import FrameDirection, FrameProcessor

logger = structlog.get_logger(__name__)

try:
    from pipecat.frames.frames import OutputAudioRawFrame
except ImportError:
    try:
        from pipecat.frames.frames import TTSAudioRawFrame as OutputAudioRawFrame
    except ImportError:
        OutputAudioRawFrame = None


class TTSDebugWrapper(FrameProcessor):
    """
    Google TTS Service를 감싸서 입출력을 로깅.
    
    Pipeline: korean_tts_numbers → [TTSDebugWrapper → GoogleTTS] → tts_complete_notifier
    """
    
    def __init__(self, tts_service: FrameProcessor, call_id: str = "", **kwargs):
        super().__init__(**kwargs)
        self._tts = tts_service
        self._call_id = call_id
        self._text_frame_count = 0
        self._audio_frame_count = 0
        self._last_text_time = 0.0
        self._last_audio_time = 0.0
        self._tts_start_time = 0.0
    
    async def process_frame(self, frame: Frame, direction: FrameDirection):
        await super().process_frame(frame, direction)
        
        # Downstream (RAG → TTS): TextFrame 입력 추적
        if isinstance(frame, TextFrame) and direction == FrameDirection.DOWNSTREAM:
            self._text_frame_count += 1
            now = datetime.now()
            
            if self._text_frame_count == 1:
                self._tts_start_time = now.timestamp()
            
            interval_ms = 0.0
            if self._last_text_time > 0:
                interval_ms = (now.timestamp() - self._last_text_time) * 1000
            
            self._last_text_time = now.timestamp()
            
            logger.info("tts_wrapper_text_input",
                       call_id=self._call_id,
                       progress="tts",
                       category="tts",
                       text_frame_num=self._text_frame_count,
                       text_len=len(frame.text or ""),
                       text_preview=(frame.text or "")[:100],
                       interval_ms=round(interval_ms, 2) if interval_ms > 0 else None,
                       ts_iso=now.isoformat(timespec="milliseconds"),
                       note="TextFrame → Google TTS 입력")
        
        # 모든 프레임을 TTS Service로 전달 (downstream)
        if direction == FrameDirection.DOWNSTREAM:
            await self._tts.process_frame(frame, direction)
            return
        
        # Upstream (TTS → Output): 오디오 출력 추적
        if OutputAudioRawFrame and isinstance(frame, OutputAudioRawFrame) and direction == FrameDirection.UPSTREAM:
            self._audio_frame_count += 1
            now = datetime.now()
            
            audio_data = getattr(frame, "audio", None)
            audio_len = len(audio_data) if audio_data and isinstance(audio_data, bytes) else 0
            
            interval_ms = 0.0
            if self._last_audio_time > 0:
                interval_ms = (now.timestamp() - self._last_audio_time) * 1000
            
            self._last_audio_time = now.timestamp()
            
            # 첫 오디오 생성 시간 (TTS 레이턴시)
            tts_latency_ms = None
            if self._audio_frame_count == 1 and self._tts_start_time > 0:
                tts_latency_ms = round((now.timestamp() - self._tts_start_time) * 1000, 2)
            
            logger.info("tts_wrapper_audio_output",
                       call_id=self._call_id,
                       progress="tts",
                       category="tts",
                       audio_frame_num=self._audio_frame_count,
                       audio_len=audio_len,
                       interval_ms=round(interval_ms, 2) if interval_ms > 0 else None,
                       tts_latency_ms=tts_latency_ms,
                       ts_iso=now.isoformat(timespec="milliseconds"),
                       note="Google TTS 오디오 출력 (합성 완료)")
        
        # Upstream 프레임을 하류로 전달
        await self.push_frame(frame, direction)
    
    async def cleanup(self):
        """Cleanup wrapper and wrapped TTS service"""
        logger.info("tts_wrapper_cleanup",
                   call_id=self._call_id,
                   text_frames_received=self._text_frame_count,
                   audio_frames_sent=self._audio_frame_count)
        if hasattr(self._tts, "cleanup"):
            await self._tts.cleanup()
