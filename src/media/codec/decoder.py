"""Audio Decoder 인터페이스

코덱별 디코더 추상 클래스
"""

from abc import ABC, abstractmethod
from enum import Enum
from dataclasses import dataclass
from typing import Optional


class DecoderType(str, Enum):
    """디코더 타입"""
    G711_ALAW = "g711_alaw"     # G.711 A-law (PT=8)
    G711_MULAW = "g711_mulaw"   # G.711 μ-law (PT=0)
    OPUS = "opus"               # Opus (PT=dynamic, 일반적으로 96-127)
    UNKNOWN = "unknown"


@dataclass
class DecodedAudio:
    """디코딩된 오디오 데이터
    
    PCM 형식
    """
    pcm_data: bytes              # PCM 데이터 (16-bit signed)
    sample_rate: int             # 샘플링 레이트 (Hz)
    channels: int = 1            # 채널 수 (mono=1, stereo=2)
    bits_per_sample: int = 16    # 샘플당 비트 (16-bit)
    
    def get_duration_ms(self) -> float:
        """오디오 길이 (밀리초)
        
        Returns:
            길이 (ms)
        """
        bytes_per_sample = self.bits_per_sample // 8
        num_samples = len(self.pcm_data) // (bytes_per_sample * self.channels)
        return (num_samples / self.sample_rate) * 1000
    
    def get_num_samples(self) -> int:
        """샘플 수
        
        Returns:
            샘플 개수
        """
        bytes_per_sample = self.bits_per_sample // 8
        return len(self.pcm_data) // (bytes_per_sample * self.channels)


class AudioDecoder(ABC):
    """오디오 디코더 추상 클래스"""
    
    def __init__(self, sample_rate: int = 8000):
        """초기화
        
        Args:
            sample_rate: 샘플링 레이트 (Hz)
        """
        self.sample_rate = sample_rate
    
    @abstractmethod
    def decode(self, payload: bytes) -> DecodedAudio:
        """RTP payload 디코딩
        
        Args:
            payload: RTP payload (인코딩된 오디오)
            
        Returns:
            디코딩된 PCM 오디오
            
        Raises:
            ValueError: 디코딩 실패
        """
        pass
    
    @abstractmethod
    def get_decoder_type(self) -> DecoderType:
        """디코더 타입 반환
        
        Returns:
            디코더 타입
        """
        pass
    
    def reset(self) -> None:
        """디코더 상태 초기화 (선택사항)"""
        pass


def get_decoder_for_payload_type(payload_type: int, sample_rate: int = 8000) -> Optional[AudioDecoder]:
    """Payload Type에 따른 디코더 생성
    
    Args:
        payload_type: RTP Payload Type
        sample_rate: 샘플링 레이트 (Hz)
        
    Returns:
        디코더 인스턴스 또는 None (지원하지 않는 타입)
    """
    from src.media.codec.g711 import G711ALawDecoder, G711MuLawDecoder
    
    # RFC 3551 - RTP Payload Types
    if payload_type == 0:
        # PCMU (μ-law)
        return G711MuLawDecoder(sample_rate=sample_rate)
    elif payload_type == 8:
        # PCMA (A-law)
        return G711ALawDecoder(sample_rate=sample_rate)
    # 추가 코덱은 여기에...
    
    return None

