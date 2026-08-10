"""SIP 전용 프로세스에서 API 워커가 채팅 MESSAGE 릴레이를 호출할 수 있는 내부 HTTP.

환경 변수:
  SIP_INTERNAL_API_SECRET  (필수) 비어 있으면 서버를 띄우지 않음
  SIP_INTERNAL_HTTP_HOST   (선택) 기본 127.0.0.1
  SIP_INTERNAL_HTTP_PORT   (선택) 기본 18080
"""

from __future__ import annotations

import logging
import os
import threading
from typing import Any, Dict

from fastapi import FastAPI, Header, HTTPException
from pydantic import BaseModel

logger = logging.getLogger(__name__)

internal_app = FastAPI(title="SIP PBX Internal", docs_url=None, redoc_url=None, openapi_url=None)


class InternalChatMessageBody(BaseModel):
    from_user: str
    to_user: str
    body: str
    suppress_ai_loop: bool = False
    wait_for_final_response: bool = True
    sender_registration_required: bool = True


def _expected_secret() -> str:
    return (os.environ.get("SIP_INTERNAL_API_SECRET") or "").strip()


def _authorize(x_sip_pbx_internal_key: str | None, authorization: str | None) -> bool:
    expected = _expected_secret()
    if not expected:
        return False
    if x_sip_pbx_internal_key and x_sip_pbx_internal_key.strip() == expected:
        return True
    if authorization and authorization.strip().lower().startswith("bearer "):
        return authorization.strip()[7:].strip() == expected
    return False


@internal_app.post("/internal/sip/chat-message")
def internal_chat_message(
    body: InternalChatMessageBody,
    x_sip_pbx_internal_key: str | None = Header(None, alias="X-SIP-PBX-Internal-Key"),
    authorization: str | None = Header(None),
) -> Dict[str, Any]:
    if not _authorize(x_sip_pbx_internal_key, authorization):
        raise HTTPException(status_code=403, detail="invalid or missing internal secret")
    import src.main as _main

    ep = getattr(_main, "_sip_endpoint", None)
    send_fn = getattr(ep, "send_chat_sip_message", None) if ep else None
    if not callable(send_fn):
        raise HTTPException(status_code=503, detail="sip endpoint not ready")
    return send_fn(
        body.from_user,
        body.to_user,
        body.body,
        suppress_ai_loop=bool(body.suppress_ai_loop),
        wait_for_final_response=bool(body.wait_for_final_response),
        sender_registration_required=bool(body.sender_registration_required),
    )


def start_sip_internal_http_server_in_thread() -> None:
    """SIP_INTERNAL_API_SECRET 이 설정된 경우에만 루프백(또는 지정 호스트)에 내부 API를 바인딩."""
    if not _expected_secret():
        logger.info("sip_internal_http_skipped", reason="SIP_INTERNAL_API_SECRET unset")
        return
    host = (os.environ.get("SIP_INTERNAL_HTTP_HOST") or "127.0.0.1").strip() or "127.0.0.1"
    try:
        port = int(os.environ.get("SIP_INTERNAL_HTTP_PORT", "18080"))
    except ValueError:
        port = 18080

    def _run() -> None:
        import uvicorn

        uvicorn.run(internal_app, host=host, port=port, log_level="warning")

    t = threading.Thread(target=_run, name="sip-internal-http", daemon=True)
    t.start()
    logger.info("sip_internal_http_thread_started", host=host, port=port)
