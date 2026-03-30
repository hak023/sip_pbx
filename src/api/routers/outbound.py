"""Outbound Call API Router

AI 아웃바운드 콜 생성·취소·조회 엔드포인트 제공.
"""

from __future__ import annotations

from typing import List, Optional

import structlog
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

logger = structlog.get_logger(__name__)

router = APIRouter(prefix="/api/outbound", tags=["outbound"])


# ============================================================================
# Request/Response 모델
# ============================================================================


class OutboundCreateRequest(BaseModel):
    """아웃바운드 콜 생성 요청"""

    caller_number: str = Field(..., description="발신번호 (AI 봇 번호)", min_length=1)
    callee_number: str = Field(..., description="착신번호 (고객)", min_length=1)
    purpose: str = Field(..., description="통화 목적", min_length=1)
    questions: List[str] = Field(
        default_factory=list, description="질문 목록 (TaskTracker용)"
    )
    caller_display_name: str = Field(default="", description="발신자 표시 이름")
    max_duration: int = Field(default=300, description="최대 통화 시간(초)", ge=30, le=1800)
    retry_on_no_answer: bool = Field(default=True, description="무응답 시 재시도 여부")
    metadata: Optional[dict] = Field(default=None, description="추가 메타데이터")


class OutboundCreateResponse(BaseModel):
    """아웃바운드 콜 생성 응답"""

    success: bool
    outbound_id: str
    message: str


class OutboundCancelRequest(BaseModel):
    """아웃바운드 콜 취소 요청"""

    outbound_id: str = Field(..., description="취소할 아웃바운드 콜 ID")
    reason: str = Field(default="operator_cancel", description="취소 사유")


class OutboundRetryRequest(BaseModel):
    """아웃바운드 콜 재시도 요청"""

    outbound_id: str = Field(..., description="재시도할 아웃바운드 콜 ID")


# ============================================================================
# 엔드포인트
# ============================================================================


@router.post("/create", response_model=OutboundCreateResponse)
async def create_outbound_call(req: OutboundCreateRequest):
    """아웃바운드 콜 생성 및 발신 시작

    - OutboundCallManager를 통해 콜 요청 생성
    - 동시 통화 수 제한 체크 후 즉시 발신 또는 대기열 추가
    """
    try:
        from src.sip_core.call_manager import get_call_manager

        cm = get_call_manager()
        if not cm:
            raise HTTPException(status_code=503, detail="CallManager not initialized")

        if not hasattr(cm, "_outbound_manager") or not cm._outbound_manager:
            raise HTTPException(
                status_code=503, detail="OutboundCallManager not enabled in config"
            )

        obm = cm._outbound_manager

        record = await obm.create_call(
            caller_number=req.caller_number,
            callee_number=req.callee_number,
            purpose=req.purpose,
            questions=req.questions,
            caller_display_name=req.caller_display_name,
            max_duration=req.max_duration,
            retry_on_no_answer=req.retry_on_no_answer,
            metadata=req.metadata,
        )

        logger.info(
            "outbound_create_api_success",
            outbound_id=record.outbound_id,
            callee=req.callee_number,
            purpose=req.purpose,
        )

        return OutboundCreateResponse(
            success=True,
            outbound_id=record.outbound_id,
            message=f"아웃바운드 콜이 생성되었습니다. ID: {record.outbound_id}",
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error("outbound_create_api_error", error=str(e))
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/cancel")
async def cancel_outbound_call(req: OutboundCancelRequest):
    """아웃바운드 콜 취소

    - DIALING/RINGING: CANCEL 전송
    - CONNECTED: AI 중지 + BYE 전송
    """
    try:
        from src.sip_core.call_manager import get_call_manager

        cm = get_call_manager()
        if not cm or not getattr(cm, "_outbound_manager", None):
            raise HTTPException(status_code=503, detail="OutboundCallManager not available")

        obm = cm._outbound_manager
        result = await obm.cancel_call(req.outbound_id, reason=req.reason)

        if not result:
            raise HTTPException(status_code=404, detail=f"Outbound call {req.outbound_id} not found")

        logger.info("outbound_cancel_api_success", outbound_id=req.outbound_id)

        return {"success": True, "message": "아웃바운드 콜이 취소되었습니다."}

    except HTTPException:
        raise
    except Exception as e:
        logger.error("outbound_cancel_api_error", error=str(e))
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/retry")
async def retry_outbound_call(req: OutboundRetryRequest):
    """아웃바운드 콜 수동 재시도

    - 이력에서 찾아 같은 요청으로 새로 발신
    """
    try:
        from src.sip_core.call_manager import get_call_manager

        cm = get_call_manager()
        if not cm or not getattr(cm, "_outbound_manager", None):
            raise HTTPException(status_code=503, detail="OutboundCallManager not available")

        obm = cm._outbound_manager
        new_record = await obm.retry_call(req.outbound_id)

        if not new_record:
            raise HTTPException(
                status_code=404,
                detail=f"Outbound call {req.outbound_id} not found or not retryable",
            )

        logger.info(
            "outbound_retry_api_success",
            old_outbound_id=req.outbound_id,
            new_outbound_id=new_record.outbound_id,
        )

        return {
            "success": True,
            "new_outbound_id": new_record.outbound_id,
            "message": "재시도가 시작되었습니다.",
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error("outbound_retry_api_error", error=str(e))
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/active")
async def get_active_outbound_calls():
    """활성 아웃바운드 콜 목록 조회"""
    try:
        from src.sip_core.call_manager import get_call_manager

        cm = get_call_manager()
        if not cm or not getattr(cm, "_outbound_manager", None):
            return {"items": []}

        obm = cm._outbound_manager
        items = obm.get_active_calls()

        return {"items": items}

    except Exception as e:
        logger.error("outbound_active_api_error", error=str(e))
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/history")
async def get_outbound_call_history(limit: int = 50):
    """아웃바운드 콜 이력 조회"""
    try:
        from src.sip_core.call_manager import get_call_manager

        cm = get_call_manager()
        if not cm or not getattr(cm, "_outbound_manager", None):
            return {"items": []}

        obm = cm._outbound_manager
        items = obm.get_call_history(limit=min(limit, 200))

        return {"items": items}

    except Exception as e:
        logger.error("outbound_history_api_error", error=str(e))
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/stats")
async def get_outbound_stats():
    """아웃바운드 콜 통계 조회"""
    try:
        from src.sip_core.call_manager import get_call_manager

        cm = get_call_manager()
        if not cm or not getattr(cm, "_outbound_manager", None):
            return {
                "total_calls": 0,
                "completed_count": 0,
                "task_completed_count": 0,
                "success_rate": 0.0,
                "avg_duration_seconds": 0,
                "no_answer_count": 0,
                "busy_count": 0,
                "active_count": 0,
                "queue_size": 0,
            }

        obm = cm._outbound_manager
        stats = obm.get_stats()

        return stats

    except Exception as e:
        logger.error("outbound_stats_api_error", error=str(e))
        raise HTTPException(status_code=500, detail=str(e))
