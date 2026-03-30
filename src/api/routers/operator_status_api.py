"""
운영자 응대 가능 / 자리 비움 — `OperatorAvailabilityToggle` 과 SIP `OperatorStatusManager` 연동.
"""

from __future__ import annotations

from fastapi import APIRouter, Query
from pydantic import BaseModel, Field

from src.sip_core.operator_status import OperatorStatus, get_operator_status_manager

router = APIRouter(prefix="/operator", tags=["operator"])


class OperatorStatusUpdate(BaseModel):
    available: bool = Field(..., description="True=응대 가능, False=자리 비움(AI 우선)")
    tenant_id: str = Field(..., min_length=1, description="내선/테넌트 owner")


@router.get("/status")
def get_operator_status(
    tenant_id: str = Query(..., description="내선/테넌트 owner"),
) -> dict:
    mgr = get_operator_status_manager()
    uid = tenant_id.strip()
    st = mgr.get_status(uid)
    # AWAY → 프론트에서 '자리 비움' / available False
    available = st != OperatorStatus.AWAY
    return {"available": available, "status": st.value}


@router.post("/status")
def post_operator_status(body: OperatorStatusUpdate) -> dict:
    mgr = get_operator_status_manager()
    uid = body.tenant_id.strip()
    if body.available:
        mgr.set_status(uid, OperatorStatus.AVAILABLE)
    else:
        mgr.set_status(uid, OperatorStatus.AWAY)
    return {"success": True, "available": body.available, "status": mgr.get_status(uid).value}
