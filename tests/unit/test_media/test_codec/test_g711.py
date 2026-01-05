"""G.711 Codec 테스트"""

import pytest
import audioop
import struct
from src.media.codec.g711 import G711ALawDecoder, G711MuLawDecoder
from src.media.codec.decoder import DecoderType, get_decoder_for_payload_type
from src.common.logger import setup_logging


@pytest.fixture(scope="module", autouse=True)
def setup_test_logging():
    """테스트용 로깅 설정"""
    setup_logging(level="DEBUG", format_type="text")


class TestG711ALawDecoder:
    """G.711 A-law 디코더 테스트"""
    
    def test_decoder_creation(self):
        """디코더 생성 테스트"""
        decoder = G711ALawDecoder()
        
        assert decoder.sample_rate == 8000
        assert decoder.get_decoder_type() == DecoderType.G711_ALAW
    
    def test_decode_alaw(self):
        """A-law 디코딩 테스트"""
        decoder = G711ALawDecoder()
        
        # 테스트용 PCM 데이터 (16-bit)
        original_pcm = b'\x00\x10\x00\x20\x00\x30\x00\x40' * 20  # 160 bytes = 80 samples
        
        # PCM → A-law 인코딩
        alaw_data = audioop.lin2alaw(original_pcm, 2)
        
        # A-law → PCM 디코딩
        decoded = decoder.decode(alaw_data)
        
        # 검증
        assert decoded.sample_rate == 8000
        assert decoded.channels == 1
        assert decoded.bits_per_sample == 16
        assert len(decoded.pcm_data) == len(original_pcm)
        
        # 디코딩된 데이터가 원본과 유사한지 (완전히 같지는 않음 - 손실 압축)
        # 최소한 같은 길이여야 함
        assert decoded.get_num_samples() == 80
    
    def test_decode_empty_payload(self):
        """빈 payload 처리"""
        decoder = G711ALawDecoder()
        
        with pytest.raises(ValueError) as exc_info:
            decoder.decode(b'')
        
        assert "Empty payload" in str(exc_info.value)
    
    def test_decode_duration(self):
        """디코딩된 오디오 길이 계산"""
        decoder = G711ALawDecoder()
        
        # 160 bytes A-law = 160 samples = 20ms @ 8kHz
        alaw_data = b'\x55' * 160  # Silence in A-law
        
        decoded = decoder.decode(alaw_data)
        
        # 160 samples @ 8000Hz = 20ms
        duration_ms = decoded.get_duration_ms()
        assert 19.5 <= duration_ms <= 20.5  # 허용 오차
    
    def test_decode_realistic_frame(self):
        """실제 G.711 프레임 크기 테스트"""
        decoder = G711ALawDecoder()
        
        # G.711: 20ms frame = 160 samples @ 8kHz = 160 bytes
        frame_size = 160
        
        # 샘플 A-law 데이터
        alaw_data = bytes([0xD5] * frame_size)  # A-law encoded silence
        
        decoded = decoder.decode(alaw_data)
        
        assert len(decoded.pcm_data) == frame_size * 2  # 16-bit = 2 bytes per sample
        assert decoded.get_num_samples() == frame_size


class TestG711MuLawDecoder:
    """G.711 μ-law 디코더 테스트"""
    
    def test_decoder_creation(self):
        """디코더 생성 테스트"""
        decoder = G711MuLawDecoder()
        
        assert decoder.sample_rate == 8000
        assert decoder.get_decoder_type() == DecoderType.G711_MULAW
    
    def test_decode_mulaw(self):
        """μ-law 디코딩 테스트"""
        decoder = G711MuLawDecoder()
        
        # 테스트용 PCM 데이터 (16-bit)
        original_pcm = b'\x00\x10\x00\x20\x00\x30\x00\x40' * 20  # 160 bytes = 80 samples
        
        # PCM → μ-law 인코딩
        ulaw_data = audioop.lin2ulaw(original_pcm, 2)
        
        # μ-law → PCM 디코딩
        decoded = decoder.decode(ulaw_data)
        
        # 검증
        assert decoded.sample_rate == 8000
        assert decoded.channels == 1
        assert decoded.bits_per_sample == 16
        assert len(decoded.pcm_data) == len(original_pcm)
        assert decoded.get_num_samples() == 80
    
    def test_decode_empty_payload(self):
        """빈 payload 처리"""
        decoder = G711MuLawDecoder()
        
        with pytest.raises(ValueError) as exc_info:
            decoder.decode(b'')
        
        assert "Empty payload" in str(exc_info.value)
    
    def test_decode_duration(self):
        """디코딩된 오디오 길이 계산"""
        decoder = G711MuLawDecoder()
        
        # 160 bytes μ-law = 160 samples = 20ms @ 8kHz
        ulaw_data = b'\xFF' * 160  # Silence in μ-law
        
        decoded = decoder.decode(ulaw_data)
        
        # 160 samples @ 8000Hz = 20ms
        duration_ms = decoded.get_duration_ms()
        assert 19.5 <= duration_ms <= 20.5  # 허용 오차
    
    def test_decode_realistic_frame(self):
        """실제 G.711 프레임 크기 테스트"""
        decoder = G711MuLawDecoder()
        
        # G.711: 20ms frame = 160 samples @ 8kHz = 160 bytes
        frame_size = 160
        
        # 샘플 μ-law 데이터
        ulaw_data = bytes([0xFF] * frame_size)  # μ-law encoded silence
        
        decoded = decoder.decode(ulaw_data)
        
        assert len(decoded.pcm_data) == frame_size * 2  # 16-bit = 2 bytes per sample
        assert decoded.get_num_samples() == frame_size


class TestDecoderFactory:
    """디코더 팩토리 테스트"""
    
    def test_get_pcmu_decoder(self):
        """PCMU (PT=0) 디코더 생성"""
        decoder = get_decoder_for_payload_type(0)
        
        assert decoder is not None
        assert isinstance(decoder, G711MuLawDecoder)
        assert decoder.get_decoder_type() == DecoderType.G711_MULAW
    
    def test_get_pcma_decoder(self):
        """PCMA (PT=8) 디코더 생성"""
        decoder = get_decoder_for_payload_type(8)
        
        assert decoder is not None
        assert isinstance(decoder, G711ALawDecoder)
        assert decoder.get_decoder_type() == DecoderType.G711_ALAW
    
    def test_unsupported_payload_type(self):
        """지원하지 않는 Payload Type"""
        decoder = get_decoder_for_payload_type(99)
        
        assert decoder is None
    
    def test_custom_sample_rate(self):
        """커스텀 샘플링 레이트"""
        decoder = get_decoder_for_payload_type(0, sample_rate=16000)
        
        assert decoder is not None
        assert decoder.sample_rate == 16000


class TestG711Performance:
    """G.711 디코딩 성능 테스트"""
    
    def test_decode_performance(self):
        """디코딩 성능: 1초 오디오 → 50ms 이내"""
        import time
        
        decoder = G711MuLawDecoder()
        
        # 1초 오디오 = 8000 samples = 8000 bytes (μ-law)
        # 20ms 프레임 50개
        frame_count = 50
        frame_size = 160
        
        total_data = bytes([0xFF] * (frame_count * frame_size))
        
        start_time = time.perf_counter()
        
        # 프레임별로 디코딩
        for i in range(frame_count):
            frame = total_data[i*frame_size:(i+1)*frame_size]
            decoded = decoder.decode(frame)
            assert len(decoded.pcm_data) == frame_size * 2
        
        end_time = time.perf_counter()
        elapsed_ms = (end_time - start_time) * 1000
        
        # 1초 오디오를 50ms 이내에 디코딩
        assert elapsed_ms < 50, f"Decoding too slow: {elapsed_ms:.2f}ms"
        
        print(f"\nG.711 디코딩 성능: 1초 오디오 → {elapsed_ms:.2f}ms")


class TestDecodedAudio:
    """DecodedAudio 데이터 클래스 테스트"""
    
    def test_decoded_audio_properties(self):
        """DecodedAudio 속성 테스트"""
        from src.media.codec.decoder import DecodedAudio
        
        # 160 samples @ 8kHz = 20ms
        pcm_data = b'\x00\x00' * 160  # 16-bit samples
        
        decoded = DecodedAudio(
            pcm_data=pcm_data,
            sample_rate=8000,
            channels=1,
            bits_per_sample=16,
        )
        
        assert decoded.get_num_samples() == 160
        assert 19.5 <= decoded.get_duration_ms() <= 20.5
    
    def test_stereo_audio(self):
        """스테레오 오디오"""
        from src.media.codec.decoder import DecodedAudio
        
        # 160 samples per channel, stereo = 320 samples total
        pcm_data = b'\x00\x00' * 320
        
        decoded = DecodedAudio(
            pcm_data=pcm_data,
            sample_rate=8000,
            channels=2,
            bits_per_sample=16,
        )
        
        assert decoded.get_num_samples() == 160  # per channel
        assert 19.5 <= decoded.get_duration_ms() <= 20.5

