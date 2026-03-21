"""
Business State Update 노드.

대화 진행에 따른 비즈니스 상태 전이를 관리.
상태: initial → inquiry → resolution → closing

턴 카운트도 함께 업데이트.
"""

import time
import structlog
from src.ai_voicebot.langgraph.state import ConversationState

logger = structlog.get_logger(__name__)

# 상태 전이 규칙. 설계: AI_RESPONSE_HUMANLIKE_DESIGN.md §6
# 정책: AI는 통화를 끊지 않음. farewell(끝인사)를 해도 closing으로 가지 않고 inquiry 유지 → 대화 이어가기 가능.
STATE_TRANSITIONS = {
    "initial": {
        "greeting": "initial",
        "question": "inquiry",
        "complaint": "inquiry",
        "transfer": "closing",
        "farewell": "inquiry",  # closing 아님: 끝인사 후에도 대화 이어갈 수 있도록
        "unknown": "inquiry",
        # B/C/E 그룹
        "affirm": "initial",
        "deny": "initial",
        "gratitude": "initial",
        "doubt": "initial",
        "positive_reaction": "initial",
        "negative_reaction": "initial",
        "chitchat": "inquiry",
        "repeat": "initial",
        "clarification": "initial",
        "help": "initial",
        "out_of_scope": "inquiry",
        "nlu_fallback": "inquiry",
    },
    "inquiry": {
        "greeting": "inquiry",
        "question": "inquiry",
        "complaint": "inquiry",
        "transfer": "closing",
        "farewell": "inquiry",  # AI는 통화 종료하지 않음
        "unknown": "inquiry",
        "affirm": "inquiry",
        "deny": "inquiry",
        "gratitude": "inquiry",
        "doubt": "inquiry",
        "positive_reaction": "inquiry",
        "negative_reaction": "inquiry",
        "chitchat": "inquiry",
        "repeat": "inquiry",
        "clarification": "inquiry",
        "help": "inquiry",
        "out_of_scope": "inquiry",
        "nlu_fallback": "inquiry",
    },
    "resolution": {
        "greeting": "resolution",
        "question": "inquiry",
        "complaint": "inquiry",
        "transfer": "closing",
        "farewell": "resolution",  # 끝인사 후에도 대화 이어가기 가능
        "unknown": "resolution",
        "affirm": "resolution",
        "deny": "resolution",
        "gratitude": "resolution",
        "doubt": "resolution",
        "positive_reaction": "resolution",
        "negative_reaction": "resolution",
        "chitchat": "inquiry",
        "repeat": "resolution",
        "clarification": "resolution",
        "help": "resolution",
        "out_of_scope": "inquiry",
        "nlu_fallback": "resolution",
    },
    "closing": {
        "greeting": "inquiry",
        "question": "inquiry",
        "complaint": "inquiry",
        "transfer": "closing",
        "farewell": "closing",
        "unknown": "closing",
        "affirm": "closing",
        "deny": "closing",
        "gratitude": "closing",
        "doubt": "closing",
        "positive_reaction": "closing",
        "negative_reaction": "closing",
        "chitchat": "closing",
        "repeat": "closing",
        "clarification": "closing",
        "help": "closing",
        "out_of_scope": "closing",
        "nlu_fallback": "closing",
    },
}


# farewell 시 사용할 기본 마무리 멘트 (org_manager·DB에 없을 때)
DEFAULT_CLOSING_MESSAGE = "감사합니다. 필요하시면 다시 연락 주세요."


async def update_state_node(state: ConversationState) -> dict:
    """
    비즈니스 상태 업데이트.

    1. intent + 현재 상태 → 다음 상태 결정
    2. confidence가 높으면 resolution 전이 검토
    3. 턴 카운트 증가
    4. farewell 시 마무리 멘트를 state.response에 설정 (DB closing_templates 또는 기본값)
    """
    _start = time.time()
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

    out: dict = {
        "business_state": next_state,
        "turn_count": turn,
    }

    # HITL: template/fallback 등에서 설정한 needs_human·hitl_reason 유지 (설계 §5.3, §8)
    if state.get("needs_human") is not None:
        out["needs_human"] = state["needs_human"]
    if state.get("hitl_reason") is not None:
        out["hitl_reason"] = state.get("hitl_reason", "")

    # farewell(감사합니다, 끊을게 등) 시 마무리 멘트를 TTS로 재생하도록 response 설정
    if intent == "farewell":
        closing = DEFAULT_CLOSING_MESSAGE
        org_manager = state.get("_org_manager")
        if org_manager and hasattr(org_manager, "get_random_closing_template"):
            try:
                closing = org_manager.get_random_closing_template() or closing
            except Exception:
                pass
        out["response"] = closing
        logger.info("farewell_closing_message_set",
                    intent=intent,
                    response_preview=closing[:50] if closing else "")

    elapsed = time.time() - _start
    logger.info("timing_segment", segment="update_state", elapsed_sec=round(elapsed, 3))
    return out
