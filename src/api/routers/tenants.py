"""
Tenants API - 테넌트(착신번호) 목록 조회

Frontend 로그인 페이지에서 호출됨
"""

from fastapi import APIRouter
from typing import List, Dict, Any

router = APIRouter(prefix="/api/tenants", tags=["tenants"])


# 하드코딩된 테넌트 목록 (추후 DB로 이관 가능)
TENANTS_DATA = [
    {
        "owner": "1004",
        "name": "기상청",
        "name_en": "Korea Meteorological Administration",
        "type": "government_agency",
        "description": "날씨 정보 및 기상 예보",
        "is_active": True,
    },
    {
        "owner": "1005",
        "name": "기상청 담당부서",
        "name_en": "KMA Department",
        "type": "government_agency",
        "description": "기상청 전문 상담",
        "is_active": True,
    },
    {
        "owner": "1006",
        "name": "일반 상담원",
        "name_en": "General Support",
        "type": "default",
        "description": "일반 고객 상담",
        "is_active": True,
    },
]


@router.get("")
async def get_tenants() -> Dict[str, Any]:
    """
    테넌트(착신번호) 목록 조회
    
    Frontend 로그인 페이지에서 착신번호 선택을 위해 호출
    
    Returns:
        {
            "tenants": [
                {
                    "owner": "1004",
                    "name": "기상청",
                    "name_en": "Korea Meteorological Administration",
                    "type": "government_agency",
                    "description": "날씨 정보 및 기상 예보",
                    "is_active": True
                }
            ]
        }
    """
    # is_active가 True인 테넌트만 반환
    active_tenants = [t for t in TENANTS_DATA if t.get("is_active", True)]
    
    return {
        "tenants": active_tenants,
        "total": len(active_tenants)
    }


@router.get("/{tenant_id}")
async def get_tenant(tenant_id: str) -> Dict[str, Any]:
    """
    특정 테넌트 상세 조회
    
    Args:
        tenant_id: 테넌트 ID (owner, 예: "1004")
    
    Returns:
        테넌트 상세 정보
    """
    for tenant in TENANTS_DATA:
        if tenant["owner"] == tenant_id:
            return tenant
    
    return {
        "error": "Tenant not found",
        "tenant_id": tenant_id
    }
