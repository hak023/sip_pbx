"""Media Session Cleaner

Stuck 세션 감지 및 강제 종료
"""

from typing import List, Optional
from datetime import datetime

from src.media.session_manager import MediaSessionManager
from src.common.logger import get_logger

logger = get_logger(__name__)


class SessionCleaner:
    """미디어 세션 정리기
    
    RTP 타임아웃이 발생한 세션을 감지하고 정리
    """
    
    def __init__(
        self,
        media_session_manager: MediaSessionManager,
        rtp_timeout: int = 60,
    ):
        """초기화
        
        Args:
            media_session_manager: 미디어 세션 관리자
            rtp_timeout: RTP 타임아웃 (초)
        """
        self.media_session_manager = media_session_manager
        self.rtp_timeout = rtp_timeout
        
        # 통계
        self.stats = {
            "cleaned_sessions": 0,
            "last_cleanup_time": None,
        }
        
        logger.info("session_cleaner_initialized",
                   rtp_timeout=rtp_timeout)
    
    def find_stuck_sessions(self) -> List[str]:
        """Stuck 세션 찾기
        
        RTP 타임아웃이 발생한 세션들의 call_id 목록 반환
        
        Returns:
            Stuck 세션 call_id 목록
        """
        stuck_sessions = []
        
        for call_id, session in self.media_session_manager._sessions.items():
            # 활성 세션만 검사
            if not session.is_active():
                continue
            
            # 마지막 RTP 수신 이후 경과 시간 확인
            seconds_since_last_rtp = session.get_seconds_since_last_rtp()
            
            if seconds_since_last_rtp is None:
                # RTP를 한 번도 받지 못한 세션
                # 생성 후 일정 시간이 지났는지 확인
                age_seconds = int((datetime.utcnow() - session.created_at).total_seconds())
                
                if age_seconds > self.rtp_timeout:
                    logger.warning("stuck_session_no_rtp",
                                 call_id=call_id,
                                 age_seconds=age_seconds)
                    stuck_sessions.append(call_id)
            
            elif seconds_since_last_rtp > self.rtp_timeout:
                # RTP 타임아웃 발생
                logger.warning("stuck_session_rtp_timeout",
                             call_id=call_id,
                             seconds_since_last_rtp=seconds_since_last_rtp)
                stuck_sessions.append(call_id)
        
        return stuck_sessions
    
    def cleanup_stuck_sessions(self) -> int:
        """Stuck 세션 정리
        
        Returns:
            정리된 세션 수
        """
        stuck_sessions = self.find_stuck_sessions()
        
        cleaned_count = 0
        
        for call_id in stuck_sessions:
            try:
                destroyed = self.media_session_manager.destroy_session(call_id)
                
                if destroyed:
                    cleaned_count += 1
                    logger.info("stuck_session_cleaned",
                              call_id=call_id)
            
            except Exception as e:
                logger.error("stuck_session_cleanup_error",
                           call_id=call_id,
                           error=str(e))
        
        # 통계 업데이트
        self.stats["cleaned_sessions"] += cleaned_count
        self.stats["last_cleanup_time"] = datetime.utcnow()
        
        if cleaned_count > 0:
            logger.info("stuck_sessions_cleaned",
                       count=cleaned_count,
                       total_cleaned=self.stats["cleaned_sessions"])
        
        return cleaned_count
    
    def get_stats(self) -> dict:
        """통계 조회
        
        Returns:
            정리기 통계
        """
        return {
            **self.stats,
            "rtp_timeout": self.rtp_timeout,
        }

