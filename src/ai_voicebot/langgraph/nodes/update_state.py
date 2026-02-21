"""
Business State Update 노드.

대화 진행에 따른 비즈니스 상태 전이를 관리.
상태: initial → inquiry → resolution → closing

턴 카운트도 함께 업데이트.
"""

import structlog
from src.ai_voicebot.langgraph.state import ConversationState

logger = structlog.get_logger(__name__)

# 상태 전이 규칙
STATE_TRANSITIONS = {
    "initial": {
        "greeting": "initial",
        "question": "inquiry",
        "complaint": "inquiry",
        "transfer": "closing",
        "farewell": "closing",
        "unknown": "inquiry",
    },
    "inquiry": {
        "greeting": "inquiry",
        "question": "inquiry",
        "complaint": "inquiry",
        "transfer": "closing",
        "farewell": "closing",
        "unknown": "inquiry",
    },
    "resolution": {
        "greeting": "resolution",
        "question": "inquiry",    # 추가 질문 → 다시 inquiry
        "complaint": "inquiry",
        "transfer": "closing",
        "farewell": "closing",
        "unknown": "resolution",
    },
    "closing": {
        "greeting": "inquiry",    # 다시 대화 시작
        "question": "inquiry",
        "complaint": "inquiry",
        "transfer": "closing",
        "farewell": "closing",
        "unknown": "closing",
    },
}


async def update_state_node(state: ConversationState) -> dict:
    """
    비즈니스 상태 업데이트.
    
    1. intent + 현재 상태 → 다음 상태 결정
    2. confidence가 높으면 resolution 전이 검토
    3. 턴 카운트 증가
    """
    current = state.get("business_state", "initial")
    intent = state.get("intent", "unknown")
    confidence = state.get("confidence", 0.0)
    turn = state.get("turn_count", 0) + 1

    # 상태 전이
    transitions = STATE_TRANSITIONS.get(current, STATE_TRANSITIONS["initial"])
    next_state = transitions.get(intent, current)

    # 높은 confidence로 질문에 답했으면 → resolution
    if next_state == "inquiry" and confidence >= 0.8:
        next_state = "resolution"

    if next_state != current:
        logger.info("business_state_transition",
                   prev=current, next=next_state,
                   intent=intent, turn=turn)
    
    return {
        "business_state": next_state,
        "turn_count": turn,
    }
