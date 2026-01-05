"""Session Cleaner 테스트"""

import pytest
from datetime import datetime, timedelta
from unittest.mock import Mock, patch

from src.media.session_cleaner import SessionCleaner
from src.media.session_manager import MediaSessionManager
from src.media.media_session import MediaSession, MediaLeg
from src.media.port_pool import PortPoolManager
from src.config.models import PortPoolConfig
from src.sip_core.models.enums import Direction
from src.common.logger import setup_logging


@pytest.fixture(scope="module", autouse=True)
def setup_test_logging():
    """테스트용 로깅 설정"""
    setup_logging(level="DEBUG", format_type="text")


@pytest.fixture
def port_pool():
    """포트 풀"""
    config = PortPoolConfig(start=10000, end=10100)
    return PortPoolManager(config=config)


@pytest.fixture
def media_session_manager(port_pool):
    """미디어 세션 관리자"""
    return MediaSessionManager(port_pool=port_pool)


@pytest.fixture
def session_cleaner(media_session_manager):
    """세션 정리기"""
    return SessionCleaner(
        media_session_manager=media_session_manager,
        rtp_timeout=60,
    )


class TestSessionCleaner:
    """SessionCleaner 테스트"""
    
    def test_cleaner_creation(self, session_cleaner):
        """정리기 생성 테스트"""
        assert session_cleaner is not None
        assert session_cleaner.rtp_timeout == 60
        assert session_cleaner.stats["cleaned_sessions"] == 0
    
    def test_find_stuck_sessions_empty(self, session_cleaner):
        """Stuck 세션 없음"""
        stuck_sessions = session_cleaner.find_stuck_sessions()
        
        assert len(stuck_sessions) == 0
    
    def test_find_stuck_session_no_rtp(self, session_cleaner, media_session_manager):
        """RTP를 한 번도 받지 못한 세션"""
        # 세션 생성
        sdp = "v=0\r\no=- 1 1 IN IP4 10.0.0.1\r\ns=-\r\nc=IN IP4 10.0.0.1\r\nt=0 0\r\nm=audio 20000 RTP/AVP 0\r\n"
        session = media_session_manager.create_session("call-1", sdp)
        
        # 생성 시간을 과거로 변경 (61초 전)
        session.created_at = datetime.utcnow() - timedelta(seconds=61)
        
        # Stuck 세션 찾기
        stuck_sessions = session_cleaner.find_stuck_sessions()
        
        assert len(stuck_sessions) == 1
        assert "call-1" in stuck_sessions
    
    def test_find_stuck_session_rtp_timeout(self, session_cleaner, media_session_manager):
        """RTP 타임아웃 발생"""
        # 세션 생성
        sdp = "v=0\r\no=- 1 1 IN IP4 10.0.0.1\r\ns=-\r\nc=IN IP4 10.0.0.1\r\nt=0 0\r\nm=audio 20000 RTP/AVP 0\r\n"
        session = media_session_manager.create_session("call-2", sdp)
        
        # RTP 수신 시간을 과거로 변경 (61초 전)
        past_time = datetime.utcnow() - timedelta(seconds=61)
        session.caller_leg.last_rtp_received = past_time
        session.started_at = past_time
        
        # Stuck 세션 찾기
        stuck_sessions = session_cleaner.find_stuck_sessions()
        
        assert len(stuck_sessions) == 1
        assert "call-2" in stuck_sessions
    
    def test_find_active_session_with_recent_rtp(self, session_cleaner, media_session_manager):
        """최근 RTP가 있는 활성 세션은 제외"""
        # 세션 생성
        sdp = "v=0\r\no=- 1 1 IN IP4 10.0.0.1\r\ns=-\r\nc=IN IP4 10.0.0.1\r\nt=0 0\r\nm=audio 20000 RTP/AVP 0\r\n"
        session = media_session_manager.create_session("call-3", sdp)
        
        # 최근 RTP 수신 (10초 전)
        session.update_rtp_received(from_caller=True)
        
        # Stuck 세션 찾기
        stuck_sessions = session_cleaner.find_stuck_sessions()
        
        assert len(stuck_sessions) == 0
    
    def test_cleanup_stuck_sessions(self, session_cleaner, media_session_manager):
        """Stuck 세션 정리"""
        # Stuck 세션 생성
        sdp = "v=0\r\no=- 1 1 IN IP4 10.0.0.1\r\ns=-\r\nc=IN IP4 10.0.0.1\r\nt=0 0\r\nm=audio 20000 RTP/AVP 0\r\n"
        session = media_session_manager.create_session("call-4", sdp)
        
        # 타임아웃 상태로 변경
        session.created_at = datetime.utcnow() - timedelta(seconds=61)
        
        assert media_session_manager.get_session("call-4") is not None
        
        # 정리
        cleaned_count = session_cleaner.cleanup_stuck_sessions()
        
        assert cleaned_count == 1
        assert media_session_manager.get_session("call-4") is None
        assert session_cleaner.stats["cleaned_sessions"] == 1
    
    def test_cleanup_multiple_stuck_sessions(self, session_cleaner, media_session_manager):
        """여러 Stuck 세션 정리"""
        sdp = "v=0\r\no=- 1 1 IN IP4 10.0.0.1\r\ns=-\r\nc=IN IP4 10.0.0.1\r\nt=0 0\r\nm=audio 20000 RTP/AVP 0\r\n"
        
        # Stuck 세션 3개 생성
        for i in range(3):
            session = media_session_manager.create_session(f"call-stuck-{i}", sdp)
            session.created_at = datetime.utcnow() - timedelta(seconds=61)
        
        # 활성 세션 1개 생성
        active_session = media_session_manager.create_session("call-active", sdp)
        active_session.update_rtp_received(from_caller=True)
        
        # 정리
        cleaned_count = session_cleaner.cleanup_stuck_sessions()
        
        assert cleaned_count == 3
        assert media_session_manager.get_session("call-active") is not None
    
    def test_get_stats(self, session_cleaner, media_session_manager):
        """통계 조회"""
        # 초기 통계
        stats = session_cleaner.get_stats()
        assert stats["cleaned_sessions"] == 0
        assert stats["rtp_timeout"] == 60
        assert stats["last_cleanup_time"] is None
        
        # Stuck 세션 정리
        sdp = "v=0\r\no=- 1 1 IN IP4 10.0.0.1\r\ns=-\r\nc=IN IP4 10.0.0.1\r\nt=0 0\r\nm=audio 20000 RTP/AVP 0\r\n"
        session = media_session_manager.create_session("call-5", sdp)
        session.created_at = datetime.utcnow() - timedelta(seconds=61)
        
        session_cleaner.cleanup_stuck_sessions()
        
        # 업데이트된 통계
        stats = session_cleaner.get_stats()
        assert stats["cleaned_sessions"] == 1
        assert stats["last_cleanup_time"] is not None
    
    def test_cleanup_with_no_stuck_sessions(self, session_cleaner):
        """Stuck 세션이 없을 때 정리"""
        cleaned_count = session_cleaner.cleanup_stuck_sessions()
        
        assert cleaned_count == 0
    
    def test_different_timeout_values(self, media_session_manager):
        """다양한 타임아웃 값"""
        # 30초 타임아웃
        cleaner_30s = SessionCleaner(
            media_session_manager=media_session_manager,
            rtp_timeout=30,
        )
        
        assert cleaner_30s.rtp_timeout == 30
        
        # 120초 타임아웃
        cleaner_120s = SessionCleaner(
            media_session_manager=media_session_manager,
            rtp_timeout=120,
        )
        
        assert cleaner_120s.rtp_timeout == 120


class TestPortExhaustionScenario:
    """포트 고갈 시나리오 테스트"""
    
    def test_port_exhaustion_detection(self):
        """포트 고갈 감지"""
        # 작은 포트 풀 (24개 포트 = 3개 호, 호당 8포트)
        config = PortPoolConfig(start=10000, end=10024)
        port_pool = PortPoolManager(config=config)
        
        max_calls = port_pool.get_max_concurrent_calls()
        assert max_calls == 3
        
        # 최대 호수까지 할당
        for i in range(max_calls):
            port_pool.allocate_ports(f"call-max-{i}")
        
        # 포트 사용률 확인
        utilization = port_pool.get_utilization()
        assert utilization >= 0.95
        
        # Low on ports 확인
        assert port_pool.is_low_on_ports(threshold=0.9) is True
        
        # 추가 할당 시도 (실패)
        from src.common.exceptions import PortPoolExhaustedError
        
        with pytest.raises(PortPoolExhaustedError):
            port_pool.allocate_ports("overflow-call")
    
    def test_port_recovery_after_release(self):
        """포트 반환 후 재사용"""
        config = PortPoolConfig(start=10000, end=10024)
        port_pool = PortPoolManager(config=config)
        
        max_calls = port_pool.get_max_concurrent_calls()
        
        # 최대 호수까지 할당
        for i in range(max_calls):
            port_pool.allocate_ports(f"call-{i}")
        
        # 포트 고갈
        assert port_pool.is_low_on_ports(threshold=0.9) is True
        
        # 일부 호 종료 (포트 반환)
        for i in range(3):
            port_pool.release_ports(f"call-{i}")
        
        # 포트 사용률 감소
        utilization = port_pool.get_utilization()
        assert utilization < 0.9
        
        # 새 호 할당 가능
        port_pool.allocate_ports("new-call-1")
        port_pool.allocate_ports("new-call-2")
        
        assert port_pool.get_active_call_count() == max_calls - 1

