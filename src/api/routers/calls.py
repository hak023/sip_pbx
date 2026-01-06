"""통화 관련 API"""
from fastapi import APIRouter, HTTPException
from typing import List
import structlog

from ..models import ActiveCall, ConversationMessage, CallerInfo

logger = structlog.get_logger(__name__)

router = APIRouter()


@router.get("/active", response_model=List[ActiveCall])
async def get_active_calls():
    """
    활성 통화 목록 조회
    
    추후 실제 Call Manager와 연동
    """
    # Mock 데이터
    mock_calls = [
        ActiveCall(
            call_id="call_001",
            caller=CallerInfo(uri="sip:1001@localhost", name="김철수", number="010-1234-5678"),
            callee=CallerInfo(uri="sip:1002@localhost", name="이영희", number="010-8765-4321"),
            status="active",
            is_ai_handled=True,
            duration=45,
            current_question="영업시간이 언제인가요?",
            ai_confidence=0.85,
            needs_hitl=False
        )
    ]
    
    return mock_calls


@router.get("/{call_id}/transcript")
async def get_call_transcript(call_id: str):
    """
    특정 통화의 트랜스크립트 조회
    """
    # Mock 데이터
    if call_id == "call_001":
        return {
            "call_id": call_id,
            "messages": [
                {
                    "role": "assistant",
                    "content": "안녕하세요, 무엇을 도와드릴까요?",
                    "timestamp": "2026-01-05T18:00:00",
                    "is_final": True
                },
                {
                    "role": "user",
                    "content": "영업시간이 언제인가요?",
                    "timestamp": "2026-01-05T18:00:05",
                    "is_final": True
                }
            ],
            "is_speaking": False,
            "current_state": "listening"
        }
    else:
        raise HTTPException(status_code=404, detail="Call not found")

