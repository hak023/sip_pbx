"""
FastAPI 앱 진입점.

  uvicorn src.api.main:app --host 0.0.0.0 --port 8000

녹음 경로: 환경변수 `SIP_RECORDINGS_DIR` 또는 `RECORDINGS_DIR` (기본 `./recordings`).
"""

from __future__ import annotations

from typing import Any, Dict, List

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from src.api.routers import (
    auth_compat,
    call_history,
    knowledge_api,
    metrics,
    operator_status_api,
    outbound,
    persona,
)

app = FastAPI(title="SIP PBX API", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth_compat.router, prefix="/api")
app.include_router(knowledge_api.router, prefix="/api")
app.include_router(call_history.router, prefix="/api")
app.include_router(metrics.router)  # /api/metrics prefix already in router
app.include_router(operator_status_api.router, prefix="/api")
app.include_router(outbound.router)  # /api/outbound prefix already included
app.include_router(persona.router)  # /api/persona prefix already included


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
