"""Background Session Cleaner

백그라운드에서 주기적으로 Stuck 세션 정리
"""

import asyncio
from typing import Optional

from src.media.session_cleaner import SessionCleaner
from src.common.logger import get_logger

logger = get_logger(__name__)


class BackgroundSessionCleaner:
    """백그라운드 세션 정리기
    
    주기적으로 RTP 타임아웃된 세션을 검사하고 정리
    """
    
    def __init__(
        self,
        session_cleaner: SessionCleaner,
        check_interval: int = 10,
    ):
        """초기화
        
        Args:
            session_cleaner: 세션 정리기
            check_interval: 검사 주기 (초)
        """
        self.session_cleaner = session_cleaner
        self.check_interval = check_interval
        
        self._task: Optional[asyncio.Task] = None
        self._running = False
        
        logger.info("background_cleaner_initialized",
                   check_interval=check_interval,
                   rtp_timeout=session_cleaner.rtp_timeout)
    
    async def start(self) -> None:
        """백그라운드 정리 작업 시작"""
        if self._running:
            logger.warning("background_cleaner_already_running")
            return
        
        self._running = True
        self._task = asyncio.create_task(self._run())
        
        logger.info("background_cleaner_started",
                   check_interval=self.check_interval)
    
    async def stop(self) -> None:
        """백그라운드 정리 작업 중지"""
        if not self._running:
            return
        
        self._running = False
        
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        
        logger.info("background_cleaner_stopped")
    
    async def _run(self) -> None:
        """백그라운드 정리 루프"""
        logger.info("background_cleaner_loop_started")
        
        try:
            while self._running:
                try:
                    # Stuck 세션 정리
                    cleaned_count = self.session_cleaner.cleanup_stuck_sessions()
                    
                    if cleaned_count > 0:
                        logger.info("background_cleanup_executed",
                                  cleaned_count=cleaned_count)
                    
                    # 다음 검사까지 대기
                    await asyncio.sleep(self.check_interval)
                
                except Exception as e:
                    logger.error("background_cleanup_error",
                               error=str(e),
                               exc_info=True)
                    # 에러가 발생해도 계속 실행
                    await asyncio.sleep(self.check_interval)
        
        except asyncio.CancelledError:
            logger.info("background_cleaner_cancelled")
            raise
    
    def is_running(self) -> bool:
        """실행 중 여부
        
        Returns:
            실행 중이면 True
        """
        return self._running
    
    def get_stats(self) -> dict:
        """통계 조회
        
        Returns:
            백그라운드 정리기 통계
        """
        return {
            "is_running": self._running,
            "check_interval": self.check_interval,
            **self.session_cleaner.get_stats(),
        }

