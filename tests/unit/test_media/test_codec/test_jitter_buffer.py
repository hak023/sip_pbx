"""Jitter Buffer 테스트"""

import pytest
import struct
from datetime import datetime
from src.media.codec.jitter_buffer import JitterBuffer, JitterBufferEntry
from src.media.rtp_reflector import AudioPacket
from src.media.rtp_packet import RTPParser
from src.common.logger import setup_logging


@pytest.fixture(scope="module", autouse=True)
def setup_test_logging():
    """테스트용 로깅 설정"""
    setup_logging(level="DEBUG", format_type="text")


def create_audio_packet(seq: int, ts: int, ssrc: int = 0x12345678) -> AudioPacket:
    """테스트용 AudioPacket 생성
    
    Args:
        seq: Sequence number
        ts: Timestamp
        ssrc: SSRC
        
    Returns:
        AudioPacket
    """
    # RTP 패킷 생성
    header = bytearray()
    header.append(0x80)  # V=2, P=0, X=0, CC=0
    header.append(0x00)  # M=0, PT=0 (PCMU)
    header.extend(struct.pack('!H', seq))
    header.extend(struct.pack('!I', ts))
    header.extend(struct.pack('!I', ssrc))
    
    payload = b'x' * 160
    rtp_data = bytes(header) + payload
    
    rtp_packet = RTPParser.parse(rtp_data)
    
    return AudioPacket(
        call_id="test-call",
        from_caller=True,
        rtp_packet=rtp_packet,
        received_at=datetime.utcnow(),
    )


class TestJitterBuffer:
    """Jitter Buffer 테스트"""
    
    def test_buffer_creation(self):
        """버퍼 생성 테스트"""
        buffer = JitterBuffer(buffer_size=10, max_delay_ms=100)
        
        assert buffer.buffer_size == 10
        assert buffer.max_delay_ms == 100
        assert buffer.get_buffer_level() == 0
    
    def test_add_and_get_packet(self):
        """패킷 추가 및 가져오기"""
        buffer = JitterBuffer()
        
        # 패킷 추가
        packet1 = create_audio_packet(seq=100, ts=1000)
        buffer.add_packet(packet1)
        
        assert buffer.get_buffer_level() == 1
        
        # 첫 패킷 가져오기
        output = buffer.get_next_packet()
        assert output is not None
        assert output.get_sequence() == 100
        assert buffer.get_buffer_level() == 0
    
    def test_in_order_packets(self):
        """순서대로 도착한 패킷"""
        buffer = JitterBuffer()
        
        # 순서대로 추가
        for i in range(5):
            packet = create_audio_packet(seq=100+i, ts=1000+i*160)
            buffer.add_packet(packet)
        
        assert buffer.get_buffer_level() == 5
        
        # 순서대로 가져오기
        for i in range(5):
            output = buffer.get_next_packet()
            assert output is not None
            assert output.get_sequence() == 100 + i
    
    def test_out_of_order_packets(self):
        """순서가 뒤바뀐 패킷 (재정렬)"""
        buffer = JitterBuffer(max_delay_ms=50)
        
        # 순서: 100, 102, 101 (101이 늦게 도착)
        packet1 = create_audio_packet(seq=100, ts=1000)
        packet3 = create_audio_packet(seq=102, ts=1160)
        packet2 = create_audio_packet(seq=101, ts=1080)
        
        buffer.add_packet(packet1)
        buffer.add_packet(packet3)
        buffer.add_packet(packet2)
        
        # 첫 패킷
        output1 = buffer.get_next_packet()
        assert output1.get_sequence() == 100
        
        # 두 번째 패킷 (101이 도착했으므로 출력)
        output2 = buffer.get_next_packet()
        assert output2.get_sequence() == 101
        
        # 세 번째 패킷
        output3 = buffer.get_next_packet()
        assert output3.get_sequence() == 102
    
    def test_duplicate_packet(self):
        """중복 패킷 처리"""
        buffer = JitterBuffer()
        
        packet1 = create_audio_packet(seq=100, ts=1000)
        packet2 = create_audio_packet(seq=100, ts=1000)  # 중복
        
        buffer.add_packet(packet1)
        buffer.add_packet(packet2)
        
        # 하나만 버퍼에 있어야 함
        assert buffer.get_buffer_level() == 1
        
        stats = buffer.get_stats()
        assert stats["packets_dropped"] == 1
    
    def test_packet_loss_detection(self):
        """패킷 loss 감지"""
        buffer = JitterBuffer(packet_loss_threshold=3)
        
        # 100, 105 (101-104 loss)
        packet1 = create_audio_packet(seq=100, ts=1000)
        packet2 = create_audio_packet(seq=105, ts=1800)
        
        buffer.add_packet(packet1)
        buffer.add_packet(packet2)
        
        # 첫 패킷
        output1 = buffer.get_next_packet()
        assert output1.get_sequence() == 100
        
        # 두 번째 패킷 (loss 감지 후 출력)
        output2 = buffer.get_next_packet()
        assert output2.get_sequence() == 105
        
        stats = buffer.get_stats()
        assert stats["packet_losses_detected"] > 0
    
    def test_late_packet_dropped(self):
        """늦게 도착한 패킷 드롭"""
        buffer = JitterBuffer()
        
        # 순서: 100, 101, 99 (99가 늦게 도착)
        packet1 = create_audio_packet(seq=100, ts=1000)
        packet2 = create_audio_packet(seq=101, ts=1160)
        
        buffer.add_packet(packet1)
        buffer.add_packet(packet2)
        
        # 100, 101 출력
        output1 = buffer.get_next_packet()
        output2 = buffer.get_next_packet()
        
        assert output1.get_sequence() == 100
        assert output2.get_sequence() == 101
        
        # 99 추가 (이미 101까지 출력했으므로 늦은 패킷)
        packet_late = create_audio_packet(seq=99, ts=840)
        buffer.add_packet(packet_late)
        
        # 99는 드롭되어야 함
        output3 = buffer.get_next_packet()
        assert output3 is None  # 버퍼가 비어있음
        
        stats = buffer.get_stats()
        assert stats["packets_dropped"] > 0
    
    def test_buffer_overflow(self):
        """버퍼 오버플로우"""
        buffer = JitterBuffer(buffer_size=3)
        
        # 4개 추가 (버퍼 크기 3)
        for i in range(4):
            packet = create_audio_packet(seq=100+i, ts=1000+i*160)
            buffer.add_packet(packet)
        
        # 버퍼 크기 제한
        assert buffer.get_buffer_level() <= 3
        
        stats = buffer.get_stats()
        assert stats["packets_dropped"] > 0
    
    def test_flush_buffer(self):
        """버퍼 flush"""
        buffer = JitterBuffer()
        
        # 여러 패킷 추가
        for i in range(5):
            packet = create_audio_packet(seq=100+i, ts=1000+i*160)
            buffer.add_packet(packet)
        
        # Flush
        packets = buffer.flush()
        
        assert len(packets) == 5
        assert buffer.get_buffer_level() == 0
        
        # 순서대로 출력되었는지 확인
        for i, packet in enumerate(packets):
            assert packet.get_sequence() == 100 + i
    
    def test_reset_buffer(self):
        """버퍼 리셋"""
        buffer = JitterBuffer()
        
        # 패킷 추가
        for i in range(3):
            packet = create_audio_packet(seq=100+i, ts=1000+i*160)
            buffer.add_packet(packet)
        
        assert buffer.get_buffer_level() == 3
        
        # 리셋
        buffer.reset()
        
        assert buffer.get_buffer_level() == 0
        assert buffer.last_output_seq is None
    
    def test_sequence_wrap_around(self):
        """Sequence number wrap around (16-bit)"""
        buffer = JitterBuffer()
        
        # 순서대로 추가: 65534, 65535
        packet1 = create_audio_packet(seq=65534, ts=1000)
        packet2 = create_audio_packet(seq=65535, ts=1160)
        
        buffer.add_packet(packet1)
        buffer.add_packet(packet2)
        
        # 첫 두 패킷 출력
        output1 = buffer.get_next_packet()
        output2 = buffer.get_next_packet()
        
        assert output1.get_sequence() == 65534
        assert output2.get_sequence() == 65535
        
        # Wrap around 후: 0, 1
        packet3 = create_audio_packet(seq=0, ts=1320)
        packet4 = create_audio_packet(seq=1, ts=1480)
        
        buffer.add_packet(packet3)
        buffer.add_packet(packet4)
        
        # 다음 두 패킷 출력
        output3 = buffer.get_next_packet()
        output4 = buffer.get_next_packet()
        
        assert output3.get_sequence() == 0
        assert output4.get_sequence() == 1
    
    def test_statistics(self):
        """통계 수집"""
        buffer = JitterBuffer()
        
        # 패킷 추가
        for i in range(5):
            packet = create_audio_packet(seq=100+i, ts=1000+i*160)
            buffer.add_packet(packet)
        
        # 중복 패킷 (드롭되므로 버퍼에 추가 안됨)
        dup = create_audio_packet(seq=102, ts=1320)
        buffer.add_packet(dup)
        
        # 출력
        for _ in range(5):
            buffer.get_next_packet()
        
        stats = buffer.get_stats()
        assert stats["packets_buffered"] == 5  # 중복은 버퍼에 추가 안됨
        assert stats["packets_output"] == 5
        assert stats["packets_dropped"] == 1  # 중복


class TestJitterBufferHelpers:
    """Jitter Buffer 헬퍼 메서드 테스트"""
    
    def test_next_sequence(self):
        """다음 sequence number"""
        buffer = JitterBuffer()
        
        assert buffer._next_sequence(100) == 101
        assert buffer._next_sequence(65535) == 0  # Wrap around
    
    def test_is_older_sequence(self):
        """Sequence 비교"""
        buffer = JitterBuffer()
        
        # 100이 99보다 더 최신
        assert buffer._is_older_sequence(99, 100) is True
        assert buffer._is_older_sequence(100, 99) is False
        
        # Wrap around
        assert buffer._is_older_sequence(65535, 0) is True
        assert buffer._is_older_sequence(0, 65535) is False
    
    def test_sequence_diff(self):
        """Sequence 차이 계산"""
        buffer = JitterBuffer()
        
        assert buffer._sequence_diff(105, 100) == 5
        assert buffer._sequence_diff(100, 95) == 5
        
        # Wrap around
        diff = buffer._sequence_diff(2, 65534)
        assert diff == 4  # 65534, 65535, 0, 1, 2

