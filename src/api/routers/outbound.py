"""
아웃바운드 콜 요청 API.

- POST /api/outbound/: 발신 요청 생성
- GET /api/outbound/: 목록 조회 (state 필터 지원)
- GET /api/outbound/stats: 통계
- POST /api/outbound/{outbound_id}/cancel: 취소

발신 요청 생성 시 대시보드 활성 통화 목록에 등록하고 call_data_record 로그에 기록.
취소 시 활성 통화에서 해제하고 로그 기록.
"""

import time
import uuid
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

router = APIRouter(prefix="/api/outbound", tags=["outbound"])


def _register_outbound_as_active(outbound_id: str, caller_number: str, callee_number: str) -> None:
    """대시보드 활성 통화 목록에 아웃바운드 요청 등록."""
    try:
        from src.api.routers.calls import register_active_call
        register_active_call(
            outbound_id,
            caller=caller_number,
            callee=callee_number,
            is_ai_handled=True,
        )
    except Exception:
        pass


def _unregister_outbound_from_active(outbound_id: str) -> None:
    """대시보드 활성 통화 목록에서 아웃바운드 제거."""
    try:
        from src.api.routers.calls import unregister_active_call
        unregister_active_call(outbound_id)
    except Exception:
        pass


def _log_outbound_event(outbound_id: str, event: str, **kwargs: Any) -> None:
    """call_data_record 로그에 아웃바운드 이벤트 기록."""
    try:
        from src.common.call_data_record_logger import log_call_data
        log_call_data(outbound_id, "call_event", event, **kwargs)
    except Exception:
        pass

# 인메모리 저장소 (실제 아웃바운드 엔진 연동 전)
_store: Dict[str, Dict[str, Any]] = {}


class OutboundCreate(BaseModel):
    caller_number: str = Field(..., min_length=1)
    callee_number: str = Field(..., min_length=1)
    purpose: str = Field(..., min_length=1)
    questions: List[str] = Field(default_factory=list, min_length=1)
    caller_display_name: Optional[str] = None
    max_duration: int = Field(default=180, ge=30, le=1800)
    retry_on_no_answer: bool = True


@router.post("/")
async def create_outbound(body: OutboundCreate) -> Dict[str, Any]:
    """아웃바운드 발신 요청 생성."""
    outbound_id = str(uuid.uuid4())
    now = time.time()
    _store[outbound_id] = {
        "outbound_id": outbound_id,
        "call_id": None,
        "caller_number": body.caller_number,
        "callee_number": body.callee_number,
        "purpose": body.purpose,
        "questions": body.questions,
        "caller_display_name": body.caller_display_name or "",
        "state": "queued",
        "created_at": now,
        "started_at": None,
        "answered_at": None,
        "completed_at": None,
        "attempt_count": 0,
        "failure_reason": None,
        "result": None,
        "max_duration": body.max_duration,
        "retry_on_no_answer": body.retry_on_no_answer,
    }
    # 대시보드 활성 통화 목록에 표시 + call_data_record 로그
    _register_outbound_as_active(outbound_id, body.caller_number, body.callee_number)
    _log_outbound_event(
        outbound_id,
        "outbound_request_created",
        caller_number=body.caller_number,
        callee_number=body.callee_number,
        purpose=body.purpose,
        caller_display_name=body.caller_display_name or "",
    )
    return {"outbound_id": outbound_id}


@router.get("/")
async def list_outbound(state: Optional[str] = Query(None)) -> Dict[str, Any]:
    """아웃바운드 목록 (state 필터 선택)."""
    calls = list(_store.values())
    if state:
        calls = [c for c in calls if c.get("state") == state]
    # 최신순
    calls.sort(key=lambda c: c.get("created_at") or 0, reverse=True)
    return {"calls": calls}


@router.get("/stats")
async def outbound_stats() -> Dict[str, Any]:
    """아웃바운드 통계."""
    calls = list(_store.values())
    completed = [c for c in calls if c.get("state") == "completed"]
    return {
        "total_calls": len(calls),
        "completed_count": len(completed),
        "task_completed_count": len(completed),
        "success_rate": len(completed) / len(calls) * 100 if calls else 0,
        "avg_duration_seconds": 0,
        "no_answer_count": len([c for c in calls if c.get("state") == "no_answer"]),
        "busy_count": len([c for c in calls if c.get("state") == "busy"]),
        "active_count": len([c for c in calls if c.get("state") in ("queued", "dialing", "ringing", "connected")]),
        "queue_size": len([c for c in calls if c.get("state") == "queued"]),
    }


@router.post("/{outbound_id}/cancel")
async def cancel_outbound(outbound_id: str) -> Dict[str, str]:
    """아웃바운드 요청 취소."""
    if outbound_id not in _store:
        raise HTTPException(status_code=404, detail="Not Found")
    rec = _store[outbound_id]
    if rec.get("state") not in ("queued", "dialing", "ringing"):
        raise HTTPException(status_code=400, detail="이미 진행 중이거나 완료된 요청은 취소할 수 없습니다.")
    rec["state"] = "cancelled"
    # 대시보드 활성 통화 목록에서 제거 + call_data_record 로그
    _unregister_outbound_from_active(outbound_id)
    _log_outbound_event(
        outbound_id,
        "outbound_cancelled",
        caller_number=rec.get("caller_number"),
        callee_number=rec.get("callee_number"),
    )
    return {"status": "cancelled"}
