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
    available: bool = Field(..., description="True=응대 가능, False=자리 비움(AI 우선)")
    tenant_id: str = Field(..., min_length=1, description="내선/테넌트 owner")
    away_message: str | None = Field(None, description="자리 비움 시 안내 메시지 (선택)")


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
    }


@router.post("/status")
def post_operator_status(body: OperatorStatusUpdate) -> dict:
    uid = body.tenant_id.strip()
    if not uid:
        raise HTTPException(status_code=422, detail="tenant_id는 빈 문자열일 수 없습니다.")
    mgr = get_operator_status_manager()
    if body.available:
        mgr.set_status(uid, OperatorStatus.AVAILABLE)
    else:
        mgr.set_status(uid, OperatorStatus.AWAY, away_message=body.away_message)
    info = mgr.get_status_info(uid)
    return {
        "success": True,
        "available": body.available,
        "status": info["status"],
        "status_changed_at": info.get("status_changed_at"),
    }
