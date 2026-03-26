"""
활성 통화 API — 대시보드 실시간 통화 목록용.

GET /api/calls/active: CallManager 또는 파이프라인 등록 통화 목록 반환.
- CallManager가 주입되면 get_active_calls() 사용.
- 없으면 파이프라인에서 등록한 활성 통화 레지스트리 사용 (대시보드가 빈 목록 대신 실시간 통화 표시 가능).
"""

import time
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

security = HTTPBearer(auto_error=False)

router = APIRouter(prefix="/api/calls", tags=["calls"])

# main에서 주입 (python -m src.main 실행 시)
_call_manager: Optional[Any] = None

# 파이프라인에서 통화 시작/종료 시 등록·해제하는 인메모리 활성 통화 (CallManager 없을 때 사용)
_active_calls_registry: Dict[str, Dict[str, Any]] = {}


def set_call_manager(manager: Any) -> None:
    global _call_manager
    _call_manager = manager


def register_active_call(
    call_id: str,
    callee: str = "",
    caller: str = "",
    is_ai_handled: bool = True,
) -> None:
    """파이프라인에서 통화 시작 시 호출 (대시보드 활성 통화 목록용)."""
    if not call_id:
        return
    _active_calls_registry[call_id] = {
        "call_id": call_id,
        "callee": callee,
        "caller": caller,
        "state": "active",
        "duration_seconds": 0,
        "is_ai_handled": is_ai_handled,
        "started_at": time.time(),
    }


def unregister_active_call(call_id: str) -> None:
    """파이프라인에서 통화 종료 시 호출."""
    _active_calls_registry.pop(call_id, None)


def _get_active_calls_from_registry() -> List[Dict[str, Any]]:
    """레지스트리에서 활성 통화 목록 반환 (duration_seconds 계산)."""
    now = time.time()
    out: List[Dict[str, Any]] = []
    for c in _active_calls_registry.values():
        st = c.get("started_at", now)
        dur = int(now - st) if isinstance(st, (int, float)) else 0
        row = {
            "call_id": c["call_id"],
            "caller": c.get("caller"),
            "callee": c.get("callee"),
            "state": c.get("state", "active"),
            "duration_seconds": dur,
            "is_ai_handled": c.get("is_ai_handled", True),
        }
        if isinstance(st, (int, float)):
            row["started_at"] = datetime.fromtimestamp(st, tz=timezone.utc).isoformat().replace("+00:00", "Z")
        out.append(row)
    return out


def _get_active_calls_from_manager() -> List[Dict[str, Any]]:
    """CallManager에서 활성 통화 목록 추출. 메서드/속성은 구현체에 맞춰 시도."""
    if _call_manager is None:
        return []
    # CallManager: get_active_sessions() -> List[CallSession] (유저 간·B2BUA 공통)
    if callable(getattr(_call_manager, "get_active_sessions", None)):
        try:
            sessions = _call_manager.get_active_sessions()
            if not sessions:
                pass
            else:
                ai_set = getattr(_call_manager, "ai_enabled_calls", None) or set()
                rows: List[Dict[str, Any]] = []
                for s in sessions:
                    cid = getattr(s, "call_id", None) or ""
                    if not cid:
                        continue
                    state = getattr(s, "state", None)
                    state_val = getattr(state, "value", None) or (str(state) if state is not None else "active")
                    caller = s.get_caller_uri() if callable(getattr(s, "get_caller_uri", None)) else None
                    callee = s.get_callee_uri() if callable(getattr(s, "get_callee_uri", None)) else None
                    elapsed = 0
                    if callable(getattr(s, "get_elapsed_seconds", None)):
                        try:
                            elapsed = int(s.get_elapsed_seconds())
                        except Exception:
                            elapsed = 0
                    started_at_iso: Optional[str] = None
                    at = getattr(s, "answer_time", None)
                    if isinstance(at, datetime):
                        try:
                            au = at if at.tzinfo else at.replace(tzinfo=timezone.utc)
                            started_at_iso = au.isoformat().replace("+00:00", "Z")
                        except Exception:
                            started_at_iso = None
                    # Pipecat은 register_active_call로 레지스트리에만 넣고 ai_enabled_calls에 안 넣는 경로가 있음.
                    # 부재중 전환 등은 metadata.is_ai_handled만 세팅될 수 있음. 대시보드 호전환 버튼용으로 병합.
                    meta = getattr(s, "metadata", None)
                    meta_ai = bool(isinstance(meta, dict) and meta.get("is_ai_handled"))
                    reg = _active_calls_registry.get(cid)
                    registry_ai = bool(reg and reg.get("is_ai_handled"))
                    is_ai_handled = (cid in ai_set) or meta_ai or registry_ai
                    row: Dict[str, Any] = {
                        "call_id": cid,
                        "caller": caller,
                        "callee": callee,
                        "state": state_val,
                        "duration_seconds": elapsed,
                        "is_ai_handled": is_ai_handled,
                    }
                    if started_at_iso:
                        row["started_at"] = started_at_iso
                    rows.append(row)
                return rows
        except Exception:
            pass
    # get_active_calls() (다른 구현체)
    if callable(getattr(_call_manager, "get_active_calls", None)):
        try:
            out = _call_manager.get_active_calls()
            return list(out) if out is not None else []
        except Exception:
            return []
    # get_calls()
    if callable(getattr(_call_manager, "get_calls", None)):
        try:
            out = _call_manager.get_calls()
            return list(out) if out is not None else []
        except Exception:
            return []
    # .calls (dict 또는 list)
    calls = getattr(_call_manager, "calls", None)
    if calls is None:
        return []
    if isinstance(calls, dict):
        return list(calls.values())
    if isinstance(calls, list):
        return calls
    return []


def _normalize_call_item(raw: Any) -> Dict[str, Any]:
    """원시 통화 객체를 대시보드 형식으로 정규화."""
    if isinstance(raw, dict):
        d: Dict[str, Any] = {
            "call_id": raw.get("call_id") or raw.get("id") or "",
            "caller": raw.get("caller"),
            "callee": raw.get("callee"),
            "state": raw.get("state", "active"),
            "duration_seconds": raw.get("duration_seconds") or raw.get("duration"),
            "is_ai_handled": raw.get("is_ai_handled", False),
        }
        if raw.get("started_at"):
            d["started_at"] = raw.get("started_at")
        return d
    return {
        "call_id": getattr(raw, "call_id", None) or getattr(raw, "id", None) or "",
        "caller": getattr(raw, "caller", None),
        "callee": getattr(raw, "callee", None),
        "state": getattr(raw, "state", "active"),
        "duration_seconds": getattr(raw, "duration_seconds", None) or getattr(raw, "duration", None),
        "is_ai_handled": getattr(raw, "is_ai_handled", False),
    }


@router.get("/active")
async def get_active_calls(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(security),
) -> List[Dict[str, Any]]:
    """
    활성 통화 목록 (대시보드 실시간 통화용).
    CallManager가 있으면 해당 목록, 없으면 파이프라인에서 등록한 레지스트리 사용.
    """
    if _call_manager is not None:
        raw_list = _get_active_calls_from_manager()
    else:
        raw_list = _get_active_calls_from_registry()
    items = [_normalize_call_item(c) for c in raw_list]
    items = [x for x in items if x.get("call_id")]
    return items
