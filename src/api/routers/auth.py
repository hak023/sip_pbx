"""인증 관련 API"""
from fastapi import APIRouter, HTTPException, Depends
from datetime import datetime, timedelta
import structlog

from ..models import LoginRequest, LoginResponse, User

logger = structlog.get_logger(__name__)

router = APIRouter()


@router.post("/login", response_model=LoginResponse)
async def login(request: LoginRequest):
    """
    사용자 로그인
    
    개발 중: Mock 인증 (추후 실제 DB 연동)
    """
    # Mock 사용자 데이터
    if request.email == "operator@example.com" and request.password == "password":
        user = User(
            id="1",
            email=request.email,
            name="Operator User",
            role="operator",
            is_active=True,
            created_at=datetime.now(),
            last_login=datetime.now()
        )
        
        # Mock JWT 토큰 (추후 실제 JWT 구현)
        access_token = f"mock_token_{user.id}_{datetime.now().timestamp()}"
        
        logger.info("User logged in", user_id=user.id, email=user.email)
        
        return LoginResponse(
            access_token=access_token,
            user=user
        )
    else:
        raise HTTPException(status_code=401, detail="Invalid credentials")


@router.post("/logout")
async def logout():
    """사용자 로그아웃"""
    return {"message": "Logged out successfully"}


@router.get("/me", response_model=User)
async def get_current_user():
    """현재 로그인한 사용자 정보"""
    # Mock 사용자 반환 (추후 JWT 토큰 검증)
    return User(
        id="1",
        email="operator@example.com",
        name="Operator User",
        role="operator",
        is_active=True,
        created_at=datetime.now(),
        last_login=datetime.now()
    )

