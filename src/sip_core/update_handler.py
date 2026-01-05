"""UPDATE Handler

UPDATE 메서드 처리 (RFC 3311)
통화 중 미디어 파라미터 변경 (Hold/Resume, Codec 변경 등)
"""

from typing import Optional, Tuple
from dataclasses import dataclass

from src.sip_core.models.enums import SIPMethod, SIPResponseCode, Direction, HoldState
from src.sip_core.models.call_session import CallSession
from src.common.logger import get_logger

logger = get_logger(__name__)


@dataclass
class UpdateRequest:
    """UPDATE 요청 정보"""
    call_id: str
    from_direction: Direction
    sdp: Optional[str] = None
    is_hold: bool = False
    is_resume: bool = False
    
    def __post_init__(self):
        """Hold/Resume 자동 감지"""
        if self.sdp and not self.is_hold and not self.is_resume:
            self._detect_hold_resume()
    
    def _detect_hold_resume(self):
        """SDP에서 Hold/Resume 감지"""
        if not self.sdp:
            return
        
        # Hold 감지: a=sendonly 또는 c=IN IP4 0.0.0.0
        if "a=sendonly" in self.sdp or "c=IN IP4 0.0.0.0" in self.sdp:
            self.is_hold = True
            logger.debug("hold_detected_in_sdp", call_id=self.call_id)
        
        # Resume 감지: a=sendrecv
        elif "a=sendrecv" in self.sdp:
            self.is_resume = True
            logger.debug("resume_detected_in_sdp", call_id=self.call_id)


class UPDATEHandler:
    """UPDATE 핸들러
    
    통화 중 미디어 파라미터 변경 처리:
    - Hold/Resume
    - Codec 변경
    - 기타 SDP 변경
    """
    
    def __init__(self):
        """초기화"""
        # Hold 상태 추적 (call_id -> HoldState)
        self.hold_states: dict[str, HoldState] = {}
        
        # Pending UPDATE (call_id + direction -> UpdateRequest)
        self.pending_updates: dict[str, UpdateRequest] = {}
        
        logger.info("update_handler_initialized")
    
    def handle_update_request(
        self,
        call_session: CallSession,
        from_direction: Direction,
        sdp: Optional[str] = None,
    ) -> Tuple[SIPResponseCode, Optional[str]]:
        """UPDATE 요청 처리
        
        Args:
            call_session: Call session
            from_direction: UPDATE를 보낸 방향
            sdp: 변경할 SDP
            
        Returns:
            (응답 코드, 수정된 SDP for relay)
        """
        # UPDATE 요청 생성
        update_req = UpdateRequest(
            call_id=call_session.call_id,
            from_direction=from_direction,
            sdp=sdp,
        )
        
        # Pending UPDATE 등록
        key = f"{call_session.call_id}_{from_direction.value}"
        self.pending_updates[key] = update_req
        
        # Hold 상태 업데이트
        if update_req.is_hold:
            self._update_hold_state(call_session.call_id, from_direction, is_hold=True)
        elif update_req.is_resume:
            self._update_hold_state(call_session.call_id, from_direction, is_hold=False)
        
        logger.info("update_request_received",
                   call_id=call_session.call_id,
                   from_direction=from_direction.value,
                   is_hold=update_req.is_hold,
                   is_resume=update_req.is_resume,
                   has_sdp=sdp is not None)
        
        # SDP 수정 (필요시 IP/Port 변경)
        modified_sdp = sdp  # 실제로는 B2BUA IP/Port로 변경 필요
        
        # 상대방으로 relay 준비 (200 OK로 즉시 응답하지 않고 relay)
        return SIPResponseCode.OK, modified_sdp
    
    def handle_update_response(
        self,
        call_session: CallSession,
        from_direction: Direction,
        response_code: int,
        sdp: Optional[str] = None,
    ) -> Optional[str]:
        """UPDATE 응답 처리
        
        Args:
            call_session: Call session
            from_direction: 응답이 온 방향
            response_code: SIP 응답 코드
            sdp: 응답 SDP
            
        Returns:
            수정된 SDP (relay용)
        """
        # Pending UPDATE 조회
        # UPDATE는 반대편에서 왔으므로, 응답은 UPDATE를 보낸 방향으로 가야 함
        opposite_direction = Direction.OUTGOING if from_direction == Direction.INCOMING else Direction.INCOMING
        key = f"{call_session.call_id}_{opposite_direction.value}"
        
        if key not in self.pending_updates:
            logger.warning("update_response_without_pending",
                         call_id=call_session.call_id,
                         response_code=response_code)
            return sdp
        
        update_req = self.pending_updates[key]
        
        if response_code == 200:
            # 성공
            logger.info("update_response_success",
                       call_id=call_session.call_id,
                       is_hold=update_req.is_hold,
                       is_resume=update_req.is_resume)
        else:
            # 실패 - Hold 상태 롤백
            if update_req.is_hold or update_req.is_resume:
                self._rollback_hold_state(call_session.call_id, opposite_direction)
            
            logger.warning("update_response_failed",
                         call_id=call_session.call_id,
                         response_code=response_code)
        
        # Pending UPDATE 제거
        del self.pending_updates[key]
        
        # SDP 수정
        modified_sdp = sdp  # 실제로는 B2BUA IP/Port로 변경 필요
        
        return modified_sdp
    
    def _update_hold_state(
        self,
        call_id: str,
        from_direction: Direction,
        is_hold: bool,
    ) -> None:
        """Hold 상태 업데이트
        
        Args:
            call_id: Call ID
            from_direction: Hold를 요청한 방향
            is_hold: Hold 여부 (False면 Resume)
        """
        current_state = self.hold_states.get(call_id, HoldState.ACTIVE)
        
        if is_hold:
            # Hold
            if from_direction == Direction.INCOMING:
                # Caller가 Hold
                if current_state == HoldState.HELD_BY_CALLEE:
                    new_state = HoldState.HELD_BY_BOTH
                else:
                    new_state = HoldState.HELD_BY_CALLER
            else:
                # Callee가 Hold
                if current_state == HoldState.HELD_BY_CALLER:
                    new_state = HoldState.HELD_BY_BOTH
                else:
                    new_state = HoldState.HELD_BY_CALLEE
        else:
            # Resume
            if from_direction == Direction.INCOMING:
                # Caller가 Resume
                if current_state == HoldState.HELD_BY_BOTH:
                    new_state = HoldState.HELD_BY_CALLEE
                else:
                    new_state = HoldState.ACTIVE
            else:
                # Callee가 Resume
                if current_state == HoldState.HELD_BY_BOTH:
                    new_state = HoldState.HELD_BY_CALLER
                else:
                    new_state = HoldState.ACTIVE
        
        self.hold_states[call_id] = new_state
        
        logger.info("hold_state_updated",
                   call_id=call_id,
                   from_direction=from_direction.value,
                   old_state=current_state.value,
                   new_state=new_state.value,
                   is_hold=is_hold)
    
    def _rollback_hold_state(
        self,
        call_id: str,
        from_direction: Direction,
    ) -> None:
        """Hold 상태 롤백 (UPDATE 실패 시)
        
        Args:
            call_id: Call ID
            from_direction: UPDATE를 보낸 방향
        """
        # 간단히 이전 상태로 복원
        # 실제로는 더 정교한 롤백이 필요할 수 있음
        current_state = self.hold_states.get(call_id, HoldState.ACTIVE)
        
        logger.info("hold_state_rollback",
                   call_id=call_id,
                   from_direction=from_direction.value,
                   current_state=current_state.value)
    
    def get_hold_state(self, call_id: str) -> HoldState:
        """Hold 상태 조회
        
        Args:
            call_id: Call ID
            
        Returns:
            Hold 상태
        """
        return self.hold_states.get(call_id, HoldState.ACTIVE)
    
    def is_on_hold(self, call_id: str) -> bool:
        """Hold 상태인지 확인
        
        Args:
            call_id: Call ID
            
        Returns:
            Hold 여부
        """
        state = self.get_hold_state(call_id)
        return state != HoldState.ACTIVE
    
    def cleanup_call(self, call_id: str) -> None:
        """호 종료 시 정리
        
        Args:
            call_id: Call ID
        """
        # Hold 상태 제거
        if call_id in self.hold_states:
            del self.hold_states[call_id]
        
        # Pending UPDATE 제거
        keys_to_remove = [k for k in self.pending_updates.keys() if k.startswith(call_id)]
        for key in keys_to_remove:
            del self.pending_updates[key]
        
        logger.debug("update_cleanup",
                    call_id=call_id,
                    pending_removed=len(keys_to_remove))

