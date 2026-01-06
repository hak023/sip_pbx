"""HITL 관련 API"""
from fastapi import APIRouter, HTTPException
from typing import List
import structlog
from datetime import datetime, timedelta

from ..models import HITLRequest, HITLResponse

logger = structlog.get_logger(__name__)

router = APIRouter()

# Mock HITL 큐
mock_hitl_queue: dict[str, HITLRequest] = {}


@router.get("/queue", response_model=List[HITLRequest])
async def get_hitl_queue():
    """
    대기 중인 HITL 요청 목록
    
    추후 Redis와 연동
    """
    # Mock 데이터
    mock_requests = [
        HITLRequest(
            call_id="call_002",
            question="다음 주 화요일 오후에 김대리님과 미팅 가능한가요?",
            context={
                "previousMessages": [],
                "ragResults": [],
                "callerInfo": {"uri": "sip:1003@localhost", "name": "박과장"}
            },
            urgency="high",
            timestamp=datetime.now()
        )
    ]
    
    return mock_requests


@router.post("/response")
async def submit_hitl_response(response: HITLResponse):
    """
    HITL 답변 제출
    
    추후 AI Orchestrator와 WebSocket 연동
    """
    logger.info("HITL response submitted", 
               call_id=response.call_id,
               save_to_kb=response.save_to_kb)
    
    # Mock: HITL 큐에서 제거
    if response.call_id in mock_hitl_queue:
        del mock_hitl_queue[response.call_id]
    
    return {
        "success": True,
        "message": "Response submitted successfully"
    }


@router.get("/history")
async def get_hitl_history():
    """HITL 해결 이력"""
    # Mock 데이터
    return {
        "items": [],
        "total": 0
    }

