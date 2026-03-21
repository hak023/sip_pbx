"""
Auth API - 인증 및 로그인

Frontend 로그인 처리
"""

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import Dict, Any
import secrets

router = APIRouter(prefix="/api/auth", tags=["auth"])


class LoginRequest(BaseModel):
    """로그인 요청"""
    extension: str  # 착신번호 (예: "1004")


# 하드코딩된 테넌트 정보 (tenants.py와 동기화)
TENANTS_DATA = {
    "1004": {
        "owner": "1004",
        "name": "기상청",
        "name_en": "Korea Meteorological Administration",
        "type": "government_agency",
        "description": "날씨 정보 및 기상 예보",
        "is_active": True,
    },
    "1005": {
        "owner": "1005",
        "name": "기상청 담당부서",
        "name_en": "KMA Department",
        "type": "government_agency",
        "description": "기상청 전문 상담",
        "is_active": True,
    },
    "1006": {
        "owner": "1006",
        "name": "일반 상담원",
        "name_en": "General Support",
        "type": "default",
        "description": "일반 고객 상담",
        "is_active": True,
    },
}


@router.post("/login")
async def login(request: LoginRequest) -> Dict[str, Any]:
    """
    로그인
    
    Frontend에서 착신번호(extension) 선택 시 호출
    
    Args:
        request: { "extension": "1004" }
    
    Returns:
        {
            "access_token": "...",
            "tenant": { ... },
            "user": { ... }
        }
    """
    extension = request.extension
    
    # 테넌트 확인
    if extension not in TENANTS_DATA:
        raise HTTPException(status_code=404, detail=f"테넌트를 찾을 수 없습니다: {extension}")
    
    tenant = TENANTS_DATA[extension]
    
    # 테넌트가 비활성화된 경우
    if not tenant.get("is_active", True):
        raise HTTPException(status_code=403, detail="비활성화된 테넌트입니다")
    
    # 액세스 토큰 생성 (간단한 랜덤 토큰)
    # TODO: 실제 JWT 토큰 구현 필요
    access_token = f"tok_{extension}_{secrets.token_urlsafe(32)}"
    
    # 사용자 정보 생성
    user = {
        "id": extension,
        "extension": extension,
        "name": tenant["name"],
        "role": "operator",  # operator, admin 등
    }
    
    return {
        "access_token": access_token,
        "token_type": "bearer",
        "tenant": tenant,
        "user": user,
    }


@router.post("/logout")
async def logout() -> Dict[str, str]:
    """
    로그아웃
    
    현재는 클라이언트에서 토큰 삭제만 수행
    """
    return {
        "message": "Logged out successfully"
    }


@router.get("/me")
async def get_current_user() -> Dict[str, Any]:
    """
    현재 로그인한 사용자 정보 조회
    
    TODO: JWT 토큰 검증 및 사용자 정보 반환 구현 필요
    """
    # TODO: Authorization 헤더에서 토큰 추출 및 검증
    return {
        "message": "Not implemented yet",
        "note": "JWT 인증 구현 필요"
    }
