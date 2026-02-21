"""AI Outbound Call API

AI 아웃바운드 콜 요청 생성, 조회, 취소, 재시도 API
"""
from fastapi import APIRouter, HTTPException, Query
from typing import Optional, List
from datetime import datetime
from pydantic import BaseModel, Field
import structlog

logger = structlog.get_logger(__name__)
router = APIRouter()


# =========================================================================
# Request / Response Models
# =========================================================================

class OutboundCallCreateRequest(BaseModel):
    """아웃바운드 콜 요청 생성"""
    caller_number: str = Field(..., description="발신번호")
    callee_number: str = Field(..., description="착신번호")
    purpose: str = Field(..., description="통화 목적")
    questions: List[str] = Field(..., min_length=1, description="확인 필요 사항")
    caller_display_name: Optional[str] = Field(default="", description="발신자 표시명")
    max_duration: Optional[int] = Field(default=0, ge=0, le=1800, description="최대 통화 시간 (초)")
    retry_on_no_answer: bool = Field(default=True, description="미응답 시 재시도")


class OutboundCallCreateResponse(BaseModel):
    """아웃바운드 콜 생성 응답"""
    outbound_id: str
    state: str
    created_at: str
    message: str


class QuestionAnswerEntry(BaseModel):
    """개별 확인 사항 응답"""
    question_id: str
    question_text: str
    status: str
    answer_text: Optional[str] = None
    answer_summary: Optional[str] = None
    confidence: float = 0.0


class TranscriptEntryModel(BaseModel):
    """대화록 엔트리"""
    timestamp: float
    speaker: str
    text: str


class OutboundCallResultModel(BaseModel):
    """통화 결과"""
    answers: List[QuestionAnswerEntry] = []
    summary: str = ""
    task_completed: bool = False
    transcript: List[TranscriptEntryModel] = []
    duration_seconds: int = 0
    ai_turns: int = 0
    customer_turns: int = 0


class OutboundCallEntry(BaseModel):
    """아웃바운드 콜 항목"""
    outbound_id: str
    call_id: Optional[str] = None
    caller_number: str
    callee_number: str
    purpose: str
    questions: List[str] = []
    caller_display_name: str = ""
    max_duration: int = 180
    state: str
    created_at: Optional[str] = None
    started_at: Optional[str] = None
    answered_at: Optional[str] = None
    completed_at: Optional[str] = None
    result: Optional[OutboundCallResultModel] = None
    attempt_count: int = 0
    failure_reason: Optional[str] = None


class OutboundCallListResponse(BaseModel):
    """아웃바운드 콜 목록 응답"""
    calls: List[OutboundCallEntry]
    total: int
    active_count: int


class OutboundCallStatsResponse(BaseModel):
    """아웃바운드 콜 통계"""
    total_calls: int = 0
    completed_count: int = 0
    task_completed_count: int = 0
    success_rate: float = 0.0
    avg_duration_seconds: float = 0
    no_answer_count: int = 0
    busy_count: int = 0
    active_count: int = 0
    queue_size: int = 0


# =========================================================================
# Outbound Manager 접근 헬퍼
# =========================================================================

_outbound_manager_ref = None


def set_outbound_manager(manager):
    """OutboundCallManager 참조 설정"""
    global _outbound_manager_ref
    _outbound_manager_ref = manager
    logger.info("outbound_api_manager_set")


def _get_outbound_manager():
    """OutboundCallManager 인스턴스 가져오기"""
    return _outbound_manager_ref


# =========================================================================
# API Endpoints
# =========================================================================

@router.post("/", response_model=OutboundCallCreateResponse, status_code=202)
async def create_outbound_call(request: OutboundCallCreateRequest):
    """아웃바운드 콜 요청 생성"""
    manager = _get_outbound_manager()
    if not manager:
        raise HTTPException(status_code=503, detail="Outbound call service not available")
    
    try:
        record = await manager.create_call(
            caller_number=request.caller_number,
            callee_number=request.callee_number,
            purpose=request.purpose,
            questions=request.questions,
            caller_display_name=request.caller_display_name or "",
            max_duration=request.max_duration or 0,
            retry_on_no_answer=request.retry_on_no_answer,
        )
        
        return OutboundCallCreateResponse(
            outbound_id=record.outbound_id,
            state=record.state.value,
            created_at=record.created_at.isoformat(),
            message="아웃바운드 콜이 요청되었습니다.",
        )
    except Exception as e:
        logger.error("outbound_create_error", error=str(e))
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/", response_model=OutboundCallListResponse)
async def list_outbound_calls(
    state: Optional[str] = Query(None, description="상태 필터"),
    limit: int = Query(50, ge=1, le=200),
):
    """아웃바운드 콜 목록 조회 (활성 + 이력)"""
    manager = _get_outbound_manager()
    if not manager:
        return OutboundCallListResponse(calls=[], total=0, active_count=0)
    
    active = manager.get_active_calls()
    history = manager.get_call_history(limit=limit)
    all_calls = active + history
    
    if state:
        all_calls = [c for c in all_calls if c.get("state") == state]
    
    entries = []
    for c in all_calls[:limit]:
        try:
            entries.append(OutboundCallEntry(**c))
        except Exception:
            pass
    
    return OutboundCallListResponse(
        calls=entries,
        total=len(all_calls),
        active_count=len(active),
    )


@router.get("/active", response_model=OutboundCallListResponse)
async def list_active_outbound_calls():
    """활성 아웃바운드 콜만 조회"""
    manager = _get_outbound_manager()
    if not manager:
        return OutboundCallListResponse(calls=[], total=0, active_count=0)
    
    active = manager.get_active_calls()
    entries = []
    for c in active:
        try:
            entries.append(OutboundCallEntry(**c))
        except Exception:
            pass
    
    return OutboundCallListResponse(
        calls=entries,
        total=len(active),
        active_count=len(active),
    )


@router.get("/stats", response_model=OutboundCallStatsResponse)
async def get_outbound_stats():
    """아웃바운드 콜 통계"""
    manager = _get_outbound_manager()
    if not manager:
        return OutboundCallStatsResponse()
    
    stats = manager.get_stats()
    return OutboundCallStatsResponse(**stats)


@router.get("/{outbound_id}")
async def get_outbound_call(outbound_id: str):
    """개별 아웃바운드 콜 상세"""
    manager = _get_outbound_manager()
    if not manager:
        raise HTTPException(status_code=404, detail="Outbound call not found")
    
    record = manager.get_call(outbound_id)
    if not record:
        raise HTTPException(status_code=404, detail="Outbound call not found")
    
    return record.to_dict()


@router.get("/{outbound_id}/result")
async def get_outbound_result(outbound_id: str):
    """통화 결과 조회 (답변 + 대화록 + 요약)"""
    manager = _get_outbound_manager()
    if not manager:
        raise HTTPException(status_code=404, detail="Outbound call not found")
    
    record = manager.get_call(outbound_id)
    if not record:
        raise HTTPException(status_code=404, detail="Outbound call not found")
    
    data = record.to_dict()
    if not data.get("result"):
        raise HTTPException(status_code=404, detail="Result not yet available")
    
    return {
        "outbound_id": data["outbound_id"],
        "state": data["state"],
        "caller_number": data["caller_number"],
        "callee_number": data["callee_number"],
        "purpose": data["purpose"],
        **data["result"],
        "created_at": data["created_at"],
        "answered_at": data["answered_at"],
        "completed_at": data["completed_at"],
    }


@router.post("/{outbound_id}/cancel")
async def cancel_outbound_call(outbound_id: str):
    """아웃바운드 콜 취소"""
    manager = _get_outbound_manager()
    if not manager:
        raise HTTPException(status_code=503, detail="Outbound call service not available")
    
    record = await manager.cancel_call(outbound_id, reason="operator_cancel")
    if not record:
        raise HTTPException(status_code=404, detail="Active outbound call not found")
    
    return {"outbound_id": outbound_id, "state": "cancelled", "message": "콜이 취소되었습니다."}


@router.post("/{outbound_id}/retry")
async def retry_outbound_call(outbound_id: str):
    """아웃바운드 콜 재시도"""
    manager = _get_outbound_manager()
    if not manager:
        raise HTTPException(status_code=503, detail="Outbound call service not available")
    
    new_record = await manager.retry_call(outbound_id)
    if not new_record:
        raise HTTPException(status_code=400, detail="Cannot retry this call (not in failed state or not found)")
    
    return {
        "outbound_id": new_record.outbound_id,
        "state": new_record.state.value,
        "message": "재시도가 요청되었습니다.",
    }
