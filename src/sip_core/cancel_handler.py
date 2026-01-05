"""CANCEL Handler

CANCEL 메서드 처리 (RFC 3261)
통화 연결 전 INVITE 취소
"""

from typing import Optional, Tuple
from dataclasses import dataclass, field
from datetime import datetime

from src.sip_core.models.enums import SIPMethod, SIPResponseCode, Direction, CallState
from src.sip_core.models.call_session import CallSession
from src.common.logger import get_logger

logger = get_logger(__name__)


@dataclass
class CancelRequest:
    """CANCEL 요청 정보"""
    call_id: str
    from_direction: Direction
    reason: Optional[str] = None  # Reason 헤더
    timestamp: datetime = field(default_factory=datetime.utcnow)


class CANCELHandler:
    """CANCEL 핸들러
    
    통화 연결 전 INVITE 취소 처리:
    - CANCEL 수신 및 200 OK 응답
    - Pending INVITE에 대한 487 Request Terminated
    - Outgoing leg으로 CANCEL 전달
    - Dialog 종료 및 리소스 정리
    """
    
    def __init__(self):
        """초기화"""
        # Pending CANCEL (call_id -> CancelRequest)
        self.pending_cancels: dict[str, CancelRequest] = {}
        
        # Race condition 추적 (call_id -> bool)
        # CANCEL과 200 OK (for INVITE)가 거의 동시에 도착하는 경우
        self.race_conditions: dict[str, bool] = {}
        
        logger.info("cancel_handler_initialized")
    
    def handle_cancel_request(
        self,
        call_session: CallSession,
        from_direction: Direction,
        reason: Optional[str] = None,
    ) -> SIPResponseCode:
        """CANCEL 요청 처리
        
        Args:
            call_session: Call session
            from_direction: CANCEL을 보낸 방향
            reason: Reason 헤더 값 (optional)
            
        Returns:
            응답 코드 (200 OK for CANCEL)
        """
        # CANCEL 요청 등록
        cancel_req = CancelRequest(
            call_id=call_session.call_id,
            from_direction=from_direction,
            reason=reason,
        )
        
        self.pending_cancels[call_session.call_id] = cancel_req
        
        logger.info("cancel_request_received",
                   call_id=call_session.call_id,
                   from_direction=from_direction.value,
                   reason=reason,
                   call_state=call_session.state.value)
        
        # CANCEL은 오직 PROCEEDING, RINGING 상태에서만 유효
        if call_session.state not in [CallState.PROCEEDING, CallState.RINGING]:
            logger.warning("cancel_received_in_invalid_state",
                         call_id=call_session.call_id,
                         state=call_session.state.value)
            
            # 이미 연결되었거나 종료된 경우
            if call_session.state == CallState.ESTABLISHED:
                # Race condition: 200 OK가 먼저 도착
                self.race_conditions[call_session.call_id] = True
                logger.info("cancel_race_condition_200ok_first",
                          call_id=call_session.call_id)
                return SIPResponseCode.OK
            
            return SIPResponseCode.CALL_DOES_NOT_EXIST
        
        # CANCEL에 대해 즉시 200 OK 응답
        return SIPResponseCode.OK
    
    def should_send_487(self, call_session: CallSession) -> bool:
        """Pending INVITE에 대해 487을 보내야 하는지 확인
        
        Args:
            call_session: Call session
            
        Returns:
            487 전송 여부
        """
        if call_session.call_id not in self.pending_cancels:
            return False
        
        # Race condition이면 487을 보내지 않음
        if self.race_conditions.get(call_session.call_id, False):
            return False
        
        return True
    
    def get_cancel_reason(self, call_id: str) -> Optional[str]:
        """CANCEL의 Reason 헤더 조회
        
        Args:
            call_id: Call ID
            
        Returns:
            Reason 헤더 값
        """
        cancel_req = self.pending_cancels.get(call_id)
        return cancel_req.reason if cancel_req else None
    
    def handle_cancel_propagation(
        self,
        call_session: CallSession,
    ) -> bool:
        """Outgoing leg으로 CANCEL 전달 필요 여부
        
        Args:
            call_session: Call session
            
        Returns:
            CANCEL 전달 필요 여부
        """
        if call_session.call_id not in self.pending_cancels:
            return False
        
        # Outgoing leg이 이미 연결되었으면 전달하지 않음
        if call_session.state == CallState.ESTABLISHED:
            return False
        
        logger.info("cancel_propagation_needed",
                   call_id=call_session.call_id)
        
        return True
    
    def handle_cancel_response(
        self,
        call_session: CallSession,
        from_direction: Direction,
        response_code: int,
    ) -> None:
        """CANCEL 응답 처리 (outgoing leg에서)
        
        Args:
            call_session: Call session
            from_direction: 응답이 온 방향
            response_code: SIP 응답 코드
        """
        if response_code == 200:
            logger.info("cancel_response_success",
                       call_id=call_session.call_id,
                       from_direction=from_direction.value)
        else:
            logger.warning("cancel_response_failed",
                         call_id=call_session.call_id,
                         from_direction=from_direction.value,
                         response_code=response_code)
    
    def handle_487_response(
        self,
        call_session: CallSession,
        from_direction: Direction,
    ) -> None:
        """487 Request Terminated 응답 처리
        
        Args:
            call_session: Call session
            from_direction: 응답이 온 방향
        """
        logger.info("487_response_received",
                   call_id=call_session.call_id,
                   from_direction=from_direction.value)
        
        # CANCEL 완료 - 정리
        self.cleanup_call(call_session.call_id)
    
    def handle_200ok_race_condition(
        self,
        call_session: CallSession,
    ) -> bool:
        """200 OK (for INVITE)가 CANCEL과 거의 동시에 도착하는 경우
        
        Args:
            call_session: Call session
            
        Returns:
            Race condition 발생 여부
        """
        if call_session.call_id in self.pending_cancels:
            # CANCEL이 pending 중인데 200 OK가 도착
            self.race_conditions[call_session.call_id] = True
            
            logger.warning("cancel_race_condition_detected",
                         call_id=call_session.call_id,
                         call_state=call_session.state.value)
            
            # 200 OK를 우선하고 CANCEL은 무시
            # 하지만 caller에게는 487을 보내지 않고 200 OK를 전달
            return True
        
        return False
    
    def is_cancelled(self, call_id: str) -> bool:
        """통화가 취소되었는지 확인
        
        Args:
            call_id: Call ID
            
        Returns:
            취소 여부
        """
        return call_id in self.pending_cancels
    
    def cleanup_call(self, call_id: str) -> None:
        """호 종료 시 정리
        
        Args:
            call_id: Call ID
        """
        # Pending CANCEL 제거
        if call_id in self.pending_cancels:
            cancel_req = self.pending_cancels[call_id]
            logger.info("cancel_cleanup",
                       call_id=call_id,
                       reason=cancel_req.reason)
            del self.pending_cancels[call_id]
        
        # Race condition 추적 제거
        if call_id in self.race_conditions:
            del self.race_conditions[call_id]
    
    def get_stats(self) -> dict:
        """통계 조회
        
        Returns:
            CANCEL 핸들러 통계
        """
        return {
            "pending_cancels": len(self.pending_cancels),
            "race_conditions": len(self.race_conditions),
        }

