"""
Call History & Unresolved HITL API

통화 이력 및 미처리 HITL 요청 관리 API
"""

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from typing import Optional, List, Dict, Any
from datetime import datetime
from enum import Enum
import structlog

logger = structlog.get_logger(__name__)

router = APIRouter(prefix="/api/call-history", tags=["call-history"])


class UnresolvedHITLFilter(str, Enum):
    """미처리 HITL 필터"""
    ALL = "all"
    UNRESOLVED = "unresolved"
    NOTED = "noted"
    RESOLVED = "resolved"
    CONTACTED = "contacted"


class CallHistoryItem(BaseModel):
    """통화 이력 항목"""
    call_id: str
    caller_id: str
    callee_id: str
    start_time: datetime
    end_time: Optional[datetime]
    hitl_status: Optional[str]
    user_question: Optional[str]
    ai_confidence: Optional[float]
    timestamp: Optional[datetime]


class CallHistoryResponse(BaseModel):
    """통화 이력 응답"""
    items: List[CallHistoryItem]
    total: int
    page: int
    limit: int


class CallTranscript(BaseModel):
    """STT 트랜스크립트"""
    speaker: str  # user | ai
    text: str
    timestamp: datetime


class CallDetailResponse(BaseModel):
    """통화 상세 응답"""
    call_info: Dict[str, Any]
    transcripts: List[CallTranscript]
    hitl_request: Optional[Dict[str, Any]]


class CallNoteCreate(BaseModel):
    """통화 메모 생성"""
    operator_note: str
    follow_up_required: bool = False
    follow_up_phone: Optional[str] = None


class CallNoteResponse(BaseModel):
    """통화 메모 응답"""
    call_id: str
    operator_note: str
    follow_up_required: bool
    status: str


class ResolveResponse(BaseModel):
    """처리 완료 응답"""
    call_id: str
    status: str
    resolved_at: datetime


# Dependencies (실제 구현 시 주입)
async def get_db():
    """Database 클라이언트 가져오기"""
    # TODO: 실제 DB 클라이언트 반환
    return None


async def get_current_operator():
    """현재 운영자 정보 가져오기"""
    # TODO: JWT 토큰에서 운영자 정보 추출
    return {"id": "operator_123", "name": "Operator"}


@router.get("", response_model=CallHistoryResponse)
async def get_call_history(
    page: int = Query(1, ge=1),
    limit: int = Query(50, ge=1, le=100),
    unresolved_hitl: Optional[UnresolvedHITLFilter] = None,
    date_from: Optional[datetime] = None,
    date_to: Optional[datetime] = None,
    db=Depends(get_db),
    current_user=Depends(get_current_operator)
):
    """
    통화 이력 조회 (미처리 HITL 요청 포함)
    
    Args:
        page: 페이지 번호
        limit: 페이지당 항목 수
        unresolved_hitl: HITL 필터 (all | unresolved | noted | resolved | contacted)
        date_from: 시작 날짜
        date_to: 종료 날짜
        
    Returns:
        통화 이력 목록
    """
    try:
        # SQL 쿼리 구성
        sql = """
            SELECT 
                ch.call_id,
                ch.caller_id,
                ch.callee_id,
                ch.start_time,
                ch.end_time,
                uhr.status as hitl_status,
                uhr.user_question,
                uhr.ai_confidence,
                uhr.timestamp
            FROM call_history ch
            LEFT JOIN unresolved_hitl_requests uhr ON ch.call_id = uhr.call_id
            WHERE 1=1
        """
        
        params = {}
        
        # 미처리 HITL 필터
        if unresolved_hitl and unresolved_hitl != UnresolvedHITLFilter.ALL:
            sql += " AND uhr.status = :hitl_status"
            params["hitl_status"] = unresolved_hitl.value
        
        # 날짜 필터
        if date_from:
            sql += " AND ch.start_time >= :date_from"
            params["date_from"] = date_from
        if date_to:
            sql += " AND ch.start_time <= :date_to"
            params["date_to"] = date_to
        
        # 정렬 (최신순)
        sql += " ORDER BY ch.start_time DESC"
        
        # 페이지네이션
        sql += " LIMIT :limit OFFSET :offset"
        params["limit"] = limit
        params["offset"] = (page - 1) * limit
        
        if db:
            results = await db.fetch_all(sql, params)
            
            # 총 개수 조회
            count_sql = """
                SELECT COUNT(*) as cnt
                FROM call_history ch
                LEFT JOIN unresolved_hitl_requests uhr ON ch.call_id = uhr.call_id
                WHERE 1=1
            """
            if unresolved_hitl and unresolved_hitl != UnresolvedHITLFilter.ALL:
                count_sql += " AND uhr.status = :hitl_status"
            if date_from:
                count_sql += " AND ch.start_time >= :date_from"
            if date_to:
                count_sql += " AND ch.start_time <= :date_to"
            
            total_result = await db.fetch_one(count_sql, params)
            total = total_result["cnt"] if total_result else 0
            
            items = [CallHistoryItem(**row) for row in results]
        else:
            # Mock 데이터 (DB 없을 때)
            items = []
            total = 0
        
        logger.info("Call history retrieved",
                   page=page,
                   limit=limit,
                   total=total,
                   filter=unresolved_hitl)
        
        return CallHistoryResponse(
            items=items,
            total=total,
            page=page,
            limit=limit
        )
        
    except Exception as e:
        logger.error("Failed to get call history",
                    error=str(e),
                    exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to get call history: {str(e)}")


@router.get("/{call_id}", response_model=CallDetailResponse)
async def get_call_detail(
    call_id: str,
    db=Depends(get_db),
    current_user=Depends(get_current_operator)
):
    """
    특정 통화 상세 정보 조회 (STT 전체 기록 포함)
    
    Args:
        call_id: 통화 ID
        
    Returns:
        통화 상세 정보
    """
    try:
        if not db:
            raise HTTPException(status_code=503, detail="Database not available")
        
        # 통화 정보 조회
        call_info_query = """
            SELECT ch.*, uhr.*
            FROM call_history ch
            LEFT JOIN unresolved_hitl_requests uhr ON ch.call_id = uhr.call_id
            WHERE ch.call_id = :call_id
        """
        call_info = await db.fetch_one(call_info_query, {"call_id": call_id})
        
        if not call_info:
            raise HTTPException(status_code=404, detail="Call not found")
        
        # STT 전체 기록 조회
        transcripts_query = """
            SELECT speaker, text, timestamp
            FROM call_transcripts
            WHERE call_id = :call_id
            ORDER BY timestamp ASC
        """
        transcripts_data = await db.fetch_all(transcripts_query, {"call_id": call_id})
        transcripts = [CallTranscript(**row) for row in transcripts_data]
        
        logger.info("Call detail retrieved", call_id=call_id)
        
        return CallDetailResponse(
            call_info=dict(call_info),
            transcripts=transcripts,
            hitl_request=dict(call_info) if call_info.get("user_question") else None
        )
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error("Failed to get call detail",
                    call_id=call_id,
                    error=str(e),
                    exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to get call detail: {str(e)}")


@router.post("/{call_id}/note", response_model=CallNoteResponse)
async def add_call_note(
    call_id: str,
    note: CallNoteCreate,
    db=Depends(get_db),
    current_user=Depends(get_current_operator)
):
    """
    통화 이력에 운영자 메모 추가
    
    Args:
        call_id: 통화 ID
        note: 메모 내용
        
    Returns:
        메모 응답
    """
    try:
        if not db:
            raise HTTPException(status_code=503, detail="Database not available")
        
        operator_id = current_user["id"]
        
        # 메모 저장
        update_query = """
            UPDATE unresolved_hitl_requests
            SET 
                operator_note = :note,
                follow_up_required = :follow_up_required,
                follow_up_phone = :follow_up_phone,
                status = 'noted',
                noted_at = :noted_at,
                noted_by = :operator_id
            WHERE call_id = :call_id
        """
        
        await db.execute(update_query, {
            "note": note.operator_note,
            "follow_up_required": note.follow_up_required,
            "follow_up_phone": note.follow_up_phone,
            "noted_at": datetime.now(),
            "operator_id": operator_id,
            "call_id": call_id
        })
        
        logger.info("Call note added",
                   call_id=call_id,
                   operator_id=operator_id,
                   follow_up_required=note.follow_up_required)
        
        return CallNoteResponse(
            call_id=call_id,
            operator_note=note.operator_note,
            follow_up_required=note.follow_up_required,
            status="noted"
        )
        
    except Exception as e:
        logger.error("Failed to add call note",
                    call_id=call_id,
                    error=str(e),
                    exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to add call note: {str(e)}")


@router.put("/{call_id}/resolve", response_model=ResolveResponse)
async def resolve_hitl_request(
    call_id: str,
    db=Depends(get_db),
    current_user=Depends(get_current_operator)
):
    """
    미처리 HITL 요청 해결 처리
    
    Args:
        call_id: 통화 ID
        
    Returns:
        처리 완료 응답
    """
    try:
        if not db:
            raise HTTPException(status_code=503, detail="Database not available")
        
        operator_id = current_user["id"]
        resolved_at = datetime.now()
        
        # 해결 처리
        update_query = """
            UPDATE unresolved_hitl_requests
            SET 
                status = 'resolved',
                resolved_at = :resolved_at,
                resolved_by = :operator_id
            WHERE call_id = :call_id
        """
        
        await db.execute(update_query, {
            "resolved_at": resolved_at,
            "operator_id": operator_id,
            "call_id": call_id
        })
        
        logger.info("HITL request resolved",
                   call_id=call_id,
                   operator_id=operator_id)
        
        return ResolveResponse(
            call_id=call_id,
            status="resolved",
            resolved_at=resolved_at
        )
        
    except Exception as e:
        logger.error("Failed to resolve HITL request",
                    call_id=call_id,
                    error=str(e),
                    exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to resolve HITL request: {str(e)}")

