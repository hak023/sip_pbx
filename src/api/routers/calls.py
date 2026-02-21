"""통화 관련 API"""
from fastapi import APIRouter, HTTPException, Depends
from typing import List, Optional
from datetime import datetime
import structlog

from ..models import ActiveCall, ConversationMessage, CallerInfo
from ..routers.auth import get_current_extension
from src.sip_core.utils import extract_extension_from_uri
from src.sip_core.call_manager import CallManager
from src.sip_core.models.enums import CallState

logger = structlog.get_logger(__name__)

router = APIRouter()

# CallManager 인스턴스 (전역, main.py에서 주입 필요. API 단독 실행 시 None)
_call_manager: Optional[CallManager] = None


def set_call_manager(call_manager: CallManager):
    """CallManager 인스턴스 주입"""
    global _call_manager
    _call_manager = call_manager


def get_call_manager() -> CallManager:
    """CallManager 인스턴스 반환 (없으면 503)"""
    if _call_manager is None:
        raise HTTPException(status_code=503, detail="Call manager not available")
    return _call_manager


def _get_call_manager_optional() -> Optional[CallManager]:
    """CallManager 인스턴스 반환 (없으면 None). /active 등에서 사용."""
    return _call_manager


@router.get("/active", response_model=List[ActiveCall])
async def get_active_calls(extension: str = Depends(get_current_extension)):
    """
    활성 통화 목록 조회 (본인 extension만)
    
    CallManager가 주입되지 않은 경우(API 단독 실행) 503 반환 → 프론트에서 안내 가능.
    """
    call_manager = _get_call_manager_optional()
    if call_manager is None:
        logger.debug("active_calls_skipped_no_call_manager", extension=extension)
        raise HTTPException(status_code=503, detail="Call manager not available. Run server with python -m src.main for real-time calls.")

    # 활성 세션 조회
    active_sessions = call_manager.call_repository.get_active_sessions()
    
    # callee extension 필터링 (문자열로 통일해 비교)
    extension_str = str(extension).strip() if extension else ""
    filtered_calls = []
    for session in active_sessions:
        callee_uri = session.get_callee_uri()
        callee_extension = extract_extension_from_uri(callee_uri) if callee_uri else ""
        callee_extension_str = str(callee_extension).strip() if callee_extension else ""
        
        # 본인 extension과 일치하는 통화만
        if callee_extension_str == extension_str:
            # CallSession → ActiveCall 변환
            active_call = _session_to_active_call(session, call_manager)
            filtered_calls.append(active_call)
    
    logger.info("active_calls_retrieved",
               progress="realtime",
               extension=extension,
               total_active=len(active_sessions),
               filtered_count=len(filtered_calls))
    
    return filtered_calls


def _session_to_active_call(session, call_manager: CallManager) -> ActiveCall:
    """CallSession → ActiveCall 변환
    
    Args:
        session: CallSession 인스턴스
        call_manager: CallManager (ai_enabled_calls 확인용)
        
    Returns:
        ActiveCall: API 응답 모델
    """
    caller_uri = session.get_caller_uri() or ""
    callee_uri = session.get_callee_uri() or ""
    
    caller_extension = extract_extension_from_uri(caller_uri)
    callee_extension = extract_extension_from_uri(callee_uri)
    
    # 상태 매핑
    status_map = {
        CallState.INITIAL: "ringing",
        CallState.PROCEEDING: "ringing",
        CallState.RINGING: "ringing",
        CallState.ESTABLISHED: "active",
        CallState.TERMINATING: "ending",
        CallState.TERMINATED: "ending",
        CallState.FAILED: "ending"
    }
    status = status_map.get(session.state, "ringing")
    
    # duration 계산
    if session.answer_time:
        duration = int((datetime.utcnow() - session.answer_time).total_seconds())
    else:
        duration = 0
    
    # AI 응대 여부
    is_ai_handled = session.call_id in call_manager.ai_enabled_calls
    
    return ActiveCall(
        call_id=session.call_id,
        caller=CallerInfo(
            uri=caller_uri,
            name=caller_extension,
            number=caller_extension
        ),
        callee=CallerInfo(
            uri=callee_uri,
            name=callee_extension,
            number=callee_extension
        ),
        status=status,
        is_ai_handled=is_ai_handled,
        duration=duration,
        current_question=None,  # TODO: 대화 컨텍스트에서 추출
        ai_confidence=None,  # TODO: LLM 결과에서 추출
        needs_hitl=False  # TODO: HITL 상태 확인
    )


@router.get("/{call_id}/transcript")
async def get_call_transcript(
    call_id: str,
    extension: str = Depends(get_current_extension)
):
    """
    특정 통화의 트랜스크립트 조회 (권한 검사)
    
    Args:
        call_id: 통화 ID
        extension: JWT에서 추출한 extension
        
    Returns:
        트랜스크립트 데이터
        
    Raises:
        HTTPException: 통화 없음(404) 또는 권한 없음(403)
    """
    call_manager = get_call_manager()
    
    # CallSession 조회
    session = call_manager.get_session(call_id)
    if not session:
        raise HTTPException(status_code=404, detail="Call not found")
    
    # callee 권한 검사
    callee_uri = session.get_callee_uri()
    callee_extension = extract_extension_from_uri(callee_uri) if callee_uri else ""
    
    if callee_extension != extension:
        logger.warning("transcript_access_forbidden",
                      progress="audit",
                      call_id=call_id,
                      user_extension=extension,
                      actual_callee=callee_extension)
        raise HTTPException(status_code=403, detail="Access forbidden")
    
    # TODO: 실제 트랜스크립트 조회 (현재는 빈 데이터)
    logger.info("transcript_accessed",
               progress="audit",
               call_id=call_id,
               extension=extension)
    
    return {
        "call_id": call_id,
        "messages": [],
        "is_speaking": False,
        "current_state": "listening"
    }

