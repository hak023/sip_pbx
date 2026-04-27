"""채팅(SIP MESSAGE)·RCS(텍스트 게이트웨이) 관리 API 라우터.

엔드포인트:
    GET  /api/chat/threads?owner=       스레드 목록 (고객별 최신 메시지)
    GET  /api/chat/messages?thread_id=&owner=  특정 스레드 메시지 이력
    GET  /api/chat/relay?owner=         테넌트별 ``chat_relay_settings`` (SIP MESSAGE AI 스위치·접두어 등)
    PUT  /api/chat/relay?owner=         ``message_ai_reply_*`` 저장 (LangGraph 텍스트 응답 경로)
    POST /api/chat/send                 SIP MESSAGE 릴레이 + DB (HTTP 200, success=실제 2xx 여부)
    POST /api/chat/retry/{message_id}   실패한 발신 메시지 재전송
"""

from __future__ import annotations

from typing import Any, List, Optional

import structlog
from fastapi import APIRouter, Body, HTTPException, Query
from pydantic import BaseModel

logger = structlog.get_logger(__name__)

router = APIRouter(prefix="/api/chat", tags=["Chat"])


# ── 요청/응답 모델 ────────────────────────────────────────────────────

class ChatSendRequest(BaseModel):
    to_phone: str
    """수신자 SIP username 또는 전화번호 (REGISTER 키와 일치 권장)"""
    body: str
    """메시지 본문"""
    owner: str = ""
    """발신자 테넌트 ID (로그인 착신번호·내선 — SIP REGISTER 와 동일)"""
    call_id: str = ""
    """연관 통화 ID (선택)"""


class ChatSendResponse(BaseModel):
    success: bool
    to_phone: str
    body: str
    message_id: int
    error_code: str = ""
    detail: str = ""


class ChatRelayUpsertRequest(BaseModel):
    sip_username: Optional[str] = None
    """레거시: SIP REGISTER 별칭 매핑. 비우면 owner 문자열만 사용. UI에서 제거됨 — 생략 시 기존 유지."""
    message_ai_policy: str | None = None
    """사용 안 함. 생략 시 서버가 ``settings`` 로 저장한다."""
    message_ai_reply_enabled: bool | None = None
    """SIP MESSAGE·RCS 텍스트 수신 시 AI 자동응답 여부(설정 페이지 스위치)."""
    message_ai_reply_prefix: str | None = None
    """자동응답 본문 앞에 붙는 접두어(비우면 서버 기본값)."""


class ChatRelaySettingsResponse(BaseModel):
    owner: str
    sip_username: str = ""
    updated_at: str = ""
    message_ai_policy: str = "settings"
    message_ai_reply_enabled: bool = False
    message_ai_reply_prefix: str = ""


# ── 엔드포인트 ────────────────────────────────────────────────────────


@router.get("/relay", response_model=ChatRelaySettingsResponse)
async def get_chat_relay(owner: str = Query(..., description="테넌트 owner")) -> ChatRelaySettingsResponse:
    """테넌트별 SIP 릴레이 내선(chat_relay_settings) 조회."""
    from src.services.chat_relay_service import get_chat_relay_settings

    row = get_chat_relay_settings(owner)
    return ChatRelaySettingsResponse(
        owner=str(row.get("owner") or owner),
        sip_username=str(row.get("sip_username") or ""),
        updated_at=str(row.get("updated_at") or ""),
        message_ai_policy=str(row.get("message_ai_policy") or "settings"),
        message_ai_reply_enabled=bool(int(row.get("message_ai_reply_enabled") or 0)),
        message_ai_reply_prefix=str(row.get("message_ai_reply_prefix") or ""),
    )


@router.put("/relay", response_model=ChatRelaySettingsResponse)
async def put_chat_relay(
    owner: str = Query(..., description="테넌트 owner"),
    body: ChatRelayUpsertRequest = Body(...),
) -> ChatRelaySettingsResponse:
    """REGISTER 와 일치하는 sip_username 및 메시지 AI(설정) 필드를 저장한다."""
    from src.services.chat_relay_service import get_chat_relay_settings, upsert_chat_relay_settings

    patch = body.model_dump(exclude_unset=True)
    cur = get_chat_relay_settings(owner)
    sip_f = patch["sip_username"] if "sip_username" in patch else str(cur.get("sip_username") or "")
    row = upsert_chat_relay_settings(
        owner,
        sip_f,
        message_ai_policy=patch.get("message_ai_policy"),
        message_ai_reply_enabled=patch.get("message_ai_reply_enabled"),
        message_ai_reply_prefix=patch.get("message_ai_reply_prefix"),
    )
    return ChatRelaySettingsResponse(
        owner=str(row.get("owner") or owner),
        sip_username=str(row.get("sip_username") or ""),
        updated_at=str(row.get("updated_at") or ""),
        message_ai_policy=str(row.get("message_ai_policy") or "settings"),
        message_ai_reply_enabled=bool(int(row.get("message_ai_reply_enabled") or 0)),
        message_ai_reply_prefix=str(row.get("message_ai_reply_prefix") or ""),
    )

@router.get("/threads")
async def list_threads(owner: str = Query(..., description="테넌트 owner")) -> List[dict[str, Any]]:
    """채팅 스레드 목록을 반환한다 (고객 번호 단위, 최신 활동 순).

    각 항목:
        thread_id     : 고객 번호
        last_body     : 마지막 메시지 본문 (미리보기)
        last_time     : 마지막 메시지 시각
        message_count : 총 메시지 수
        inbound_count : 수신 메시지 수
        last_direction: 마지막 메시지 방향 ('inbound'|'outbound')
    """
    try:
        from src.services.chat_service import get_threads
        return get_threads(owner)
    except Exception as e:
        logger.error("chat_list_threads_error", error=str(e), exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/messages")
async def list_messages(
    thread_id: str = Query(..., description="스레드 ID (상대 착신번호)"),
    owner: str = Query(..., description="테넌트 owner"),
    limit: int = Query(100, ge=1, le=500),
) -> List[dict[str, Any]]:
    """특정 고객과의 메시지 이력을 시간 오름차순으로 반환한다."""
    try:
        from src.services.chat_service import get_messages
        return get_messages(thread_id=thread_id, owner=owner, limit=limit)
    except Exception as e:
        logger.error("chat_list_messages_error", error=str(e), exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/send", response_model=ChatSendResponse)
async def send_message(req: ChatSendRequest) -> ChatSendResponse:
    """REGISTER 맵을 사용해 SIP MESSAGE를 발신하고 chat_messages에 기록한다.

    전송 실패 시에도 HTTP 200과 ``success: false`` 로 내려 프론트에서 재전송 UI를 쓸 수 있게 한다.
    """
    from src.services.chat_relay_service import resolve_sip_from_for_outbound
    from src.services.chat_sip_delivery import deliver_chat_sip_message
    from src.services.chat_service import save_chat_message

    tenant_owner = (req.owner or "").strip() or "pbx"
    sip_from = resolve_sip_from_for_outbound(tenant_owner)
    to_phone = (req.to_phone or "").strip()
    body = (req.body or "").strip()

    if not to_phone or not body:
        msg_id = save_chat_message(
            thread_id=to_phone or "unknown",
            owner=tenant_owner,
            direction="outbound",
            from_phone=sip_from,
            to_phone=to_phone,
            body=body or "(empty)",
            call_id=req.call_id or "",
            status="failed",
            error_code="invalid_request",
        )
        return ChatSendResponse(
            success=False,
            to_phone=to_phone,
            body=body,
            message_id=msg_id,
            error_code="invalid_request",
            detail="수신 번호와 메시지 본문이 필요합니다.",
        )

    sip_r = deliver_chat_sip_message(sip_from, to_phone, body)
    ok = bool(sip_r.get("success"))
    code = str(sip_r.get("code") or "")
    detail = str(sip_r.get("message") or "")
    if not ok and code == "sip_timeout":
        hint = "상대 단말에는 이미 전달되었을 수 있으니 목록을 확인하세요."
        detail = f"{detail} {hint}".strip() if detail.strip() else hint
    status = "sent" if ok else "failed"

    msg_id = save_chat_message(
        thread_id=to_phone,
        owner=tenant_owner,
        direction="outbound",
        from_phone=sip_from,
        to_phone=to_phone,
        body=body,
        call_id=req.call_id or "",
        status=status,
        error_code="" if ok else code,
    )

    logger.info("chat_send_done", ok=ok, to=to_phone, owner=tenant_owner, sip_from=sip_from, msg_id=msg_id, code=code or None)
    return ChatSendResponse(
        success=ok,
        to_phone=to_phone,
        body=body,
        message_id=msg_id,
        error_code=code,
        detail=detail,
    )


@router.post("/retry/{message_id}", response_model=ChatSendResponse)
async def retry_message(
    message_id: int,
    owner: str = Query(..., description="테넌트 owner (발신 내선)"),
) -> ChatSendResponse:
    """실패한 발신 메시지를 동일 본문·수신자로 재전송하고 DB 상태를 갱신한다."""
    from src.services.chat_relay_service import resolve_sip_from_for_outbound
    from src.services.chat_sip_delivery import deliver_chat_sip_message
    from src.services.chat_service import get_message_by_id, update_message_after_retry

    row = get_message_by_id(message_id, owner)
    if not row:
        raise HTTPException(status_code=404, detail="메시지를 찾을 수 없습니다.")
    if row.get("direction") != "outbound":
        raise HTTPException(status_code=400, detail="발신 메시지만 재전송할 수 있습니다.")
    if row.get("status") != "failed":
        raise HTTPException(status_code=400, detail="실패한 메시지만 재전송할 수 있습니다.")

    body = str(row.get("body") or "")
    to_phone = str(row.get("to_phone") or "")
    sip_from = resolve_sip_from_for_outbound(owner)

    sip_r = deliver_chat_sip_message(sip_from, to_phone, body)
    ok = bool(sip_r.get("success"))
    code = str(sip_r.get("code") or "")
    detail = str(sip_r.get("message") or "")
    if not ok and code == "sip_timeout":
        hint = "상대 단말에는 이미 전달되었을 수 있으니 목록을 확인하세요."
        detail = f"{detail} {hint}".strip() if detail.strip() else hint

    update_message_after_retry(
        message_id,
        owner,
        "sent" if ok else "failed",
        "" if ok else code,
    )

    logger.info("chat_retry_done", ok=ok, message_id=message_id, owner=owner, code=code or None)
    return ChatSendResponse(
        success=ok,
        to_phone=to_phone,
        body=body,
        message_id=message_id,
        error_code=code,
        detail=detail,
    )
