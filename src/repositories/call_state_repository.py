"""통화 상태 저장소

메모리 기반 CallSession 관리
"""

from typing import Dict, Optional, List
from threading import RLock

from src.sip_core.models.call_session import CallSession
from src.common.logger import get_logger

logger = get_logger(__name__)


class CallStateRepository:
    """통화 상태 저장소 (In-Memory)
    
    Thread-safe한 CallSession 관리
    """
    
    def __init__(self):
        """초기화"""
        self._sessions: Dict[str, CallSession] = {}
        self._lock = RLock()  # Reentrant lock (재진입 가능)
        
        logger.info("call_state_repository_initialized")
    
    def add(self, session: CallSession) -> None:
        """세션 추가
        
        Args:
            session: 통화 세션
        """
        with self._lock:
            self._sessions[session.call_id] = session
            logger.info("call_session_added",
                       call_id=session.call_id,
                       state=session.state.value)
    
    def get(self, call_id: str) -> Optional[CallSession]:
        """세션 조회
        
        Args:
            call_id: 통화 ID
            
        Returns:
            CallSession 또는 None
        """
        with self._lock:
            return self._sessions.get(call_id)
    
    def update(self, session: CallSession) -> None:
        """세션 업데이트
        
        Args:
            session: 통화 세션
        """
        with self._lock:
            if session.call_id in self._sessions:
                self._sessions[session.call_id] = session
                logger.debug("call_session_updated",
                           call_id=session.call_id,
                           state=session.state.value)
            else:
                logger.warning("call_session_not_found_for_update",
                             call_id=session.call_id)
    
    def remove(self, call_id: str) -> Optional[CallSession]:
        """세션 삭제
        
        Args:
            call_id: 통화 ID
            
        Returns:
            삭제된 CallSession 또는 None
        """
        with self._lock:
            session = self._sessions.pop(call_id, None)
            if session:
                logger.info("call_session_removed",
                           call_id=call_id,
                           duration=session.get_duration_seconds())
            return session
    
    def get_all(self) -> List[CallSession]:
        """모든 세션 조회
        
        Returns:
            CallSession 리스트
        """
        with self._lock:
            return list(self._sessions.values())
    
    def get_active_sessions(self) -> List[CallSession]:
        """활성 세션만 조회
        
        Returns:
            활성 CallSession 리스트
        """
        with self._lock:
            return [s for s in self._sessions.values() if s.is_active()]
    
    def count(self) -> int:
        """전체 세션 수
        
        Returns:
            세션 개수
        """
        with self._lock:
            return len(self._sessions)
    
    def count_active(self) -> int:
        """활성 세션 수
        
        Returns:
            활성 세션 개수
        """
        with self._lock:
            return sum(1 for s in self._sessions.values() if s.is_active())
    
    def find_by_sip_call_id(self, sip_call_id: str) -> Optional[CallSession]:
        """SIP Call-ID 헤더로 세션 검색
        
        Args:
            sip_call_id: SIP Call-ID 헤더 값
            
        Returns:
            CallSession 또는 None
        """
        with self._lock:
            for session in self._sessions.values():
                if session.incoming_leg and session.incoming_leg.call_id_header == sip_call_id:
                    return session
                if session.outgoing_leg and session.outgoing_leg.call_id_header == sip_call_id:
                    return session
            return None
    
    def clear(self) -> None:
        """모든 세션 삭제 (테스트용)"""
        with self._lock:
            count = len(self._sessions)
            self._sessions.clear()
            logger.info("call_state_repository_cleared", removed_count=count)

