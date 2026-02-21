"""JWT 인증 유틸리티

JWT 토큰 생성, 검증, 파싱 기능 제공
"""
from datetime import datetime, timedelta
from typing import Optional, Dict, Any
import jwt
import structlog

logger = structlog.get_logger(__name__)

# JWT 설정 (환경 변수로 관리 권장)
JWT_SECRET_KEY = "your-secret-key-change-in-production"  # TODO: 환경 변수로 교체
JWT_ALGORITHM = "HS256"
JWT_EXPIRE_MINUTES = 480  # 8시간


class JWTError(Exception):
    """JWT 관련 에러"""
    pass


class JWTExpiredError(JWTError):
    """JWT 만료 에러"""
    pass


class JWTInvalidError(JWTError):
    """JWT 무효 에러"""
    pass


def create_jwt(extension: str, role: str = "operator", **extra_claims) -> str:
    """JWT 토큰 생성
    
    Args:
        extension: 착신번호 (예: "1004")
        role: 사용자 역할 (기본: "operator")
        **extra_claims: 추가 클레임
        
    Returns:
        str: JWT 토큰
        
    Example:
        >>> token = create_jwt("1004", role="admin", tenant="기상청")
    """
    now = datetime.utcnow()
    payload = {
        "sub": extension,  # subject: extension
        "extension": extension,  # 명시적 extension 필드
        "role": role,
        "iat": now,  # issued at
        "exp": now + timedelta(minutes=JWT_EXPIRE_MINUTES),  # expiration
        **extra_claims
    }
    
    token = jwt.encode(payload, JWT_SECRET_KEY, algorithm=JWT_ALGORITHM)
    
    logger.debug("jwt_created",
                extension=extension,
                role=role,
                expires_in_minutes=JWT_EXPIRE_MINUTES)
    
    return token


def is_jwt_format(token: str) -> bool:
    """JWT 형식 여부 확인 (header.payload.signature 세그먼트).
    Mock/비JWT 문자열로 decode 시도 방지용."""
    if not token or not isinstance(token, str):
        return False
    parts = token.split(".")
    return len(parts) == 3 and all(len(p) > 0 for p in parts)


def decode_jwt(token: str) -> Dict[str, Any]:
    """JWT 토큰 검증 및 파싱
    
    Args:
        token: JWT 토큰 문자열
        
    Returns:
        Dict[str, Any]: 토큰 payload
        
    Raises:
        JWTExpiredError: 토큰 만료 시
        JWTInvalidError: 토큰 무효 시
        
    Example:
        >>> payload = decode_jwt(token)
        >>> extension = payload["extension"]
    """
    if not is_jwt_format(token):
        logger.warning("jwt_invalid", error="Not a JWT format (expected header.payload.signature)")
        raise JWTInvalidError("Invalid token: not a valid JWT format")
    try:
        payload = jwt.decode(token, JWT_SECRET_KEY, algorithms=[JWT_ALGORITHM])
        return payload
    except jwt.ExpiredSignatureError:
        logger.warning("jwt_expired", token_prefix=token[:20])
        raise JWTExpiredError("Token has expired")
    except jwt.InvalidTokenError as e:
        logger.warning("jwt_invalid", error=str(e), token_prefix=token[:20])
        raise JWTInvalidError(f"Invalid token: {str(e)}")


def extract_extension_from_jwt(token: str) -> Optional[str]:
    """JWT에서 extension 추출
    
    Args:
        token: JWT 토큰 문자열
        
    Returns:
        Optional[str]: extension (없으면 None)
    """
    try:
        payload = decode_jwt(token)
        return payload.get("extension") or payload.get("sub")
    except JWTError:
        return None


def extract_role_from_jwt(token: str) -> Optional[str]:
    """JWT에서 role 추출
    
    Args:
        token: JWT 토큰 문자열
        
    Returns:
        Optional[str]: role (없으면 None)
    """
    try:
        payload = decode_jwt(token)
        return payload.get("role")
    except JWTError:
        return None
