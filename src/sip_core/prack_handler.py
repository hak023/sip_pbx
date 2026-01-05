"""PRACK Handler

PRACK (Provisional Response Acknowledgement) 처리
RFC 3262 - Reliability of Provisional Responses in SIP
"""

from typing import Optional
from dataclasses import dataclass

from src.sip_core.models.enums import SIPMethod, SIPResponseCode, Direction
from src.sip_core.models.call_session import CallSession, Leg
from src.common.logger import get_logger

logger = get_logger(__name__)


@dataclass
class ReliableProvisionalResponse:
    """신뢰성 있는 Provisional Response (183 등)
    
    RSeq와 함께 전송되며 PRACK로 확인되어야 함
    """
    call_id: str
    leg: Leg
    response_code: int
    rseq: int  # Reliable Sequence Number
    cseq: int  # CSeq 번호
    cseq_method: str  # CSeq 메서드 (INVITE 등)
    sdp: Optional[str] = None  # Early media SDP
    
    def needs_prack(self) -> bool:
        """PRACK가 필요한 응답인지"""
        return True  # 183은 항상 PRACK 필요


class PRACKHandler:
    """PRACK 핸들러
    
    183 Session Progress와 같은 신뢰성 있는 provisional response 처리
    """
    
    def __init__(self):
        """초기화"""
        # RSeq 추적 (call_id -> current rseq)
        self.rseq_tracker: dict[str, int] = {}
        
        # Pending PRACK (call_id + leg -> ReliableProvisionalResponse)
        self.pending_prack: dict[str, ReliableProvisionalResponse] = {}
        
        logger.info("prack_handler_initialized")
    
    def generate_rseq(self, call_id: str) -> int:
        """새로운 RSeq 번호 생성
        
        Args:
            call_id: Call ID
            
        Returns:
            RSeq 번호 (1부터 시작)
        """
        if call_id not in self.rseq_tracker:
            self.rseq_tracker[call_id] = 1
        else:
            self.rseq_tracker[call_id] += 1
        
        rseq = self.rseq_tracker[call_id]
        
        logger.debug("rseq_generated",
                    call_id=call_id,
                    rseq=rseq)
        
        return rseq
    
    def handle_183_session_progress(
        self,
        call_session: CallSession,
        from_direction: Direction,
        sdp: Optional[str] = None,
    ) -> tuple[int, Optional[str]]:
        """183 Session Progress 처리
        
        Args:
            call_session: Call session
            from_direction: 응답이 온 방향
            sdp: Early media SDP
            
        Returns:
            (RSeq, 수정된 SDP)
        """
        # RSeq 생성
        rseq = self.generate_rseq(call_session.call_id)
        
        # Pending PRACK 등록
        # 183을 보낸 측의 leg 정보를 저장
        # (PRACK는 반대편에서 오므로 응답한 leg를 저장)
        if from_direction == Direction.OUTGOING:
            # Callee가 보낸 183 → 이 183에 대한 PRACK는 Caller가 보냄
            # 따라서 outgoing leg 정보 저장
            response_leg = call_session.outgoing_leg
            # Key는 PRACK를 보낼 leg (incoming)으로 생성
            key_leg = call_session.incoming_leg
        else:
            # Caller가 보낸 183 (드물지만 가능)
            response_leg = call_session.incoming_leg
            key_leg = call_session.outgoing_leg
        
        response = ReliableProvisionalResponse(
            call_id=call_session.call_id,
            leg=response_leg,
            response_code=183,
            rseq=rseq,
            cseq=response_leg.cseq,
            cseq_method=SIPMethod.INVITE.value,
            sdp=sdp,
        )
        
        key = f"{call_session.call_id}_{key_leg.tag}_{rseq}"
        self.pending_prack[key] = response
        
        logger.info("183_session_progress_sent",
                   call_id=call_session.call_id,
                   rseq=rseq,
                   has_sdp=sdp is not None,
                   direction=from_direction.value,
                   key=key)
        
        # Early media SDP 처리 (필요시 IP/Port 변경)
        modified_sdp = sdp  # 실제로는 SDP 변경 필요
        
        return rseq, modified_sdp
    
    def handle_prack_request(
        self,
        call_session: CallSession,
        from_direction: Direction,
        rack_header: str,
    ) -> Optional[SIPResponseCode]:
        """PRACK 요청 처리
        
        Args:
            call_session: Call session
            from_direction: PRACK를 보낸 방향
            rack_header: RAck 헤더 값 (예: "1 1 INVITE")
            
        Returns:
            응답 코드 (200 OK 또는 에러)
        """
        try:
            # RAck 헤더 파싱: "rseq cseq method"
            parts = rack_header.split()
            if len(parts) != 3:
                logger.error("invalid_rack_header",
                           call_id=call_session.call_id,
                           rack=rack_header)
                return SIPResponseCode.BAD_REQUEST
            
            rseq = int(parts[0])
            cseq = int(parts[1])
            method = parts[2]
            
            # Pending PRACK 확인
            if from_direction == Direction.INCOMING:
                # Caller가 보낸 PRACK
                leg = call_session.incoming_leg
            else:
                # Callee가 보낸 PRACK (드물지만 가능)
                leg = call_session.outgoing_leg
            
            key = f"{call_session.call_id}_{leg.tag}_{rseq}"
            
            if key not in self.pending_prack:
                logger.warning("prack_without_pending_response",
                             call_id=call_session.call_id,
                             rseq=rseq)
                return SIPResponseCode.CALL_DOES_NOT_EXIST
            
            response = self.pending_prack[key]
            
            # RSeq/CSeq 검증
            if response.rseq != rseq:
                logger.error("prack_rseq_mismatch",
                           call_id=call_session.call_id,
                           expected=response.rseq,
                           received=rseq)
                return SIPResponseCode.BAD_REQUEST
            
            if response.cseq != cseq:
                logger.error("prack_cseq_mismatch",
                           call_id=call_session.call_id,
                           expected=response.cseq,
                           received=cseq)
                return SIPResponseCode.BAD_REQUEST
            
            # PRACK 성공
            del self.pending_prack[key]
            
            logger.info("prack_acknowledged",
                       call_id=call_session.call_id,
                       rseq=rseq,
                       cseq=cseq,
                       method=method)
            
            return SIPResponseCode.OK
        
        except Exception as e:
            logger.error("prack_processing_error",
                        call_id=call_session.call_id,
                        error=str(e))
            return SIPResponseCode.SERVER_INTERNAL_ERROR
    
    def check_supported_100rel(self, supported_header: Optional[str]) -> bool:
        """Supported 헤더에 100rel이 있는지 확인
        
        Args:
            supported_header: Supported 헤더 값
            
        Returns:
            100rel 지원 여부
        """
        if not supported_header:
            return False
        
        return "100rel" in supported_header.lower()
    
    def cleanup_call(self, call_id: str) -> None:
        """호 종료 시 정리
        
        Args:
            call_id: Call ID
        """
        # RSeq 추적 제거
        if call_id in self.rseq_tracker:
            del self.rseq_tracker[call_id]
        
        # Pending PRACK 제거
        keys_to_remove = [k for k in self.pending_prack.keys() if k.startswith(call_id)]
        for key in keys_to_remove:
            del self.pending_prack[key]
        
        logger.debug("prack_cleanup",
                    call_id=call_id,
                    pending_removed=len(keys_to_remove))
    
    def get_pending_prack_count(self, call_id: str) -> int:
        """Pending PRACK 개수 조회
        
        Args:
            call_id: Call ID
            
        Returns:
            Pending PRACK 수
        """
        return sum(1 for k in self.pending_prack.keys() if k.startswith(call_id))

