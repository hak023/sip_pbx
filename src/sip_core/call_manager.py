"""Call Manager

통화 생명주기 관리
"""

from typing import Optional, Dict, Any
from datetime import datetime

from src.sip_core.models.call_session import CallSession, Leg
from src.sip_core.models.enums import CallState, Direction, SIPResponseCode
from src.repositories.call_state_repository import CallStateRepository
from src.media.session_manager import MediaSessionManager
from src.media.sdp_parser import SDPManipulator
from src.common.logger import get_logger
from src.common.exceptions import InvalidSIPMessageError, PortPoolExhaustedError

logger = get_logger(__name__)


class CallManager:
    """통화 생명주기 관리자
    
    INVITE, BYE 등 SIP 메시지 처리 및 CallSession 관리
    미디어 세션 관리 통합 (B2BUA SDP 수정)
    """
    
    def __init__(
        self,
        call_repository: CallStateRepository,
        media_session_manager: Optional[MediaSessionManager] = None,
        b2bua_ip: str = "127.0.0.1",
        ai_orchestrator = None,  # AI Orchestrator (optional)
        no_answer_timeout: int = 10,  # AI 활성화 타임아웃 (초)
    ):
        """초기화
        
        Args:
            call_repository: 통화 상태 저장소
            media_session_manager: 미디어 세션 관리자 (None이면 미디어 처리 비활성화)
            b2bua_ip: B2BUA IP 주소 (SDP에 사용)
            ai_orchestrator: AI Orchestrator (None이면 AI 기능 비활성화)
            no_answer_timeout: 부재중 타임아웃 시간 (초)
        """
        self.call_repository = call_repository
        self.media_session_manager = media_session_manager
        self.b2bua_ip = b2bua_ip
        
        # AI 보이스봇 지원
        self.ai_orchestrator = ai_orchestrator
        self.no_answer_timeout = no_answer_timeout
        self.ai_enabled_calls = set()  # AI 모드가 활성화된 통화 ID 집합
        
        logger.info("call_manager_initialized",
                   media_enabled=media_session_manager is not None,
                   b2bua_ip=b2bua_ip,
                   ai_enabled=ai_orchestrator is not None,
                   no_answer_timeout=no_answer_timeout)
    
    def handle_incoming_invite(
        self,
        from_uri: str,
        to_uri: str,
        call_id_header: str,
        contact: Optional[str] = None,
        sdp: Optional[str] = None,
    ) -> tuple[CallSession, int]:
        """수신 INVITE 처리
        
        Args:
            from_uri: SIP From URI
            to_uri: SIP To URI
            call_id_header: SIP Call-ID 헤더
            contact: SIP Contact 헤더
            sdp: SDP body
            
        Returns:
            tuple[CallSession, SIP 응답 코드]
            
        Raises:
            InvalidSIPMessageError: 잘못된 INVITE 메시지
        """
        # 1. 기본 검증
        if not from_uri or not to_uri or not call_id_header:
            logger.warning("invalid_invite_missing_headers",
                          from_uri=from_uri,
                          to_uri=to_uri,
                          call_id=call_id_header)
            raise InvalidSIPMessageError("Missing required headers: From, To, or Call-ID")
        
        # SDP 검증 (없으면 400 Bad Request)
        if not sdp:
            logger.warning("invalid_invite_no_sdp", call_id=call_id_header)
            raise InvalidSIPMessageError("INVITE must contain SDP")
        
        # 2. Incoming Leg 생성
        incoming_leg = Leg(
            direction=Direction.INCOMING,
            call_id_header=call_id_header,
            from_uri=from_uri,
            to_uri=to_uri,
            contact=contact,
            sdp_raw=sdp,
        )
        
        # 3. CallSession 생성
        call_session = CallSession(
            state=CallState.PROCEEDING,  # 100 Trying 상태
            incoming_leg=incoming_leg,
        )
        
        # 4. 미디어 세션 생성 (포트 할당)
        if self.media_session_manager:
            try:
                media_session = self.media_session_manager.create_session(
                    call_id=call_session.call_id,
                    caller_sdp=sdp,
                )
                logger.info("media_session_created_for_invite",
                           call_id=call_session.call_id,
                           caller_ports=media_session.caller_leg.allocated_ports)
            except PortPoolExhaustedError as e:
                logger.error("port_pool_exhausted_on_invite",
                           call_id=call_session.call_id,
                           error=str(e))
                # 503 Service Unavailable 반환
                return call_session, SIPResponseCode.SERVICE_UNAVAILABLE
        
        # 5. Repository에 저장
        self.call_repository.add(call_session)
        
        logger.info("invite_received",
                   call_id=call_session.call_id,
                   sip_call_id=call_id_header,
                   from_uri=from_uri,
                   to_uri=to_uri,
                   has_sdp=sdp is not None)
        
        # 6. 100 Trying 응답 코드 반환
        return call_session, SIPResponseCode.TRYING
    
    def get_session(self, call_id: str) -> Optional[CallSession]:
        """세션 조회
        
        Args:
            call_id: 통화 ID
            
        Returns:
            CallSession 또는 None
        """
        return self.call_repository.get(call_id)
    
    def get_session_by_sip_call_id(self, sip_call_id: str) -> Optional[CallSession]:
        """SIP Call-ID로 세션 조회
        
        Args:
            sip_call_id: SIP Call-ID 헤더 값
            
        Returns:
            CallSession 또는 None
        """
        return self.call_repository.find_by_sip_call_id(sip_call_id)
    
    def get_active_call_count(self) -> int:
        """활성 통화 수 반환
        
        Returns:
            활성 통화 개수
        """
        return self.call_repository.count_active()
    
    def create_outgoing_invite(
        self,
        call_session: CallSession,
        b2bua_contact: str,
    ) -> tuple[Leg, str]:
        """Outgoing INVITE 생성 (B2BUA → Callee)
        
        Args:
            call_session: 기존 통화 세션 (incoming leg 포함)
            b2bua_contact: B2BUA Contact URI (예: sip:pbx@192.168.1.1:5060)
            
        Returns:
            tuple[Leg, SDP]: (생성된 outgoing leg, 수정된 SDP)
            
        Raises:
            InvalidSIPMessageError: incoming leg가 없거나 SDP가 없는 경우
        """
        if not call_session.incoming_leg:
            raise InvalidSIPMessageError("No incoming leg found in call session")
        
        if not call_session.incoming_leg.sdp_raw:
            raise InvalidSIPMessageError("No SDP in incoming leg")
        
        incoming_leg = call_session.incoming_leg
        
        # Outgoing Leg 생성
        outgoing_leg = Leg(
            direction=Direction.OUTGOING,
            # Outgoing leg의 Call-ID는 새로 생성 (B2BUA이므로 독립적)
            call_id_header=f"outgoing-{call_session.call_id}",
            from_uri=b2bua_contact,  # From: B2BUA
            to_uri=incoming_leg.to_uri,  # To: 원래 destination
            contact=b2bua_contact,  # Contact: B2BUA
        )
        
        # SDP 수정 (B2BUA IP/Port로 변경)
        modified_sdp = incoming_leg.sdp_raw
        
        if self.media_session_manager:
            # 미디어 세션 조회
            media_session = self.media_session_manager.get_session(call_session.call_id)
            
            if media_session:
                # B2BUA IP로 Connection 변경
                modified_sdp = SDPManipulator.replace_connection_ip(modified_sdp, self.b2bua_ip)
                
                # Callee leg의 할당된 포트로 변경
                audio_port = media_session.callee_leg.get_audio_rtp_port()
                video_port = media_session.callee_leg.get_video_rtp_port()
                
                modified_sdp = SDPManipulator.replace_multiple_ports(
                    modified_sdp,
                    audio_port=audio_port,
                    video_port=video_port,
                )
                
                logger.info("sdp_modified_for_outgoing_invite",
                           call_id=call_session.call_id,
                           b2bua_ip=self.b2bua_ip,
                           audio_port=audio_port,
                           video_port=video_port)
        
        outgoing_leg.sdp_raw = modified_sdp
        
        # Call Session에 outgoing leg 추가
        call_session.outgoing_leg = outgoing_leg
        call_session.state = CallState.PROCEEDING
        
        # Repository 업데이트
        self.call_repository.update(call_session)
        
        logger.info("outgoing_invite_created",
                   call_id=call_session.call_id,
                   outgoing_call_id=outgoing_leg.call_id_header,
                   to_uri=outgoing_leg.to_uri,
                   from_uri=outgoing_leg.from_uri)
        
        return outgoing_leg, modified_sdp
    
    def handle_provisional_response(
        self,
        call_session: CallSession,
        response_code: int,
        reason: str = "",
    ) -> None:
        """Provisional 응답 처리 (180 Ringing, 183 Session Progress 등)
        
        Args:
            call_session: 통화 세션
            response_code: SIP 응답 코드 (1xx)
            reason: 응답 이유 (예: "Ringing")
        """
        if response_code == SIPResponseCode.RINGING:
            call_session.state = CallState.RINGING
        elif response_code == SIPResponseCode.SESSION_PROGRESS:
            call_session.state = CallState.PROCEEDING
        
        self.call_repository.update(call_session)
        
        logger.info("provisional_response_received",
                   call_id=call_session.call_id,
                   response_code=response_code,
                   reason=reason,
                   state=call_session.state.value)
    
    def handle_invite_timeout(
        self,
        call_session: CallSession,
        timeout_seconds: int = 30,
    ) -> int:
        """INVITE 타임아웃 처리
        
        Args:
            call_session: 통화 세션
            timeout_seconds: 타임아웃 시간 (초)
            
        Returns:
            SIP 응답 코드 (408 Request Timeout 또는 AI 활성화 시 다른 코드)
        """
        # AI 보이스봇 활성화 시도
        if self.ai_orchestrator and timeout_seconds <= self.no_answer_timeout:
            try:
                # AI 모드 활성화
                logger.info("no_answer_timeout_activating_ai",
                          call_id=call_session.call_id,
                          timeout_seconds=timeout_seconds)
                
                # AI 통화 시작 (비동기)
                import asyncio
                asyncio.create_task(
                    self.ai_orchestrator.handle_call(
                        call_id=call_session.call_id,
                        caller=call_session.get_caller_uri(),
                        callee=call_session.get_callee_uri()
                    )
                )
                
                # AI 활성화 통화로 표시
                self.ai_enabled_calls.add(call_session.call_id)
                
                # 통화 연결 상태로 전환
                call_session.mark_established()
                self.call_repository.update(call_session)
                
                logger.info("ai_mode_activated",
                          call_id=call_session.call_id)
                
                # 200 OK 반환 (AI가 응답)
                return SIPResponseCode.OK
                
            except Exception as e:
                logger.error("ai_activation_failed",
                           call_id=call_session.call_id,
                           error=str(e))
                # AI 활성화 실패 시 일반 타임아웃 처리
        
        # 일반 타임아웃 처리
        call_session.mark_failed(reason=f"timeout_after_{timeout_seconds}s")
        self.call_repository.update(call_session)
        
        logger.warning("invite_timeout",
                      call_id=call_session.call_id,
                      timeout_seconds=timeout_seconds)
        
        return SIPResponseCode.REQUEST_TIMEOUT
    
    def handle_200_ok_response(
        self,
        call_session: CallSession,
        sdp: str,
        from_direction: Direction,
    ) -> str:
        """200 OK 응답 처리
        
        Args:
            call_session: 통화 세션
            sdp: 응답에 포함된 SDP
            from_direction: 응답이 온 방향 (INCOMING 또는 OUTGOING)
            
        Returns:
            반대편으로 전달할 SDP
            
        Raises:
            InvalidSIPMessageError: SDP가 없거나 잘못된 경우
        """
        if not sdp:
            raise InvalidSIPMessageError("200 OK must contain SDP")
        
        # Outgoing leg에서 200 OK 수신 → Incoming leg에 전달
        if from_direction == Direction.OUTGOING:
            if not call_session.outgoing_leg:
                raise InvalidSIPMessageError("No outgoing leg in session")
            
            # Outgoing leg의 SDP 저장 (callee의 answer)
            call_session.outgoing_leg.sdp_raw = sdp
            
            logger.info("200_ok_received_from_outgoing",
                       call_id=call_session.call_id,
                       outgoing_call_id=call_session.outgoing_leg.call_id_header)
            
            # 미디어 세션에 Callee SDP 저장
            if self.media_session_manager:
                media_session = self.media_session_manager.get_session(call_session.call_id)
                if media_session:
                    self.media_session_manager.update_callee_sdp(call_session.call_id, sdp)
            
            # SDP를 incoming leg에 전달 (B2BUA IP/Port로 변경)
            modified_sdp = sdp
            
            if self.media_session_manager:
                media_session = self.media_session_manager.get_session(call_session.call_id)
                if media_session:
                    # B2BUA IP로 Connection 변경
                    modified_sdp = SDPManipulator.replace_connection_ip(modified_sdp, self.b2bua_ip)
                    
                    # Caller leg의 할당된 포트로 변경
                    audio_port = media_session.caller_leg.get_audio_rtp_port()
                    video_port = media_session.caller_leg.get_video_rtp_port()
                    
                    modified_sdp = SDPManipulator.replace_multiple_ports(
                        modified_sdp,
                        audio_port=audio_port,
                        video_port=video_port,
                    )
                    
                    logger.info("sdp_modified_for_200_ok_to_caller",
                               call_id=call_session.call_id,
                               b2bua_ip=self.b2bua_ip,
                               audio_port=audio_port,
                               video_port=video_port)
            
            return modified_sdp
        
        # Incoming leg에서 200 OK 수신 (일반적이지 않음, re-INVITE 시나리오)
        else:
            if not call_session.incoming_leg:
                raise InvalidSIPMessageError("No incoming leg in session")
            
            call_session.incoming_leg.sdp_raw = sdp
            
            logger.info("200_ok_received_from_incoming",
                       call_id=call_session.call_id)
            
            return sdp
    
    def handle_ack(
        self,
        call_session: CallSession,
        from_direction: Direction,
    ) -> None:
        """ACK 처리
        
        Args:
            call_session: 통화 세션
            from_direction: ACK가 온 방향 (INCOMING 또는 OUTGOING)
        """
        # Incoming leg에서 ACK 수신 → 통화 연결 완료
        if from_direction == Direction.INCOMING:
            # 통화 연결 상태로 전환
            call_session.mark_established()
            
            logger.info("ack_received_from_incoming",
                       call_id=call_session.call_id,
                       state=call_session.state.value,
                       answer_time=call_session.answer_time.isoformat() if call_session.answer_time else None)
        
        # Outgoing leg에서 ACK 수신 (re-INVITE 시나리오)
        else:
            logger.info("ack_received_from_outgoing",
                       call_id=call_session.call_id)
        
        # Repository 업데이트
        self.call_repository.update(call_session)
    
    def handle_bye(
        self,
        call_session: CallSession,
        from_direction: Direction,
        reason: str = "normal",
    ) -> int:
        """BYE 요청 처리 및 통화 종료
        
        Args:
            call_session: 통화 세션
            from_direction: BYE가 온 방향 (INCOMING 또는 OUTGOING)
            reason: 종료 이유 (예: "normal", "caller_hangup", "callee_hangup")
            
        Returns:
            SIP 응답 코드 (200 OK)
        """
        # 1. BYE 방향 로깅
        if from_direction == Direction.INCOMING:
            logger.info("bye_received_from_incoming",
                       call_id=call_session.call_id,
                       reason=reason)
        else:
            logger.info("bye_received_from_outgoing",
                       call_id=call_session.call_id,
                       reason=reason)
        
        # 2. 통화 종료 상태로 전환
        call_session.mark_terminated(reason=reason)
        
        # 3. Repository 업데이트
        self.call_repository.update(call_session)
        
        logger.info("call_terminated",
                   call_id=call_session.call_id,
                   duration_seconds=call_session.get_duration_seconds(),
                   reason=reason,
                   state=call_session.state.value)
        
        # 4. 200 OK 반환
        return SIPResponseCode.OK
    
    def cleanup_terminated_call(self, call_session: CallSession) -> Dict[str, Any]:
        """종료된 통화 정리 및 CDR 데이터 준비
        
        Args:
            call_session: 종료된 통화 세션
            
        Returns:
            CDR 데이터 딕셔너리
        """
        # AI 통화 종료 처리
        if call_session.call_id in self.ai_enabled_calls:
            if self.ai_orchestrator:
                try:
                    import asyncio
                    asyncio.create_task(self.ai_orchestrator.end_call())
                    logger.info("ai_call_ended", call_id=call_session.call_id)
                except Exception as e:
                    logger.error("ai_end_call_error",
                               call_id=call_session.call_id,
                               error=str(e))
            
            self.ai_enabled_calls.discard(call_session.call_id)
        
        # CDR 데이터 준비 (실제 CDR 생성은 Story 4.12)
        cdr_data = {
            "call_id": call_session.call_id,
            "caller_uri": call_session.get_caller_uri(),
            "callee_uri": call_session.get_callee_uri(),
            "start_time": call_session.start_time.isoformat() if call_session.start_time else None,
            "answer_time": call_session.answer_time.isoformat() if call_session.answer_time else None,
            "end_time": call_session.end_time.isoformat() if call_session.end_time else None,
            "duration_seconds": call_session.get_duration_seconds(),
            "termination_reason": call_session.termination_reason,
            "state": call_session.state.value,
            "is_ai_handled": call_session.call_id in self.ai_enabled_calls,
        }
        
        # 미디어 세션 정리 (포트 반환)
        if self.media_session_manager:
            destroyed = self.media_session_manager.destroy_session(call_session.call_id)
            if destroyed:
                logger.info("media_session_destroyed_on_cleanup",
                           call_id=call_session.call_id)
        
        # Repository에서 제거
        self.call_repository.remove(call_session.call_id)
        
        logger.info("call_cleanup_completed",
                   call_id=call_session.call_id,
                   duration=cdr_data["duration_seconds"])
        
        return cdr_data
    
    def parse_sdp_info(self, sdp: str) -> Dict[str, Any]:
        """SDP 기본 정보 파싱 (간단한 버전)
        
        Args:
            sdp: SDP 문자열
            
        Returns:
            파싱된 SDP 정보 딕셔너리
        """
        # TODO: 향후 상세 SDP 파서 구현 (Story 2.2)
        info = {
            "has_audio": "m=audio" in sdp,
            "has_video": "m=video" in sdp,
            "connection_ip": None,
            "media_port": None,
        }
        
        # c= 라인에서 IP 추출
        for line in sdp.split('\n'):
            line = line.strip()
            if line.startswith('c='):
                parts = line.split()
                if len(parts) >= 3:
                    info["connection_ip"] = parts[2]
            
            # m=audio 라인에서 포트 추출
            if line.startswith('m=audio'):
                parts = line.split()
                if len(parts) >= 2:
                    try:
                        info["media_port"] = int(parts[1])
                    except ValueError:
                        pass
        
        return info
    
    def is_ai_call(self, call_id: str) -> bool:
        """
        AI 모드 통화 여부 확인
        
        Args:
            call_id: 통화 ID
            
        Returns:
            AI 모드 통화 여부
        """
        return call_id in self.ai_enabled_calls
    
    def get_ai_stats(self) -> Dict[str, Any]:
        """
        AI 보이스봇 통계 반환
        
        Returns:
            통계 딕셔너리
        """
        return {
            "ai_enabled": self.ai_orchestrator is not None,
            "active_ai_calls": len(self.ai_enabled_calls),
            "no_answer_timeout": self.no_answer_timeout,
        }

