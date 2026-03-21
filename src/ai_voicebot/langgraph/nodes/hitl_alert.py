"""
HITL (Human-In-The-Loop) Alert 노드.

일정 조건(confidence 낮음, complaint 의도, 명시적 요청) 충족 시
운영자 개입이 필요함을 표시한다.
"""

import time
import structlog
from src.ai_voicebot.langgraph.state import ConversationState

logger = structlog.get_logger(__name__)

HITL_CONFIDENCE_THRESHOLD = 0.3
MAX_LOW_CONFIDENCE_TURNS = 2  # 연속 낮은 신뢰도 N회 시 HITL


async def hitl_alert_node(state: ConversationState) -> dict:
    """
    운영자 개입 판단.
    
    조건 (설계: TTS_RTP_AND_HITL_DESIGN.md — 모르는 내용 → "잠시만 기다려 주세요" + HITL):
    1. needs_follow_up == True (AI가 모르는 내용으로 응답한 경우)
    2. intent == "transfer" (고객이 직접 요청)
    3. intent == "complaint" + confidence < 0.5
    4. confidence < 0.3 (정보 부족)
    """
    _start = time.time()
    intent = state.get("intent", "")
    confidence = state.get("confidence", 1.0)
    needs_follow_up = state.get("needs_follow_up", False)
    needs_human = False
    reason = ""

    # 0. 모르는 내용 응답 시 → HITL로 담당자 문의 (설계 2.1·2.2)
    if needs_follow_up:
        needs_human = True
        reason = "AI가 모르는 내용으로 응답했습니다. 확인이 필요합니다."

    # 1. 직접 요청
    elif intent == "transfer":
        needs_human = True
        reason = "고객이 상담원 연결을 요청했습니다."

    # 2. 불만 + 낮은 신뢰도
    elif intent == "complaint" and confidence < 0.5:
        needs_human = True
        reason = f"고객 불만 상태이며 답변 신뢰도가 낮습니다 (confidence={confidence:.2f})."

    # 3. 극도로 낮은 신뢰도
    elif confidence < HITL_CONFIDENCE_THRESHOLD:
        needs_human = True
        reason = f"답변 신뢰도가 매우 낮습니다 (confidence={confidence:.2f}). 적절한 정보를 찾지 못했습니다."

    if needs_human:
        logger.warning("hitl_alert_triggered",
                      call=True,
                      intent=intent,
                      confidence=f"{confidence:.3f}",
                      needs_follow_up=needs_follow_up,
                      reason=reason)
    else:
        logger.debug("hitl_not_needed",
                    intent=intent,
                    confidence=f"{confidence:.3f}")

    elapsed = time.time() - _start
    logger.info("timing_segment", segment="hitl_alert", elapsed_sec=round(elapsed, 3), needs_human=needs_human)
    return {
        "needs_human": needs_human,
        "hitl_reason": reason,
    }
