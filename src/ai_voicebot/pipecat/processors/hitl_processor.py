"""
HITL (Human-In-The-Loop) Processor for Pipecat Pipeline (Phase 3).

LangGraph Agent가 needs_human=True를 반환하면:
1. 사용자에게 "담당자에게 연결해 드리겠습니다" 안내
2. 운영자 알림 전송 (로그 + 향후 웹소켓/API 확장)
3. 통화 전환 준비

Pipeline 위치: RAG-LLM 내부에서 호출 (별도 프로세서가 아닌 콜백 패턴)
"""

import asyncio
import time
from typing import Optional, Callable

import structlog

logger = structlog.get_logger(__name__)


class HITLManager:
    """
    HITL (Human-In-The-Loop) 관리자.
    
    LangGraph Agent의 hitl_alert 결과를 처리한다.
    Pipecat 파이프라인 외부에서 동작하며, RAGLLMProcessor가 호출한다.
    """
    
    def __init__(
        self,
        on_transfer_request: Optional[Callable] = None,
        on_alert: Optional[Callable] = None,
    ):
        """
        Args:
            on_transfer_request: 통화 전환 요청 콜백 (call_id, reason)
            on_alert: 운영자 알림 콜백 (call_id, alert_data)
        """
        self._on_transfer_request = on_transfer_request
        self._on_alert = on_alert
        
        # 통계
        self.stats = {
            "total_alerts": 0,
            "transfer_requests": 0,
            "complaint_alerts": 0,
            "low_confidence_alerts": 0,
        }
        
        # 상태
        self._pending_transfer = False
        self._last_alert_time: Optional[float] = None
    
    async def handle_hitl_result(
        self,
        call_id: str,
        needs_human: bool,
        hitl_reason: str = "",
        intent: str = "",
        confidence: float = 0.0,
        user_text: str = "",
    ) -> Optional[str]:
        """
        HITL 결과 처리.
        
        Args:
            call_id: 통화 ID
            needs_human: 운영자 개입 필요 여부
            hitl_reason: HITL 사유
            intent: 사용자 의도
            confidence: 응답 신뢰도
            user_text: 발신자 질문 (운영자 알림/request_human_help용)
            
        Returns:
            안내 메시지 (사용자에게 TTS로 전달) 또는 None
        """
        if not needs_human:
            return None
        
        self.stats["total_alerts"] += 1
        self._last_alert_time = time.time()
        
        # 알림 분류
        if intent == "transfer":
            self.stats["transfer_requests"] += 1
            alert_type = "transfer_request"
        elif intent == "complaint":
            self.stats["complaint_alerts"] += 1
            alert_type = "complaint"
        else:
            self.stats["low_confidence_alerts"] += 1
            alert_type = "low_confidence"
        
        logger.warning("hitl_alert_processing",
                      call=True,
                      call_id=call_id,
                      alert_type=alert_type,
                      intent=intent,
                      confidence=f"{confidence:.3f}",
                      reason=hitl_reason)
        
        # 운영자 알림 전송 (question 포함 시 HITLService.request_human_help에서 사용)
        alert_data = {
            "call_id": call_id,
            "alert_type": alert_type,
            "intent": intent,
            "confidence": confidence,
            "reason": hitl_reason,
            "timestamp": time.time(),
            "question": user_text,
        }
        
        if self._on_alert:
            try:
                if asyncio.iscoroutinefunction(self._on_alert):
                    await self._on_alert(call_id, alert_data)
                else:
                    self._on_alert(call_id, alert_data)
            except Exception as e:
                logger.error("hitl_alert_callback_error", error=str(e))
        
        # 통화 전환 요청
        if intent == "transfer":
            self._pending_transfer = True
            if self._on_transfer_request:
                try:
                    if asyncio.iscoroutinefunction(self._on_transfer_request):
                        await self._on_transfer_request(call_id, hitl_reason)
                    else:
                        self._on_transfer_request(call_id, hitl_reason)
                except Exception as e:
                    logger.error("hitl_transfer_callback_error", error=str(e))
            
            return "담당자에게 연결해 드리겠습니다. 잠시만 기다려 주세요."
        
        elif intent == "complaint":
            return ("불편을 드려 죄송합니다. "
                    "더 정확한 안내를 위해 담당자를 연결해 드릴까요?")
        
        else:
            # 낮은 신뢰도 / RAG 부족 (설계: 해당 내용 확인 필요, 잠시만 기다려 달라)
            return "해당 내용은 확인이 필요합니다. 잠시만 기다려 주세요."
    
    @property
    def pending_transfer(self) -> bool:
        return self._pending_transfer
    
    def reset(self):
        """상태 초기화"""
        self._pending_transfer = False
        self._last_alert_time = None
    
    def get_stats(self) -> dict:
        return dict(self.stats)
