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
import os
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Union

logger = logging.getLogger(__name__)

# CallManager 참조 (main에서 set_call_manager로 주입)
_call_manager: Any = None
# Socket.IO 서버 인스턴스 (start_server() 내에서 설정, emit 시 사용)
_sio: Any = None
# Socket.IO / aiohttp가 돌아가는 이벤트 루프 (별도 스레드). SIP/Pipecat 메인 루프와 다름.
_ws_loop: Optional[asyncio.AbstractEventLoop] = None

WS_PORT = 8001
CORS_ORIGINS = ["http://localhost:3000", "http://127.0.0.1:3000"]


def _socketio_cors_allowed_origins() -> Union[str, List[str]]:
    """환경변수 `WS_CORS_ORIGINS`: 쉼표 구분 출처, `*` 는 전체 허용 (LAN에서 Next 접속 시 필요)."""
    raw = (os.environ.get("WS_CORS_ORIGINS") or "").strip()
    if raw == "*":
        return "*"
    if raw:
        return [x.strip() for x in raw.split(",") if x.strip()]
    return CORS_ORIGINS

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


def set_call_manager(cm: Any) -> None:
    """대시보드 활성 통화 목록 등 연동용 CallManager 주입."""
    global _call_manager
    _call_manager = cm


def get_injected_call_manager() -> Any:
    """HTTP API `GET /api/calls/active` 등에서 동일 프로세스의 CallManager 조회 (미주입 시 None)."""
    return _call_manager


def _resolve_hitl_kb_owner(call_id: str, data: dict) -> tuple[str, str]:
    """
    HITL → 지식 저장 시 Chroma/RAG용 owner 정규화.
    우선순위: 요청 body owner/tenant_id → context.owner(hitl_requested 페이로드)
    → CallSession(call_id) → CallSession(get_session_by_sip_call_id).

    owner가 비면 Chroma에는 들어가도 RAG 검색(where owner)에서 영구히 제외될 수 있음.

    Returns:
        (normalized_owner, resolution_source) — source는 client | context | call_session | sip_call_id | empty
    """
    from src.common.sip_owner import normalize_owner_username

    raw = (data.get("owner") or data.get("tenant_id") or "").strip()
    if raw:
        n = normalize_owner_username(raw)
        if n:
            return n, "client"

    ctx = data.get("context")
    if isinstance(ctx, dict):
        raw_ctx = (ctx.get("owner") or "").strip()
        if raw_ctx:
            n = normalize_owner_username(raw_ctx)
            if n:
                return n, "context"

    if _call_manager and call_id:
        try:
            sess = _call_manager.get_session(call_id)
            if sess is None:
                sess = _call_manager.get_session_by_sip_call_id(call_id)
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
    _txt = payload.get("text")
    _txt_len = len(str(_txt)) if _txt is not None else 0
    logger.info(
        "emit_ai_greeting_dispatch call_id=%s phase=%s text_len=%s",
        call_id,
        payload.get("phase"),
        _txt_len,
    )
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
        cors_allowed_origins=_socketio_cors_allowed_origins(),
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
                "save_to_kb": bool (optional),  # True면 즉시 Chroma 저장. False면 통화 종료 시 저장.
                "category": str (optional),  # VALID_CATEGORIES 중 하나 권장; 미지정·무효 시 intent→complaint/transfer/question
                "owner" | "tenant_id": str (optional),  # Chroma owner; 없으면 CallSession 착신 URI 시도
                "question": str (optional)
            }
        
        Returns:
            {"success": bool, "message": str, "refined_response": str}
            refined_response: 운영자가 제출한 원문(response_text). 고객 TTS용 문장은
            파이프라인에서 format_hitl_reply_for_customer(질문+답변)로 생성됨.
        """
        call_id = data.get("call_id")
        response_text = data.get("response_text")
        original_question = data.get("original_question", "")  # HITL 지연 응답 설계
        # 기본 True: 운영자가 명시적으로 끄지 않으면 지식 반영(즉시 또는 통화 종료 시 flush)
        _st = str(os.environ.get("HITL_SAVE_TO_KB_DEFAULT", "true")).strip().lower()
        _default_save = _st in ("1", "true", "yes", "on")
        save_to_kb = data.get("save_to_kb", _default_save)
        if "save_to_kb" not in (data or {}):
            logger.info(
                "submit_hitl_save_to_kb_default call_id=%s save_to_kb=%s env_HITL_SAVE_TO_KB_DEFAULT=%s",
                call_id,
                save_to_kb,
                os.environ.get("HITL_SAVE_TO_KB_DEFAULT", "true"),
            )
        # 클라이언트가 question/original_question을 빠뜨려도, needs_human 시점 FIFO 질문으로 보강
        q_from_client = (data.get("question") or "").strip()
        oq = (original_question or "").strip()

        if not call_id or not response_text:
            return {"success": False, "message": "call_id 및 response_text 필수"}

        from src.services.hitl import get_hitl_service
        from src.services.hitl_kb_category import resolve_hitl_kb_category

        hitl_service = get_hitl_service()
        req_ctx = None
        try:
            req_ctx = hitl_service.pop_hitl_request_context(call_id)
            intent_for_category = (req_ctx.intent if req_ctx else "") or ""
            category = resolve_hitl_kb_category(data.get("category"), intent_for_category)
            logger.info(
                "submit_hitl_response_category_resolved call_id=%s category=%s "
                "intent_from_fifo=%s explicit_category=%s",
                call_id,
                category,
                intent_for_category,
                (data.get("category") or ""),
            )
        except Exception as e:
            logger.warning("submit_hitl_hitl_category_resolve_failed call_id=%s error=%s", call_id, e)
            category = resolve_hitl_kb_category(data.get("category"), "")

        q_from_fifo = (req_ctx.question if req_ctx else "").strip()
        # rewritten_query: LLM이 정제한 쿼리 — STT 오인식("기 삼성" 등) 보정 목적
        # KB 저장 Q 텍스트 우선순위: 클라이언트 전달 > original_question > rewritten_query > STT 원문(q_from_fifo)
        q_rewritten = (getattr(req_ctx, "rewritten_query", "") if req_ctx else "").strip()
        question = q_from_client or oq or q_rewritten or q_from_fifo
        if question and not q_from_client:
            if q_rewritten and not oq:
                logger.info(
                    "hitl_kb_question_from_rewritten_query call_id=%s "
                    "note=STT오인식_보정_rewritten_query_사용 rewritten_preview=%s",
                    call_id,
                    q_rewritten[:60],
                )
            elif q_from_fifo and not oq and not q_rewritten:
                logger.info(
                    "hitl_kb_question_from_fifo call_id=%s note=클라이언트_질문_누락_FIFO로_보강",
                    call_id,
                )
        if not question:
            logger.warning(
                "hitl_kb_question_empty call_id=%s save_to_kb=%s note=지식반영_및_콜인사이트_스킵_가능",
                call_id,
                save_to_kb,
            )

        kb_owner, kb_owner_src = _resolve_hitl_kb_owner(call_id, data if isinstance(data, dict) else {})
        if question and not kb_owner:
            logger.warning(
                "hitl_kb_owner_unresolved call_id=%s save_to_kb=%s source=%s "
                "note=owner없이_저장되면_RAG_tenant_필터에_안_잡힘_요청에_tenant_id_owner_또는_context.owner_권장",
                call_id,
                save_to_kb,
                kb_owner_src,
            )

        try:
            # 1. 큐에는 운영자 원문만 넣음. 질문+답변 형태 TTS는 RAGLLMProcessor에서
            #    LLMClient.format_hitl_reply_for_customer(original_question, text) 한 번만 수행.
            refined_response = response_text
            oq_for_tts = (question or oq or original_question or "").strip()
            logger.info(
                "hitl_response_queued_raw_operator_text call_id=%s has_resolved_question=%s "
                "note=tts_format_in_pipeline",
                call_id,
                bool(oq_for_tts),
            )

            # 2. 응답을 큐에 전달 (RAGLLMProcessor가 소비)
            # HITL 지연 응답 설계: original_question 추가
            try:
                payload = {
                    "type": "hitl_response",
                    "text": response_text,
                    "original_text": response_text,
                    "original_question": oq_for_tts or original_question,
                    "call_id": call_id,
                }
                queued_ok = await hitl_service.enqueue_response(call_id, payload)
                if queued_ok:
                    rq = hitl_service.get_response_queue(call_id)
                    qsz = rq.qsize() if rq else -1
                    logger.info(
                        "hitl_response_queued call_id=%s has_resolved_question=%s queue_size=%s",
                        call_id,
                        bool(oq_for_tts),
                        qsz,
                    )
                else:
                    logger.warning(
                        "hitl_response_queue_not_found_or_enqueue_failed call_id=%s note=no_queue_or_no_event_loop",
                        call_id,
                    )
            except Exception as e:
                logger.error("hitl_response_queue_failed call_id=%s error=%s", call_id, e)

            # 통화 이력: HITL로 처리된 질문은 AI 미응대 count·목록에서 제외
            try:
                from src.common.call_insights_buffer import mark_hitl_resolved_for_questions

                _marked = mark_hitl_resolved_for_questions(
                    call_id,
                    question or "",
                    original_question or "",
                )
                if _marked:
                    logger.info(
                        "hitl_call_insights_marked_resolved call_id=%s matched_rows=%s",
                        call_id,
                        _marked,
                    )
            except Exception as e:
                logger.debug(
                    "hitl_call_insights_mark_failed call_id=%s error=%s",
                    call_id,
                    e,
                )
            
            # 3. VectorDB에 저장 (save_to_kb=True 시 즉시; False 시 통화 종료 flush)
            if save_to_kb and question:
                try:
                    from src.services.knowledge_service import get_knowledge_service
                    knowledge_service = get_knowledge_service()

                    if kb_owner:
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
                        extra_metadata={"kb_timing": "immediate"},
                    )
                    if not result.get("success"):
                        logger.error(
                            "hitl_knowledge_save_failed call_id=%s error=%s category=%s",
                            call_id,
                            result.get("error"),
                            category,
                        )
                    else:
                        logger.info(
                            "hitl_knowledge_saved call_id=%s doc_id=%s category=%s owner_set=%s",
                            call_id,
                            result.get("doc_id"),
                            category,
                            bool(kb_owner),
                        )
                        await emit_knowledge_updated(
                            call_id,
                            {
                                "message": "HITL 응답이 지식 베이스에 저장되었습니다",
                                "doc_id": result.get("doc_id"),
                                "category": category,
                            },
                        )
                except Exception as e:
                    logger.error("hitl_knowledge_save_failed call_id=%s error=%s", call_id, e)
            elif (question or "").strip():
                # 통화 종료(BYE) 시 일괄 Chroma 적재 — 제출 시점 owner를 함께 저장(flush 시 SIP 정리 owner보다 우선)
                hitl_service.queue_hitl_kb_for_call_end(
                    call_id,
                    question.strip(),
                    response_text.strip(),
                    category,
                    sid,
                    owner=(kb_owner or None),
                )
                logger.info(
                    "hitl_kb_queued_for_call_end_hint call_id=%s owner_resolved=%s note=BYE_시_flush_또는_save_to_kb_true로_즉시저장",
                    call_id,
                    bool(kb_owner),
                )

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

    # ClientConnectionResetError: 클라이언트가 먼저 연결을 끊은 뒤 서버가 응답을 보내려 할 때
    # 발생하는 무해한 에러다 (브라우저 탭 닫기, 페이지 이동, 네트워크 재연결 등).
    # aiohttp web_protocol.py가 ERROR 레벨로 출력하는 스택트레이스를 logging filter로 억제한다.
    import logging as _logging

    class _SuppressClientResetFilter(_logging.Filter):
        """aiohttp가 ClientConnectionResetError 를 ERROR로 출력하는 것을 DEBUG로 낮춤."""
        def filter(self, record: _logging.LogRecord) -> bool:
            if record.levelno >= _logging.ERROR and record.exc_info:
                exc = record.exc_info[1]
                try:
                    from aiohttp.client_exceptions import ClientConnectionResetError as _CCRE
                    if isinstance(exc, _CCRE):
                        record.levelno = _logging.DEBUG
                        record.levelname = "DEBUG"
                        return record.levelno >= _logging.root.level
                except ImportError:
                    pass
            return True

    _aiohttp_logger = _logging.getLogger("aiohttp.server")
    _aiohttp_logger.addFilter(_SuppressClientResetFilter())

    runner = web.AppRunner(
        app,
        handle_signals=False,
    )
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", WS_PORT)
    await site.start()

    logger.info("WebSocket server started on ws://0.0.0.0:%s", WS_PORT)

    while True:
        await asyncio.sleep(3600)
