"""
Operator API - 운영자 상태 관리

- GET /api/operator/status - 운영자 상태 조회
- POST /api/operator/status - 운영자 상태 변경
"""

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel
from typing import Dict, Any

router = APIRouter(prefix="/api/operator", tags=["operator"])

# 간단한 인메모리 상태 저장 (실제로는 DB 사용)
_operator_status: Dict[str, bool] = {}


class OperatorStatusUpdate(BaseModel):
    """운영자 상태 업데이트 요청"""
    available: bool
    tenant_id: str


@router.get("/status")
async def get_operator_status(
    tenant_id: str | None = Query(None, description="테넌트 ID(착신번호)"),
) -> Dict[str, Any]:
    """
    운영자 상태 조회
    
    Args:
        tenant_id: 테넌트 ID (선택)
    
    Returns:
        {
            "available": true,
            "tenant_id": "1004"
        }
    """
    if tenant_id:
        available = _operator_status.get(tenant_id, True)  # 기본값: available
        return {
            "available": available,
            "tenant_id": tenant_id
        }
    
    return {
        "available": True,
        "tenant_id": None,
        "all_tenants": _operator_status
    }


@router.post("/status")
async def update_operator_status(
    status: OperatorStatusUpdate
) -> Dict[str, Any]:
    """
    운영자 상태 변경
    
    Args:
        status: 상태 업데이트 정보
    
    Returns:
        {
            "success": true,
            "available": true,
            "tenant_id": "1004"
        }
    """
    _operator_status[status.tenant_id] = status.available
    
    return {
        "success": True,
        "available": status.available,
        "tenant_id": status.tenant_id
    }
