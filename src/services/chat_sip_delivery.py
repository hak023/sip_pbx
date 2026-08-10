"""채팅용 SIP MESSAGE 전송.

1. SIP 엔드포인트와 **같은 프로세스**이면 ``src.main._sip_endpoint.send_chat_sip_message`` 직접 호출.
2. API 전용 프로세스이면 ``SIP_MESSAGE_RELAY_BASE_URL`` + ``SIP_INTERNAL_API_SECRET`` 로 내부 HTTP 릴레이.
"""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from typing import Any, Dict

import structlog

logger = structlog.get_logger(__name__)


def _deliver_in_process(
    from_user: str,
    to_user: str,
    body: str,
    *,
    suppress_ai_loop: bool = False,
    wait_for_final_response: bool = True,
    sender_registration_required: bool = True,
) -> Dict[str, Any] | None:
    try:
        import src.main as _main

        ep = getattr(_main, "_sip_endpoint", None)
        if ep is None:
            return None
        send_fn = getattr(ep, "send_chat_sip_message", None)
        if not callable(send_fn):
            return None
        return send_fn(
            from_user,
            to_user,
            body,
            suppress_ai_loop=suppress_ai_loop,
            wait_for_final_response=wait_for_final_response,
            sender_registration_required=sender_registration_required,
        )
    except Exception as e:
        logger.error("deliver_chat_sip_message_inproc_error", error=str(e))
        return {"success": False, "code": "error", "message": str(e)}


def _deliver_via_internal_http(
    from_user: str,
    to_user: str,
    body: str,
    *,
    suppress_ai_loop: bool = False,
    wait_for_final_response: bool = True,
    sender_registration_required: bool = True,
) -> Dict[str, Any] | None:
    base = (os.environ.get("SIP_MESSAGE_RELAY_BASE_URL") or "").strip().rstrip("/")
    secret = (os.environ.get("SIP_INTERNAL_API_SECRET") or "").strip()
    if not base or not secret:
        return None
    url = f"{base}/internal/sip/chat-message"
    payload = json.dumps(
        {
            "from_user": from_user,
            "to_user": to_user,
            "body": body,
            "suppress_ai_loop": bool(suppress_ai_loop),
            "wait_for_final_response": bool(wait_for_final_response),
            "sender_registration_required": bool(sender_registration_required),
        },
        ensure_ascii=False,
    ).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=payload,
        method="POST",
        headers={
            "Content-Type": "application/json; charset=utf-8",
            "X-SIP-PBX-Internal-Key": secret,
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=45) as resp:
            raw = resp.read().decode("utf-8")
            data = json.loads(raw) if raw.strip() else {}
            if isinstance(data, dict) and "success" in data:
                return data
            return {"success": False, "code": "relay_bad_response", "message": raw[:500]}
    except urllib.error.HTTPError as e:
        detail = ""
        try:
            detail = e.read().decode("utf-8", errors="replace")[:500]
        except Exception:
            pass
        logger.warning(
            "deliver_chat_sip_message_http_error",
            status=e.code,
            url=url,
            detail=detail[:200] if detail else None,
        )
        return {
            "success": False,
            "code": f"relay_http_{e.code}",
            "message": detail or e.reason,
        }
    except Exception as e:
        logger.error("deliver_chat_sip_message_http_failed", error=str(e), url=url)
        return {"success": False, "code": "relay_http_error", "message": str(e)}


def deliver_chat_sip_message(
    from_user: str,
    to_user: str,
    body: str,
    *,
    suppress_ai_loop: bool = False,
    wait_for_final_response: bool = True,
    sender_registration_required: bool = True,
) -> Dict[str, Any]:
    """REGISTER 정보로 발신·수신 내선 간 MESSAGE 전송.

    ``sender_registration_required=False``면 발신자(from_user)가 실제 SIP 단말로
    REGISTER되어 있지 않아도 전송을 시도한다(웹사이트 자체 발신·AI 자동응답·예약 알림
    등 물리적 단말이 아닌 경로용). 수신자(to_user) REGISTER 검사는 실제 전송 목적지를
    결정하는 데 필수라 항상 적용된다.

    Returns:
        dict: keys ``success`` (bool), ``code`` (str), ``message`` (str)
    """
    r = _deliver_in_process(
        from_user,
        to_user,
        body,
        suppress_ai_loop=suppress_ai_loop,
        wait_for_final_response=wait_for_final_response,
        sender_registration_required=sender_registration_required,
    )
    if r is not None:
        return r

    r2 = _deliver_via_internal_http(
        from_user,
        to_user,
        body,
        suppress_ai_loop=suppress_ai_loop,
        wait_for_final_response=wait_for_final_response,
        sender_registration_required=sender_registration_required,
    )
    if r2 is not None:
        return r2

    return {
        "success": False,
        "code": "sip_unavailable",
        "message": (
            "SIP 엔드포인트가 이 프로세스에 없습니다. PBX(src.main)와 함께 기동하거나, "
            "SIP_MESSAGE_RELAY_BASE_URL 과 SIP_INTERNAL_API_SECRET(및 PBX 쪽 SIP_INTERNAL_HTTP_*)을 설정하세요."
        ),
    }
