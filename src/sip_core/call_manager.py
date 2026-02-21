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
from src.events.cdr import CDR, CDRWriter

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
        recording_enabled: bool = True,  # 통화 녹음 활성화 여부
        recording_dir: str = "./recordings",  # 녹음 파일 저장 디렉토리
        knowledge_extractor = None,  # Knowledge Extractor (optional, 신규)
        gcp_credentials_path: Optional[str] = None,  # GCP 인증 파일 경로 (STT용)
        enable_post_stt: bool = True,  # 후처리 STT 활성화
        stt_language: str = "ko-KR",  # STT 언어
    ):
        """초기화
        
        Args:
            call_repository: 통화 상태 저장소
            media_session_manager: 미디어 세션 관리자 (None이면 미디어 처리 비활성화)
            b2bua_ip: B2BUA IP 주소 (SDP에 사용)
            ai_orchestrator: AI Orchestrator (None이면 AI 기능 비활성화)
            no_answer_timeout: 부재중 타임아웃 시간 (초)
            recording_enabled: 통화 녹음 활성화 여부
            recording_dir: 녹음 파일 저장 디렉토리
            knowledge_extractor: 지식 추출기 (일반 통화 지식 추출용, 선택)
            gcp_credentials_path: GCP 인증 파일 경로 (STT용)
            enable_post_stt: 후처리 STT 활성화 여부
            stt_language: STT 언어 코드
        """
        self.call_repository = call_repository
        self.media_session_manager = media_session_manager
        self.b2bua_ip = b2bua_ip
        
        # AI 보이스봇 지원
        self.ai_orchestrator = ai_orchestrator
        self.no_answer_timeout = no_answer_timeout
        self.ai_enabled_calls = set()  # AI 모드가 활성화된 통화 ID 집합
        
        # Pipecat Pipeline Builder (Phase 1)
        self.pipecat_builder = None
        
        # 통화 녹음 지원 (신규)
        self.recording_enabled = recording_enabled
        self.sip_recorder = None
        if recording_enabled:
            from .sip_call_recorder import SIPCallRecorder
            self.sip_recorder = SIPCallRecorder(
                output_dir=recording_dir,
                gcp_credentials_path=gcp_credentials_path,
                enable_post_stt=enable_post_stt,
                stt_language=stt_language
            )
            logger.info("SIP call recording enabled", recording_dir=recording_dir)
        
        # 지식 추출 지원 (신규)
        self.knowledge_extractor = knowledge_extractor
        if knowledge_extractor:
            logger.info("Knowledge extraction enabled for regular calls")
        
        # CDR Writer 초기화 (통화 이력 기록)
        self.cdr_writer = CDRWriter(output_dir="./cdr")
        logger.info("CDR writer enabled", output_dir="./cdr")
        
        logger.info("call_manager_initialized",
                   media_enabled=media_session_manager is not None,
                   b2bua_ip=b2bua_ip,
                   ai_enabled=ai_orchestrator is not None,
                   recording_enabled=recording_enabled,
                   knowledge_extraction_enabled=knowledge_extractor is not None,
                   cdr_enabled=True,
                   no_answer_timeout=no_answer_timeout)
    
    def set_ai_orchestrator(self, ai_orchestrator) -> None:
        """AI Orchestrator 동적 주입 (백그라운드 초기화 완료 후)
        
        Args:
            ai_orchestrator: AI Orchestrator 인스턴스
        """
        self.ai_orchestrator = ai_orchestrator
        
        # ★ TransferManager를 AI Orchestrator에 연결
        if ai_orchestrator and self._sip_endpoint:
            transfer_manager = getattr(self._sip_endpoint, '_transfer_manager', None)
            if transfer_manager and hasattr(ai_orchestrator, 'set_transfer_manager'):
                ai_orchestrator.set_transfer_manager(transfer_manager)
                # speak_to_caller 콜백 설정
                async def _speak_to_caller(call_id, text, allow_barge_in=True):
                    if ai_orchestrator.call_id == call_id:
                        await ai_orchestrator.speak(text)
                
                transfer_manager.set_callbacks(
                    speak_to_caller=_speak_to_caller,
                )
                logger.info("✅ [Transfer] TransferManager connected to AI Orchestrator")
        
            # ★ OutboundCallManager를 AI Orchestrator에 연결
            outbound_manager = getattr(self._sip_endpoint, '_outbound_manager', None)
            if outbound_manager:
                # start_ai 콜백: 아웃바운드 200 OK 시 AI 시작
                async def _start_outbound_ai(call_id, outbound_context):
                    if ai_orchestrator:
                        await ai_orchestrator.handle_outbound_call(call_id, outbound_context)
                
                # stop_ai 콜백: 부분 결과 수집
                async def _stop_outbound_ai(call_id):
                    if ai_orchestrator and ai_orchestrator.call_id == call_id:
                        result = await ai_orchestrator.get_partial_outbound_result()
                        await ai_orchestrator.end_call()
                        return result
                    return None
                
                outbound_manager.set_callbacks(
                    start_ai=_start_outbound_ai,
                    stop_ai=_stop_outbound_ai,
                )
                
                # 아웃바운드 완료 콜백 (AI → OutboundManager)
                ai_orchestrator.set_outbound_complete_callback(outbound_manager.on_task_completed)
                
                logger.info("✅ [Outbound] OutboundCallManager connected to AI Orchestrator")
        
        logger.info("✅ [AI Injection] AI Orchestrator injected into CallManager",
                   ai_available=ai_orchestrator is not None)
    
    def set_pipecat_builder(self, builder) -> None:
        """Pipecat Pipeline Builder 동적 주입 (Phase 1)
        
        Args:
            builder: VoiceAIPipelineBuilder 인스턴스
        """
        self.pipecat_builder = builder
        logger.info("✅ [Pipecat] Pipeline Builder injected into CallManager",
                   pipecat_available=builder is not None)
    
    def set_sip_endpoint(self, sip_endpoint) -> None:
        """SIP Endpoint 참조 설정 (Pipecat에서 RTP Worker 접근용)"""
        self._sip_endpoint = sip_endpoint

    async def request_hangup(self, call_id: str) -> bool:
        """
        해당 통화를 서버에서 종료 (발신자에게 BYE 전송).
        HITL timeout 등에서 호출.
        """
        if not getattr(self, '_sip_endpoint', None):
            logger.warning("request_hangup_no_sip_endpoint", call_id=call_id)
            return False
        try:
            return await self._sip_endpoint.send_bye_to_caller(call_id)
        except Exception as e:
            logger.error("request_hangup_error", call_id=call_id, error=str(e))
            return False

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
                           progress="call",
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
                   progress="call",
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

    def register_b2bua_call(self, call_id: str, from_uri: str, to_uri: str) -> None:
        """B2BUA 경로에서 수신한 통화를 Repository에 등록 (대시보드 실시간 통화 목록용)
        
        sip_endpoint가 INVITE 수신 시 _active_calls만 채우고 handle_incoming_invite를 호출하지
        않으므로, API의 get_active_sessions()가 비어 있던 문제를 해결하기 위해 호출한다.
        
        Args:
            call_id: SIP Call-ID (원본 통화 ID)
            from_uri: 발신자 URI (예: sip:1003@10.0.0.1)
            to_uri: 수신자 URI (예: sip:1004@10.0.0.1)
        """
        incoming_leg = Leg(
            direction=Direction.INCOMING,
            call_id_header=call_id,
            from_uri=from_uri,
            to_uri=to_uri,
        )
        session = CallSession(
            call_id=call_id,
            state=CallState.PROCEEDING,
            incoming_leg=incoming_leg,
        )
        self.call_repository.add(session)
        logger.debug("b2bua_call_registered", call_id=call_id, to_uri=to_uri)

    def mark_b2bua_established(self, call_id: str) -> None:
        """B2BUA 통화 연결(200 OK) 시 세션 상태를 ESTABLISHED로 갱신"""
        session = self.call_repository.get(call_id)
        if session:
            session.mark_established()
            self.call_repository.update(session)
            logger.debug("b2bua_call_established", call_id=call_id)

    def remove_b2bua_call(self, call_id: str) -> None:
        """B2BUA 통화 종료 시 Repository에서 제거"""
        self.call_repository.remove(call_id)
        logger.debug("b2bua_call_removed", call_id=call_id)

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
                from src.media.media_session import MediaMode
                
                # Direct 모드가 아닐 때만 SDP 수정
                if media_session.mode != MediaMode.DIRECT:
                    # B2BUA IP로 Origin 변경 (o= 라인)
                    modified_sdp = SDPManipulator.replace_origin_ip(modified_sdp, self.b2bua_ip)
                    
                    # B2BUA IP로 Connection 변경 (c= 라인)
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
                else:
                    logger.info("sdp_not_modified_direct_mode",
                               call_id=call_session.call_id,
                               mode="direct")
        
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
    
    async def handle_no_answer_timeout(
        self,
        call_id: str,
        callee_username: str
    ) -> None:
        """부재중 타임아웃 처리 (AI 응대 모드 전환)
        
        Args:
            call_id: 호 ID
            callee_username: 착신자 사용자명
        """
        import asyncio
        try:
            logger.warning("no_answer_timeout_activating_ai",
                          call_id=call_id,
                          callee=callee_username,
                          timeout=self.no_answer_timeout)
            
            # AI Orchestrator가 있으면 AI 모드로 전환
            if self.ai_orchestrator:
                logger.info("activating_ai_voicebot_for_no_answer",
                           progress="call",
                           call_id=call_id,
                           callee=callee_username)
                
                # AI 활성화 통화로 등록
                self.ai_enabled_calls.add(call_id)
                
                # Pipecat Pipeline Builder가 있으면 Pipecat 모드로 실행
                if self.pipecat_builder:
                    logger.info("🚀 [Pipecat] Starting Pipecat pipeline for AI call",
                               call_id=call_id,
                               callee=callee_username)
                    
                    call_context = {
                        "call_id": call_id,
                        "caller": callee_username,
                        "callee": callee_username,
                        "system_prompt": "",
                    }
                    
                    # RTP Worker 가져오기
                    rtp_worker = None
                    if hasattr(self, '_sip_endpoint') and self._sip_endpoint:
                        rtp_worker = self._sip_endpoint._rtp_workers.get(call_id)
                    
                    if rtp_worker:
                        # Pipecat 파이프라인 실행 (백그라운드)
                        # Phase 2: embedder/vector_db 전달 (LangGraph Semantic Cache용)
                        _rag = getattr(self.ai_orchestrator, 'rag', None)
                        asyncio.create_task(
                            self.pipecat_builder.build_and_run(
                                rtp_worker=rtp_worker,
                                call_context=call_context,
                                llm_client=getattr(self.ai_orchestrator, 'llm', None),
                                rag_engine=_rag,
                                # org_manager는 pipeline_builder 내부에서 callee 기반으로 VectorDB에서 로드
                                org_manager=None,
                                embedder=getattr(_rag, 'embedder', None) if _rag else None,
                                vector_db=getattr(_rag, 'vector_db', None) if _rag else None,
                            )
                        )
                        
                        logger.info("✅ [Pipecat] Pipeline task started",
                                   call_id=call_id)
                        logger.info("ai_voicebot_pipecat_activated",
                                   progress="call",
                                   callee=callee_username,
                                   engine="pipecat")
                    else:
                        logger.warning("pipecat_no_rtp_worker",
                                      call_id=call_id,
                                      message="RTP worker not found, falling back to legacy")
                        # Fallback to legacy orchestrator
                        await self.ai_orchestrator.handle_call(
                            call_id=call_id,
                            caller=f"sip:{callee_username}@unknown",
                            callee=callee_username,
                        )
                        logger.info("ai_voicebot_legacy_activated",
                                   callee=callee_username,
                                   engine="legacy")
                else:
                    # Legacy orchestrator 경로
                    logger.info("🔄 [AI Takeover] Starting legacy AI call takeover",
                               call_id=call_id,
                               callee=callee_username)
                    
                    await self.ai_orchestrator.handle_call(
                        call_id=call_id,
                        caller=f"sip:{callee_username}@unknown",
                        callee=callee_username,
                    )
                    
                    logger.info("ai_voicebot_activated",
                               progress="call",
                               callee=callee_username,
                               engine="legacy")
                
                logger.info("ai_mode_activated",
                           call_id=call_id,
                           callee=callee_username,
                           pipeline_engine="pipecat" if self.pipecat_builder else "legacy",
                           ai_enabled_calls=len(self.ai_enabled_calls))
                
                logger.info("✅ [AI Takeover] AI call handling started successfully",
                           call_id=call_id)
            else:
                logger.warning("ai_orchestrator_not_available",
                              call_id=call_id,
                              callee=callee_username,
                              message="AI Orchestrator is None - cannot activate AI mode")
                
                logger.warning("ai_orchestrator_not_available_for_activation",
                              callee=callee_username,
                              message="Cannot activate AI mode")
                
        except Exception as e:
            logger.error("no_answer_timeout_error",
                        call_id=call_id,
                        error=str(e),
                        exc_info=True)
    
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
                       progress="call",
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
                    # B2BUA IP로 Origin 변경 (o= 라인)
                    modified_sdp = SDPManipulator.replace_origin_ip(modified_sdp, self.b2bua_ip)
                    
                    # B2BUA IP로 Connection 변경 (c= 라인)
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
                       progress="call",
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
            
            # SIP 통화 녹음 시작 (신규)
            if self.sip_recorder and not call_session.call_id in self.ai_enabled_calls:
                try:
                    import asyncio
                    asyncio.create_task(
                        self.sip_recorder.start_recording(
                            call_id=call_session.call_id,
                            caller_id=call_session.get_caller_uri(),
                            callee_id=call_session.get_callee_uri()
                        )
                    )
                    logger.info("sip_recording_started",
                               call_id=call_session.call_id,
                               caller=call_session.get_caller_uri(),
                               callee=call_session.get_callee_uri())
                except Exception as e:
                    logger.error("sip_recording_start_error",
                               call_id=call_session.call_id,
                               error=str(e))
            
            logger.info("ack_received_from_incoming",
                       progress="call",
                       call_id=call_session.call_id,
                       state=call_session.state.value,
                       answer_time=call_session.answer_time.isoformat() if call_session.answer_time else None)
            
            # WebSocket: 통화 시작 이벤트 발송
            try:
                from src.websocket import manager as ws_manager
                import asyncio
                asyncio.create_task(ws_manager.emit_call_started(
                    call_id=call_session.call_id,
                    call_data={
                        'caller': call_session.get_caller_uri(),
                        'callee': call_session.get_callee_uri(),
                        'is_ai_handled': call_session.call_id in self.ai_enabled_calls,
                        'timestamp': datetime.now().isoformat()
                    }
                ))
            except Exception as e:
                logger.warning("call_started_event_failed", call_id=call_session.call_id, error=str(e))
        
        # Outgoing leg에서 ACK 수신 (re-INVITE 시나리오)
        else:
            logger.info("ack_received_from_outgoing",
                       progress="call",
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
                       progress="call",
                       call_id=call_session.call_id,
                       reason=reason)
        else:
            logger.info("bye_received_from_outgoing",
                       progress="call",
                       call_id=call_session.call_id,
                       reason=reason)
        
        # 2. 통화 종료 상태로 전환
        call_session.mark_terminated(reason=reason)
        
        # 3. Repository 업데이트
        self.call_repository.update(call_session)
        
        logger.info("call_terminated",
                   progress="call",
                   call_id=call_session.call_id,
                   duration_seconds=call_session.get_duration_seconds(),
                   reason=reason,
                   state=call_session.state.value)
        
        # WebSocket: 통화 종료 이벤트 발송
        try:
            from src.websocket import manager as ws_manager
            import asyncio
            asyncio.create_task(ws_manager.emit_call_ended(
                call_id=call_session.call_id
            ))
        except Exception as e:
            logger.warning("call_ended_event_failed", call_id=call_session.call_id, error=str(e))
        
        # 4. 200 OK 반환
        return SIPResponseCode.OK
    
    def cleanup_terminated_call(self, call_session: CallSession) -> Dict[str, Any]:
        """종료된 통화 정리 및 CDR 데이터 준비
        
        Args:
            call_session: 종료된 통화 세션
            
        Returns:
            CDR 데이터 딕셔너리
        """
        # SIP 통화 녹음 종료 (신규)
        recording_dir_name = None
        if self.sip_recorder and self.sip_recorder.is_recording(call_session.call_id):
            try:
                import asyncio
                # 녹음 디렉토리 정보를 미리 가져오기 (stop_recording 전에)
                recording = self.sip_recorder.active_recordings.get(call_session.call_id)
                if recording:
                    recording_dir_name = recording.get("dir_name")
                
                # 녹음 종료 (비동기, 백그라운드 실행)
                asyncio.create_task(self.sip_recorder.stop_recording(call_session.call_id))
                logger.info("sip_recording_stopped", 
                           call_id=call_session.call_id,
                           directory=recording_dir_name)
            except Exception as e:
                logger.error("sip_recording_stop_error",
                           call_id=call_session.call_id,
                           error=str(e))
        
        # AI 통화 종료 처리
        is_ai_call = call_session.call_id in self.ai_enabled_calls
        if is_ai_call:
            if self.ai_orchestrator:
                try:
                    import asyncio
                    asyncio.create_task(self.ai_orchestrator.end_call())
                    logger.info("ai_call_ended", progress="call", call_id=call_session.call_id)
                except Exception as e:
                    logger.error("ai_end_call_error",
                               call_id=call_session.call_id,
                               error=str(e))
            
            self.ai_enabled_calls.discard(call_session.call_id)
        else:
            # 일반 SIP 통화 지식 추출 (신규)
            if self.knowledge_extractor and self.recording_enabled and recording_dir_name:
                try:
                    import asyncio
                    from pathlib import Path
                    
                    transcript_path = Path(f"./recordings/{recording_dir_name}/transcript.txt")
                    
                    # 착신자 ID 추출 (to_uri에서)
                    callee_id = call_session.get_callee_uri()
                    
                    logger.info("🚀 [Knowledge Flow] Scheduling knowledge extraction for regular SIP call",
                               call_id=call_session.call_id,
                               callee_id=callee_id,
                               recording_dir=recording_dir_name,
                               transcript_path=str(transcript_path))
                    
                    # STT 완료를 기다린 후 지식 추출 실행 (5초 delay)
                    async def delayed_extraction():
                        await asyncio.sleep(5)  # STT 완료 대기
                        
                        if not transcript_path.exists():
                            logger.warning("⚠️ [Knowledge Flow] Transcript file not found after delay",
                                         call_id=call_session.call_id,
                                         path=str(transcript_path))
                            return
                        
                        logger.info("🚀 [Knowledge Flow] Starting knowledge extraction",
                                   call_id=call_session.call_id)
                        
                        await self.knowledge_extractor.extract_from_call(
                            call_id=call_session.call_id,
                            transcript_path=str(transcript_path),
                            owner_id=callee_id,
                            speaker="callee"  # 착신자 발화만 추출
                        )
                    
                    asyncio.create_task(delayed_extraction())
                    
                    logger.info("✅ [Knowledge Flow] Knowledge extraction task scheduled (5s delay for STT)",
                               call_id=call_session.call_id,
                               callee=callee_id)
                except Exception as e:
                    logger.error("❌ [Knowledge Flow] Knowledge extraction scheduling error",
                               call_id=call_session.call_id,
                               error=str(e),
                               exc_info=True)
    
    async def trigger_knowledge_extraction(
        self,
        call_id: str,
        recording_dir_name: str,
        callee_username: str
    ) -> None:
        """Knowledge Extraction 트리거 (SIP Endpoint에서 호출)
        
        Args:
            call_id: 호 ID
            recording_dir_name: 녹음 디렉토리명
            callee_username: 착신자 사용자명
        """
        if not self.knowledge_extractor or not self.recording_enabled:
            logger.debug("knowledge_extraction_disabled_or_not_configured",
                        call_id=call_id,
                        has_extractor=self.knowledge_extractor is not None,
                        recording_enabled=self.recording_enabled)
            return
        
        try:
            import asyncio
            from pathlib import Path
            
            transcript_path = Path(f"./recordings/{recording_dir_name}/transcript.txt")
            callee_id = f"sip:{callee_username}@unknown"  # URI 형식
            
            logger.info("🚀 [Knowledge Flow] Scheduling knowledge extraction for regular SIP call",
                       call_id=call_id,
                       callee_id=callee_id,
                       recording_dir=recording_dir_name,
                       transcript_path=str(transcript_path))
            
            # STT 완료를 기다린 후 지식 추출 실행 (5초 delay)
            async def delayed_extraction():
                await asyncio.sleep(5)  # STT 완료 대기
                
                if not transcript_path.exists():
                    logger.warning("⚠️ [Knowledge Flow] Transcript file not found after delay",
                                 call_id=call_id,
                                 path=str(transcript_path))
                    return
                
                logger.info("🚀 [Knowledge Flow] Starting knowledge extraction",
                           call_id=call_id)
                
                await self.knowledge_extractor.extract_from_call(
                    call_id=call_id,
                    transcript_path=str(transcript_path),
                    owner_id=callee_id,
                    speaker="both"  # ✅ 발신자+착신자 모두 추출 (대화 전체)
                )
            
            asyncio.create_task(delayed_extraction())
            
            logger.info("✅ [Knowledge Flow] Knowledge extraction task scheduled (5s delay for STT)",
                       call_id=call_id,
                       callee=callee_id)
        except Exception as e:
            logger.error("❌ [Knowledge Flow] Knowledge extraction scheduling error",
                       call_id=call_id,
                       error=str(e),
                       exc_info=True)
    
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

