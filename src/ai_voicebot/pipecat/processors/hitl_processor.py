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

    escalation_mode 분기:
      - "hitl"     : 기존 동작 — 운영자 대시보드 알림 + HITL_REQUEST_MESSAGE TTS
      - "transfer" : 상담원 내선 SIP 호전환 트리거 + TRANSFER_REQUEST_MESSAGE TTS
      - "none"     : LangGraph hitl_alert에서 AI 판정 HITL 억제(명시적 상담원 요청은 유지)
    """
    
    # HITL 시 고객 TTS용 (generate_response.HITL_CUSTOMER_TTS_MESSAGE 와 동일하게 유지)
    HITL_REQUEST_MESSAGE = (
        "죄송합니다. 해당 내용은 제가 알지 못하는 내용입니다. "
        "다른 도움이 필요하시면 말씀해 주세요."
    )

    # 상담원 연결 모드 TTS
    TRANSFER_REQUEST_MESSAGE = (
        "잠시만요. 담당 상담원에게 연결해 드리겠습니다. "
        "잠시 기다려 주세요."
    )
    
    def __init__(
        self,
        on_transfer_request: Optional[Callable] = None,
        on_alert: Optional[Callable] = None,
    ):
        """
        Args:
            on_transfer_request: 통화 전환 요청 콜백 (call_id, reason, extension?)
            on_alert: 운영자 알림 콜백 (alert_data 또는 call_id, alert_data)
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
        needs_transfer: bool = False,
        transfer_extension: Optional[str] = None,
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
            needs_transfer: True면 HITL 대신 SIP 호전환 트리거 (escalation_mode=transfer)
            transfer_extension: 호전환 대상 내선번호
            
        Returns:
            안내 메시지 (사용자에게 TTS로 전달) 또는 None
        """
        if not needs_human:
            return None
        
        self.stats["total_alerts"] += 1
        self._last_alert_time = time.time()
        
        # 알림 분류
        if intent == "transfer" or needs_transfer:
            self.stats["transfer_requests"] += 1
            alert_type = "transfer_request"
        elif intent == "complaint":
            self.stats["complaint_alerts"] += 1
            alert_type = "complaint"
        else:
            self.stats["low_confidence_alerts"] += 1
            alert_type = "low_confidence"
        
        logger.warning(
            "hitl_alert_processing",
            call=True,
            call_id=call_id,
            alert_type=alert_type,
            intent=intent,
            confidence=f"{confidence:.3f}",
            reason=hitl_reason,
            needs_transfer=needs_transfer,
            transfer_extension=transfer_extension,
        )
        
        # ── 에스컬레이션 모드 분기 ──────────────────────────────────────────
        if needs_transfer:
            # Transfer 모드: HITL 알림 없이 SIP 호전환 바로 트리거
            self._pending_transfer = True
            ext = transfer_extension or ""
            logger.warning(
                "hitl_escalation_transfer_mode",
                call_id=call_id,
                transfer_extension=ext,
                note="escalation_mode=transfer → SIP 호전환 트리거 (HITL 알림 스킵)",
            )
            if self._on_transfer_request:
                try:
                    if asyncio.iscoroutinefunction(self._on_transfer_request):
                        await self._on_transfer_request(call_id, hitl_reason, ext)
                    else:
                        self._on_transfer_request(call_id, hitl_reason, ext)
                except TypeError:
                    # 기존 (call_id, reason) 2-arg 시그니처 폴백
                    try:
                        if asyncio.iscoroutinefunction(self._on_transfer_request):
                            await self._on_transfer_request(call_id, hitl_reason)
                        else:
                            self._on_transfer_request(call_id, hitl_reason)
                    except Exception as e:
                        logger.error("hitl_transfer_callback_error", error=str(e))
                except Exception as e:
                    logger.error("hitl_transfer_callback_error", error=str(e))
            return self.TRANSFER_REQUEST_MESSAGE

        # ── HITL 모드 (기존 동작) ───────────────────────────────────────────
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
                # 콜백 시그니처: (context) — context에 call_id, alert_type 등 포함. 호출측 _default_hitl_alert(context) 호환.
                if asyncio.iscoroutinefunction(self._on_alert):
                    await self._on_alert(alert_data)
                else:
                    self._on_alert(alert_data)
            except TypeError:
                # (call_id, context) 시그니처 폴백
                try:
                    if asyncio.iscoroutinefunction(self._on_alert):
                        await self._on_alert(call_id, alert_data)
                    else:
                        self._on_alert(call_id, alert_data)
                except Exception as e:
                    logger.error("hitl_alert_callback_error", error=str(e))
            except Exception as e:
                logger.error("hitl_alert_callback_error", error=str(e))
        
        # 고객이 직접 상담원 연결 요청(intent=transfer)이면 호전환 콜백 실행 (착신 규칙으로 채운 내선 우선)
        if intent == "transfer":
            self._pending_transfer = True
            ext = (transfer_extension or "").strip()
            if self._on_transfer_request:
                try:
                    if asyncio.iscoroutinefunction(self._on_transfer_request):
                        await self._on_transfer_request(call_id, hitl_reason, ext)
                    else:
                        self._on_transfer_request(call_id, hitl_reason, ext)
                except TypeError:
                    try:
                        if asyncio.iscoroutinefunction(self._on_transfer_request):
                            await self._on_transfer_request(call_id, hitl_reason)
                        else:
                            self._on_transfer_request(call_id, hitl_reason)
                    except Exception as e:
                        logger.error("hitl_transfer_callback_error", error=str(e))
                except Exception as e:
                    logger.error("hitl_transfer_callback_error", error=str(e))
            if not ext:
                logger.warning(
                    "hitl_intent_transfer_no_extension",
                    call_id=call_id,
                    note="착신 규칙에서 전환 내선을 못 찾음 — 콜백만 시도",
                )
        
        # HITL 지연 응답 설계: intent 무관하게 통일된 메시지 반환
        return self.HITL_REQUEST_MESSAGE
    
    @property
    def pending_transfer(self) -> bool:
        return self._pending_transfer
    
    def reset(self):
        """상태 초기화"""
        self._pending_transfer = False
        self._last_alert_time = None
    
    def get_stats(self) -> dict:
        return dict(self.stats)
