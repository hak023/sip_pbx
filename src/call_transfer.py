"""
호 전환 모듈

B2BUA를 통한 SIP 호 전환 실행

B2BUA 아키텍처에서는:
1. 현재 통화: 발신자 ↔ B2BUA ↔ AI Voicebot
2. 호 전환 시:
   - B2BUA가 AI Voicebot 쪽 레그를 BYE로 종료
   - B2BUA가 대상 번호로 새 INVITE 발신
   - 발신자 ↔ B2BUA ↔ 대상 번호로 재연결

REFER 메서드는 사용하지 않음 (B2BUA 방식)
"""

import structlog
from typing import Optional

logger = structlog.get_logger(__name__)


async def initiate_call_transfer(
    call_id: str,
    target_number: str,
    department: str = "",
    phone_display: Optional[str] = None,
    user_request_text: Optional[str] = None
) -> bool:
    """
    B2BUA 호 전환 실행
    
    Args:
        call_id: 통화 ID
        target_number: 대상 전화번호 (예: "010-1234-5678")
        department: 부서명 (예: "영업팀")
        phone_display: 표시용 전화번호 (선택)
        user_request_text: 사용자 요청 원문 (선택, 로깅용)
    
    Returns:
        True: 호 전환 성공 또는 시작됨
        False: 호 전환 실패
    
    B2BUA 동작 흐름:
        1. CallManager에서 통화 세션 조회
        2. AI Voicebot 레그 종료 (BYE)
        3. 대상 번호로 새 INVITE 발신
        4. 발신자와 대상 연결
        5. WebSocket 이벤트 발송
    """
    logger.info("call_transfer_request",
               call_id=call_id,
               target=target_number,
               department=department,
               user_request=user_request_text[:100] if user_request_text else None)
    
    try:
        # 1. CallManager 가져오기
        from src.websocket.server import _call_manager
        
        if not _call_manager:
            logger.error("call_transfer_no_manager",
                        call_id=call_id,
                        note="CallManager가 websocket.server에 주입되지 않음")
            return False
        
        # 2. TransferManager 가져오기
        transfer_manager = getattr(_call_manager, 'transfer_manager', None)
        
        if not transfer_manager:
            logger.error("call_transfer_no_transfer_manager",
                        call_id=call_id,
                        note="CallManager에 transfer_manager 속성 없음")
            
            # TransferManager가 없어도 일단 WebSocket 이벤트는 발송
            try:
                from src.websocket import manager as ws_manager
                await ws_manager.emit_transfer_failed(
                    call_id=call_id,
                    target_number=target_number,
                    reason="transfer_manager_not_configured"
                )
            except Exception:
                pass
            
            return False
        
        # 3. 호 전환 실행
        logger.info("call_transfer_executing",
                   call_id=call_id,
                   target=target_number)
        
        # TransferManager의 initiate_transfer 메서드 호출
        if hasattr(transfer_manager, 'initiate_transfer'):
            success = await transfer_manager.initiate_transfer(
                call_id=call_id,
                target_number=target_number,
                department=department
            )
        elif hasattr(transfer_manager, 'transfer_call'):
            # 대안 메서드명
            success = await transfer_manager.transfer_call(
                call_id=call_id,
                target=target_number,
                context={"department": department}
            )
        else:
            logger.error("call_transfer_no_method",
                        call_id=call_id,
                        available_methods=[m for m in dir(transfer_manager) if not m.startswith('_')])
            success = False
        
        # 4. 결과 처리 및 WebSocket 이벤트
        if success:
            logger.info("call_transfer_success",
                       call_id=call_id,
                       target=target_number,
                       department=department)
            
            # WebSocket: 호 전환 성공 이벤트
            try:
                from src.websocket import manager as ws_manager
                await ws_manager.emit_transfer_success(
                    call_id=call_id,
                    target_number=target_number,
                    department=department
                )
            except Exception as e:
                logger.warning("transfer_success_event_failed",
                              call_id=call_id,
                              error=str(e))
        else:
            logger.warning("call_transfer_failed",
                          call_id=call_id,
                          target=target_number,
                          note="TransferManager가 False 반환")
            
            # WebSocket: 호 전환 실패 이벤트
            try:
                from src.websocket import manager as ws_manager
                await ws_manager.emit_transfer_failed(
                    call_id=call_id,
                    target_number=target_number,
                    reason="transfer_manager_rejected"
                )
            except Exception as e:
                logger.warning("transfer_failed_event_failed",
                              call_id=call_id,
                              error=str(e))
        
        return success
        
    except Exception as e:
        logger.error("call_transfer_error",
                    call_id=call_id,
                    target=target_number,
                    error=str(e),
                    exc_info=True)
        
        # WebSocket: 호 전환 오류 이벤트
        try:
            from src.websocket import manager as ws_manager
            await ws_manager.emit_transfer_failed(
                call_id=call_id,
                target_number=target_number,
                reason=f"exception: {str(e)}"
            )
        except Exception:
            pass
        
        return False


async def manual_transfer_from_operator(
    call_id: str,
    operator_id: str,
    operator_number: str
) -> bool:
    """
    상담원 수동 호 전환
    
    Frontend에서 상담원이 "내게 전환" 버튼을 눌렀을 때 호출
    
    Args:
        call_id: 통화 ID
        operator_id: 상담원 ID
        operator_number: 상담원 전화번호
    
    Returns:
        True: 호 전환 성공
        False: 호 전환 실패
    """
    logger.info("manual_transfer_request",
               call_id=call_id,
               operator_id=operator_id,
               operator_number_masked=operator_number[:8] + "***" if len(operator_number) > 8 else "***")
    
    return await initiate_call_transfer(
        call_id=call_id,
        target_number=operator_number,
        department=f"상담원 {operator_id}",
        user_request_text="수동 전환 (상담원 요청)"
    )


def validate_phone_number(phone_number: str) -> bool:
    """
    전화번호 유효성 검증
    
    Args:
        phone_number: 전화번호 문자열
    
    Returns:
        True: 유효한 형식
        False: 유효하지 않음
    
    Note:
        기본적인 형식만 검증 (숫자, 하이픈, +기호 포함 여부)
    """
    if not phone_number:
        return False
    
    # 허용 문자: 숫자, 하이픈, 괄호, +, 공백
    import re
    pattern = r'^[\d\-\(\)\+\s]+$'
    
    if not re.match(pattern, phone_number):
        return False
    
    # 숫자만 추출해서 길이 확인 (최소 8자, 최대 15자)
    digits_only = re.sub(r'\D', '', phone_number)
    
    if len(digits_only) < 8 or len(digits_only) > 15:
        return False
    
    return True
