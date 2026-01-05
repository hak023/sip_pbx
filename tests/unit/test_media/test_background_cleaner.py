"""Background Cleaner 테스트"""

import pytest
import asyncio
from datetime import datetime, timedelta

from src.media.background_cleaner import BackgroundSessionCleaner
from src.media.session_cleaner import SessionCleaner
from src.media.session_manager import MediaSessionManager
from src.media.port_pool import PortPoolManager
from src.config.models import PortPoolConfig
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
        rtp_timeout=5,  # 테스트용 짧은 타임아웃
    )


@pytest.fixture
def background_cleaner(session_cleaner):
    """백그라운드 정리기"""
    return BackgroundSessionCleaner(
        session_cleaner=session_cleaner,
        check_interval=1,  # 테스트용 짧은 주기
    )


class TestBackgroundSessionCleaner:
    """BackgroundSessionCleaner 테스트"""
    
    def test_cleaner_creation(self, background_cleaner):
        """정리기 생성 테스트"""
        assert background_cleaner is not None
        assert background_cleaner.check_interval == 1
        assert background_cleaner.is_running() is False
    
    @pytest.mark.asyncio
    async def test_start_stop(self, background_cleaner):
        """시작 및 중지 테스트"""
        # 시작
        await background_cleaner.start()
        
        assert background_cleaner.is_running() is True
        
        # 짧은 대기
        await asyncio.sleep(0.1)
        
        # 중지
        await background_cleaner.stop()
        
        assert background_cleaner.is_running() is False
    
    @pytest.mark.asyncio
    async def test_cleanup_execution(self, background_cleaner, media_session_manager):
        """정리 실행 테스트"""
        # Stuck 세션 생성
        sdp = "v=0\r\no=- 1 1 IN IP4 10.0.0.1\r\ns=-\r\nc=IN IP4 10.0.0.1\r\nt=0 0\r\nm=audio 20000 RTP/AVP 0\r\n"
        session = media_session_manager.create_session("call-bg-1", sdp)
        
        # 타임아웃 상태로 변경 (5초 타임아웃)
        session.created_at = datetime.utcnow() - timedelta(seconds=6)
        
        # 백그라운드 정리 시작
        await background_cleaner.start()
        
        # 정리 실행 대기 (1초 주기 + 여유)
        await asyncio.sleep(1.5)
        
        # 중지
        await background_cleaner.stop()
        
        # 세션이 정리되었는지 확인
        assert media_session_manager.get_session("call-bg-1") is None
    
    @pytest.mark.asyncio
    async def test_multiple_cleanup_cycles(self, background_cleaner, media_session_manager):
        """여러 정리 주기 테스트"""
        sdp = "v=0\r\no=- 1 1 IN IP4 10.0.0.1\r\ns=-\r\nc=IN IP4 10.0.0.1\r\nt=0 0\r\nm=audio 20000 RTP/AVP 0\r\n"
        
        # 백그라운드 정리 시작
        await background_cleaner.start()
        
        # 첫 번째 Stuck 세션
        session1 = media_session_manager.create_session("call-cycle-1", sdp)
        session1.created_at = datetime.utcnow() - timedelta(seconds=6)
        
        await asyncio.sleep(1.5)  # 첫 정리
        
        # 두 번째 Stuck 세션
        session2 = media_session_manager.create_session("call-cycle-2", sdp)
        session2.created_at = datetime.utcnow() - timedelta(seconds=6)
        
        await asyncio.sleep(1.5)  # 두 번째 정리
        
        # 중지
        await background_cleaner.stop()
        
        # 모두 정리되었는지 확인
        assert media_session_manager.get_session("call-cycle-1") is None
        assert media_session_manager.get_session("call-cycle-2") is None
    
    @pytest.mark.asyncio
    async def test_no_cleanup_for_active_sessions(self, background_cleaner, media_session_manager):
        """활성 세션은 정리하지 않음"""
        sdp = "v=0\r\no=- 1 1 IN IP4 10.0.0.1\r\ns=-\r\nc=IN IP4 10.0.0.1\r\nt=0 0\r\nm=audio 20000 RTP/AVP 0\r\n"
        
        # 활성 세션 생성
        session = media_session_manager.create_session("call-active-bg", sdp)
        session.update_rtp_received(from_caller=True)  # 최근 RTP 수신
        
        # 백그라운드 정리 시작
        await background_cleaner.start()
        
        await asyncio.sleep(1.5)
        
        # 중지
        await background_cleaner.stop()
        
        # 세션이 유지되었는지 확인
        assert media_session_manager.get_session("call-active-bg") is not None
    
    @pytest.mark.asyncio
    async def test_get_stats(self, background_cleaner, media_session_manager):
        """통계 조회"""
        # 초기 통계
        stats = background_cleaner.get_stats()
        assert stats["is_running"] is False
        assert stats["check_interval"] == 1
        assert stats["cleaned_sessions"] == 0
        
        # Stuck 세션 생성
        sdp = "v=0\r\no=- 1 1 IN IP4 10.0.0.1\r\ns=-\r\nc=IN IP4 10.0.0.1\r\nt=0 0\r\nm=audio 20000 RTP/AVP 0\r\n"
        session = media_session_manager.create_session("call-stats-bg", sdp)
        session.created_at = datetime.utcnow() - timedelta(seconds=6)
        
        # 백그라운드 정리 시작
        await background_cleaner.start()
        
        # 실행 중 통계
        stats = background_cleaner.get_stats()
        assert stats["is_running"] is True
        
        await asyncio.sleep(1.5)
        
        # 중지
        await background_cleaner.stop()
        
        # 최종 통계
        stats = background_cleaner.get_stats()
        assert stats["cleaned_sessions"] == 1
        assert stats["last_cleanup_time"] is not None
    
    @pytest.mark.asyncio
    async def test_double_start(self, background_cleaner):
        """중복 시작 방지"""
        await background_cleaner.start()
        
        # 두 번째 시작 (무시되어야 함)
        await background_cleaner.start()
        
        assert background_cleaner.is_running() is True
        
        await background_cleaner.stop()
    
    @pytest.mark.asyncio
    async def test_stop_without_start(self, background_cleaner):
        """시작하지 않고 중지 (에러 없어야 함)"""
        await background_cleaner.stop()
        
        assert background_cleaner.is_running() is False


class TestRTPTimeoutScenario:
    """RTP 타임아웃 시나리오 테스트"""
    
    @pytest.mark.asyncio
    async def test_full_rtp_timeout_flow(self, port_pool):
        """전체 RTP 타임아웃 흐름"""
        # 1. 세션 생성
        media_session_manager = MediaSessionManager(port_pool=port_pool)
        
        sdp = "v=0\r\no=- 1 1 IN IP4 10.0.0.1\r\ns=-\r\nc=IN IP4 10.0.0.1\r\nt=0 0\r\nm=audio 20000 RTP/AVP 0\r\n"
        session = media_session_manager.create_session("call-timeout-full", sdp)
        
        assert media_session_manager.get_session("call-timeout-full") is not None
        
        # 2. 정리기 설정
        session_cleaner = SessionCleaner(
            media_session_manager=media_session_manager,
            rtp_timeout=2,  # 2초 타임아웃
        )
        
        background_cleaner = BackgroundSessionCleaner(
            session_cleaner=session_cleaner,
            check_interval=1,  # 1초 주기
        )
        
        # 3. 백그라운드 정리 시작
        await background_cleaner.start()
        
        # 4. 타임아웃 상태로 변경
        session.created_at = datetime.utcnow() - timedelta(seconds=3)
        
        # 5. 정리 대기
        await asyncio.sleep(1.5)
        
        # 6. 세션이 정리되었는지 확인
        assert media_session_manager.get_session("call-timeout-full") is None
        
        # 7. 통계 확인
        stats = background_cleaner.get_stats()
        assert stats["cleaned_sessions"] >= 1
        
        # 8. 중지
        await background_cleaner.stop()
    
    @pytest.mark.asyncio
    async def test_session_with_recent_rtp_not_cleaned(self, port_pool):
        """최근 RTP가 있는 세션은 정리되지 않음"""
        media_session_manager = MediaSessionManager(port_pool=port_pool)
        
        sdp = "v=0\r\no=- 1 1 IN IP4 10.0.0.1\r\ns=-\r\nc=IN IP4 10.0.0.1\r\nt=0 0\r\nm=audio 20000 RTP/AVP 0\r\n"
        session = media_session_manager.create_session("call-rtp-recent", sdp)
        
        # 최근 RTP 수신
        session.update_rtp_received(from_caller=True)
        
        session_cleaner = SessionCleaner(
            media_session_manager=media_session_manager,
            rtp_timeout=2,
        )
        
        background_cleaner = BackgroundSessionCleaner(
            session_cleaner=session_cleaner,
            check_interval=1,
        )
        
        await background_cleaner.start()
        
        await asyncio.sleep(1.5)
        
        # 세션이 유지되었는지 확인
        assert media_session_manager.get_session("call-rtp-recent") is not None
        
        await background_cleaner.stop()

