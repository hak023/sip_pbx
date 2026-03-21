"""
통화 이력(Call History) API 라우터

- GET /api/call-history - 통화 이력 목록 조회
- GET /api/call-history/follow-ups - 확인 필요 목록 조회
- PATCH /api/call-history/follow-ups/{id} - 확인 필요 상태 업데이트
"""

from fastapi import APIRouter, Query, HTTPException
from pydantic import BaseModel
from typing import List, Optional, Dict, Any

# ✅ Transcript 파싱 유틸리티 import
from src.api.utils.call_data_record_reader import read_call_data_record_for_call
from src.api.utils.recording_paths import call_has_audio_recording, get_recordings_dir
from src.api.utils.transcript_parser import get_all_call_metadata, get_transcript_for_call

router = APIRouter(prefix="/api/call-history", tags=["call-history"])


class FollowUpUpdate(BaseModel):
    """확인 필요 상태 업데이트"""
    status: str  # pending, noted, contacted, resolved
    operator_note: Optional[str] = None


# 간단한 인메모리 저장소 (실제로는 DB 사용)
_follow_ups: Dict[str, Dict[str, Any]] = {}

# HITL 요청 저장소 (미처리 HITL 탭 데이터 소스)
_hitl_requests: Dict[str, Dict[str, Any]] = {}


def record_hitl_request(
    call_id: str,
    callee_id: str,
    user_question: str,
    ai_confidence: float,
    caller_id: Optional[str] = None,
) -> None:
    """
    HITL 요청 건 기록 (통화 이력·대시보드 미처리 HITL 목록용).
    rag_processor에서 needs_human 시 호출.
    """
    if not call_id:
        return
    import time
    key = f"{call_id}_{int(time.time() * 1000)}"  # 동일 call_id 다건 허용
    _hitl_requests[key] = {
        "id": key,
        "call_id": call_id,
        "callee_id": callee_id,
        "caller_id": caller_id or "",
        "user_question": user_question,
        "ai_confidence": ai_confidence,
        "status": "pending",
        "created_at": time.time(),
    }


@router.get("/follow-ups")
async def get_follow_ups(
    callee: Optional[str] = Query(None, description="착신자 ID 필터"),
    status: Optional[str] = Query(None, description="상태 필터")
) -> Dict[str, Any]:
    """
    확인 필요(후처리) 목록 조회
    
    AI가 "모르는 내용"으로 응답한 건
    
    Args:
        callee: 착신자 ID 필터
        status: 상태 필터 (pending, noted, contacted, resolved)
    
    Returns:
        {
            "items": [
                {
                    "id": "...",
                    "call_id": "...",
                    "user_question": "...",
                    "ai_response": "...",
                    "status": "pending",
                    "operator_note": null,
                    "created_at": "..."
                }
            ],
            "total": 0
        }
    """
    items = list(_follow_ups.values())
    
    # 필터링 (record_hitl_request는 callee_id로 저장)
    if callee:
        items = [
            item for item in items
            if item.get("callee_id") == callee or item.get("callee") == callee
        ]
    if status:
        items = [item for item in items if item.get("status") == status]
    
    return {
        "items": items,
        "total": len(items)
    }


@router.patch("/follow-ups/{id}")
async def update_follow_up(
    id: str,
    update: FollowUpUpdate
) -> Dict[str, Any]:
    """
    확인 필요 상태 업데이트
    
    Args:
        id: Follow-up ID
        update: 업데이트 정보
    
    Returns:
        {
            "success": true,
            "id": "...",
            "status": "noted"
        }
    """
    if id not in _follow_ups:
        raise HTTPException(status_code=404, detail="Follow-up not found")
    
    _follow_ups[id]["status"] = update.status
    if update.operator_note:
        _follow_ups[id]["operator_note"] = update.operator_note
    
    return {
        "success": True,
        "id": id,
        "status": update.status
    }


@router.get("/{call_id}/call-data-record")
async def get_call_data_record(call_id: str) -> Dict[str, Any]:
    """
    `logs/call_data_record_*.log` 에서 해당 통화의 상세 처리 이벤트(STT/TTS/LLM/RAG 등) 목록.
    통화이력 화면에서 행 확장 시 사용.
    """
    items = read_call_data_record_for_call(call_id)
    return {"call_id": call_id, "items": items, "total": len(items)}


@router.get("")
async def get_call_history(
    page: int = Query(1, ge=1, description="페이지 번호"),
    limit: int = Query(20, ge=1, le=100, description="페이지당 항목 수"),
    callee: Optional[str] = Query(None, description="착신자 ID 필터"),
):
    """
    통화 이력 목록 반환 (transcript 포함)
    
    Args:
        page: 페이지 번호
        limit: 페이지당 항목 수
        callee: 착신자 ID 필터 (선택)
        
    Returns:
        {
            "items": [
                {
                    "call_id": "...",
                    "caller_id": "...",
                    "callee_id": "...",
                    "start_time": "...",
                    "end_time": "...",
                    "has_recording": true,
                    "transcripts": [
                        {"role": "assistant", "content": "..."},
                        {"role": "user", "content": "..."}
                    ]
                }
            ],
            "total": 10,
            "page": 1,
            "limit": 20
        }
    """
    recordings_root = get_recordings_dir()
    # 모든 metadata 읽기
    all_metadata = get_all_call_metadata(recordings_dir=recordings_root)
    
    # callee 필터링
    if callee:
        filtered_metadata = [
            m for m in all_metadata 
            if m.get("callee_id") == callee
        ]
    else:
        filtered_metadata = all_metadata
    
    # 각 통화에 transcript 추가
    items = []
    for metadata in filtered_metadata:
        call_id = metadata.get("call_id", "")
        
        # transcript 파싱
        transcripts = get_transcript_for_call(call_id, recordings_dir=recordings_root)
        has_audio = call_has_audio_recording(call_id, recordings_root)

        item = {
            "call_id": call_id,
            "caller_id": metadata.get("caller_id", ""),
            "callee_id": metadata.get("callee_id", ""),
            "start_time": metadata.get("start_time", ""),
            "end_time": metadata.get("end_time"),
            "has_recording": has_audio,
            "has_transcript": metadata.get("has_transcript", False),
            "is_ai_handled": metadata.get("type") == "ai_call",  # type으로 판단
            "transcripts": transcripts or [],  # ✅ transcript 포함
            "transcript": None,  # 레거시 지원
            "stt_transcript": None,  # 레거시 지원
            "hitl_status": None,
            "user_question": None,
            "ai_confidence": None,
            "timestamp": metadata.get("start_time", "")
        }
        
        items.append(item)
    
    # 페이지네이션
    total = len(items)
    start_idx = (page - 1) * limit
    end_idx = start_idx + limit
    paginated_items = items[start_idx:end_idx]
    
    return {
        "items": paginated_items,
        "total": total,
        "page": page,
        "limit": limit,
        "pages": (total + limit - 1) // limit
    }
