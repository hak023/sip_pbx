"""
Operator Status Management API

운영자 상태 관리 API 엔드포인트
"""

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from typing import Optional
from datetime import datetime
from enum import Enum
import structlog

logger = structlog.get_logger(__name__)

router = APIRouter(prefix="/api/operator", tags=["operator"])


class OperatorStatus(str, Enum):
    """운영자 상태"""
    AVAILABLE = "available"
    AWAY = "away"
    BUSY = "busy"
    OFFLINE = "offline"


class OperatorStatusUpdate(BaseModel):
    """운영자 상태 업데이트 요청"""
    status: OperatorStatus
    away_message: Optional[str] = None


class OperatorStatusResponse(BaseModel):
    """운영자 상태 응답"""
    operator_id: str
    status: OperatorStatus
    away_message: str
    status_changed_at: datetime
    unresolved_hitl_count: int


# Dependency: Redis Client (실제 구현 시 주입)
async def get_redis_client():
    """Redis 클라이언트 가져오기"""
    # TODO: 실제 Redis 클라이언트 반환
    return None


# Dependency: Database Client (실제 구현 시 주입)
async def get_db():
    """Database 클라이언트 가져오기"""
    # TODO: 실제 DB 클라이언트 반환
    return None


# Dependency: 현재 운영자 가져오기 (JWT 인증)
async def get_current_operator():
    """현재 운영자 정보 가져오기"""
    # TODO: JWT 토큰에서 운영자 정보 추출
    return {"id": "operator_123", "name": "Operator"}


@router.put("/status", response_model=OperatorStatusResponse)
async def update_operator_status(
    update: OperatorStatusUpdate,
    redis_client=Depends(get_redis_client),
    db=Depends(get_db),
    current_user=Depends(get_current_operator)
):
    """
    운영자 상태 변경
    
    Args:
        update: 운영자 상태 업데이트 정보
        
    Returns:
        운영자 상태 응답
    """
    operator_id = current_user["id"]
    
    try:
        # Redis에 운영자 상태 저장
        if redis_client:
            await redis_client.set(
                f"operator:status",
                update.status.value,
                ex=86400  # 24시간
            )
            
            # 부재중 메시지 저장
            if update.away_message:
                await redis_client.set(
                    f"operator:away_message",
                    update.away_message,
                    ex=86400
                )
            
            # 상태 변경 시각 기록
            await redis_client.set(
                f"operator:status_changed_at",
                datetime.now().isoformat(),
                ex=86400
            )
        
        # 미처리 HITL 요청 수 조회
        unresolved_count = 0
        if db:
            result = await db.fetch_one(
                """
                SELECT COUNT(*) as cnt FROM unresolved_hitl_requests
                WHERE status = 'unresolved'
                """
            )
            unresolved_count = result["cnt"] if result else 0
        
        logger.info("Operator status updated",
                   operator_id=operator_id,
                   status=update.status,
                   unresolved_count=unresolved_count)
        
        return OperatorStatusResponse(
            operator_id=operator_id,
            status=update.status,
            away_message=update.away_message or "죄송합니다. 확인 후 별도로 안내드리겠습니다.",
            status_changed_at=datetime.now(),
            unresolved_hitl_count=unresolved_count
        )
        
    except Exception as e:
        logger.error("Failed to update operator status",
                    operator_id=operator_id,
                    error=str(e),
                    exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to update operator status: {str(e)}")


@router.get("/status", response_model=OperatorStatusResponse)
async def get_operator_status(
    redis_client=Depends(get_redis_client),
    db=Depends(get_db),
    current_user=Depends(get_current_operator)
):
    """
    현재 운영자 상태 조회
    
    Returns:
        운영자 상태 응답
    """
    operator_id = current_user["id"]
    
    try:
        # Redis에서 운영자 상태 조회
        status = OperatorStatus.OFFLINE
        away_message = "죄송합니다. 확인 후 별도로 안내드리겠습니다."
        status_changed_at = datetime.now()
        
        if redis_client:
            status_str = await redis_client.get("operator:status")
            if status_str:
                status = OperatorStatus(status_str.decode() if isinstance(status_str, bytes) else status_str)
            
            away_message_str = await redis_client.get("operator:away_message")
            if away_message_str:
                away_message = away_message_str.decode() if isinstance(away_message_str, bytes) else away_message_str
            
            status_changed_at_str = await redis_client.get("operator:status_changed_at")
            if status_changed_at_str:
                status_changed_at = datetime.fromisoformat(
                    status_changed_at_str.decode() if isinstance(status_changed_at_str, bytes) else status_changed_at_str
                )
        
        # 미처리 HITL 요청 수 조회
        unresolved_count = 0
        if db:
            result = await db.fetch_one(
                """
                SELECT COUNT(*) as cnt FROM unresolved_hitl_requests
                WHERE status = 'unresolved'
                """
            )
            unresolved_count = result["cnt"] if result else 0
        
        return OperatorStatusResponse(
            operator_id=operator_id,
            status=status,
            away_message=away_message,
            status_changed_at=status_changed_at,
            unresolved_hitl_count=unresolved_count
        )
        
    except Exception as e:
        logger.error("Failed to get operator status",
                    operator_id=operator_id,
                    error=str(e),
                    exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to get operator status: {str(e)}")

