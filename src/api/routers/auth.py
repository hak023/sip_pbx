"""인증 관련 API

착신번호(extension) 기반 로그인.
패스워드 없이 착신번호만으로 로그인하여 해당 테넌트의 대시보드에 접근한다.
"""
from fastapi import APIRouter, HTTPException, Header, Depends
from datetime import datetime
from typing import Optional
import structlog

from ..models import LoginRequest, LoginResponse, User, TenantInfo
from ..auth_utils import create_jwt, decode_jwt, JWTExpiredError, JWTInvalidError
from src.services.seed_data import get_tenant_list, _get_tenant_config
from src.services.knowledge_service import get_knowledge_service

logger = structlog.get_logger(__name__)

router = APIRouter()

knowledge_service = get_knowledge_service()


@router.post("/login", response_model=LoginResponse)
async def login(request: LoginRequest):
    """착신번호 기반 로그인

    패스워드 불필요. 등록된 착신번호(extension)를 선택하면 로그인된다.

    Request: { "extension": "1004" }
    Response: { "access_token": "...", "user": {...}, "tenant": {...} }
    """
    extension = request.extension

    if not extension:
        raise HTTPException(status_code=400, detail="Extension number is required")

    # VectorDB에서 테넌트 확인
    tenant_config = await _get_tenant_config(knowledge_service, extension)

    if not tenant_config:
        # 정적 목록에서 확인 (시드 데이터 투입 전이라도 허용)
        static_tenants = {t["owner"]: t for t in get_tenant_list()}
        if extension not in static_tenants:
            raise HTTPException(
                status_code=404,
                detail=f"Extension {extension} is not registered"
            )
        tenant_name = static_tenants[extension]["name"]
        tenant_type = static_tenants[extension]["type"]
    else:
        metadata = tenant_config.get("metadata", {})
        tenant_name = metadata.get("tenant_name", extension)
        tenant_type = metadata.get("tenant_type", "unknown")

    # JWT 토큰 생성
    access_token = create_jwt(
        extension=extension,
        role="operator",
        tenant_name=tenant_name,
        tenant_type=tenant_type
    )

    user = User(
        id=extension,
        email=f"{extension}@voicebot.local",
        name=f"{tenant_name} 운영자",
        role="operator",
        is_active=True,
        created_at=datetime.now(),
        last_login=datetime.now(),
    )

    tenant_info = TenantInfo(
        owner=extension,
        name=tenant_name,
        type=tenant_type,
    )

    logger.info("tenant_login",
               extension=extension,
               tenant_name=tenant_name)

    return LoginResponse(
        access_token=access_token,
        user=user,
        tenant=tenant_info,
    )


@router.post("/logout")
async def logout():
    """사용자 로그아웃"""
    return {"message": "Logged out successfully"}


async def get_current_extension(authorization: Optional[str] = Header(None)) -> str:
    """JWT에서 extension 추출 (Dependency)
    
    Args:
        authorization: "Bearer <JWT>" 형식의 헤더
        
    Returns:
        str: extension
        
    Raises:
        HTTPException: 토큰 없음/만료/무효 시 401
    """
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Missing or invalid authorization header")
    
    token = authorization.replace("Bearer ", "")
    
    try:
        payload = decode_jwt(token)
        extension = payload.get("extension") or payload.get("sub")
        if not extension:
            raise HTTPException(status_code=401, detail="Invalid token: missing extension")
        return extension
    except JWTExpiredError:
        raise HTTPException(status_code=401, detail="Token has expired")
    except JWTInvalidError as e:
        raise HTTPException(status_code=401, detail=str(e))


@router.get("/me", response_model=User)
async def get_current_user(extension: str = Depends(get_current_extension)):
    """현재 로그인한 사용자 정보 (JWT 기반)
    
    Args:
        extension: JWT에서 추출한 extension (Depends로 자동 주입)
    """
    # VectorDB에서 테넌트 확인
    tenant_config = await _get_tenant_config(knowledge_service, extension)
    
    if not tenant_config:
        static_tenants = {t["owner"]: t for t in get_tenant_list()}
        if extension in static_tenants:
            tenant_name = static_tenants[extension]["name"]
        else:
            tenant_name = extension
    else:
        metadata = tenant_config.get("metadata", {})
        tenant_name = metadata.get("tenant_name", extension)
    
    return User(
        id=extension,
        email=f"{extension}@voicebot.local",
        name=f"{tenant_name} 운영자",
        role="operator",
        is_active=True,
        created_at=datetime.now(),
        last_login=datetime.now(),
    )
