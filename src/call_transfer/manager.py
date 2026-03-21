"""
Call Transfer Manager Interface

TransferManager를 활용한 AI 동적 호 전환
"""

import logging
from typing import Optional
from src.common.logger import get_async_logger

logger = get_async_logger(__name__)

# Global TransferManager 인스턴스 (SIPEndpoint에서 설정)
_transfer_manager = None


def set_transfer_manager(transfer_manager):
    """
    TransferManager 인스턴스 설정
    
    SIPEndpoint 초기화 시 호출됨
    
    Args:
        transfer_manager: TransferManager 인스턴스
    """
    global _transfer_manager
    _transfer_manager = transfer_manager
    logger.info("transfer_manager_set", has_manager=_transfer_manager is not None)


async def initiate_call_transfer(
    call_id: str,
    target_number: str,
    department: Optional[str] = None,
    phone_display: Optional[str] = None,
    user_request_text: str = ""
) -> bool:
    """
    호 전환 시작 (AI 동적 호 전환)
    
    Args:
        call_id: 현재 통화 ID
        target_number: 전환할 대상 전화번호 (예: "1005")
        department: 부서명 (예: "기상청 담당부서")
        phone_display: 표시 번호 (선택, 기본값은 target_number)
        user_request_text: 사용자 요청 텍스트
    
    Returns:
        호 전환 시작 성공 여부
    
    Process:
        1. TransferManager에 호 전환 요청
        2. 안내 멘트 TTS 재생
        3. INVITE 메시지 전송
        4. 200 OK 대기
        5. AI Pipeline 종료
        6. RTP Relay BRIDGE 모드로 전환
    """
    if not _transfer_manager:
        logger.error("call_transfer_manager_not_available",
                    call_id=call_id,
                    note="TransferManager not set. Call set_transfer_manager() first.")
        return False
    
    try:
        logger.info("ai_call_transfer_initiated",
                   call_id=call_id,
                   target=target_number,
                   department=department,
                   note="AI 동적 호 전환 시작")
        
        # TransferManager를 통한 호 전환
        transfer_record = await _transfer_manager.initiate_transfer(
            call_id=call_id,
            transfer_to=target_number,  # SIP URI 또는 내선번호
            department_name=department or "담당 부서",
            phone_display=phone_display or target_number,
            user_request_text=user_request_text,
            caller_uri="",  # TransferManager 내부에서 찾음
            caller_display="",
        )
        
        if transfer_record:
            logger.info("ai_call_transfer_record_created",
                       call_id=call_id,
                       transfer_id=transfer_record.transfer_id,
                       target=target_number)
            return True
        else:
            logger.warning("ai_call_transfer_record_failed",
                          call_id=call_id,
                          target=target_number,
                          note="이미 활성 전환이 있거나 실패")
            return False
    
    except Exception as e:
        logger.error("ai_call_transfer_error",
                    call_id=call_id,
                    target=target_number,
                    error=str(e),
                    exc_info=True)
        return False


async def manual_transfer_from_operator(
    *,
    call_id: str,
    operator_id: str,
    operator_number: str,
) -> bool:
    """
    대시보드(WebSocket `manual_transfer_request`)에서 상담원이 활성 통화를
    본인 내선(`operator_number`, 예: 1004)으로 SIP 전환할 때 호출.

    내부적으로 `initiate_call_transfer`와 동일 경로(TransferManager)를 사용한다.
    """
    logger.info(
        "manual_transfer_from_operator",
        call_id=call_id,
        operator_id=operator_id,
        operator_number=operator_number,
    )
    return await initiate_call_transfer(
        call_id=call_id,
        target_number=operator_number.strip(),
        department=None,
        phone_display=operator_number.strip(),
        user_request_text="dashboard_manual_transfer",
    )


async def cancel_call_transfer(call_id: str, reason: str = "user_cancelled") -> bool:
    """
    호 전환 취소
    
    Args:
        call_id: 통화 ID
        reason: 취소 사유
    
    Returns:
        취소 성공 여부
    """
    if not _transfer_manager:
        logger.error("call_transfer_manager_not_available", call_id=call_id)
        return False
    
    try:
        await _transfer_manager.cancel_transfer(call_id, reason)
        logger.info("call_transfer_cancelled",
                   call_id=call_id,
                   reason=reason)
        return True
    except Exception as e:
        logger.error("call_transfer_cancel_error",
                    call_id=call_id,
                    error=str(e))
        return False


async def get_transfer_status(call_id: str) -> Optional[dict]:
    """
    호 전환 상태 조회
    
    Args:
        call_id: 통화 ID
    
    Returns:
        {
            "transfer_id": str,
            "state": str,  # "ANNOUNCE", "RINGING", "CONNECTED", "FAILED", etc.
            "department_name": str,
            "transfer_to": str,
            "phone_display": str,
            "created_at": str,
            "connected_at": str or None,
        }
    """
    if not _transfer_manager:
        logger.debug("call_transfer_manager_not_available", call_id=call_id)
        return None
    
    try:
        transfer_record = _transfer_manager.get_active_transfer(call_id)
        if transfer_record:
            return transfer_record.to_dict()
        return None
    except Exception as e:
        logger.error("get_transfer_status_error",
                    call_id=call_id,
                    error=str(e))
        return None


def is_transfer_active(call_id: str) -> bool:
    """
    호 전환이 활성 상태인지 확인
    
    Args:
        call_id: 통화 ID
    
    Returns:
        bool: 활성 전환이 있으면 True
    """
    if not _transfer_manager:
        return False
    
    return _transfer_manager.is_transfer_active(call_id)


def get_transfer_stats() -> dict:
    """
    전체 호 전환 통계 조회
    
    Returns:
        {
            "total_transfers": int,
            "success_rate": float,
            "avg_ring_duration_seconds": float,
            "active_count": int,
        }
    """
    if not _transfer_manager:
        return {
            "total_transfers": 0,
            "success_rate": 0.0,
            "avg_ring_duration_seconds": 0,
            "active_count": 0,
        }
    
    return _transfer_manager.get_stats()
