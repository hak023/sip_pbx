"""Media Session Manager 단위 테스트"""

import pytest
import time
from src.media.session_manager import MediaSessionManager
from src.media.media_session import MediaMode
from src.media.port_pool import PortPoolManager
from src.config.models import PortPoolConfig
from src.common.exceptions import PortPoolExhaustedError
from src.common.logger import setup_logging


@pytest.fixture(scope="module", autouse=True)
def setup_test_logging():
    """테스트용 로깅 설정"""
    setup_logging(level="DEBUG", format_type="text")


# 샘플 SDP들
CALLER_SDP = """v=0
o=caller 1 1 IN IP4 192.168.1.100
s=Call
c=IN IP4 192.168.1.100
t=0 0
m=audio 5004 RTP/AVP 0 8 101
a=rtpmap:0 PCMU/8000
a=rtpmap:8 PCMA/8000
a=rtpmap:101 telephone-event/8000
"""

CALLEE_SDP = """v=0
o=callee 2 2 IN IP4 192.168.1.200
s=Call
c=IN IP4 192.168.1.200
t=0 0
m=audio 6000 RTP/AVP 0 8
a=rtpmap:0 PCMU/8000
a=rtpmap:8 PCMA/8000
"""

CALLER_SDP_AV = """v=0
o=caller 3 3 IN IP4 192.168.1.100
s=Video Call
c=IN IP4 192.168.1.100
t=0 0
m=audio 5004 RTP/AVP 0
a=rtpmap:0 PCMU/8000
m=video 5006 RTP/AVP 96
a=rtpmap:96 H264/90000
"""


@pytest.fixture
def port_pool():
    """테스트용 Port Pool"""
    config = PortPoolConfig(start=10000, end=10100)
    return PortPoolManager(config)


@pytest.fixture
def session_manager(port_pool):
    """테스트용 Session Manager"""
    return MediaSessionManager(port_pool, default_mode=MediaMode.REFLECTING)


class TestMediaSessionManager:
    """Media Session Manager 기본 테스트"""
    
    def test_initialization(self, session_manager):
        """초기화 테스트"""
        assert session_manager is not None
        assert session_manager.default_mode == MediaMode.REFLECTING
        assert session_manager.get_session_count() == 0
    
    def test_create_session_success(self, session_manager):
        """세션 생성 성공 테스트"""
        call_id = "test-call-1"
        
        session = session_manager.create_session(call_id, CALLER_SDP)
        
        # 세션 검증
        assert session is not None
        assert session.call_id == call_id
        assert session.mode == MediaMode.REFLECTING
        assert session.is_active()
        
        # Caller leg 검증
        assert session.caller_leg is not None
        assert session.caller_leg.original_ip == "192.168.1.100"
        assert session.caller_leg.original_audio_port == 5004
        assert len(session.caller_leg.allocated_ports) == 4
        
        # Callee leg 검증 (아직 SDP 없음)
        assert session.callee_leg is not None
        assert len(session.callee_leg.allocated_ports) == 4
        assert session.callee_leg.original_sdp is None
        
        # 포트 할당 확인 (총 8개)
        all_ports = session.caller_leg.allocated_ports + session.callee_leg.allocated_ports
        assert len(all_ports) == 8
        assert len(set(all_ports)) == 8  # 중복 없음
    
    def test_create_session_duplicate(self, session_manager):
        """중복 call_id로 세션 생성 시도 (에러)"""
        call_id = "duplicate-call"
        
        session_manager.create_session(call_id, CALLER_SDP)
        
        with pytest.raises(ValueError) as exc_info:
            session_manager.create_session(call_id, CALLER_SDP)
        
        assert "already exists" in str(exc_info.value).lower()
    
    def test_create_session_with_audio_video(self, session_manager):
        """오디오+비디오 세션 생성"""
        call_id = "av-call"
        
        session = session_manager.create_session(call_id, CALLER_SDP_AV)
        
        assert session.caller_leg.original_audio_port == 5004
        assert session.caller_leg.original_video_port == 5006
    
    def test_update_callee_sdp(self, session_manager):
        """Callee SDP 업데이트"""
        call_id = "update-call"
        
        # 세션 생성
        session = session_manager.create_session(call_id, CALLER_SDP)
        assert session.callee_leg.original_sdp is None
        
        # Callee SDP 업데이트
        session_manager.update_callee_sdp(call_id, CALLEE_SDP)
        
        # 업데이트 확인
        session = session_manager.get_session(call_id)
        assert session.callee_leg.original_sdp is not None
        assert session.callee_leg.original_ip == "192.168.1.200"
        assert session.callee_leg.original_audio_port == 6000
    
    def test_update_callee_sdp_not_found(self, session_manager):
        """존재하지 않는 세션에 Callee SDP 업데이트 (에러)"""
        with pytest.raises(ValueError) as exc_info:
            session_manager.update_callee_sdp("non-existent", CALLEE_SDP)
        
        assert "not found" in str(exc_info.value).lower()
    
    def test_get_session(self, session_manager):
        """세션 조회"""
        call_id = "get-call"
        
        created = session_manager.create_session(call_id, CALLER_SDP)
        retrieved = session_manager.get_session(call_id)
        
        assert retrieved is not None
        assert retrieved.call_id == created.call_id
        
        # 존재하지 않는 세션
        not_found = session_manager.get_session("not-exists")
        assert not_found is None
    
    def test_destroy_session(self, session_manager):
        """세션 종료"""
        call_id = "destroy-call"
        
        # 생성
        session_manager.create_session(call_id, CALLER_SDP)
        assert session_manager.get_session_count() == 1
        
        # 종료
        result = session_manager.destroy_session(call_id)
        
        assert result is True
        assert session_manager.get_session_count() == 0
        assert session_manager.get_session(call_id) is None
    
    def test_destroy_session_not_found(self, session_manager):
        """존재하지 않는 세션 종료"""
        result = session_manager.destroy_session("not-exists")
        assert result is False
    
    def test_get_active_sessions(self, session_manager):
        """활성 세션 조회"""
        # 3개 생성
        for i in range(3):
            session_manager.create_session(f"active-{i}", CALLER_SDP)
        
        active = session_manager.get_active_sessions()
        assert len(active) == 3
        
        # 하나 종료
        session_manager.destroy_session("active-1")
        
        active = session_manager.get_active_sessions()
        assert len(active) == 2
    
    def test_update_rtp_received(self, session_manager):
        """RTP 수신 기록"""
        call_id = "rtp-call"
        
        session = session_manager.create_session(call_id, CALLER_SDP)
        assert session.started_at is None
        
        # Caller RTP 수신
        result = session_manager.update_rtp_received(call_id, from_caller=True)
        assert result is True
        
        session = session_manager.get_session(call_id)
        assert session.started_at is not None
        assert session.caller_leg.last_rtp_received is not None
        
        # Callee RTP 수신
        session_manager.update_rtp_received(call_id, from_caller=False)
        
        session = session_manager.get_session(call_id)
        assert session.callee_leg.last_rtp_received is not None
    
    def test_check_timeouts_no_rtp(self, session_manager):
        """RTP 미수신 타임아웃"""
        call_id = "timeout-no-rtp"
        
        session_manager.create_session(call_id, CALLER_SDP)
        
        # RTP를 한번도 받지 않았으므로 즉시 타임아웃
        timed_out = session_manager.check_timeouts(timeout_seconds=60)
        
        assert call_id in timed_out
    
    def test_check_timeouts_with_rtp(self, session_manager):
        """RTP 수신 후 타임아웃 체크"""
        call_id = "timeout-with-rtp"
        
        session = session_manager.create_session(call_id, CALLER_SDP)
        
        # RTP 수신
        session_manager.update_rtp_received(call_id, from_caller=True)
        
        # 짧은 타임아웃으로 체크 (아직 타임아웃 안됨)
        timed_out = session_manager.check_timeouts(timeout_seconds=1)
        assert call_id not in timed_out
        
        # 대기
        time.sleep(1.1)
        
        # 다시 체크 (타임아웃됨)
        timed_out = session_manager.check_timeouts(timeout_seconds=1)
        assert call_id in timed_out
    
    def test_get_stats(self, session_manager):
        """통계 정보"""
        # 초기 상태
        stats = session_manager.get_stats()
        assert stats["total_sessions"] == 0
        assert stats["active_sessions"] == 0
        
        # 세션 생성
        session_manager.create_session("stats-1", CALLER_SDP)
        session_manager.create_session("stats-2", CALLER_SDP)
        
        stats = session_manager.get_stats()
        assert stats["total_sessions"] == 2
        assert stats["active_sessions"] == 2
        assert stats["port_utilization"] > 0


class TestMediaSessionLifecycle:
    """미디어 세션 전체 생명주기 테스트"""
    
    def test_full_session_lifecycle(self, session_manager):
        """전체 세션 생명주기"""
        call_id = "full-lifecycle"
        
        # 1. 세션 생성 (INVITE)
        session = session_manager.create_session(call_id, CALLER_SDP)
        assert session.is_active()
        assert session.started_at is None
        
        # 2. Callee SDP 업데이트 (200 OK)
        session_manager.update_callee_sdp(call_id, CALLEE_SDP)
        
        session = session_manager.get_session(call_id)
        assert session.callee_leg.original_sdp is not None
        
        # 3. RTP 시작
        session_manager.update_rtp_received(call_id, from_caller=True)
        session_manager.update_rtp_received(call_id, from_caller=False)
        
        session = session_manager.get_session(call_id)
        assert session.started_at is not None
        
        # 4. 세션 종료 (BYE)
        session_manager.destroy_session(call_id)
        
        # 세션 삭제 확인
        assert session_manager.get_session(call_id) is None
        
        # 포트 반환 확인
        assert session_manager.port_pool.get_allocation(call_id) is None
    
    def test_multiple_sessions_concurrent(self, session_manager):
        """여러 세션 동시 관리"""
        call_ids = [f"concurrent-{i}" for i in range(5)]
        
        # 5개 세션 생성
        for call_id in call_ids:
            session_manager.create_session(call_id, CALLER_SDP)
        
        assert session_manager.get_session_count() == 5
        assert len(session_manager.get_active_sessions()) == 5
        
        # 각 세션에 RTP 수신
        for call_id in call_ids:
            session_manager.update_rtp_received(call_id, from_caller=True)
        
        # 일부 세션 종료
        session_manager.destroy_session(call_ids[0])
        session_manager.destroy_session(call_ids[2])
        
        assert session_manager.get_session_count() == 3
        assert len(session_manager.get_active_sessions()) == 3


class TestPortPoolIntegration:
    """Port Pool 통합 테스트"""
    
    def test_port_allocation_and_release(self, session_manager):
        """포트 할당 및 해제"""
        call_id = "port-test"
        
        initial_util = session_manager.port_pool.get_utilization()
        
        # 세션 생성 (포트 할당)
        session = session_manager.create_session(call_id, CALLER_SDP)
        
        assert session_manager.port_pool.get_utilization() > initial_util
        assert session_manager.port_pool.get_allocation(call_id) is not None
        
        # 세션 종료 (포트 반환)
        session_manager.destroy_session(call_id)
        
        assert session_manager.port_pool.get_utilization() == initial_util
        assert session_manager.port_pool.get_allocation(call_id) is None
    
    def test_port_exhaustion(self, session_manager):
        """포트 고갈 시나리오"""
        max_calls = session_manager.port_pool.get_max_concurrent_calls()
        
        # 최대까지 생성
        for i in range(max_calls):
            session_manager.create_session(f"exhaust-{i}", CALLER_SDP)
        
        # 추가 생성 시도 (실패)
        with pytest.raises(PortPoolExhaustedError):
            session_manager.create_session("overflow", CALLER_SDP)

