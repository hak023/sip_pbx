"""프론트엔드 진단 로그 → 서버 app.log (브라우저 콘솔 대신 운영에서 추적).

`POST /api/client-log` — 본문은 작게 유지(과도한 전송 방지).
"""

from __future__ import annotations

import json
from typing import Any, Dict, Optional

import structlog
from fastapi import APIRouter, Request
from fastapi.responses import Response
from pydantic import BaseModel, Field

# app.log 는 structlog.PrintLoggerFactory 로만 기록됨 — 표준 logging 은 파일에 안 붙을 수 있음
logger = structlog.get_logger(__name__)

router = APIRouter(prefix="/api/client-log", tags=["client-log"])

_PAYLOAD_JSON_MAX = 4000


class ClientLogBody(BaseModel):
    source: str = Field(default="unknown", max_length=64)
    event: str = Field(default="", max_length=160)
    payload: Optional[Dict[str, Any]] = None


@router.post("", status_code=204)
def post_client_log(request: Request, body: ClientLogBody) -> Response:
    """프론트에서 중요 이벤트를 app.log(structlog JSON)에 남긴다."""
    host = request.client.host if request.client else None
    src = (body.source or "unknown").strip()[:64] or "unknown"
    ev = (body.event or "").strip()[:160] or "empty_event"
    pl = body.payload
    try:
        extra = json.dumps(pl, ensure_ascii=False, default=str) if pl is not None else ""
    except TypeError:
        extra = str(pl)
    if len(extra) > _PAYLOAD_JSON_MAX:
        extra = extra[:_PAYLOAD_JSON_MAX] + "...(truncated)"

    logger.info(
        "frontend_client_log",
        source=src,
        client_log_event=ev,
        client_host=host,
        payload=extra,
    )
    return Response(status_code=204)
