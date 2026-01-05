"""RTP Reflector 단위 테스트"""

import asyncio
import pytest
import struct
from src.media.rtp_reflector import RTPReflector, RTPEndpoint, AudioPacket
from src.media.media_session import MediaSession, MediaLeg, MediaMode
from src.sip_core.models.enums import Direction
from src.common.logger import setup_logging


@pytest.fixture(scope="module", autouse=True)
def setup_test_logging():
    """테스트용 로깅 설정"""
    setup_logging(level="DEBUG", format_type="text")


# 포트 카운터 (각 테스트마다 고유 포트)
_port_counter = 50000


@pytest.fixture
def media_session():
    """테스트용 미디어 세션 (각 테스트마다 고유 포트)"""
    global _port_counter
    
    caller_ports = [_port_counter, _port_counter + 1, _port_counter + 2, _port_counter + 3]
    _port_counter += 10
    
    callee_ports = [_port_counter, _port_counter + 1, _port_counter + 2, _port_counter + 3]
    _port_counter += 10
    
    caller_leg = MediaLeg(
        direction=Direction.INCOMING,
        original_sdp="v=0\r\no=- 1 1 IN IP4 10.0.0.1\r\ns=-\r\nc=IN IP4 10.0.0.1\r\nt=0 0\r\nm=audio 20000 RTP/AVP 0\r\na=rtpmap:0 PCMU/8000\r\n",
        allocated_ports=caller_ports
    )
    
    callee_leg = MediaLeg(
        direction=Direction.OUTGOING,
        original_sdp="v=0\r\no=- 2 2 IN IP4 10.0.0.2\r\ns=-\r\nc=IN IP4 10.0.0.2\r\nt=0 0\r\nm=audio 21000 RTP/AVP 0\r\na=rtpmap:0 PCMU/8000\r\n",
        allocated_ports=callee_ports
    )
    
    return MediaSession(
        call_id="test-call-reflector",
        mode=MediaMode.REFLECTING,
        caller_leg=caller_leg,
        callee_leg=callee_leg,
    )


@pytest.mark.asyncio
class TestRTPReflector:
    """RTP Reflector 테스트"""
    
    async def test_reflector_creation(self, media_session):
        """Reflector 생성 테스트"""
        caller_endpoint = RTPEndpoint(ip="127.0.0.1", port=30000)
        callee_endpoint = RTPEndpoint(ip="127.0.0.1", port=31000)
        
        reflector = RTPReflector(
            media_session=media_session,
            caller_endpoint=caller_endpoint,
            callee_endpoint=callee_endpoint,
        )
        
        assert reflector.analysis_queue is not None
        assert reflector.max_queue_size == 1000
        assert reflector.running is False
        assert reflector.stats["packets_queued_for_analysis"] == 0
    
    async def test_reflector_start_stop(self, media_session):
        """Reflector 시작/중지 테스트"""
        caller_endpoint = RTPEndpoint(ip="127.0.0.1", port=30000)
        callee_endpoint = RTPEndpoint(ip="127.0.0.1", port=31000)
        
        reflector = RTPReflector(
            media_session=media_session,
            caller_endpoint=caller_endpoint,
            callee_endpoint=callee_endpoint,
        )
        
        # 시작
        await reflector.start()
        assert reflector.running is True
        assert len(reflector.protocols) > 0
        
        # 중지
        await reflector.stop()
        assert reflector.running is False
    
    async def test_queue_for_analysis(self, media_session):
        """분석 큐로 패킷 전송 테스트"""
        caller_endpoint = RTPEndpoint(ip="127.0.0.1", port=32000)
        callee_endpoint = RTPEndpoint(ip="127.0.0.1", port=33000)
        
        reflector = RTPReflector(
            media_session=media_session,
            caller_endpoint=caller_endpoint,
            callee_endpoint=callee_endpoint,
        )
        
        # RTP 패킷 생성
        rtp_packet = self._create_rtp_packet(seq=100, ts=1000, ssrc=0x12345678)
        
        # 큐로 전송
        reflector._queue_for_analysis(rtp_packet, from_caller=True)
        
        # 검증
        assert reflector.get_queue_size() == 1
        assert reflector.stats["packets_queued_for_analysis"] == 1
        
        # 큐에서 가져오기
        audio_packet = await asyncio.wait_for(
            reflector.analysis_queue.get(),
            timeout=1.0
        )
        
        assert isinstance(audio_packet, AudioPacket)
        assert audio_packet.call_id == media_session.call_id
        assert audio_packet.from_caller is True
        assert audio_packet.get_ssrc() == 0x12345678
        assert audio_packet.get_timestamp() == 1000
        assert audio_packet.get_sequence() == 100
    
    async def test_bidirectional_queue(self, media_session):
        """양방향 패킷 큐 테스트"""
        caller_endpoint = RTPEndpoint(ip="127.0.0.1", port=34000)
        callee_endpoint = RTPEndpoint(ip="127.0.0.1", port=35000)
        
        reflector = RTPReflector(
            media_session=media_session,
            caller_endpoint=caller_endpoint,
            callee_endpoint=callee_endpoint,
        )
        
        # Caller → Callee
        caller_packet = self._create_rtp_packet(seq=1, ts=100, ssrc=0x11111111)
        reflector._queue_for_analysis(caller_packet, from_caller=True)
        
        # Callee → Caller
        callee_packet = self._create_rtp_packet(seq=2, ts=200, ssrc=0x22222222)
        reflector._queue_for_analysis(callee_packet, from_caller=False)
        
        # 검증
        assert reflector.get_queue_size() == 2
        
        # Caller 패킷
        audio1 = await reflector.analysis_queue.get()
        assert audio1.from_caller is True
        assert audio1.get_ssrc() == 0x11111111
        
        # Callee 패킷
        audio2 = await reflector.analysis_queue.get()
        assert audio2.from_caller is False
        assert audio2.get_ssrc() == 0x22222222
    
    async def test_queue_full_drops(self, media_session):
        """큐 가득 찬 경우 드롭 테스트"""
        caller_endpoint = RTPEndpoint(ip="127.0.0.1", port=36000)
        callee_endpoint = RTPEndpoint(ip="127.0.0.1", port=37000)
        
        # 작은 큐 크기
        reflector = RTPReflector(
            media_session=media_session,
            caller_endpoint=caller_endpoint,
            callee_endpoint=callee_endpoint,
            max_queue_size=5,
        )
        
        # 큐 크기보다 많은 패킷 전송
        for i in range(10):
            rtp_packet = self._create_rtp_packet(seq=i, ts=i*160, ssrc=0x12345678)
            reflector._queue_for_analysis(rtp_packet, from_caller=True)
        
        # 검증
        assert reflector.get_queue_size() == 5  # 최대 5개
        assert reflector.stats["packets_queued_for_analysis"] == 5
        assert reflector.stats["queue_full_drops"] == 5  # 5개 드롭
    
    async def test_invalid_rtp_packet(self, media_session):
        """유효하지 않은 RTP 패킷 처리"""
        caller_endpoint = RTPEndpoint(ip="127.0.0.1", port=38000)
        callee_endpoint = RTPEndpoint(ip="127.0.0.1", port=39000)
        
        reflector = RTPReflector(
            media_session=media_session,
            caller_endpoint=caller_endpoint,
            callee_endpoint=callee_endpoint,
        )
        
        # 잘못된 패킷
        invalid_packet = b"not_an_rtp_packet"
        reflector._queue_for_analysis(invalid_packet, from_caller=True)
        
        # 검증
        assert reflector.get_queue_size() == 0
        assert reflector.stats["parse_errors"] == 1
    
    async def test_statistics(self, media_session):
        """통계 수집 테스트"""
        caller_endpoint = RTPEndpoint(ip="127.0.0.1", port=40000)
        callee_endpoint = RTPEndpoint(ip="127.0.0.1", port=41000)
        
        reflector = RTPReflector(
            media_session=media_session,
            caller_endpoint=caller_endpoint,
            callee_endpoint=callee_endpoint,
        )
        
        await reflector.start()
        
        # 수동으로 패킷 수신 시뮬레이션
        test_data = b"test_rtp_data"
        reflector.on_packet_received(
            "caller_audio_rtp",
            test_data,
            ("127.0.0.1", 20000),
            is_rtcp=False,
            from_caller=True,
        )
        
        # 통계 확인
        stats = reflector.get_stats()
        assert stats["caller_audio_packets"] == 1
        assert stats["total_bytes_relayed"] == len(test_data)
        
        await reflector.stop()
    
    async def test_rtcp_not_queued(self, media_session):
        """RTCP 패킷은 큐에 추가되지 않음"""
        caller_endpoint = RTPEndpoint(ip="127.0.0.1", port=42000)
        callee_endpoint = RTPEndpoint(ip="127.0.0.1", port=43000)
        
        reflector = RTPReflector(
            media_session=media_session,
            caller_endpoint=caller_endpoint,
            callee_endpoint=callee_endpoint,
        )
        
        await reflector.start()
        
        # RTCP 패킷 (PT=200)
        rtcp_data = bytearray()
        rtcp_data.append(0x80)  # V=2
        rtcp_data.append(200)   # PT=200 (RTCP SR)
        rtcp_data.extend(b'\x00' * 20)
        
        # RTCP는 큐에 추가 안됨
        reflector.on_packet_received(
            "caller_audio_rtcp",
            bytes(rtcp_data),
            ("127.0.0.1", 20001),
            is_rtcp=True,
            from_caller=True,
        )
        
        # 검증
        assert reflector.get_queue_size() == 0
        assert reflector.stats["packets_queued_for_analysis"] == 0
        
        await reflector.stop()
    
    # Helper methods
    
    def _create_rtp_packet(self, seq: int, ts: int, ssrc: int) -> bytes:
        """RTP 패킷 생성 헬퍼"""
        header = bytearray()
        header.append(0x80)  # V=2, P=0, X=0, CC=0
        header.append(0x00)  # M=0, PT=0 (PCMU)
        header.extend(struct.pack('!H', seq))
        header.extend(struct.pack('!I', ts))
        header.extend(struct.pack('!I', ssrc))
        
        payload = b'x' * 160  # 160 bytes = 20ms of PCMU audio
        
        return bytes(header) + payload


class TestAudioPacket:
    """AudioPacket 테스트"""
    
    def test_audio_packet_creation(self):
        """AudioPacket 생성 테스트"""
        from src.media.rtp_packet import RTPParser
        from datetime import datetime
        
        # RTP 패킷 생성
        header = bytearray()
        header.append(0x80)
        header.append(0x00)
        header.extend(struct.pack('!H', 123))
        header.extend(struct.pack('!I', 456))
        header.extend(struct.pack('!I', 0xABCDEF12))
        
        rtp_data = bytes(header) + b'payload_data'
        rtp_packet = RTPParser.parse(rtp_data)
        
        # AudioPacket 생성
        audio_packet = AudioPacket(
            call_id="test-call",
            from_caller=True,
            rtp_packet=rtp_packet,
            received_at=datetime.utcnow(),
        )
        
        # 검증
        assert audio_packet.call_id == "test-call"
        assert audio_packet.from_caller is True
        assert audio_packet.get_ssrc() == 0xABCDEF12
        assert audio_packet.get_timestamp() == 456
        assert audio_packet.get_sequence() == 123
        assert audio_packet.get_payload_type() == 0
        assert audio_packet.get_payload() == b'payload_data'

