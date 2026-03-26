"""
Socket.IO 서버 - 대시보드 WebSocket 연결 (포트 8001)

- JWT가 아닌 토큰(tok_*)도 허용해 extension 로그인 시 연결 가능.
- subscribe_call, submit_hitl_response 등 프론트 이벤트 처리.
- set_call_manager로 CallManager 주입 시 활성 통화/이벤트 연동 가능.
- emit_* / broadcast_* 는 manager 모듈에서 import되므로 여기서 정의 (실제 브로드캐스트는 _sio 사용).

의존성: pip install aiohttp python-socketio
"""

import asyncio
import logging
from datetime import datetime, timezone
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)

# CallManager 참조 (main에서 set_call_manager로 주입)
_call_manager: Any = None
# Socket.IO 서버 인스턴스 (start_server() 내에서 설정, emit 시 사용)
_sio: Any = None
# Socket.IO / aiohttp가 돌아가는 이벤트 루프 (별도 스레드). SIP/Pipecat 메인 루프와 다름.
_ws_loop: Optional[asyncio.AbstractEventLoop] = None

WS_PORT = 8001
CORS_ORIGINS = ["http://localhost:3000", "http://127.0.0.1:3000"]

# schedule_socket_emit 이 WS 미기동 시 조용히 드롭될 때 1회만 경고 (유저간 STT 등)
_stt_emit_skip_logged = False


def install_bypass_realtime_stt_callback() -> bool:
    """
    WebSocket(_sio) 준비 후 Bypass STT → stt_transcript 브로드캐스트 콜백 등록.
    SIP/RTP가 WS 스레드보다 먼저 패킷을 받는 경우 feed_audio 쪽에서 재시도할 수 있음.
    """
    if not _sio or not _ws_loop:
        return False
    try:
        from src.media.bypass_realtime_stt import get_broadcast_callback, set_broadcast_callback

        if get_broadcast_callback() is not None:
            return True

        def _bypass_stt_dashboard_cb(
            cid: str, text: str, is_final: bool, channel: str
        ) -> None:
            schedule_socket_emit(
                "stt_transcript",
                {
                    "call_id": cid,
                    "text": text,
                    "is_final": is_final,
                    "speaker": channel,
                    "channel": channel,
                    "source": "bypass_human",
                    "timestamp": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
                },
            )

        set_broadcast_callback(_bypass_stt_dashboard_cb)
        logger.info("bypass_realtime_stt_dashboard_callback_registered")
        return True
    except Exception as e:
        logger.warning("bypass_stt_callback_register_failed error=%s", e)
        return False


def _llm_client_for_hitl_refine():
    """대시보드 HITL 답변 다듬기용 LLM (config.yaml gemini + 환경변수). 실패 시 None."""
    import os

    from src.ai_voicebot.ai_pipeline.llm_client import LLMClient
    from src.config.config_loader import load_config

    try:
        cfg = load_config(None)
    except Exception:
        return None
    av = getattr(cfg, "ai_voicebot", None)
    if not av or not getattr(av, "google_cloud", None):
        return None
    gc = av.google_cloud
    gemini = (gc.gemini or {}) if gc else {}
    if not isinstance(gemini, dict):
        try:
            gemini = dict(gemini)
        except Exception:
            gemini = {}
    api_key = (
        gemini.get("api_key")
        or os.environ.get("GEMINI_API_KEY")
        or os.environ.get("GOOGLE_API_KEY")
    )
    if not api_key:
        return None
    return LLMClient(gemini, api_key)


def set_call_manager(cm: Any) -> None:
    """대시보드 활성 통화 목록 등 연동용 CallManager 주입."""
    global _call_manager
    _call_manager = cm


def _resolve_hitl_kb_owner(call_id: str, data: dict) -> tuple[str, str]:
    """
    HITL → 지식 저장 시 Chroma/RAG용 owner 정규화.
    우선순위: 요청 body owner/tenant_id → CallSession 착신 URI(get_callee_uri).

    Returns:
        (normalized_owner, resolution_source) — source는 client | call_session | empty
    """
    from src.common.sip_owner import normalize_owner_username

    raw = (data.get("owner") or data.get("tenant_id") or "").strip()
    if raw:
        n = normalize_owner_username(raw)
        if n:
            return n, "client"

    if _call_manager and call_id:
        try:
            sess = _call_manager.get_session(call_id)
            if sess is not None:
                uri = sess.get_callee_uri() or ""
                n = normalize_owner_username(uri)
                if n:
                    return n, "call_session"
        except Exception as e:
            logger.debug(
                "hitl_kb_owner_session_lookup_failed call_id=%s error=%s",
                call_id,
                e,
            )
    return "", "empty"


# ---------- Socket.IO는 WS 전용 스레드 루프에서만 안전하게 emit. SIP/Pipecat 루프에서는 스케줄만 함. ----------


def schedule_socket_emit(event: str, payload: Dict[str, Any], **emit_kwargs: Any) -> None:
    """동기 콜백·타 스레드에서 Socket.IO emit (fire-and-forget)."""
    global _stt_emit_skip_logged
    if not _sio or not _ws_loop:
        if event == "stt_transcript" and not _stt_emit_skip_logged:
            _stt_emit_skip_logged = True
            logger.warning(
                "schedule_socket_emit_skipped_ws_not_ready event=%s "
                "note=WebSocket_스레드_미기동_또는_socketio_미설치로_STT_이벤트_유실",
                event,
            )
        return

    async def _do_emit() -> None:
        try:
            await _sio.emit(event, payload, **emit_kwargs)
        except Exception as e:
            logger.debug("schedule_socket_emit_failed event=%s error=%s", event, e)

    try:
        fut = asyncio.run_coroutine_threadsafe(_do_emit(), _ws_loop)

        def _log_exc(f: asyncio.Future) -> None:
            try:
                f.result()
            except Exception as e:
                logger.debug("scheduled_emit_done_failed event=%s error=%s", event, e)

        fut.add_done_callback(_log_exc)
    except Exception as e:
        logger.debug("run_coroutine_threadsafe_failed event=%s error=%s", event, e)


async def _emit_on_ws_loop(event: str, payload: Dict[str, Any], **emit_kwargs: Any) -> None:
    """현재 코루틴이 WS 루프이면 직접 emit, 아니면 WS 루프에 위임."""
    if not _sio:
        return

    async def _do_emit() -> None:
        try:
            await _sio.emit(event, payload, **emit_kwargs)
        except Exception as e:
            logger.debug("emit_on_ws_loop_failed event=%s error=%s", event, e)

    try:
        cur = asyncio.get_running_loop()
    except RuntimeError:
        cur = None

    if _ws_loop is not None and cur is _ws_loop:
        await _do_emit()
    elif _ws_loop is not None:
        try:
            fut = asyncio.run_coroutine_threadsafe(_do_emit(), _ws_loop)

            def _log_exc(f: asyncio.Future) -> None:
                try:
                    f.result()
                except Exception as e:
                    logger.debug("emit_threadsafe_done_failed event=%s error=%s", event, e)

            fut.add_done_callback(_log_exc)
        except Exception as e:
            logger.debug("emit_threadsafe_submit_failed event=%s error=%s", event, e)
    else:
        await _do_emit()


# ---------- emit / broadcast (manager에서 import됨) ----------

async def emit_call_started(call_id: str, call_data: Dict[str, Any]) -> None:
    """통화 시작 이벤트를 대시보드에 전송."""
    await _emit_on_ws_loop("call_started", {"call_id": call_id, **call_data})


async def emit_call_ended(call_id: str) -> None:
    """통화 종료 이벤트를 대시보드에 전송."""
    await _emit_on_ws_loop("call_ended", {"call_id": call_id})


async def emit_stt_transcript(
    call_id: str,
    data: Optional[Dict[str, Any]] = None,
    *,
    text: Optional[str] = None,
    is_final: Optional[bool] = None,
    **kwargs: Any,
) -> None:
    """STT 인식 결과 전송.

    두 가지 호출 방식 모두 허용:
      emit_stt_transcript(call_id, {"text": ..., "is_final": ...})   # 딕셔너리
      emit_stt_transcript(call_id, text=..., is_final=...)           # 키워드
    """
    payload: Dict[str, Any] = {}
    if data:
        payload.update(data)
    if text is not None:
        payload["text"] = text
    if is_final is not None:
        payload["is_final"] = is_final
    payload.update(kwargs)
    payload.setdefault("timestamp", datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"))
    await _emit_on_ws_loop("stt_transcript", {"call_id": call_id, **payload})


async def emit_tts_started(
    call_id: str,
    data: Optional[Dict[str, Any]] = None,
    *,
    text: Optional[str] = None,
    **kwargs: Any,
) -> None:
    """TTS 시작 이벤트 전송.

    두 가지 호출 방식 모두 허용:
      emit_tts_started(call_id, {"text": ...})   # 딕셔너리
      emit_tts_started(call_id, text=...)        # 키워드
    """
    payload: Dict[str, Any] = {}
    if data:
        payload.update(data)
    if text is not None:
        payload["text"] = text
    payload.update(kwargs)
    payload.setdefault("timestamp", datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"))
    await _emit_on_ws_loop("tts_started", {"call_id": call_id, **payload})


async def emit_tts_completed(
    call_id: str,
    data: Optional[Dict[str, Any]] = None,
    **kwargs: Any,
) -> None:
    payload: Dict[str, Any] = {}
    if data:
        payload.update(data)
    payload.update(kwargs)
    payload.setdefault("timestamp", datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"))
    await _emit_on_ws_loop("tts_completed", {"call_id": call_id, **payload})


async def emit_ai_greeting(
    call_id: str,
    data_or_phase: Any = None,
    text: Optional[str] = None,
    **kwargs: Any,
) -> None:
    """AI 인사말 이벤트 전송.

    세 가지 호출 방식 모두 허용:
      emit_ai_greeting(call_id, {"text": ..., "phase": ...})   # 딕셔너리
      emit_ai_greeting(call_id, 1, "안녕하세요")               # (call_id, phase, text)
      emit_ai_greeting(call_id, text=..., phase=...)           # 키워드
    """
    payload: Dict[str, Any] = {}
    if isinstance(data_or_phase, dict):
        payload.update(data_or_phase)
    elif isinstance(data_or_phase, int):
        # emit_ai_greeting(call_id, phase_num, text_str) 형식
        payload["phase"] = data_or_phase
        if text is not None:
            payload["text"] = text
    elif data_or_phase is not None:
        payload["data"] = data_or_phase
    if text is not None and "text" not in payload:
        payload["text"] = text
    payload.update(kwargs)
    payload.setdefault("timestamp", datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"))
    payload.setdefault("role", "assistant")
    await _emit_on_ws_loop("ai_greeting", {"call_id": call_id, **payload})


async def emit_hitl_requested(call_id: str, question: str, context: Dict[str, Any], urgency: str = "medium") -> None:
    await _emit_on_ws_loop(
        "hitl_requested",
        {"call_id": call_id, "question": question, "context": context, "urgency": urgency},
    )


async def emit_hitl_fallback_available(call_id: str, data: Optional[Dict[str, Any]] = None) -> None:
    await _emit_on_ws_loop("hitl_fallback_available", {"call_id": call_id, **(data or {})})


async def emit_hitl_timeout(call_id: str, data: Optional[Dict[str, Any]] = None) -> None:
    """HITL timeout 발생 시 프론트엔드에 알림 (AI가 다시 연결받음)"""
    await _emit_on_ws_loop("hitl_timeout", {"call_id": call_id, **(data or {})})
    logger.info("hitl_timeout_emitted call_id=%s", call_id)


async def emit_knowledge_updated(call_id: str, data: Dict[str, Any]) -> None:
    await _emit_on_ws_loop("knowledge_updated", {"call_id": call_id, **data})


# ---------- Transfer Events (AI Dynamic Call Transfer) ----------

async def emit_transfer_initiated(
    call_id: str,
    target_number: str,
    department: Optional[str] = None,
    **kwargs: Any,
) -> None:
    """
    호 전환 시작 이벤트
    
    Frontend에서 수신하여 실시간 통화 화면에 "호 전환 중..." 표시
    
    Args:
        call_id: 통화 ID
        target_number: 대상 전화번호
        department: 부서명
    """
    payload = {
        "call_id": call_id,
        "target_number": target_number,
        "department": department or "",
        "timestamp": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        **kwargs,
    }
    await _emit_on_ws_loop("transfer_initiated", payload)
    logger.info("ws_transfer_initiated_sent call_id=%s target=%s", call_id, target_number)


async def emit_transfer_ringing(
    call_id: str,
    target_number: str,
    **kwargs: Any,
) -> None:
    """
    호 전환 대상이 응답 중 (180 Ringing) 이벤트
    
    Args:
        call_id: 통화 ID
        target_number: 대상 전화번호
    """
    payload = {
        "call_id": call_id,
        "target_number": target_number,
        "timestamp": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        **kwargs,
    }
    await _emit_on_ws_loop("transfer_ringing", payload)
    logger.info("ws_transfer_ringing_sent call_id=%s target=%s", call_id, target_number)


async def emit_transfer_success(
    call_id: str,
    target_number: str,
    department: Optional[str] = None,
    **kwargs: Any,
) -> None:
    """
    호 전환 성공 이벤트
    
    Frontend에서 수신하여:
    - "호 전환 완료" 표시
    - AI 응대 화면 → 일반 통화 화면으로 전환
    
    Args:
        call_id: 통화 ID
        target_number: 대상 전화번호
        department: 부서명
    """
    payload = {
        "call_id": call_id,
        "target_number": target_number,
        "department": department or "",
        "timestamp": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        **kwargs,
    }
    await _emit_on_ws_loop("transfer_success", payload)
    logger.info("ws_transfer_success_sent call_id=%s target=%s", call_id, target_number)


async def emit_transfer_failed(
    call_id: str,
    target_number: str,
    reason: str = "unknown",
    **kwargs: Any,
) -> None:
    """
    호 전환 실패 이벤트
    
    Frontend에서 수신하여 "호 전환 실패" 알림
    
    Args:
        call_id: 통화 ID
        target_number: 대상 전화번호
        reason: 실패 사유
    """
    payload = {
        "call_id": call_id,
        "target_number": target_number,
        "reason": reason,
        "timestamp": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        **kwargs,
    }
    await _emit_on_ws_loop("transfer_failed", payload)
    logger.warning(
        "ws_transfer_failed_sent call_id=%s target=%s reason=%s",
        call_id,
        target_number,
        reason,
    )


async def broadcast_to_call(call_id: str, event: str, data: Dict[str, Any]) -> None:
    """해당 통화 구독자에게만 전송 (room call_{call_id})."""
    room = f"call_{call_id}"
    await _emit_on_ws_loop(event, data, room=room)


async def broadcast_to_operators(event: str, data: Dict[str, Any]) -> None:
    """연산자(대시보드) 전원에게 전송. room이 없으면 전역 broadcast로 대체."""
    await _emit_on_ws_loop(event, data)


async def broadcast_global(event: str, data: Dict[str, Any]) -> None:
    """전체 클라이언트에게 전송."""
    await _emit_on_ws_loop(event, data)


async def start_server() -> None:
    """Socket.IO 서버 기동 (0.0.0.0:8001). tok_* / JWT 모두 허용."""
    global _sio, _ws_loop
    try:
        import socketio
        from aiohttp import web
    except ImportError as e:
        logger.warning(
            "WebSocket 서버 의존성 없음: %s. pip install aiohttp python-socketio 후 재시작하거나, ws-server(npm start)를 8001에서 실행하세요.",
            e,
        )
        while True:
            await asyncio.sleep(3600)
        return

    sio = socketio.AsyncServer(
        async_mode="aiohttp",
        cors_allowed_origins=CORS_ORIGINS,
    )
    app = web.Application()
    sio.attach(app)
    _sio = sio
    _ws_loop = asyncio.get_running_loop()

    # 유저 간(Bypass) RTP → Google 스트리밍 STT → 대시보드 stt_transcript
    install_bypass_realtime_stt_callback()

    @sio.event
    async def connect(sid: str, environ: dict, auth: Optional[dict]) -> None:
        # tok_* 및 JWT 모두 허용 (거부하지 않음)
        await sio.emit(
            "connection_established",
            {
                "message": "Connected",
                "timestamp": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
            },
            room=sid,
        )

    @sio.event
    async def subscribe_call(sid: str, data: dict) -> Optional[dict]:
        """클라이언트 콜백에 응답 반환 (return 값이 ack로 전달됨)."""
        if isinstance(data, dict) and data.get("call_id"):
            return {"success": True, "call_id": data["call_id"]}
        return {"success": False, "error": "call_id required"}

    @sio.event
    async def unsubscribe_call(sid: str, data: dict) -> None:
        pass

    @sio.event
    async def submit_hitl_response(sid: str, data: dict) -> dict:
        """
        운영자 HITL 응답 제출 처리.
        
        HITL 지연 응답 설계: original_question 필드 추가
        
        Args:
            sid: Socket.IO 세션 ID
            data: {
                "call_id": str,
                "response_text": str,
                "original_question": str (추가),  # HITL 요청 시의 원래 질문
                "save_to_kb": bool (optional),
                "category": str (optional),  # 미지정 시 question (RAG complaint/transfer $in 정합)
                "owner" | "tenant_id": str (optional),  # Chroma owner; 없으면 CallSession 착신 URI 시도
                "question": str (optional)
            }
        
        Returns:
            {"success": bool, "message": str, "refined_response": str (optional)}
        """
        call_id = data.get("call_id")
        response_text = data.get("response_text")
        original_question = data.get("original_question", "")  # HITL 지연 응답 설계
        save_to_kb = data.get("save_to_kb", False)
        # "faq"는 doc_type 용어와 혼동되고 RAG complaint/transfer category $in에 없음 → 기본 question
        category = data.get("category") or "question"
        question = data.get("question", original_question)  # question이 없으면 original_question 사용
        
        if not call_id or not response_text:
            return {"success": False, "message": "call_id 및 response_text 필수"}
        
        try:
            # 1. LLM으로 응답 다듬기
            refined_response = response_text  # 기본값
            try:
                llm = _llm_client_for_hitl_refine()
                if llm is None:
                    logger.warning(
                        "hitl_llm_refine_skipped_no_client call_id=%s note=config_or_api_key_missing",
                        call_id,
                    )
                    refined_response = f"확인해 드렸습니다. {response_text}"
                else:
                    refine_prompt = (
                        f"운영자가 작성한 답변을 발신자에게 자연스럽고 친절하게 전달하는 문장으로 변환하세요.\n\n"
                        f"운영자 답변: {response_text}\n\n"
                        f"변환된 답변 (한 문장, '확인해 드렸습니다'로 시작):"
                    )

                    refined_response = await llm.generate_simple(refine_prompt)
                    if not refined_response or len(refined_response.strip()) < 5:
                        refined_response = f"확인해 드렸습니다. {response_text}"

                    logger.info(
                        "hitl_response_refined call_id=%s original_len=%s refined_len=%s",
                        call_id,
                        len(response_text),
                        len(refined_response),
                    )
            except Exception as e:
                logger.warning("hitl_llm_refine_failed call_id=%s error=%s", call_id, e)
                refined_response = f"확인해 드렸습니다. {response_text}"
            
            # 2. 응답을 큐에 전달 (RAGLLMProcessor가 소비)
            # HITL 지연 응답 설계: original_question 추가
            try:
                from src.services.hitl import get_hitl_service
                hitl_service = get_hitl_service()
                payload = {
                    "type": "hitl_response",
                    "text": refined_response,
                    "original_text": response_text,
                    "original_question": original_question,
                    "call_id": call_id,
                }
                queued_ok = await hitl_service.enqueue_response(call_id, payload)
                if queued_ok:
                    rq = hitl_service.get_response_queue(call_id)
                    qsz = rq.qsize() if rq else -1
                    logger.info(
                        "hitl_response_queued call_id=%s has_original_question=%s queue_size=%s",
                        call_id,
                        bool(original_question),
                        qsz,
                    )
                else:
                    logger.warning(
                        "hitl_response_queue_not_found_or_enqueue_failed call_id=%s note=no_queue_or_no_event_loop",
                        call_id,
                    )
            except Exception as e:
                logger.error("hitl_response_queue_failed call_id=%s error=%s", call_id, e)
            
            # 3. VectorDB에 저장 (save_to_kb=True 시)
            if save_to_kb and question:
                try:
                    from src.services.knowledge_service import get_knowledge_service
                    knowledge_service = get_knowledge_service()

                    kb_owner, kb_owner_src = _resolve_hitl_kb_owner(call_id, data if isinstance(data, dict) else {})
                    if not kb_owner:
                        logger.warning(
                            "hitl_kb_owner_unresolved call_id=%s save_to_kb=True "
                            "category=%s note=owner없으면_RAG_where_owner에_안_걸림_요청에_tenant_id_권장",
                            call_id,
                            category,
                        )
                    else:
                        logger.info(
                            "hitl_kb_owner_resolved call_id=%s owner=%s source=%s",
                            call_id,
                            kb_owner,
                            kb_owner_src,
                        )

                    result = await knowledge_service.add_from_hitl(
                        question=question,
                        answer=response_text,
                        call_id=call_id,
                        operator_id=sid,  # Socket.IO 세션 ID를 운영자 ID로 사용
                        category=category,
                        owner=kb_owner or None,
                    )
                    
                    logger.info(
                        "hitl_knowledge_saved call_id=%s doc_id=%s category=%s owner_set=%s",
                        call_id,
                        result.get("doc_id"),
                        category,
                        bool(kb_owner),
                    )
                    
                    # Frontend에 지식 업데이트 알림
                    await emit_knowledge_updated(call_id, {
                        "message": "HITL 응답이 지식 베이스에 저장되었습니다",
                        "doc_id": result.get("doc_id"),
                        "category": category
                    })
                except Exception as e:
                    logger.error("hitl_knowledge_save_failed call_id=%s error=%s", call_id, e)
            
            # 4. hitl_resolved 이벤트 전송
            try:
                await _sio.emit("hitl_resolved", {
                    "call_id": call_id,
                    "response": refined_response,
                    "timestamp": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
                })
            except Exception as e:
                logger.debug("hitl_resolved_emit_failed call_id=%s error=%s", call_id, e)
            
            return {
                "success": True,
                "message": "HITL 응답이 처리되었습니다",
                "refined_response": refined_response
            }
            
        except Exception as e:
            logger.exception("submit_hitl_response_failed call_id=%s error=%s", call_id, e)
            return {
                "success": False,
                "message": f"HITL 응답 처리 실패: {str(e)}"
            }
    
    @sio.event
    async def manual_transfer_request(sid: str, data: dict) -> dict:
        """
        상담원 수동 호 전환 요청
        
        Args:
            sid: Socket.IO 세션 ID
            data: {
                "call_id": str,
                "operator_id": str,
                "operator_number": str  # 상담원 자신의 전화번호
            }
        
        Returns:
            {"success": bool, "message": str}
        """
        call_id = data.get("call_id")
        operator_id = data.get("operator_id")
        operator_number = data.get("operator_number")
        
        if not call_id or not operator_number:
            return {
                "success": False,
                "message": "call_id 및 operator_number 필수"
            }
        
        try:
            from src.call_transfer import manual_transfer_from_operator
            
            logger.info(
                "manual_transfer_request_received call_id=%s operator_id=%s sid=%s",
                call_id,
                operator_id,
                sid,
            )
            
            success = await manual_transfer_from_operator(
                call_id=call_id,
                operator_id=operator_id or sid,
                operator_number=operator_number
            )
            
            if success:
                return {
                    "success": True,
                    "message": "호 전환이 시작되었습니다."
                }
            else:
                return {
                    "success": False,
                    "message": "호 전환 실패"
                }
                
        except Exception as e:
            logger.exception("manual_transfer_error call_id=%s error=%s", call_id, e)
            return {
                "success": False,
                "message": f"오류: {str(e)}"
            }

    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", WS_PORT)
    await site.start()

    logger.info("WebSocket server started on ws://0.0.0.0:%s", WS_PORT)

    while True:
        await asyncio.sleep(3600)
