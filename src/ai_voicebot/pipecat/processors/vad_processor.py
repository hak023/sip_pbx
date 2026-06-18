"""
Pipecat VAD Processor - VADDetector를 Pipecat 파이프라인에서 사용 가능하도록 FrameProcessor로 래핑
"""

import asyncio
from typing import Optional

import structlog

try:
    from pipecat.frames.frames import (
        Frame,
        InputAudioRawFrame,
    )
    from pipecat.processors.frame_processor import FrameProcessor
    from pipecat.pipeline.pipeline import FrameDirection

    from src.ai_voicebot.pipecat.interruption_compat import StartInterruptionFrame

    _PIPECAT_AVAILABLE = True
except ImportError:
    Frame = None
    InputAudioRawFrame = None
    StartInterruptionFrame = None
    FrameProcessor = object
    FrameDirection = None
    _PIPECAT_AVAILABLE = False

from src.ai_voicebot.vad_detector import VADDetector

logger = structlog.get_logger(__name__)


class PipecatVADProcessor(FrameProcessor):
    """
    VADDetector를 Pipecat 파이프라인에서 사용하기 위한 FrameProcessor 래퍼.
    
    InputAudioRawFrame을 받아 VADDetector로 음성 활동을 감지하고,
    Barge-in 조건이 만족되면 StartInterruptionFrame을 발행합니다.
    """
    
    def __init__(
        self,
        vad_detector: VADDetector,
        enable_barge_in: bool = True,
        **kwargs
    ):
        """
        Args:
            vad_detector: VADDetector 인스턴스
            enable_barge_in: Barge-in 기능 활성화 여부
            **kwargs: FrameProcessor 기본 인자들
        """
        if not _PIPECAT_AVAILABLE:
            raise RuntimeError("pipecat not available. Install pipecat-ai.")
        
        super().__init__(**kwargs)
        self._vad = vad_detector
        self._enable_barge_in = enable_barge_in
        self._is_speaking = False  # TTS 재생 중 여부 (downstream에서 설정)
        
        logger.info("pipecat_vad_processor_initialized",
                   enable_barge_in=enable_barge_in)
    
    async def process_frame(self, frame: Frame, direction: FrameDirection):
        """프레임 처리: InputAudioRawFrame → VAD 감지 → Barge-in 판단"""
        await super().process_frame(frame, direction)
        
        # InputAudioRawFrame만 VAD 처리
        if isinstance(frame, InputAudioRawFrame):
            audio_data = frame.audio if hasattr(frame, 'audio') else None
            if audio_data:
                try:
                    # VAD 감지
                    is_speech = self._vad.detect(audio_data)
                    
                    # Barge-in 조건 확인: TTS 재생 중 + 사용자 말하기 시작
                    if self._enable_barge_in and self._is_speaking and self._vad.is_barge_in():
                        logger.info("barge_in_detected_sending_interrupt",
                                   speech_ratio=self._vad.get_speech_ratio())
                        # StartInterruptionFrame 발행 → downstream TTS가 중단
                        await self.push_frame(StartInterruptionFrame())
                        self._is_speaking = False  # TTS 중단됨
                    
                except Exception as e:
                    logger.error("vad_processing_error", error=str(e))
        
        # 모든 프레임을 downstream으로 전달
        await self.push_frame(frame, direction)
    
    def set_speaking(self, is_speaking: bool):
        """
        TTS 재생 상태 설정 (외부에서 호출).
        
        Args:
            is_speaking: TTS 재생 중 여부
        """
        self._is_speaking = is_speaking
        if not is_speaking:
            # TTS 종료 시 VAD 상태 리셋
            self._vad.reset()
