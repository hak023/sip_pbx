"""G.711 Codec Decoder

G.711 A-law 및 μ-law 디코더
"""

import audioop
from src.media.codec.decoder import AudioDecoder, DecoderType, DecodedAudio
from src.common.logger import get_logger

logger = get_logger(__name__)


class G711Decoder(AudioDecoder):
    """G.711 디코더 기본 클래스"""
    
    def __init__(self, sample_rate: int = 8000):
        """초기화
        
        Args:
            sample_rate: 샘플링 레이트 (기본: 8000Hz - G.711 표준)
        """
        super().__init__(sample_rate=sample_rate)
        
        # G.711은 항상 8kHz
        if sample_rate != 8000:
            logger.warning("g711_non_standard_sample_rate",
                          sample_rate=sample_rate,
                          standard=8000)


class G711ALawDecoder(G711Decoder):
    """G.711 A-law 디코더
    
    RTP Payload Type: 8 (PCMA)
    샘플링 레이트: 8000 Hz
    비트레이트: 64 kbps
    """
    
    def decode(self, payload: bytes) -> DecodedAudio:
        """A-law 디코딩
        
        Args:
            payload: A-law 인코딩된 데이터
            
        Returns:
            16-bit PCM 오디오
            
        Raises:
            ValueError: 디코딩 실패
        """
        if not payload:
            raise ValueError("Empty payload")
        
        try:
            # audioop.alaw2lin: A-law → linear PCM (16-bit)
            # width=2 → 16-bit samples
            pcm_data = audioop.alaw2lin(payload, 2)
            
            return DecodedAudio(
                pcm_data=pcm_data,
                sample_rate=self.sample_rate,
                channels=1,
                bits_per_sample=16,
            )
        
        except Exception as e:
            logger.error("g711_alaw_decode_error", error=str(e))
            raise ValueError(f"G.711 A-law decoding failed: {e}")
    
    def get_decoder_type(self) -> DecoderType:
        """디코더 타입
        
        Returns:
            G.711 A-law
        """
        return DecoderType.G711_ALAW


class G711MuLawDecoder(G711Decoder):
    """G.711 μ-law (mu-law) 디코더
    
    RTP Payload Type: 0 (PCMU)
    샘플링 레이트: 8000 Hz
    비트레이트: 64 kbps
    """
    
    def decode(self, payload: bytes) -> DecodedAudio:
        """μ-law 디코딩
        
        Args:
            payload: μ-law 인코딩된 데이터
            
        Returns:
            16-bit PCM 오디오
            
        Raises:
            ValueError: 디코딩 실패
        """
        if not payload:
            raise ValueError("Empty payload")
        
        try:
            # audioop.ulaw2lin: μ-law → linear PCM (16-bit)
            # width=2 → 16-bit samples
            pcm_data = audioop.ulaw2lin(payload, 2)
            
            return DecodedAudio(
                pcm_data=pcm_data,
                sample_rate=self.sample_rate,
                channels=1,
                bits_per_sample=16,
            )
        
        except Exception as e:
            logger.error("g711_mulaw_decode_error", error=str(e))
            raise ValueError(f"G.711 μ-law decoding failed: {e}")
    
    def get_decoder_type(self) -> DecoderType:
        """디코더 타입
        
        Returns:
            G.711 μ-law
        """
        return DecoderType.G711_MULAW

