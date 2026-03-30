"""Call Manager

통화 생명주기 관리
"""

import asyncio
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
        enable_post_stt: bool = False,  # WAV 후처리 STT (실시간 파이프라인 대본이 없을 때만 사용)
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
        # ACK 수신 시 TTS 시작용 (인사말을 call_established 이후에 재생해 RTP가 전달되도록)
        self._call_established_events: Dict[str, asyncio.Event] = {}
        
        # Pipecat Pipeline Builder (Phase 1)
        self.pipecat_builder = None
        # Pipecat Pipeline task 참조 (BYE 수신 시 즉시 취소용)
        self._pipecat_tasks: Dict[str, asyncio.Task] = {}
        # Pipeline 취소 대기 타임아웃 (초) - Pipecat cancel_timeout 20초 고려
        self._pipecat_cancel_timeout_secs = 25.0
        
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
        
            # ★ OutboundCallManager를 Pipecat 파이프라인에 연결
            outbound_manager = getattr(self._sip_endpoint, '_outbound_manager', None)
            if outbound_manager:
                _self_ref = self  # CallManager 약한 참조 (클로저 순환 방지)

                async def _start_outbound_ai(call_id: str, outbound_context: dict):
                    """아웃바운드 200 OK 수신 시 Pipecat 파이프라인 기동.

                    인바운드 handle_no_answer_timeout과 동일한 Pipecat 경로를 사용한다.
                    - RTP Worker는 sip_endpoint.handle_outbound_response(200 OK) 시 이미 생성됨
                    - enable_pipecat_mode() → build_and_run() → _pipecat_tasks 등록
                    """
                    logger.info("outbound_pipecat_start",
                                call_id=call_id,
                                outbound_id=outbound_context.get("outbound_id"),
                                has_pipecat_builder=_self_ref.pipecat_builder is not None)

                    if not _self_ref.pipecat_builder:
                        logger.error("outbound_pipecat_no_builder",
                                     call_id=call_id,
                                     note="pipecat_builder가 없음 — AI 응대 불가")
                        return

                    # RTP Worker 가져오기 (send_outbound_invite에서 미디어 포트 할당 완료)
                    rtp_worker = None
                    if _self_ref._sip_endpoint:
                        rtp_worker = _self_ref._sip_endpoint._rtp_workers.get(call_id)

                    if not rtp_worker:
                        logger.error("outbound_pipecat_no_rtp_worker",
                                     call_id=call_id,
                                     note="RTP Worker 없음 — sip_endpoint에서 outbound RTP 등록 확인")
                        return

                    # Pipecat 모드로 전환 (오디오 큐 생성·RTP→파이프라인 라우팅)
                    rtp_worker.enable_pipecat_mode()

                    # 대시보드 등록 (활성 통화 목록)
                    callee_number = outbound_context.get("callee_number", "")
                    _self_ref.ai_enabled_calls.add(call_id)
                    try:
                        from src.api.routers.calls import register_active_call
                        register_active_call(
                            call_id=call_id,
                            callee=callee_number,
                            caller=outbound_context.get("caller_display_name", ""),
                            is_ai_handled=True,
                        )
                    except Exception as _e:
                        logger.debug("outbound_register_active_call_failed",
                                     call_id=call_id, error=str(_e))

                    # WebSocket call_started 이벤트
                    try:
                        from src.websocket import manager as ws_manager
                        await ws_manager.emit_call_started(call_id, {
                            "callee": callee_number,
                            "caller": outbound_context.get("caller_display_name", ""),
                            "is_ai_handled": True,
                            "status": "AI 아웃바운드 응대 중",
                            "sip_phase": "ai_active",
                            "outbound_id": outbound_context.get("outbound_id", ""),
                            "purpose": outbound_context.get("purpose", ""),
                        })
                    except Exception as _e:
                        logger.warning("outbound_emit_call_started_failed",
                                       call_id=call_id, error=str(_e))

                    # STT / TTS 통화별 인스턴스 생성
                    _stt_pipecat = None
                    _tts_pipecat = None
                    try:
                        from src.ai_voicebot.factory import (
                            create_google_stt_service_per_pipeline,
                            create_google_tts_service_per_pipeline,
                        )
                        _stt_pipecat = await create_google_stt_service_per_pipeline()
                        _tts_pipecat = await create_google_tts_service_per_pipeline(call_id=call_id)
                    except Exception as svc_err:
                        logger.error("outbound_pipecat_stt_tts_failed",
                                     call_id=call_id, error=str(svc_err))
                        _stt_pipecat = getattr(_self_ref.ai_orchestrator, 'stt', None)
                        _tts_pipecat = getattr(_self_ref.ai_orchestrator, 'tts', None)

                    # VAD 래핑
                    _vad_raw = getattr(_self_ref.ai_orchestrator, 'vad', None)
                    _vad_processor = None
                    if _vad_raw:
                        try:
                            from src.ai_voicebot.pipecat.processors.vad_processor import PipecatVADProcessor
                            _vad_processor = PipecatVADProcessor(
                                vad_detector=_vad_raw,
                                enable_barge_in=True,
                            )
                        except Exception as _e:
                            logger.warning("outbound_vad_wrap_failed",
                                           call_id=call_id, error=str(_e))

                    # HITL 콜백
                    _hitl_on_alert = None
                    try:
                        from src.websocket import manager as ws_manager
                        async def _outbound_hitl_alert(context: dict):
                            cid = context.get("call_id", "")
                            question = context.get("question", "")
                            urgency = context.get("urgency", "medium")
                            await ws_manager.emit_hitl_requested(cid, question, context, urgency)
                        _hitl_on_alert = _outbound_hitl_alert
                    except Exception:
                        pass

                    # Knowledge Service
                    _knowledge_service = None
                    try:
                        from src.services.knowledge_service import get_knowledge_service
                        _knowledge_service = get_knowledge_service()
                    except Exception:
                        pass

                    # RAG 엔진
                    _rag = getattr(_self_ref.ai_orchestrator, 'rag', None) if _self_ref.ai_orchestrator else None

                    # 아웃바운드 전용 시스템 프롬프트 (목적·질문 주입)
                    _purpose = outbound_context.get("purpose", "")
                    _questions = outbound_context.get("questions", [])
                    _display_name = outbound_context.get("caller_display_name", "AI 봇")
                    _qs_text = "\n".join(f"- {q}" for q in _questions) if _questions else ""
                    _outbound_system_prompt = (
                        f"당신은 {_display_name}를 대표하는 AI 어시스턴트입니다. "
                        f"이 통화의 목적은 다음과 같습니다: {_purpose}\n"
                        + (f"확인이 필요한 사항:\n{_qs_text}\n" if _qs_text else "")
                        + "상대방과 자연스럽게 대화하며 목적을 달성하세요. "
                        "모든 질문에 대한 답변을 얻으면 정중히 통화를 마무리하세요."
                    )

                    # 미션 완료 시 SIP BYE 전송 콜백
                    async def _outbound_hangup(cid: str):
                        logger.info("outbound_mission_hangup", call_id=cid)
                        if _self_ref._sip_endpoint:
                            await _self_ref._sip_endpoint.send_outbound_bye(cid)

                    _coro = _self_ref.pipecat_builder.build_and_run(
                        callee_number,
                        rtp_worker,
                        vad=_vad_processor,
                        stt=_stt_pipecat,
                        tts=_tts_pipecat,
                        llm_client=getattr(_self_ref.ai_orchestrator, 'llm', None) if _self_ref.ai_orchestrator else None,
                        rag_engine=_rag,
                        knowledge_service=_knowledge_service,
                        hitl_on_alert=_hitl_on_alert,
                        embedder=getattr(_rag, 'embedder', None) if _rag else None,
                        vector_db=getattr(_rag, 'vector_db', None) if _rag else None,
                        system_prompt=_outbound_system_prompt,
                        outbound_purpose=_purpose,
                        outbound_questions=_questions,
                        hangup_callback=_outbound_hangup,
                    )
                    pipeline_task = asyncio.create_task(_coro)
                    _self_ref._pipecat_tasks[call_id] = pipeline_task

                    def _on_done(t):
                        _self_ref._pipecat_tasks.pop(call_id, None)
                        _self_ref.ai_enabled_calls.discard(call_id)
                        logger.info("outbound_pipecat_pipeline_done", call_id=call_id)
                    pipeline_task.add_done_callback(_on_done)

                    logger.info("outbound_pipecat_pipeline_started",
                                call_id=call_id,
                                outbound_id=outbound_context.get("outbound_id"),
                                callee=callee_number)

                async def _stop_outbound_ai(call_id: str):
                    """아웃바운드 통화 중단 — Pipecat 파이프라인 태스크 취소."""
                    logger.info("outbound_pipecat_stop", call_id=call_id)
                    cancelled = await _self_ref.cancel_pipeline(call_id)
                    _self_ref.ai_enabled_calls.discard(call_id)
                    logger.info("outbound_pipecat_cancelled",
                                call_id=call_id, cancelled=cancelled)
                    return None  # 부분 결과는 Pipecat 경로에서 별도 수집 불필요

                outbound_manager.set_callbacks(
                    start_ai=_start_outbound_ai,
                    stop_ai=_stop_outbound_ai,
                )

                logger.info("✅ [Outbound] OutboundCallManager connected to Pipecat pipeline")
        
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

    async def shutdown_sip_recording_ingest(self) -> None:
        """RTP 녹음 인입 워커·큐 정리. 이벤트 루프/프로세스 종료 전에 호출."""
        if self.sip_recorder is None:
            return
        await self.sip_recorder.shutdown_rtp_ingest_worker()

    async def cancel_pipeline(self, call_id: str) -> bool:
        """BYE 수신 시 Pipecat Pipeline task 즉시 취소.
        
        Args:
            call_id: 통화 ID (원본 Call-ID)
            
        Returns:
            bool: 취소 성공 여부 (task가 있었고 취소됨)
        """
        task = self._pipecat_tasks.pop(call_id, None)
        if task is None:
            return False
        if task.done():
            return True
        try:
            task.cancel()
            try:
                await asyncio.wait_for(
                    asyncio.shield(task),
                    timeout=self._pipecat_cancel_timeout_secs,
                )
            except asyncio.CancelledError:
                pass
            except asyncio.TimeoutError:
                logger.warning(
                    "pipecat_pipeline_cancel_timeout",
                    call_id=call_id,
                    timeout_secs=self._pipecat_cancel_timeout_secs,
                )
            except Exception as e:
                logger.warning("pipecat_pipeline_cancel_error", call_id=call_id, error=str(e))
            else:
                logger.info("pipecat_pipeline_cancelled", call_id=call_id)
            return True
        except Exception as e:
            logger.warning("pipecat_pipeline_cancel_error", call_id=call_id, error=str(e))
            return False

    async def cancel_all_pipelines(self) -> int:
        """서버 종료 시 모든 활성 Pipecat Pipeline task 취소 (Graceful shutdown).
        
        Returns:
            int: 취소된 task 수
        """
        if not self._pipecat_tasks:
            return 0
        tasks = list(self._pipecat_tasks.items())
        self._pipecat_tasks.clear()
        cancelled = 0
        for call_id, task in tasks:
            if task.done():
                cancelled += 1
                continue
            try:
                task.cancel()
                try:
                    await asyncio.wait_for(
                        asyncio.shield(task),
                        timeout=self._pipecat_cancel_timeout_secs,
                    )
                except asyncio.CancelledError:
                    pass
                except asyncio.TimeoutError:
                    logger.warning(
                        "pipecat_pipeline_cancel_timeout",
                        call_id=call_id,
                        timeout_secs=self._pipecat_cancel_timeout_secs,
                    )
                cancelled += 1
            except Exception as e:
                logger.warning(
                    "pipecat_pipeline_cancel_error",
                    call_id=call_id,
                    error=str(e),
                )
        if cancelled:
            logger.info("pipecat_all_pipelines_cancelled", count=cancelled)
        return cancelled

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

    def get_active_sessions(self):
        """대시보드/GET /api/calls/active용 활성 통화 세션 목록."""
        return self.call_repository.get_active_sessions()

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

    def notify_call_established(self, call_id: str) -> None:
        """ACK 수신(통화 수립) 시 호출. AI 인사말을 이 시점 이후에 재생하도록 대기 중인 이벤트를 set."""
        event = self._call_established_events.pop(call_id, None)
        if event:
            event.set()
            logger.debug("call_established_event_set", call_id=call_id)

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
        # 4.1 중복 방지: 동일 call_id로 이미 처리 시작됐으면 한 번만 실행
        activated = getattr(self, "_no_answer_activated_call_ids", None)
        if activated is None:
            self._no_answer_activated_call_ids = set()
            activated = self._no_answer_activated_call_ids
        if call_id in activated:
            logger.debug("no_answer_timeout_already_activated",
                         call_id=call_id,
                         callee=callee_username)
            return
        activated.add(call_id)
        try:
            # 진단: 부재중 터크오버 시점의 AI 준비 상태 (ai_orchestrator_not_available 원인 추적용)
            logger.info("no_answer_timeout_activating_ai",
                        call_id=call_id,
                        callee=callee_username,
                        timeout=self.no_answer_timeout,
                        ai_orchestrator_is_set=self.ai_orchestrator is not None,
                        pipecat_builder_is_set=self.pipecat_builder is not None,
                        diagnostic="둘 다 False면 서버 기동 로그에서 ai_readiness_after_background_init 또는 ai_voicebot_background_init_error 검색")
            
            # AI Orchestrator가 있으면 AI 모드로 전환
            if self.ai_orchestrator:
                logger.info("activating_ai_voicebot_for_no_answer",
                           progress="call",
                           call_id=call_id,
                           callee=callee_username)
                
                # AI 활성화 통화로 등록
                self.ai_enabled_calls.add(call_id)
                
                # API 레지스트리에도 등록 (REST API /api/calls/active에서 참조)
                try:
                    from src.api.routers.calls import register_active_call
                    register_active_call(
                        call_id=call_id,
                        callee=callee_username,
                        caller=caller_username if caller_username else "",
                        is_ai_handled=True
                    )
                except Exception as reg_err:
                    logger.debug("register_active_call_failed", call_id=call_id, error=str(reg_err))
                
                # CallSession을 AI 응대로 업데이트 (대시보드 활성 통화 목록에 표시되도록)
                call_session = self.get_session(call_id)
                if call_session:
                    call_session.mark_established()  # 상태를 ESTABLISHED로
                    # AI 응대 플래그 설정 (Frontend에서 'AI 응대' 표시)
                    if hasattr(call_session, 'metadata'):
                        if call_session.metadata is None:
                            call_session.metadata = {}
                        call_session.metadata['is_ai_handled'] = True
                    self.call_repository.update(call_session)
                    logger.info("call_session_marked_as_ai",
                               call_id=call_id,
                               state=call_session.state.value,
                               note="Repository 업데이트 완료 - 대시보드에 표시됨")
                    
                    # WebSocket: call_started 이벤트 발송 (Frontend 실시간 업데이트)
                    try:
                        from src.websocket import manager as ws_manager
                        call_data = {
                            "caller": call_session.get_caller_uri() if hasattr(call_session, 'get_caller_uri') else "",
                            "callee": call_session.get_callee_uri() if hasattr(call_session, 'get_callee_uri') else callee_username,
                            "state": call_session.state.value if hasattr(call_session.state, 'value') else str(call_session.state),
                            "is_ai_handled": True,
                            "status": "AI 응대 중",
                            "sip_phase": "ai_active",
                        }
                        await ws_manager.emit_call_started(call_id, call_data)
                        logger.info("ai_call_started_event_emitted", call_id=call_id)
                    except Exception as ws_err:
                        logger.warning("ai_call_started_event_failed", call_id=call_id, error=str(ws_err))
                else:
                    logger.warning("call_session_not_found_for_ai_takeover",
                                  call_id=call_id,
                                  note="Repository에 세션 없음 - 대시보드에 표시 안 될 수 있음")
                
                # ACK 수신 시 인사말 시작용 이벤트 (TTS를 call_established 이후에 재생해 RTP 전달 보장)
                call_established_event = asyncio.Event()
                self._call_established_events[call_id] = call_established_event
                if hasattr(self.ai_orchestrator, 'set_call_established_event'):
                    self.ai_orchestrator.set_call_established_event(call_id, call_established_event)
                
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
                        # RTP Worker를 Pipecat 모드로 전환 (오디오 큐 생성·RTP→파이프라인 라우팅 활성화)
                        rtp_worker.enable_pipecat_mode()
                        # Pipecat 파이프라인 실행 (백그라운드)
                        # Phase 2: embedder/vector_db 전달 (LangGraph Semantic Cache용)
                        _rag = getattr(self.ai_orchestrator, 'rag', None)
                        _effective_callee = callee_username or ""
                        
                        # HITL 콜백 준비 (프론트엔드 알림 연동)
                        _hitl_on_alert = None
                        try:
                            from src.websocket import manager as ws_manager
                            async def _default_hitl_alert(context: dict):
                                """HITL 알림 — hitl_processor가 (context) 1인자로 호출. context에 call_id, question 등 포함."""
                                cid = context.get("call_id", "")
                                question = context.get("question", "")
                                urgency = context.get("urgency", "medium")
                                await ws_manager.emit_hitl_requested(cid, question, context, urgency)
                            _hitl_on_alert = _default_hitl_alert
                        except Exception as e:
                            logger.debug("hitl_on_alert_setup_failed", error=str(e))
                        
                        # Knowledge Service 준비 (org_manager 자동 로딩용)
                        _knowledge_service = None
                        try:
                            from src.services.knowledge_service import get_knowledge_service
                            _knowledge_service = get_knowledge_service()
                        except Exception as e:
                            logger.debug("knowledge_service_import_failed", error=str(e))
                        
                        logger.info("pipecat_pipeline_args",
                                   call_id=call_id,
                                   callee=_effective_callee,
                                   has_vad=getattr(self.ai_orchestrator, 'vad', None) is not None,
                                   has_stt=getattr(self.ai_orchestrator, 'stt', None) is not None,
                                   has_tts=getattr(self.ai_orchestrator, 'tts', None) is not None,
                                   has_llm=getattr(self.ai_orchestrator, 'llm', None) is not None,
                                   has_rag=_rag is not None,
                                   has_hitl=_hitl_on_alert is not None,
                                   has_knowledge_service=_knowledge_service is not None)
                        
                        # VAD를 Pipecat processor로 래핑 (VADDetector → PipecatVADProcessor)
                        _vad_raw = getattr(self.ai_orchestrator, 'vad', None)
                        _vad_processor = None
                        if _vad_raw:
                            try:
                                from src.ai_voicebot.pipecat.processors.vad_processor import PipecatVADProcessor
                                _vad_processor = PipecatVADProcessor(
                                    vad_detector=_vad_raw,
                                    enable_barge_in=True,  # 바지인 켬. TTS 중단은 BargeInSuppressProcessor에서 InterruptionFrame 차단으로 STT 확정 시에만
                                )
                                logger.info("vad_wrapped_for_pipecat", call_id=call_id)
                            except Exception as vad_err:
                                logger.warning("vad_wrap_failed", call_id=call_id, error=str(vad_err))
                                _vad_processor = None
                        
                        # STT·TTS: 파이프라인마다 전용 인스턴스 (동시/연속 통화 시 Singleton 공유는 스트림·내부 태스크 꼬임)
                        _stt_pipecat = None
                        _tts_pipecat = None
                        try:
                            from src.ai_voicebot.factory import (
                                create_google_stt_service_per_pipeline,
                                create_google_tts_service_per_pipeline,
                            )

                            _stt_pipecat = await create_google_stt_service_per_pipeline()
                            if _stt_pipecat:
                                logger.info(
                                    "google_stt_service_per_pipeline_for_call",
                                    call_id=call_id,
                                    note="통화별 STT — 동시 Pipecat 호에서 Singleton 공유 금지",
                                )
                            
                            _tts_pipecat = await create_google_tts_service_per_pipeline(call_id=call_id)
                            if _tts_pipecat:
                                logger.info(
                                    "google_tts_service_per_pipeline_for_call",
                                    call_id=call_id,
                                    note="통화별 TTS — 이전 파이프라인 취소 후 Singleton 잔류로 PCM 미생성 방지",
                                )
                            
                        except Exception as service_err:
                            logger.error("google_service_singleton_failed", 
                                       call_id=call_id, 
                                       error=str(service_err),
                                       exc_info=True,
                                       fallback="Using legacy STT/TTS")
                            # Fallback: legacy STT/TTS (FrameProcessor 아니므로 파이프라인 오류 발생 가능)
                            _stt_pipecat = getattr(self.ai_orchestrator, 'stt', None)
                            _tts_pipecat = getattr(self.ai_orchestrator, 'tts', None)
                        
                        _coro = self.pipecat_builder.build_and_run(
                            _effective_callee,
                            rtp_worker,
                            vad=_vad_processor,
                            stt=_stt_pipecat,
                            tts=_tts_pipecat,
                            llm_client=getattr(self.ai_orchestrator, 'llm', None),
                            rag_engine=_rag,
                            org_manager=None,
                            knowledge_service=_knowledge_service,
                            hitl_on_alert=_hitl_on_alert,
                            embedder=getattr(_rag, 'embedder', None) if _rag else None,
                            vector_db=getattr(_rag, 'vector_db', None) if _rag else None,
                        )
                        pipeline_task = asyncio.create_task(_coro)
                        self._pipecat_tasks[call_id] = pipeline_task
                        def _on_pipeline_done(t):
                            self._pipecat_tasks.pop(call_id, None)
                        pipeline_task.add_done_callback(_on_pipeline_done)
                        
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
                # 근본 원인: 서버 기동 시 AI 초기화 미완료/실패/비활성화 → set_ai_orchestrator 미호출
                logger.warning("ai_orchestrator_not_available",
                              call_id=call_id,
                              callee=callee_username,
                              message="AI Orchestrator is None - cannot activate AI mode",
                              ai_orchestrator_is_set=False,
                              pipecat_builder_is_set=self.pipecat_builder is not None,
                              root_cause_check="서버 기동 로그에서 ai_readiness_at_startup 확인. ai_orchestrator_set=False면 초기화 타임아웃/실패/비활성화. docs/reports/AI_ORCHESTRATOR_NONE_ROOT_CAUSE.md 참고.",
                              suggest_check="app.log에서 ai_readiness_after_background_init(성공) 또는 ai_voicebot_background_init_error(실패) 또는 AI 초기화 타임아웃(60s) 검색")

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
                        'status': '통화 연결됨 (ACK)',
                        'sip_phase': 'answered',
                        'timestamp': datetime.now().isoformat(),
                        'started_at': call_session.answer_time.isoformat() if call_session.answer_time else datetime.now().isoformat(),
                    }
                ))
            except Exception as e:
                logger.warning("call_started_event_failed", call_id=call_session.call_id, error=str(e))

            # 유저 간 통화: AI 파이프라인 없음 — call_data_record에 연결·사후 Chroma 흐름 요약
            if call_session.call_id not in self.ai_enabled_calls:
                try:
                    from src.common.call_data_record_logger import log_call_data
                    from src.common.knowledge_call_data_helpers import chroma_context_for_call_data

                    log_call_data(
                        call_session.call_id,
                        "call_event",
                        "call_connected",
                        mode="human_human",
                        is_ai_handled=False,
                        realtime_llm_intent_rag="none",
                        note=(
                            "실시간 LangGraph/Pipecat 미사용. Bypass RTP·실시간 STT는 stt_bypass_final 등으로 기록. "
                            "통화 종료 후 transcript.txt가 있으면 KnowledgeExtractor/ExtractionPipeline이 "
                            "LLM judge_usefulness → Chroma knowledge 컬렉션 upsert."
                        ),
                        recording_enabled=self.recording_enabled,
                        knowledge_extractor_configured=self.knowledge_extractor is not None,
                        **chroma_context_for_call_data(),
                    )
                except Exception as e:
                    logger.debug("human_call_connected_call_data_failed", error=str(e))
        
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
        # Bypass 모드 실시간 STT 스트림 정리 (유저 간 통화)
        try:
            from src.media.bypass_realtime_stt import get_bypass_realtime_stt

            get_bypass_realtime_stt().end_call(call_session.call_id)
        except Exception as e:
            logger.debug(
                "bypass_realtime_stt_end_call_failed",
                call_id=call_session.call_id,
                error=str(e),
            )

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
            import asyncio

            try:
                from src.common.sip_owner import normalize_owner_username
                from src.services.hitl import get_hitl_service

                _uri = call_session.get_callee_uri() or ""
                _own = normalize_owner_username(_uri) or None
                asyncio.create_task(
                    get_hitl_service().flush_hitl_kb_for_call(call_session.call_id, _own)
                )
            except Exception as e:
                logger.debug(
                    "hitl_kb_flush_cleanup_terminated_schedule_failed call_id=%s error=%s",
                    call_session.call_id,
                    e,
                )
            if self.ai_orchestrator:
                try:
                    asyncio.create_task(self.ai_orchestrator.end_call())
                    logger.info("ai_call_ended", progress="call", call_id=call_session.call_id)
                except Exception as e:
                    logger.error("ai_end_call_error",
                               call_id=call_session.call_id,
                               error=str(e))
            
            self.discard_ai_enabled_call(call_session.call_id)
        else:
            # 일반 SIP 통화: 종료 시 call_data_record 요약 (AI 파이프라인 없음)
            try:
                from src.common.call_data_record_logger import log_call_data
                from src.common.knowledge_call_data_helpers import chroma_context_for_call_data

                _will_schedule = bool(
                    self.knowledge_extractor and self.recording_enabled and recording_dir_name
                )
                log_call_data(
                    call_session.call_id,
                    "call_event",
                    "human_human_call_ended",
                    mode="human_human",
                    is_ai_handled=False,
                    recording_dir_name=recording_dir_name or "",
                    recording_enabled=self.recording_enabled,
                    knowledge_extractor_configured=self.knowledge_extractor is not None,
                    post_call_extraction_scheduled=_will_schedule,
                    post_call_extraction_skip_reason=(
                        None
                        if _will_schedule
                        else (
                            "no_knowledge_extractor"
                            if not self.knowledge_extractor
                            else "recording_disabled"
                            if not self.recording_enabled
                            else "no_recording_dir"
                        )
                    ),
                    **chroma_context_for_call_data(),
                )
            except Exception as e:
                logger.debug("human_call_ended_call_data_failed", error=str(e))

            # 일반 SIP 통화 지식 추출 (신규)
            if self.knowledge_extractor and self.recording_enabled and recording_dir_name:
                try:
                    import asyncio
                    from pathlib import Path
                    
                    transcript_path = Path(f"./recordings/{recording_dir_name}/transcript.txt")
                    
                    # 착신자 ID → Chroma owner는 username만 (sip:user@host → user)
                    from src.common.sip_owner import normalize_owner_username
                    callee_id = normalize_owner_username(
                        call_session.get_callee_uri() or ""
                    )
                    
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
                            try:
                                from src.common.call_data_record_logger import log_call_data

                                log_call_data(
                                    call_session.call_id,
                                    "knowledge",
                                    "post_call_extraction_skipped",
                                    reason="transcript_missing_after_delay",
                                    transcript_path=str(transcript_path),
                                    speaker_filter="callee",
                                    owner_id=callee_id,
                                )
                            except Exception:
                                pass
                            return
                        
                        logger.info("🚀 [Knowledge Flow] Starting knowledge extraction",
                                   call_id=call_session.call_id)
                        try:
                            from src.common.call_data_record_logger import log_call_data
                            from src.common.knowledge_call_data_helpers import chroma_context_for_call_data

                            log_call_data(
                                call_session.call_id,
                                "knowledge",
                                "post_call_extraction_started",
                                transcript_path=str(transcript_path),
                                speaker_filter="callee",
                                owner_id=callee_id,
                                extractor_type=type(self.knowledge_extractor).__name__,
                                **chroma_context_for_call_data(),
                            )
                        except Exception:
                            pass

                        res = await self.knowledge_extractor.extract_from_call(
                            call_id=call_session.call_id,
                            transcript_path=str(transcript_path),
                            owner_id=callee_id,
                            speaker="callee"  # 착신자 발화만 추출
                        )
                        try:
                            from src.common.call_data_record_logger import log_call_data
                            from src.common.knowledge_call_data_helpers import chroma_context_for_call_data

                            if hasattr(res, "stored_count"):
                                log_call_data(
                                    call_session.call_id,
                                    "knowledge",
                                    "post_call_extraction_finished",
                                    pipeline_version=getattr(res, "pipeline_version", "v2"),
                                    success=bool(getattr(res, "success", False)),
                                    stored_count=int(getattr(res, "stored_count", 0)),
                                    skipped_duplicate=int(getattr(res, "skipped_duplicate", 0)),
                                    skipped_quality=int(getattr(res, "skipped_quality", 0)),
                                    skipped_hallucination=int(getattr(res, "skipped_hallucination", 0)),
                                    error=(getattr(res, "error", None) or ""),
                                    **chroma_context_for_call_data(),
                                )
                            elif isinstance(res, dict):
                                log_call_data(
                                    call_session.call_id,
                                    "knowledge",
                                    "post_call_extraction_finished",
                                    pipeline_version="v1_knowledge_extractor",
                                    success=bool(res.get("success")),
                                    stored_count=int(res.get("extracted_count", 0)),
                                    confidence=res.get("confidence"),
                                    **chroma_context_for_call_data(),
                                )
                        except Exception:
                            pass
                    
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
            from src.common.sip_owner import normalize_owner_username
            callee_id = normalize_owner_username(f"sip:{callee_username}@unknown")
            
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
                    try:
                        from src.common.call_data_record_logger import log_call_data

                        log_call_data(
                            call_id,
                            "knowledge",
                            "post_call_extraction_skipped",
                            reason="transcript_missing_after_delay",
                            path="trigger_knowledge_extraction",
                            transcript_path=str(transcript_path),
                            speaker_filter="both",
                            owner_id=callee_id,
                        )
                    except Exception:
                        pass
                    return
                
                logger.info("🚀 [Knowledge Flow] Starting knowledge extraction",
                           call_id=call_id)
                try:
                    from src.common.call_data_record_logger import log_call_data
                    from src.common.knowledge_call_data_helpers import chroma_context_for_call_data

                    log_call_data(
                        call_id,
                        "knowledge",
                        "post_call_extraction_started",
                        path="trigger_knowledge_extraction",
                        transcript_path=str(transcript_path),
                        speaker_filter="both",
                        owner_id=callee_id,
                        extractor_type=type(self.knowledge_extractor).__name__,
                        **chroma_context_for_call_data(),
                    )
                except Exception:
                    pass

                res = await self.knowledge_extractor.extract_from_call(
                    call_id=call_id,
                    transcript_path=str(transcript_path),
                    owner_id=callee_id,
                    speaker="both"  # ✅ 발신자+착신자 모두 추출 (대화 전체)
                )
                try:
                    from src.common.call_data_record_logger import log_call_data
                    from src.common.knowledge_call_data_helpers import chroma_context_for_call_data

                    if hasattr(res, "stored_count"):
                        log_call_data(
                            call_id,
                            "knowledge",
                            "post_call_extraction_finished",
                            path="trigger_knowledge_extraction",
                            pipeline_version=getattr(res, "pipeline_version", "v2"),
                            success=bool(getattr(res, "success", False)),
                            stored_count=int(getattr(res, "stored_count", 0)),
                            skipped_duplicate=int(getattr(res, "skipped_duplicate", 0)),
                            skipped_quality=int(getattr(res, "skipped_quality", 0)),
                            skipped_hallucination=int(getattr(res, "skipped_hallucination", 0)),
                            error=(getattr(res, "error", None) or ""),
                            **chroma_context_for_call_data(),
                        )
                    elif isinstance(res, dict):
                        log_call_data(
                            call_id,
                            "knowledge",
                            "post_call_extraction_finished",
                            path="trigger_knowledge_extraction",
                            pipeline_version="v1_knowledge_extractor",
                            success=bool(res.get("success")),
                            stored_count=int(res.get("extracted_count", 0)),
                            confidence=res.get("confidence"),
                            **chroma_context_for_call_data(),
                        )
                except Exception:
                    pass
            
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
    
    def discard_ai_enabled_call(self, call_id: str) -> bool:
        """SIP BYE·`_cleanup_call` 등에서 `ai_enabled_calls`에서 제거.

        `cleanup_terminated_call`이 B2BUA 경로에서 호출되지 않을 때 집합 누수를 막는다.
        """
        if call_id not in self.ai_enabled_calls:
            logger.debug(
                "ai_enabled_call_discard_skip",
                call_id=call_id,
                note="집합에 없음 — 일반 통화이거나 이미 제거됨",
            )
            return False
        self.ai_enabled_calls.discard(call_id)
        logger.info(
            "ai_enabled_call_discarded",
            call_id=call_id,
            remaining_ai_calls=len(self.ai_enabled_calls),
            note="SIP 정리 경로에서 AI 활성 집합에서 제거",
        )
        return True

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

