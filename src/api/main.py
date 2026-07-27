"""
FastAPI 앱 진입점.

  uvicorn src.api.main:app --host 0.0.0.0 --port 8000

녹음 경로: 환경변수 `SIP_RECORDINGS_DIR` 또는 `RECORDINGS_DIR` (기본 `./recordings`).

채팅 SIP MESSAGE는 SIP 프로세스(`src.main`)와 분리 기동 시
`SIP_MESSAGE_RELAY_BASE_URL` + `SIP_INTERNAL_API_SECRET` 으로 PBX 내부 HTTP에 위임한다
(`src.services.chat_sip_delivery`, `src.sip_core.sip_internal_http` 참고).
"""

from __future__ import annotations

from typing import Any, Dict, List

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from src.api.routers import (
    auth_compat,
    call_control_api,
    call_history,
    caller_contacts,
    contact_folders,
    client_log,
    knowledge_api,
    metrics,
    operator_status_api,
    outbound,
    persona,
)
from src.api.routers import booking as booking_router
from src.api.routers import messages as messages_router
from src.api.routers import chat as chat_router
from src.api.routers import google_calendar as google_calendar_router
from src.api.routers import ringback as ringback_router
from src.api.routers import self_service as self_service_router
from src.api.routers import self_service_test as self_service_test_router
from src.api.routers import ai_pipeline_test as ai_pipeline_test_router
from src.api.routers import settings_ai_assistant as settings_ai_assistant_router
from src.api.http_error_logging import register_http_error_logging
from src.booking.database import init_db
from src.call_control.db import init_db as init_call_control_db

app = FastAPI(title="SIP PBX API", version="1.0.0")

# 예약 DB 초기화 (앱 기동 시 테이블 생성)
init_db()
# Call Control DB 초기화
init_call_control_db()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 4xx/422 시 detail + 요청 본문 미리보기를 structlog(app.log)에 남김
register_http_error_logging(app)

app.include_router(auth_compat.router, prefix="/api")
app.include_router(knowledge_api.router, prefix="/api")
app.include_router(call_history.router, prefix="/api")
app.include_router(caller_contacts.router, prefix="/api")
app.include_router(contact_folders.router, prefix="/api")
app.include_router(client_log.router)
app.include_router(metrics.router)  # /api/metrics prefix already in router
app.include_router(operator_status_api.router, prefix="/api")
app.include_router(outbound.router)  # /api/outbound prefix already included
app.include_router(persona.router)  # /api/persona prefix already included
app.include_router(booking_router.router, prefix="/api")
app.include_router(messages_router.router)  # /api/messages prefix already in router
app.include_router(chat_router.router)       # /api/chat prefix already in router
app.include_router(google_calendar_router.router)  # /api/google prefix already in router
app.include_router(ringback_router.router)         # /api/ringback prefix already in router
app.include_router(call_control_api.router)        # /api/call-control
app.include_router(self_service_router.router)      # /api/self-service (Story 1.9)
app.include_router(self_service_test_router.router)  # /api/self-service/test (BMAD QA 자동 테스트, 기본 비활성화)
app.include_router(ai_pipeline_test_router.router)  # /api/ai-pipeline/test (voice-latency QA 자동 테스트, 기본 비활성화)
app.include_router(settings_ai_assistant_router.router)  # /api/settings/ai-assistant/docs


def _serialize_active_sessions(cm: Any) -> List[Dict[str, Any]]:
    """CallManager.get_active_sessions() → 대시보드 REST `ActiveCallRestRaw` 형태."""
    try:
        sessions = cm.get_active_sessions()
    except Exception:
        return []
    if not sessions:
        return []
    out: List[Dict[str, Any]] = []
    for s in sessions:
        try:
            cid = getattr(s, "call_id", None)
            if not cid:
                continue
            caller = ""
            callee = ""
            gf = getattr(s, "get_caller_uri", None)
            if callable(gf):
                try:
                    caller = gf() or ""
                except Exception:
                    caller = ""
            if not isinstance(caller, str):
                caller = str(caller)
            gt = getattr(s, "get_callee_uri", None)
            if callable(gt):
                try:
                    callee = gt() or ""
                except Exception:
                    callee = ""
            if not isinstance(callee, str):
                callee = str(callee)
            state = getattr(s, "state", None)
            state_str = getattr(state, "name", None) or (
                str(state) if state is not None else "진행 중"
            )
            started_at = None
            for attr in ("established_at", "created_at", "started_at"):
                dt = getattr(s, attr, None)
                if dt is not None:
                    started_at = dt.isoformat() if hasattr(dt, "isoformat") else str(dt)
                    break
            is_ai = getattr(s, "is_ai_handled", None)
            if is_ai is None:
                is_ai = getattr(s, "is_ai_call", None)
            out.append(
                {
                    "call_id": str(cid),
                    "caller": caller,
                    "callee": callee,
                    "state": state_str,
                    "started_at": started_at,
                    "is_ai_handled": bool(is_ai),
                }
            )
        except Exception:
            continue
    return out


@app.get("/api/calls/active")
def calls_active() -> list:
    """
    WebSocket과 동일 프로세스일 때 `set_call_manager`로 주입된 CallManager에서 활성 통화 조회.
    미주입(단독 API)이면 빈 목록 — 실시간은 Socket.IO `call_started` 이벤트에 의존.
    """
    try:
        from src.websocket.server import get_injected_call_manager

        cm = get_injected_call_manager()
        if cm is not None:
            rows = _serialize_active_sessions(cm)
            if rows:
                return rows
    except Exception:
        pass
    return []


# metrics 라우터로 이동됨 (routers/metrics.py)


@app.get("/health")
def health() -> dict:
    return {"status": "ok"}
