"""
Voice Activity Detector (VAD)

WebRTC VAD 기반 음성 활동 감지 및 Barge-in 지원
"""

import webrtcvad
from collections import deque
from typing import Optional
import structlog

logger = structlog.get_logger(__name__)


class VADDetector:
    """
    Voice Activity Detector (음성 활동 감지기)
    
    WebRTC VAD를 사용하여 실시간 음성 활동을 감지하고
    Barge-in 기능을 제공합니다.
    """
    
    def __init__(
        self,
        mode: int = 3,  # 0-3, 3이 가장 민감
        sample_rate: int = 16000,
        frame_duration_ms: int = 30,
        trigger_threshold: float = 0.5,
        speech_frame_count: int = 3
    ):
        """
        Args:
            mode: VAD 모드 (0-3, 3이 가장 민감)
            sample_rate: 샘플레이트 (8000, 16000, 32000, 48000만 지원)
            frame_duration_ms: 프레임 길이 (10, 20, 30ms만 지원)
            trigger_threshold: Barge-in 트리거 임계값 (0.0-1.0)
            speech_frame_count: 연속 음성 프레임 수
        """
        if mode not in [0, 1, 2, 3]:
            raise ValueError("VAD mode must be 0-3")
        
        if sample_rate not in [8000, 16000, 32000, 48000]:
            raise ValueError(f"Invalid sample rate: {sample_rate}. Must be 8000, 16000, 32000, or 48000")
        
        if frame_duration_ms not in [10, 20, 30]:
            raise ValueError(f"Invalid frame duration: {frame_duration_ms}. Must be 10, 20, or 30")
        
        self.vad = webrtcvad.Vad(mode)
        self.sample_rate = sample_rate
        self.frame_duration_ms = frame_duration_ms
        self.trigger_threshold = trigger_threshold
        self.speech_frame_count = speech_frame_count
        
        # 프레임 크기 (bytes): sample_rate * duration / 1000 * 2 (16-bit)
        self.frame_size = int(sample_rate * frame_duration_ms / 1000 * 2)
        
        # 최근 프레임 히스토리
        self.recent_frames = deque(maxlen=10)
        self.consecutive_speech = 0
        
        # 통계
        self.total_frames = 0
        self.speech_frames = 0
        
        logger.info("VADDetector initialized", 
                   mode=mode,
                   sample_rate=sample_rate,
                   frame_duration_ms=frame_duration_ms,
                   frame_size=self.frame_size)
    
    def detect(self, audio_frame: bytes) -> bool:
        """
        음성 감지
        
        Args:
            audio_frame: 오디오 프레임 (16-bit PCM)
            
        Returns:
            음성 감지 여부
        """
        # 프레임 크기 맞추기
        if len(audio_frame) != self.frame_size:
            if len(audio_frame) < self.frame_size:
                # 패딩
                audio_frame = audio_frame + b'\x00' * (self.frame_size - len(audio_frame))
            else:
                # 자르기
                audio_frame = audio_frame[:self.frame_size]
        
        try:
            is_speech = self.vad.is_speech(audio_frame, self.sample_rate)
            
            # 연속 음성 카운트
            if is_speech:
                self.consecutive_speech += 1
                self.speech_frames += 1
            else:
                self.consecutive_speech = 0
            
            # 히스토리 업데이트
            self.recent_frames.append(is_speech)
            self.total_frames += 1
            
            return is_speech
            
        except Exception as e:
            logger.error("VAD detection failed", error=str(e), exc_info=True)
            return False
    
    def is_speaking(self) -> bool:
        """
        현재 발화 중인지 확인 (Barge-in 트리거용)
        
        Returns:
            발화 중 여부
        """
        return self.consecutive_speech >= self.speech_frame_count
    
    def get_speech_ratio(self) -> float:
        """
        최근 윈도우의 음성 비율
        
        Returns:
            음성 비율 (0.0-1.0)
        """
        if not self.recent_frames:
            return 0.0
        
        speech_count = sum(1 for is_speech in self.recent_frames if is_speech)
        return speech_count / len(self.recent_frames)
    
    def is_barge_in(self) -> bool:
        """
        Barge-in 조건 만족 여부
        
        사용자가 AI 응답 중에 말하기 시작했는지 확인합니다.
        
        Returns:
            Barge-in 조건 만족 여부
        """
        if not self.is_speaking():
            return False
        
        speech_ratio = self.get_speech_ratio()
        return speech_ratio >= self.trigger_threshold
    
    def reset(self):
        """VAD 상태 초기화"""
        self.recent_frames.clear()
        self.consecutive_speech = 0
        logger.debug("VAD state reset")
    
    def get_stats(self) -> dict:
        """VAD 통계 반환"""
        total = self.total_frames if self.total_frames > 0 else 1
        return {
            "total_frames": self.total_frames,
            "speech_frames": self.speech_frames,
            "speech_ratio": self.speech_frames / total,
            "consecutive_speech": self.consecutive_speech,
            "is_speaking": self.is_speaking(),
            "is_barge_in": self.is_barge_in(),
        }


class SimpleVAD:
    """
    간단한 에너지 기반 VAD (WebRTC VAD 대안)
    
    webrtcvad가 설치되지 않은 경우 사용할 수 있습니다.
    """
    
    def __init__(
        self,
        energy_threshold: float = 500.0,
        sample_rate: int = 16000,
        frame_duration_ms: int = 30
    ):
        """
        Args:
            energy_threshold: 에너지 임계값
            sample_rate: 샘플레이트
            frame_duration_ms: 프레임 길이
        """
        self.energy_threshold = energy_threshold
        self.sample_rate = sample_rate
        self.frame_duration_ms = frame_duration_ms
        
        self.recent_frames = deque(maxlen=10)
        self.consecutive_speech = 0
        
        logger.info("SimpleVAD initialized", threshold=energy_threshold)
    
    def detect(self, audio_frame: bytes) -> bool:
        """
        에너지 기반 음성 감지
        
        Args:
            audio_frame: 오디오 프레임
            
        Returns:
            음성 감지 여부
        """
        try:
            # 16-bit PCM을 정수 배열로 변환
            import struct
            samples = struct.unpack(f'{len(audio_frame)//2}h', audio_frame)
            
            # RMS 에너지 계산
            energy = sum(s * s for s in samples) / len(samples)
            rms_energy = energy ** 0.5
            
            is_speech = rms_energy > self.energy_threshold
            
            if is_speech:
                self.consecutive_speech += 1
            else:
                self.consecutive_speech = 0
            
            self.recent_frames.append(is_speech)
            
            return is_speech
            
        except Exception as e:
            logger.error("SimpleVAD detection failed", error=str(e))
            return False
    
    def is_speaking(self) -> bool:
        """발화 중 여부"""
        return self.consecutive_speech >= 3
    
    def is_barge_in(self) -> bool:
        """Barge-in 조건 만족 여부"""
        if not self.is_speaking():
            return False
        
        speech_count = sum(1 for is_speech in self.recent_frames if is_speech)
        speech_ratio = speech_count / len(self.recent_frames) if self.recent_frames else 0
        return speech_ratio >= 0.5
    
    def reset(self):
        """VAD 상태 초기화"""
        self.recent_frames.clear()
        self.consecutive_speech = 0

