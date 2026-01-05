"""Opus Codec 테스트"""

import pytest
import numpy as np
import sys
from unittest.mock import Mock, patch, MagicMock
from src.media.codec.decoder import DecoderType
from src.common.logger import setup_logging


@pytest.fixture(scope="module", autouse=True)
def setup_test_logging():
    """테스트용 로깅 설정"""
    setup_logging(level="DEBUG", format_type="text")


# Mock opuslib 모듈
mock_opuslib = MagicMock()
sys.modules['opuslib'] = mock_opuslib


class TestOpusDecoder:
    """Opus 디코더 테스트 (Mock 사용)"""
    
    def test_decoder_creation(self):
        """디코더 생성 테스트"""
        from src.media.codec.opus import OpusDecoder
        
        # Mock Decoder
        mock_decoder = Mock()
        mock_opuslib.Decoder.return_value = mock_decoder
        
        decoder = OpusDecoder(sample_rate=48000, channels=1)
        
        assert decoder.sample_rate == 48000
        assert decoder.channels == 1
        assert decoder.get_decoder_type() == DecoderType.OPUS
    
    def test_decode_opus(self):
        """Opus 디코딩 테스트"""
        from src.media.codec.opus import OpusDecoder
        
        # Mock Decoder
        mock_decoder = Mock()
        # 디코딩 결과: 20ms @ 48kHz = 960 samples = 1920 bytes (16-bit)
        pcm_result = b'\x00\x00' * 960
        mock_decoder.decode.return_value = pcm_result
        mock_opuslib.Decoder.return_value = mock_decoder
        
        decoder = OpusDecoder(sample_rate=48000, channels=1)
        
        # Opus 인코딩된 데이터 (가짜)
        opus_data = b'\x01\x02\x03\x04' * 10
        
        decoded = decoder.decode(opus_data)
        
        # 검증
        assert decoded.sample_rate == 48000
        assert decoded.channels == 1
        assert decoded.bits_per_sample == 16
        assert len(decoded.pcm_data) == 1920  # 960 samples * 2 bytes
    
    def test_decode_with_resampling(self):
        """리샘플링과 함께 디코딩 (48kHz → 16kHz)"""
        from src.media.codec.opus import OpusDecoder
        
        # Mock Decoder
        mock_decoder = Mock()
        # 48kHz, 20ms = 960 samples
        pcm_48k = np.zeros(960, dtype=np.int16)
        for i in range(960):
            pcm_48k[i] = int(np.sin(2 * np.pi * 1000 * i / 48000) * 10000)
        
        mock_decoder.decode.return_value = pcm_48k.tobytes()
        mock_opuslib.Decoder.return_value = mock_decoder
        
        # 48kHz로 디코딩하지만 16kHz로 리샘플링
        decoder = OpusDecoder(
            sample_rate=48000,
            channels=1,
            target_sample_rate=16000,
        )
        
        opus_data = b'\x01\x02\x03\x04' * 10
        
        decoded = decoder.decode(opus_data)
        
        # 16kHz로 리샘플링되었는지 확인
        assert decoded.sample_rate == 16000
        
        # 샘플 수: 48kHz 960 samples → 16kHz 320 samples
        expected_samples = 320
        assert decoded.get_num_samples() == expected_samples
        assert len(decoded.pcm_data) == expected_samples * 2  # 16-bit
    
    def test_decode_empty_payload(self):
        """빈 payload 처리"""
        from src.media.codec.opus import OpusDecoder
        
        mock_decoder = Mock()
        mock_opuslib.Decoder.return_value = mock_decoder
        
        decoder = OpusDecoder()
        
        with pytest.raises(ValueError) as exc_info:
            decoder.decode(b'')
        
        assert "Empty payload" in str(exc_info.value)
    
    def test_decode_with_fec(self):
        """FEC를 사용한 디코딩 (packet loss 복구)"""
        from src.media.codec.opus import OpusDecoder
        
        # Mock Decoder
        mock_decoder = Mock()
        fec_result = b'\x00\x00' * 960  # 20ms @ 48kHz
        mock_decoder.decode.return_value = fec_result
        mock_opuslib.Decoder.return_value = mock_decoder
        
        decoder = OpusDecoder(sample_rate=48000)
        
        # 현재 패킷은 loss (None)
        # 다음 패킷에서 FEC 정보 사용
        next_packet = b'\x05\x06\x07\x08' * 10
        
        decoded = decoder.decode_with_fec(
            payload=None,  # Loss
            next_payload=next_packet,
        )
        
        # FEC로 복구되었는지 확인
        assert decoded is not None
        assert len(decoded.pcm_data) == 1920
    
    def test_different_sample_rates(self):
        """다양한 샘플링 레이트"""
        from src.media.codec.opus import OpusDecoder
        
        mock_decoder = Mock()
        mock_opuslib.Decoder.return_value = mock_decoder
        
        for sample_rate in [8000, 12000, 16000, 24000, 48000]:
            decoder = OpusDecoder(sample_rate=sample_rate)
            assert decoder.sample_rate == sample_rate
    
    def test_stereo_decoding(self):
        """스테레오 디코딩"""
        from src.media.codec.opus import OpusDecoder
        
        mock_decoder = Mock()
        # 스테레오: 960 samples per channel = 1920 samples total
        pcm_stereo = b'\x00\x00' * 1920
        mock_decoder.decode.return_value = pcm_stereo
        mock_opuslib.Decoder.return_value = mock_decoder
        
        decoder = OpusDecoder(sample_rate=48000, channels=2)
        
        opus_data = b'\x01\x02\x03\x04' * 10
        decoded = decoder.decode(opus_data)
        
        assert decoded.channels == 2
        assert decoded.get_num_samples() == 960  # per channel
    
    def test_decoder_reset(self):
        """디코더 리셋"""
        from src.media.codec.opus import OpusDecoder
        
        mock_decoder = Mock()
        mock_opuslib.Decoder.return_value = mock_decoder
        
        decoder = OpusDecoder()
        
        # 리셋
        decoder.reset()


class TestOpusResampling:
    """Opus 리샘플링 테스트"""
    
    def test_resample_48k_to_16k(self):
        """48kHz → 16kHz 리샘플링"""
        from src.media.codec.opus import OpusDecoder
        
        mock_decoder = Mock()
        mock_opuslib.Decoder.return_value = mock_decoder
        
        decoder = OpusDecoder(sample_rate=48000)
        
        # 48kHz PCM 데이터 (1초 = 48000 samples)
        pcm_48k = np.zeros(48000, dtype=np.int16)
        for i in range(48000):
            pcm_48k[i] = int(np.sin(2 * np.pi * 1000 * i / 48000) * 10000)
        
        # 리샘플링
        pcm_16k = decoder._resample(pcm_48k.tobytes(), 48000, 16000)
        
        # 16kHz = 16000 samples
        samples_16k = np.frombuffer(pcm_16k, dtype=np.int16)
        assert len(samples_16k) == 16000
    
    def test_resample_48k_to_8k(self):
        """48kHz → 8kHz 리샘플링"""
        from src.media.codec.opus import OpusDecoder
        
        mock_decoder = Mock()
        mock_opuslib.Decoder.return_value = mock_decoder
        
        decoder = OpusDecoder(sample_rate=48000)
        
        # 48kHz PCM 데이터 (20ms = 960 samples)
        pcm_48k = np.zeros(960, dtype=np.int16)
        
        # 리샘플링
        pcm_8k = decoder._resample(pcm_48k.tobytes(), 48000, 8000)
        
        # 8kHz, 20ms = 160 samples
        samples_8k = np.frombuffer(pcm_8k, dtype=np.int16)
        assert len(samples_8k) == 160


class TestOpusFrameSizes:
    """Opus 프레임 크기 테스트"""
    
    def test_frame_size_20ms(self):
        """20ms 프레임"""
        from src.media.codec.opus import OpusDecoder
        
        mock_decoder = Mock()
        # 48kHz, 20ms = 960 samples
        mock_decoder.decode.return_value = b'\x00\x00' * 960
        mock_opuslib.Decoder.return_value = mock_decoder
        
        decoder = OpusDecoder(sample_rate=48000)
        
        opus_data = b'\x01\x02\x03\x04' * 10
        decoded = decoder.decode(opus_data, frame_size=960)
        
        assert decoded.get_duration_ms() == pytest.approx(20, abs=0.5)
    
    def test_frame_size_40ms(self):
        """40ms 프레임"""
        from src.media.codec.opus import OpusDecoder
        
        mock_decoder = Mock()
        # 48kHz, 40ms = 1920 samples
        mock_decoder.decode.return_value = b'\x00\x00' * 1920
        mock_opuslib.Decoder.return_value = mock_decoder
        
        decoder = OpusDecoder(sample_rate=48000)
        
        opus_data = b'\x01\x02\x03\x04' * 10
        decoded = decoder.decode(opus_data, frame_size=1920)
        
        assert decoded.get_duration_ms() == pytest.approx(40, abs=0.5)
    
    def test_frame_size_60ms(self):
        """60ms 프레임"""
        from src.media.codec.opus import OpusDecoder
        
        mock_decoder = Mock()
        # 48kHz, 60ms = 2880 samples
        mock_decoder.decode.return_value = b'\x00\x00' * 2880
        mock_opuslib.Decoder.return_value = mock_decoder
        
        decoder = OpusDecoder(sample_rate=48000)
        
        opus_data = b'\x01\x02\x03\x04' * 10
        decoded = decoder.decode(opus_data, frame_size=2880)
        
        assert decoded.get_duration_ms() == pytest.approx(60, abs=0.5)


class TestOpusPerformance:
    """Opus 디코딩 성능 테스트"""
    
    def test_decode_performance(self):
        """디코딩 성능: 1초 오디오 → 50ms 이내"""
        import time
        from src.media.codec.opus import OpusDecoder
        
        mock_decoder = Mock()
        # 20ms 프레임
        mock_decoder.decode.return_value = b'\x00\x00' * 960
        mock_opuslib.Decoder.return_value = mock_decoder
        
        decoder = OpusDecoder(sample_rate=48000)
        
        # 1초 = 50개의 20ms 프레임
        frame_count = 50
        opus_frame = b'\x01\x02\x03\x04' * 10
        
        start_time = time.perf_counter()
        
        for _ in range(frame_count):
            decoded = decoder.decode(opus_frame)
            assert len(decoded.pcm_data) > 0
        
        end_time = time.perf_counter()
        elapsed_ms = (end_time - start_time) * 1000
        
        # 1초 오디오를 50ms 이내에 디코딩
        # Mock이므로 매우 빠름
        assert elapsed_ms < 50, f"Decoding too slow: {elapsed_ms:.2f}ms"
        
        print(f"\nOpus 디코딩 성능 (Mock): 1초 오디오 → {elapsed_ms:.2f}ms")

