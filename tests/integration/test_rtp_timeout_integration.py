"""RTP Timeout 통합 테스트

전체 RTP 타임아웃 흐름을 검증
"""

import pytest
import asyncio
from datetime import datetime, timedelta

from src.media.port_pool import PortPoolManager
from src.media.session_manager import MediaSessionManager
from src.media.session_cleaner import SessionCleaner
from src.media.background_cleaner import BackgroundSessionCleaner
from src.config.models import PortPoolConfig
from src.common.logger import setup_logging


@pytest.fixture(scope="module", autouse=True)
def setup_test_logging():
    """테스트용 로깅 설정"""
    setup_logging(level="INFO", format_type="text")


@pytest.fixture
def port_pool():
    """포트 풀"""
    config = PortPoolConfig(start=15000, end=15100)
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
        rtp_timeout=3,  # 통합 테스트용 짧은 타임아웃
    )


@pytest.fixture
def background_cleaner(session_cleaner):
    """백그라운드 정리기"""
    cleaner = BackgroundSessionCleaner(
        session_cleaner=session_cleaner,
        check_interval=1,  # 통합 테스트용 짧은 주기
    )
    yield cleaner
    # Cleanup after test
    if cleaner.is_running():
        asyncio.run(cleaner.stop())


class TestRTPTimeoutIntegration:
    """RTP 타임아웃 통합 테스트"""
    
    @pytest.mark.asyncio
    async def test_full_lifecycle_with_timeout(
        self,
        port_pool,
        media_session_manager,
        session_cleaner,
        background_cleaner,
    ):
        """전체 라이프사이클 (생성 -> 타임아웃 -> 정리)"""
        # 1. 세션 생성
        sdp = "v=0\r\no=- 1 1 IN IP4 192.168.1.100\r\ns=-\r\nc=IN IP4 192.168.1.100\r\nt=0 0\r\nm=audio 30000 RTP/AVP 0 8\r\n"
        
        session = media_session_manager.create_session("call-lifecycle-1", sdp)
        
        assert session is not None
        assert media_session_manager.get_session("call-lifecycle-1") is not None
        
        # 포트가 할당되었는지 확인
        assert len(session.caller_leg.allocated_ports) == 4
        assert len(session.callee_leg.allocated_ports) == 4
        
        initial_port_count = port_pool.get_active_call_count()
        assert initial_port_count == 1
        
        # 2. 백그라운드 정리 시작
        await background_cleaner.start()
        
        # 3. 세션을 타임아웃 상태로 변경
        session.created_at = datetime.utcnow() - timedelta(seconds=4)
        
        # 4. 정리 대기
        await asyncio.sleep(1.5)
        
        # 5. 세션이 정리되었는지 확인
        assert media_session_manager.get_session("call-lifecycle-1") is None
        
        # 6. 포트가 반환되었는지 확인
        assert port_pool.get_active_call_count() == 0
        
        # 7. 통계 확인
        stats = background_cleaner.get_stats()
        assert stats["cleaned_sessions"] >= 1
        
        # 8. 정리 중지
        await background_cleaner.stop()
    
    @pytest.mark.asyncio
    async def test_multiple_sessions_different_timeouts(
        self,
        media_session_manager,
        background_cleaner,
    ):
        """여러 세션, 다른 타임아웃"""
        sdp = "v=0\r\no=- 1 1 IN IP4 192.168.1.100\r\ns=-\r\nc=IN IP4 192.168.1.100\r\nt=0 0\r\nm=audio 30000 RTP/AVP 0\r\n"
        
        # 세션 1: 타임아웃됨
        session1 = media_session_manager.create_session("call-timeout-1", sdp)
        session1.created_at = datetime.utcnow() - timedelta(seconds=4)
        
        # 세션 2: 활성 (최근 RTP)
        session2 = media_session_manager.create_session("call-active-1", sdp)
        session2.update_rtp_received(from_caller=True)
        
        # 세션 3: 타임아웃됨
        session3 = media_session_manager.create_session("call-timeout-2", sdp)
        session3.created_at = datetime.utcnow() - timedelta(seconds=4)
        
        # 백그라운드 정리 시작
        await background_cleaner.start()
        
        await asyncio.sleep(1.5)
        
        # 타임아웃된 세션만 정리되었는지 확인
        assert media_session_manager.get_session("call-timeout-1") is None
        assert media_session_manager.get_session("call-active-1") is not None
        assert media_session_manager.get_session("call-timeout-2") is None
        
        # 정리 중지
        await background_cleaner.stop()
    
    @pytest.mark.asyncio
    async def test_session_receives_rtp_during_cleanup(
        self,
        media_session_manager,
        background_cleaner,
    ):
        """정리 중 RTP 수신 시 세션 유지"""
        sdp = "v=0\r\no=- 1 1 IN IP4 192.168.1.100\r\ns=-\r\nc=IN IP4 192.168.1.100\r\nt=0 0\r\nm=audio 30000 RTP/AVP 0\r\n"
        
        # 오래된 세션 생성
        session = media_session_manager.create_session("call-receives-rtp", sdp)
        session.created_at = datetime.utcnow() - timedelta(seconds=4)
        
        # 백그라운드 정리 시작
        await background_cleaner.start()
        
        # 정리 전에 RTP 수신
        session.update_rtp_received(from_caller=True)
        
        await asyncio.sleep(1.5)
        
        # 세션이 유지되었는지 확인
        assert media_session_manager.get_session("call-receives-rtp") is not None
        
        # 정리 중지
        await background_cleaner.stop()
    
    @pytest.mark.asyncio
    async def test_continuous_cleanup_over_time(
        self,
        media_session_manager,
        background_cleaner,
    ):
        """지속적인 정리 (여러 주기)"""
        sdp = "v=0\r\no=- 1 1 IN IP4 192.168.1.100\r\ns=-\r\nc=IN IP4 192.168.1.100\r\nt=0 0\r\nm=audio 30000 RTP/AVP 0\r\n"
        
        # 백그라운드 정리 시작
        await background_cleaner.start()
        
        # 주기 1: 세션 1 생성 및 타임아웃
        session1 = media_session_manager.create_session("call-cycle-1", sdp)
        session1.created_at = datetime.utcnow() - timedelta(seconds=4)
        
        await asyncio.sleep(1.5)
        assert media_session_manager.get_session("call-cycle-1") is None
        
        # 주기 2: 세션 2 생성 및 타임아웃
        session2 = media_session_manager.create_session("call-cycle-2", sdp)
        session2.created_at = datetime.utcnow() - timedelta(seconds=4)
        
        await asyncio.sleep(1.5)
        assert media_session_manager.get_session("call-cycle-2") is None
        
        # 주기 3: 세션 3 생성 및 타임아웃
        session3 = media_session_manager.create_session("call-cycle-3", sdp)
        session3.created_at = datetime.utcnow() - timedelta(seconds=4)
        
        await asyncio.sleep(1.5)
        assert media_session_manager.get_session("call-cycle-3") is None
        
        # 통계 확인
        stats = background_cleaner.get_stats()
        assert stats["cleaned_sessions"] >= 3
        
        # 정리 중지
        await background_cleaner.stop()
    
    @pytest.mark.asyncio
    async def test_port_pool_recovery_after_cleanup(
        self,
        port_pool,
        media_session_manager,
        session_cleaner,
        background_cleaner,
    ):
        """정리 후 포트 풀 복구"""
        sdp = "v=0\r\no=- 1 1 IN IP4 192.168.1.100\r\ns=-\r\nc=IN IP4 192.168.1.100\r\nt=0 0\r\nm=audio 30000 RTP/AVP 0\r\n"
        
        # 여러 세션 생성
        for i in range(5):
            session = media_session_manager.create_session(f"call-port-{i}", sdp)
            session.created_at = datetime.utcnow() - timedelta(seconds=4)
        
        initial_call_count = port_pool.get_active_call_count()
        assert initial_call_count == 5
        
        # 백그라운드 정리 시작
        await background_cleaner.start()
        
        await asyncio.sleep(1.5)
        
        # 모든 세션이 정리되었는지 확인
        for i in range(5):
            assert media_session_manager.get_session(f"call-port-{i}") is None
        
        # 포트가 모두 반환되었는지 확인
        assert port_pool.get_active_call_count() == 0
        
        # 새 세션을 생성할 수 있는지 확인
        new_session = media_session_manager.create_session("call-new-after-cleanup", sdp)
        assert new_session is not None
        assert port_pool.get_active_call_count() == 1
        
        # 정리 중지
        await background_cleaner.stop()


class TestManualCleanupTrigger:
    """수동 정리 트리거 테스트"""
    
    def test_manual_cleanup_trigger(self, media_session_manager):
        """수동으로 세션 정리 트리거"""
        sdp = "v=0\r\no=- 1 1 IN IP4 192.168.1.100\r\ns=-\r\nc=IN IP4 192.168.1.100\r\nt=0 0\r\nm=audio 30000 RTP/AVP 0\r\n"
        
        # 타임아웃된 세션 생성
        session = media_session_manager.create_session("call-manual-cleanup", sdp)
        session.created_at = datetime.utcnow() - timedelta(seconds=4)
        
        # 정리기 생성 및 수동 실행
        session_cleaner = SessionCleaner(
            media_session_manager=media_session_manager,
            rtp_timeout=3,
        )
        
        # 수동 정리 실행
        cleaned_count = session_cleaner.cleanup_stuck_sessions()
        
        assert cleaned_count == 1
        assert media_session_manager.get_session("call-manual-cleanup") is None
    
    def test_manual_cleanup_no_stuck_sessions(self, media_session_manager):
        """Stuck 세션이 없을 때 수동 정리"""
        sdp = "v=0\r\no=- 1 1 IN IP4 192.168.1.100\r\ns=-\r\nc=IN IP4 192.168.1.100\r\nt=0 0\r\nm=audio 30000 RTP/AVP 0\r\n"
        
        # 활성 세션 생성
        session = media_session_manager.create_session("call-active-manual", sdp)
        session.update_rtp_received(from_caller=True)
        
        session_cleaner = SessionCleaner(
            media_session_manager=media_session_manager,
            rtp_timeout=3,
        )
        
        # 수동 정리 실행 (아무것도 정리되지 않아야 함)
        cleaned_count = session_cleaner.cleanup_stuck_sessions()
        
        assert cleaned_count == 0
        assert media_session_manager.get_session("call-active-manual") is not None

