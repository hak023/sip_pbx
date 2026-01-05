"""Opus Codec Decoder

Opus 코덱 디코더 (RFC 6716)
"""

from typing import Optional
import numpy as np

from src.media.codec.decoder import AudioDecoder, DecoderType, DecodedAudio
from src.common.logger import get_logger

logger = get_logger(__name__)


class OpusDecoder(AudioDecoder):
    """Opus 디코더
    
    Opus는 고품질 오디오 코덱:
    - Variable bitrate (6-510 kbps)
    - 샘플링 레이트: 8kHz ~ 48kHz
    - 프레임 크기: 2.5ms ~ 60ms
    - FEC (Forward Error Correction) 지원
    """
    
    def __init__(
        self,
        sample_rate: int = 48000,
        channels: int = 1,
        target_sample_rate: Optional[int] = None,
    ):
        """초기화
        
        Args:
            sample_rate: Opus 디코딩 샘플링 레이트 (8000, 12000, 16000, 24000, 48000)
            channels: 채널 수 (1=mono, 2=stereo)
            target_sample_rate: 목표 샘플링 레이트 (리샘플링, None이면 원본 유지)
        """
        super().__init__(sample_rate=sample_rate)
        
        self.channels = channels
        self.target_sample_rate = target_sample_rate
        
        # Opus 디코더 인스턴스
        self._decoder: Optional[object] = None
        self._init_decoder()
        
        logger.info("opus_decoder_created",
                   sample_rate=sample_rate,
                   channels=channels,
                   target_sample_rate=target_sample_rate)
    
    def _init_decoder(self) -> None:
        """Opus 디코더 초기화"""
        try:
            import opuslib
            
            # Opus 디코더 생성
            self._decoder = opuslib.Decoder(
                fs=self.sample_rate,
                channels=self.channels,
            )
            
            logger.debug("opus_decoder_initialized",
                        sample_rate=self.sample_rate,
                        channels=self.channels)
        
        except ImportError:
            logger.error("opuslib_not_installed")
            raise ImportError(
                "opuslib is not installed. "
                "Install it with: pip install opuslib"
            )
        except Exception as e:
            logger.error("opus_decoder_init_error", error=str(e))
            raise ValueError(f"Failed to initialize Opus decoder: {e}")
    
    def decode(self, payload: bytes, frame_size: Optional[int] = None) -> DecodedAudio:
        """Opus 디코딩
        
        Args:
            payload: Opus 인코딩된 데이터
            frame_size: 프레임 크기 (샘플 수, None이면 자동)
            
        Returns:
            16-bit PCM 오디오
            
        Raises:
            ValueError: 디코딩 실패
        """
        if not payload:
            raise ValueError("Empty payload")
        
        if self._decoder is None:
            raise ValueError("Opus decoder not initialized")
        
        try:
            # 프레임 크기 자동 계산 (일반적으로 20ms)
            if frame_size is None:
                frame_size = self.sample_rate // 50  # 20ms
            
            # Opus 디코딩 → PCM (16-bit signed integers)
            pcm_data = self._decoder.decode(payload, frame_size)
            
            # bytes → numpy array → bytes
            if isinstance(pcm_data, bytes):
                # 이미 bytes 형태
                pass
            else:
                # numpy array → bytes
                pcm_data = bytes(pcm_data)
            
            # 리샘플링 필요한 경우
            if self.target_sample_rate and self.target_sample_rate != self.sample_rate:
                pcm_data = self._resample(pcm_data, self.sample_rate, self.target_sample_rate)
                output_sample_rate = self.target_sample_rate
            else:
                output_sample_rate = self.sample_rate
            
            return DecodedAudio(
                pcm_data=pcm_data,
                sample_rate=output_sample_rate,
                channels=self.channels,
                bits_per_sample=16,
            )
        
        except Exception as e:
            logger.error("opus_decode_error", error=str(e))
            raise ValueError(f"Opus decoding failed: {e}")
    
    def decode_with_fec(
        self,
        payload: Optional[bytes],
        next_payload: bytes,
        frame_size: Optional[int] = None,
    ) -> DecodedAudio:
        """FEC를 사용한 Opus 디코딩
        
        Packet loss 발생 시 다음 패킷의 FEC 정보를 사용하여 복구
        
        Args:
            payload: 현재 패킷 (None이면 loss)
            next_payload: 다음 패킷 (FEC 정보 포함)
            frame_size: 프레임 크기
            
        Returns:
            16-bit PCM 오디오
        """
        if payload is not None:
            # 정상 패킷
            return self.decode(payload, frame_size)
        
        # Packet loss: FEC 사용
        try:
            if frame_size is None:
                frame_size = self.sample_rate // 50
            
            # FEC 디코딩 (다음 패킷에서 복구)
            pcm_data = self._decoder.decode(next_payload, frame_size, fec=True)
            
            if not isinstance(pcm_data, bytes):
                pcm_data = bytes(pcm_data)
            
            # 리샘플링
            if self.target_sample_rate and self.target_sample_rate != self.sample_rate:
                pcm_data = self._resample(pcm_data, self.sample_rate, self.target_sample_rate)
                output_sample_rate = self.target_sample_rate
            else:
                output_sample_rate = self.sample_rate
            
            logger.debug("opus_fec_recovery_success")
            
            return DecodedAudio(
                pcm_data=pcm_data,
                sample_rate=output_sample_rate,
                channels=self.channels,
                bits_per_sample=16,
            )
        
        except Exception as e:
            logger.error("opus_fec_decode_error", error=str(e))
            raise ValueError(f"Opus FEC decoding failed: {e}")
    
    def _resample(self, pcm_data: bytes, from_rate: int, to_rate: int) -> bytes:
        """샘플링 레이트 변환
        
        Args:
            pcm_data: 원본 PCM 데이터
            from_rate: 원본 샘플링 레이트
            to_rate: 목표 샘플링 레이트
            
        Returns:
            리샘플링된 PCM 데이터
        """
        try:
            # bytes → numpy array (16-bit signed int)
            samples = np.frombuffer(pcm_data, dtype=np.int16)
            
            # 샘플 수 계산
            num_samples = len(samples)
            duration_sec = num_samples / from_rate
            target_num_samples = int(duration_sec * to_rate)
            
            # Linear interpolation을 사용한 리샘플링
            indices = np.linspace(0, num_samples - 1, target_num_samples)
            resampled = np.interp(indices, np.arange(num_samples), samples)
            
            # numpy array → bytes
            resampled_bytes = resampled.astype(np.int16).tobytes()
            
            logger.debug("opus_resampling_done",
                        from_rate=from_rate,
                        to_rate=to_rate,
                        original_samples=num_samples,
                        resampled_samples=target_num_samples)
            
            return resampled_bytes
        
        except Exception as e:
            logger.error("opus_resample_error", error=str(e))
            # 리샘플링 실패 시 원본 반환
            return pcm_data
    
    def get_decoder_type(self) -> DecoderType:
        """디코더 타입
        
        Returns:
            Opus
        """
        return DecoderType.OPUS
    
    def reset(self) -> None:
        """디코더 상태 초기화"""
        if self._decoder:
            # Opus 디코더 재생성
            self._init_decoder()
            logger.debug("opus_decoder_reset")

