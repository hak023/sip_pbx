"""
운영자 응대 가능 / 자리 비움 — `OperatorAvailabilityToggle` 과 SIP `OperatorStatusManager` 연동.

상태는 파일로 영속화되어 서버 재시작 후에도 유지된다.
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from src.sip_core.operator_status import OperatorStatus, get_operator_status_manager

router = APIRouter(prefix="/operator", tags=["operator"])


class OperatorStatusUpdate(BaseModel):
    available: bool | None = Field(None, description="True=응대 가능, False=자리 비움(AI 우선). None이면 변경 안 함.")
    tenant_id: str = Field(..., min_length=1, description="내선/테넌트 owner")
    away_message: str | None = Field(None, description="자리 비움 시 안내 메시지 (선택)")
    ai_fallback_mode: str | None = Field(None, description="hitl | transfer — AI 모를 때 처리 방식")


@router.get("/status")
def get_operator_status(
    tenant_id: str = Query(..., description="내선/테넌트 owner"),
) -> dict:
    uid = tenant_id.strip()
    if not uid:
        raise HTTPException(status_code=422, detail="tenant_id는 빈 문자열일 수 없습니다.")
    mgr = get_operator_status_manager()
    info = mgr.get_status_info(uid)
    available = info["status"] != OperatorStatus.AWAY.value
    return {
        "available": available,
        "status": info["status"],
        "status_changed_at": info.get("status_changed_at"),
        "ai_fallback_mode": info.get("ai_fallback_mode", "hitl"),
    }


@router.post("/status")
def post_operator_status(body: OperatorStatusUpdate) -> dict:
    uid = body.tenant_id.strip()
    if not uid:
        raise HTTPException(status_code=422, detail="tenant_id는 빈 문자열일 수 없습니다.")
    mgr = get_operator_status_manager()

    # 응대 가능/자리 비움 변경 (None이면 유지)
    if body.available is not None:
        if body.available:
            mgr.set_status(uid, OperatorStatus.AVAILABLE)
        else:
            mgr.set_status(uid, OperatorStatus.AWAY, away_message=body.away_message)

    # ai_fallback_mode 저장 (hitl | transfer)
    if body.ai_fallback_mode in ("hitl", "transfer"):
        mgr.set_fallback_mode(uid, body.ai_fallback_mode)

    info = mgr.get_status_info(uid)
    available = info["status"] != OperatorStatus.AWAY.value
    return {
        "success": True,
        "available": available,
        "status": info["status"],
        "status_changed_at": info.get("status_changed_at"),
        "ai_fallback_mode": info.get("ai_fallback_mode", "hitl"),
    }
