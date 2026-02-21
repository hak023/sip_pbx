"""
Operator Status Manager

운영자 부재중 상태 관리
"""

from enum import Enum
from typing import Dict, Optional
from datetime import datetime
import structlog

logger = structlog.get_logger(__name__)


class OperatorStatus(str, Enum):
    """운영자 상태"""
    AVAILABLE = "available"
    AWAY = "away"  # 부재중 (AI 응대 모드)
    BUSY = "busy"
    OFFLINE = "offline"


class OperatorStatusManager:
    """운영자 상태 관리자 (인메모리)"""
    
    def __init__(self):
        self._status: Dict[str, OperatorStatus] = {}
        self._away_messages: Dict[str, str] = {}
        self._status_changed_at: Dict[str, datetime] = {}
        logger.info("OperatorStatusManager initialized")
    
    def set_status(
        self,
        user_id: str,
        status: OperatorStatus,
        away_message: Optional[str] = None
    ) -> None:
        """운영자 상태 설정
        
        Args:
            user_id: 사용자 ID (예: "1003", "1004")
            status: 운영자 상태
            away_message: 부재중 메시지 (AWAY 상태일 때만)
        """
        self._status[user_id] = status
        self._status_changed_at[user_id] = datetime.now()
        
        if status == OperatorStatus.AWAY and away_message:
            self._away_messages[user_id] = away_message
        elif status != OperatorStatus.AWAY:
            self._away_messages.pop(user_id, None)
        
        logger.info("operator_status_updated",
                   user_id=user_id,
                   status=status.value,
                   has_away_message=away_message is not None)
    
    def get_status(self, user_id: str) -> OperatorStatus:
        """운영자 상태 조회
        
        Args:
            user_id: 사용자 ID
            
        Returns:
            운영자 상태 (기본값: AVAILABLE)
        """
        return self._status.get(user_id, OperatorStatus.AVAILABLE)
    
    def is_away(self, user_id: str) -> bool:
        """부재중 상태 확인
        
        Args:
            user_id: 사용자 ID
            
        Returns:
            부재중 여부
        """
        return self.get_status(user_id) == OperatorStatus.AWAY
    
    def get_away_message(self, user_id: str) -> str:
        """부재중 메시지 조회
        
        Args:
            user_id: 사용자 ID
            
        Returns:
            부재중 메시지 (기본 메시지)
        """
        return self._away_messages.get(
            user_id,
            "죄송합니다. 현재 자리를 비웠습니다. AI 비서가 도와드리겠습니다."
        )
    
    def get_status_info(self, user_id: str) -> dict:
        """운영자 상태 상세 정보 조회
        
        Args:
            user_id: 사용자 ID
            
        Returns:
            상태 정보 딕셔너리
        """
        status = self.get_status(user_id)
        return {
            "user_id": user_id,
            "status": status.value,
            "is_away": status == OperatorStatus.AWAY,
            "away_message": self.get_away_message(user_id) if status == OperatorStatus.AWAY else None,
            "status_changed_at": self._status_changed_at.get(user_id)
        }
    
    def clear_status(self, user_id: str) -> None:
        """운영자 상태 초기화
        
        Args:
            user_id: 사용자 ID
        """
        self._status.pop(user_id, None)
        self._away_messages.pop(user_id, None)
        self._status_changed_at.pop(user_id, None)
        logger.info("operator_status_cleared", user_id=user_id)


# 싱글톤 인스턴스
_operator_status_manager: Optional[OperatorStatusManager] = None


def get_operator_status_manager() -> OperatorStatusManager:
    """운영자 상태 관리자 싱글톤 인스턴스 가져오기"""
    global _operator_status_manager
    if _operator_status_manager is None:
        _operator_status_manager = OperatorStatusManager()
    return _operator_status_manager
