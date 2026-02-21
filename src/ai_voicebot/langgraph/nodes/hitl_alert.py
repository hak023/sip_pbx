"""
HITL (Human-In-The-Loop) Alert 노드.

일정 조건(confidence 낮음, complaint 의도, 명시적 요청) 충족 시
운영자 개입이 필요함을 표시한다.
"""

import structlog
from src.ai_voicebot.langgraph.state import ConversationState

logger = structlog.get_logger(__name__)

HITL_CONFIDENCE_THRESHOLD = 0.3
MAX_LOW_CONFIDENCE_TURNS = 2  # 연속 낮은 신뢰도 N회 시 HITL


async def hitl_alert_node(state: ConversationState) -> dict:
    """
    운영자 개입 판단.
    
    조건:
    1. intent == "transfer" (고객이 직접 요청)
    2. intent == "complaint" + confidence < 0.5
    3. confidence < 0.3 (정보 부족)
    """
    intent = state.get("intent", "")
    confidence = state.get("confidence", 1.0)
    needs_human = False
    reason = ""

    # 1. 직접 요청
    if intent == "transfer":
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
                      reason=reason)
    else:
        logger.debug("hitl_not_needed",
                    intent=intent,
                    confidence=f"{confidence:.3f}")

    return {
        "needs_human": needs_human,
        "hitl_reason": reason,
    }
