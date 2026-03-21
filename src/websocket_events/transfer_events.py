"""
WebSocket Manager for AI Dynamic Call Transfer

호 전환 관련 WebSocket 이벤트 발송 (실제 구현 완료)
"""

import logging
from typing import Optional
from src.common.logger import get_async_logger

logger = get_async_logger(__name__)


async def emit_transfer_initiated(
    call_id: str,
    target_number: str,
    department: Optional[str] = None
):
    """
    호 전환 시작 이벤트 발송
    
    Args:
        call_id: 통화 ID
        target_number: 대상 전화번호
        department: 부서명
    
    Frontend에서 수신하여 실시간 통화 화면에 "호 전환 중..." 표시
    """
    try:
        from src.websocket import manager
        await manager.emit_transfer_initiated(
            call_id=call_id,
            target_number=target_number,
            department=department
        )
        logger.info("ws_transfer_initiated_emitted",
                   call_id=call_id,
                   target=target_number,
                   department=department)
    except Exception as e:
        logger.warning("ws_transfer_initiated_emit_failed",
                      call_id=call_id,
                      error=str(e))


async def emit_transfer_ringing(call_id: str, target_number: str):
    """
    호 전환 대상이 응답 중 (180 Ringing) 이벤트
    
    Args:
        call_id: 통화 ID
        target_number: 대상 전화번호
    """
    try:
        from src.websocket import manager
        await manager.emit_transfer_ringing(
            call_id=call_id,
            target_number=target_number
        )
        logger.info("ws_transfer_ringing_emitted",
                   call_id=call_id,
                   target=target_number)
    except Exception as e:
        logger.warning("ws_transfer_ringing_emit_failed",
                      call_id=call_id,
                      error=str(e))


async def emit_transfer_success(
    call_id: str,
    target_number: str,
    department: Optional[str] = None
):
    """
    호 전환 성공 이벤트 발송
    
    Args:
        call_id: 통화 ID
        target_number: 대상 전화번호
        department: 부서명
    
    Frontend에서 수신하여:
    - "호 전환 완료" 표시
    - AI 응대 화면 → 일반 통화 화면으로 전환
    """
    try:
        from src.websocket import manager
        await manager.emit_transfer_success(
            call_id=call_id,
            target_number=target_number,
            department=department
        )
        logger.info("ws_transfer_success_emitted",
                   call_id=call_id,
                   target=target_number,
                   department=department)
    except Exception as e:
        logger.warning("ws_transfer_success_emit_failed",
                      call_id=call_id,
                      error=str(e))


async def emit_transfer_failed(
    call_id: str,
    target_number: str,
    reason: str = "unknown"
):
    """
    호 전환 실패 이벤트 발송
    
    Args:
        call_id: 통화 ID
        target_number: 대상 전화번호
        reason: 실패 사유
    
    Frontend에서 수신하여 "호 전환 실패" 알림
    """
    try:
        from src.websocket import manager
        await manager.emit_transfer_failed(
            call_id=call_id,
            target_number=target_number,
            reason=reason
        )
        logger.warning("ws_transfer_failed_emitted",
                      call_id=call_id,
                      target=target_number,
                      reason=reason)
    except Exception as e:
        logger.error("ws_transfer_failed_emit_failed",
                    call_id=call_id,
                    error=str(e))

