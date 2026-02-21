"""
Barge-in Controller

TTS 발화 중 사용자 음성 감지(Barge-in)를 제어하는 모듈
"""

import asyncio
import time
from typing import Optional
import structlog

logger = structlog.get_logger(__name__)


class BargeInController:
    """
    Barge-in 제어기
    
    TTS 발화 중에는 사용자 음성을 무시하고,
    TTS 완료 후에만 사용자 음성을 처리합니다.
    """
    
    def __init__(self, silence_threshold: float = 2.0):
        """
        Args:
            silence_threshold: 발화 종료로 간주할 침묵 시간 (초)
        """
        self.silence_threshold = silence_threshold
        
        # TTS 상태
        self.tts_speaking = False
        self.tts_start_time: Optional[float] = None
        
        # Barge-in 상태
        self.barge_in_enabled = True
        
        # 사용자 발화 추적
        self.last_speech_time: Optional[float] = None
        self.current_utterance = ""
        
        # 통계
        self.total_barge_in_detected = 0
        self.total_barge_in_ignored = 0
        
        logger.info("BargeInController initialized",
                   silence_threshold=silence_threshold)
    
    async def on_tts_start(self):
        """TTS 시작 시 호출"""
        self.tts_speaking = True
        self.tts_start_time = time.time()
        logger.info("TTS started, barge-in disabled")
    
    async def on_tts_end(self):
        """TTS 종료 시 호출"""
        self.tts_speaking = False
        duration = time.time() - self.tts_start_time if self.tts_start_time else 0
        logger.info("TTS ended, barge-in enabled", duration=f"{duration:.2f}s")
    
    def should_process_speech(self, is_final: bool = False) -> bool:
        """
        사용자 발화를 처리할지 결정
        
        Args:
            is_final: STT 최종 결과 여부
            
        Returns:
            처리 여부 (True: 처리, False: 무시)
        """
        # 1. Barge-in이 비활성화되어 있으면 무시
        if not self.barge_in_enabled:
            return False
        
        # 2. TTS 발화 중이면 무시
        if self.tts_speaking:
            self.total_barge_in_ignored += 1
            logger.debug("Speech ignored during TTS",
                        is_final=is_final,
                        total_ignored=self.total_barge_in_ignored)
            return False
        
        # 3. 중간 결과는 무시하지 않음 (침묵 감지용)
        if not is_final:
            return True
        
        # 4. 최종 결과는 처리
        self.total_barge_in_detected += 1
        return True
    
    def on_speech_detected(self, transcript: str, is_final: bool):
        """
        음성 감지 시 호출
        
        Args:
            transcript: STT 결과
            is_final: 최종 결과 여부
        """
        if not self.should_process_speech(is_final):
            return
        
        # 마지막 발화 시간 업데이트
        self.last_speech_time = time.time()
        
        # 발화 내용 누적
        if is_final:
            self.current_utterance += transcript
            logger.debug("Speech detected (final)",
                        transcript=transcript,
                        total_length=len(self.current_utterance))
        else:
            logger.debug("Speech detected (interim)",
                        transcript=transcript)
    
    def check_silence(self) -> bool:
        """
        침묵 감지 (사용자가 말을 멈췄는지 확인)
        
        Returns:
            침묵 감지 여부
        """
        if self.last_speech_time is None:
            return False
        
        silence_duration = time.time() - self.last_speech_time
        
        if silence_duration >= self.silence_threshold:
            logger.info("Silence detected",
                       silence_duration=f"{silence_duration:.2f}s",
                       threshold=f"{self.silence_threshold:.2f}s")
            return True
        
        return False
    
    def get_and_reset_utterance(self) -> str:
        """
        누적된 발화 내용을 반환하고 초기화
        
        Returns:
            누적된 발화 내용
        """
        utterance = self.current_utterance.strip()
        self.current_utterance = ""
        self.last_speech_time = None
        
        logger.info("Utterance completed",
                   length=len(utterance),
                   preview=utterance[:50] if len(utterance) > 50 else utterance)
        
        return utterance
    
    def reset(self):
        """상태 초기화"""
        self.current_utterance = ""
        self.last_speech_time = None
        self.tts_speaking = False
        logger.debug("BargeInController reset")
    
    def enable_barge_in(self):
        """Barge-in 활성화"""
        self.barge_in_enabled = True
        logger.info("Barge-in enabled")
    
    def disable_barge_in(self):
        """Barge-in 비활성화"""
        self.barge_in_enabled = False
        logger.info("Barge-in disabled")
    
    def get_stats(self) -> dict:
        """통계 반환"""
        return {
            "tts_speaking": self.tts_speaking,
            "barge_in_enabled": self.barge_in_enabled,
            "total_barge_in_detected": self.total_barge_in_detected,
            "total_barge_in_ignored": self.total_barge_in_ignored,
            "current_utterance_length": len(self.current_utterance),
            "silence_threshold": self.silence_threshold,
        }
