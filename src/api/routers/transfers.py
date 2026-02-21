"""호 전환(Transfer) 관리 API

AI 호 연결 상태 조회, 이력, 통계 API
"""
from fastapi import APIRouter, HTTPException, Query
from typing import Optional, List
from datetime import datetime
from pydantic import BaseModel
import structlog

logger = structlog.get_logger(__name__)
router = APIRouter()


# =========================================================================
# Response Models
# =========================================================================

class TransferEntry(BaseModel):
    """Transfer 항목"""
    transfer_id: str
    call_id: str
    transfer_leg_call_id: str = ""
    department_name: str
    transfer_to: str
    phone_display: str
    caller_uri: str = ""
    caller_display: str = ""
    state: str
    initiated_at: Optional[str] = None
    ringing_at: Optional[str] = None
    connected_at: Optional[str] = None
    ended_at: Optional[str] = None
    failure_reason: Optional[str] = None
    duration_seconds: Optional[int] = None
    user_request_text: str = ""


class TransferListResponse(BaseModel):
    """Transfer 목록 응답"""
    transfers: List[TransferEntry]
    total: int
    active_count: int


class TransferStatsResponse(BaseModel):
    """Transfer 통계 응답"""
    total_transfers: int
    success_rate: float
    avg_ring_duration_seconds: float
    avg_call_duration_seconds: float
    active_count: int


# =========================================================================
# Transfer Manager 접근 헬퍼
# =========================================================================

def _get_transfer_manager():
    """TransferManager 인스턴스 가져오기"""
    try:
        # SIPEndpoint에서 TransferManager 접근
        # 글로벌 인스턴스 또는 앱 상태에서 가져오기
        from src.api.routers.transfers import _transfer_manager_ref
        if _transfer_manager_ref:
            return _transfer_manager_ref
    except (ImportError, AttributeError):
        pass
    return None


# TransferManager 참조 (startup 시 설정)
_transfer_manager_ref = None


def set_transfer_manager(manager):
    """TransferManager 참조 설정 (앱 시작 시 호출)"""
    global _transfer_manager_ref
    _transfer_manager_ref = manager
    logger.info("transfer_api_manager_set")


# =========================================================================
# API Endpoints
# =========================================================================

@router.get("/", response_model=TransferListResponse)
async def list_transfers(
    state: Optional[str] = Query(None, description="상태 필터 (announce, ringing, connected, failed)"),
    limit: int = Query(50, ge=1, le=200),
):
    """전환 목록 조회 (활성 + 최근 이력)"""
    manager = _get_transfer_manager()
    if not manager:
        return TransferListResponse(transfers=[], total=0, active_count=0)
    
    # 활성 전환
    active = manager.get_active_transfers()
    
    # 이력
    history = manager.get_transfer_history(limit=limit)
    
    # 합치기 (활성 우선)
    all_transfers = active + history
    
    # 상태 필터
    if state:
        all_transfers = [t for t in all_transfers if t.get("state") == state]
    
    entries = [TransferEntry(**t) for t in all_transfers[:limit]]
    
    return TransferListResponse(
        transfers=entries,
        total=len(all_transfers),
        active_count=len(active),
    )


@router.get("/active", response_model=TransferListResponse)
async def list_active_transfers():
    """활성 전환만 조회"""
    manager = _get_transfer_manager()
    if not manager:
        return TransferListResponse(transfers=[], total=0, active_count=0)
    
    active = manager.get_active_transfers()
    entries = [TransferEntry(**t) for t in active]
    
    return TransferListResponse(
        transfers=entries,
        total=len(active),
        active_count=len(active),
    )


@router.get("/stats", response_model=TransferStatsResponse)
async def get_transfer_stats():
    """전환 통계"""
    manager = _get_transfer_manager()
    if not manager:
        return TransferStatsResponse(
            total_transfers=0,
            success_rate=0.0,
            avg_ring_duration_seconds=0,
            avg_call_duration_seconds=0,
            active_count=0,
        )
    
    stats = manager.get_stats()
    return TransferStatsResponse(**stats)


@router.get("/{transfer_id}")
async def get_transfer(transfer_id: str):
    """개별 전환 상세"""
    manager = _get_transfer_manager()
    if not manager:
        raise HTTPException(status_code=404, detail="Transfer not found")
    
    # 활성에서 찾기
    for record in manager.active_transfers.values():
        if record.transfer_id == transfer_id:
            return record.to_dict()
    
    # 이력에서 찾기
    for record in manager.transfer_history:
        if record.transfer_id == transfer_id:
            return record.to_dict()
    
    raise HTTPException(status_code=404, detail="Transfer not found")
