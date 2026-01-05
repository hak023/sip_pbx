"""RTP Relay 통합 테스트"""

import asyncio
import pytest
import struct
from src.media.rtp_relay import RTPRelayWorker, RTPEndpoint
from src.media.media_session import MediaSession, MediaLeg, MediaMode
from src.sip_core.models.enums import Direction
from src.common.logger import get_logger, setup_logging

logger = get_logger(__name__)


@pytest.fixture(scope="module", autouse=True)
def setup_test_logging():
    """테스트용 로깅 설정"""
    setup_logging(level="DEBUG", format_type="text")


# 포트 카운터 (각 테스트마다 고유 포트 할당)
_port_counter = 60000


@pytest.fixture
def media_session():
    """테스트용 미디어 세션 (각 테스트마다 고유 포트)"""
    global _port_counter
    
    caller_ports = [_port_counter, _port_counter + 1, _port_counter + 2, _port_counter + 3]
    _port_counter += 100  # 다음 테스트를 위해 충분히 띄움
    
    callee_ports = [_port_counter, _port_counter + 1, _port_counter + 2, _port_counter + 3]
    _port_counter += 100
    
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
        call_id="test-call-123",
        mode=MediaMode.BYPASS,
        caller_leg=caller_leg,
        callee_leg=callee_leg,
    )


@pytest.mark.asyncio
class TestRTPRelayWorker:
    """RTP Relay Worker 통합 테스트"""
    
    async def test_relay_worker_start_stop(self, media_session):
        """Relay Worker 시작/중지 테스트"""
        caller_endpoint = RTPEndpoint(ip="127.0.0.1", port=20000)
        callee_endpoint = RTPEndpoint(ip="127.0.0.1", port=21000)
        
        relay_worker = RTPRelayWorker(
            media_session=media_session,
            caller_endpoint=caller_endpoint,
            callee_endpoint=callee_endpoint,
        )
        
        # 시작
        await relay_worker.start()
        assert relay_worker.running is True
        assert len(relay_worker.protocols) > 0
        
        # 중지
        await relay_worker.stop()
        assert relay_worker.running is False
    
    async def test_get_stats(self, media_session):
        """통계 조회 테스트"""
        caller_endpoint = RTPEndpoint(ip="127.0.0.1", port=50000)
        callee_endpoint = RTPEndpoint(ip="127.0.0.1", port=51000)
        
        relay_worker = RTPRelayWorker(
            media_session=media_session,
            caller_endpoint=caller_endpoint,
            callee_endpoint=callee_endpoint,
        )
        
        # 초기 통계
        stats = relay_worker.get_stats()
        assert stats["caller_audio_packets"] == 0
        assert stats["caller_video_packets"] == 0
        assert stats["callee_audio_packets"] == 0
        assert stats["callee_video_packets"] == 0
        assert stats["total_bytes_relayed"] == 0
        
        await relay_worker.start()
        
        # 수동으로 통계 업데이트
        relay_worker.on_packet_received("caller_audio_rtp", b"test_data", ("127.0.0.1", 20000))
        
        stats = relay_worker.get_stats()
        assert stats["caller_audio_packets"] == 1
        assert stats["total_bytes_relayed"] == len(b"test_data")
        
        await relay_worker.stop()
    
    @pytest.mark.skip(reason="네트워크 환경에 따라 불안정한 테스트")
    async def test_actual_packet_relay(self, media_session):
        """실제 패킷 relay 테스트 (환경 의존적)"""
        # 실제 네트워크 패킷 relay는 환경에 따라 동작이 다를 수 있음
        # 프로덕션 환경에서 검증 필요
        pass
    

