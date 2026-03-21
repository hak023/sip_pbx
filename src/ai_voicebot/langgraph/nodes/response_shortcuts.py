"""
단축 응답 노드 (캐시/RAG/LLM 스킵).

설계: docs/design/AI_RESPONSE_HUMANLIKE_DESIGN.md §4
- template_response: B 그룹 반응/피드백 (affirm, deny, gratitude 등)
- repeat_response: 다시 말해줘
- clarification_response: 무슨 뜻이에요
- help_response: 뭘 할 수 있어요 (capability 안내)
- fallback_response: out_of_scope, nlu_fallback (고정 멘트, 선택적 HITL)
"""

import random
import structlog
from src.ai_voicebot.langgraph.state import ConversationState

logger = structlog.get_logger(__name__)

# 설계 §4.1 그룹 B 템플릿 (intent별 랜덤 1문장)
INTENT_RESPONSE_TEMPLATES = {
    "affirm": [
        "네, 알겠습니다. 더 필요하시면 말씀해 주세요.",
        "좋습니다. 다른 궁금한 점 있으시면 말씀해 주세요.",
    ],
    "deny": [
        "알겠습니다. 다른 건 도와드릴까요?",
        "네, 그럼 필요하실 때 말씀해 주세요.",
    ],
    "gratitude": [
        "천만에요. 더 필요하시면 말씀해 주세요.",
        "도움이 되었다니 다행이에요. 좋은 하루 되세요.",
    ],
    "doubt": [
        "괜찮아요. 정하시면 말씀해 주세요.",
        "네, 필요하실 때 다시 말씀해 주세요.",
    ],
    "positive_reaction": [
        "감사합니다. 더 궁금하신 점 있으시면 편하게 말씀해 주세요.",
        "도움이 되셨다니 좋겠어요. 다른 문의 있으시면 말씀해 주세요.",
    ],
    "negative_reaction": [
        "불편을 드려 죄송합니다. 다른 방법으로 안내해 드릴까요?",
        "그렇군요. 담당자 연결이 필요하시면 말씀해 주세요.",
    ],
}

# repeat/clarification 기본 문장
DEFAULT_REPEAT_MESSAGE = "방금 말씀드린 내용을 다시 안내드릴게요."
DEFAULT_CLARIFICATION_MESSAGE = "어떤 점이 궁금하신지 조금만 더 말씀해 주시면 안내해 드릴게요."
DEFAULT_HELP_MESSAGE = "어떤 내용이 궁금하신지 말씀해 주시면 안내해 드릴게요."
# HITL 요청 시 발신자에게 먼저 재생 (이후 관리자에게 HITL 요청)
DEFAULT_FALLBACK_MESSAGE = "확인해보겠습니다. 잠시만 기다려 주세요."

# 관리자 미응답 시 발신자에게 재생 후, 긍정(affirm) 시 frontend에 fallback 가능 표시 (설계 §5.5)
HITL_FALLBACK_OFFER_MESSAGE = "해당 내용 확인 후 별도 연락을 드릴까요?"

# fallback 시 HITL 사용 여부 (설정으로 오버라이드 가능)
FALLBACK_NEEDS_HITL_DEFAULT = True
FALLBACK_HITL_REASON = "의도 분류 불명 또는 업무 범위 외 발화. 확인이 필요합니다."


def _last_assistant_content(messages: list) -> str:
    """messages에서 마지막 assistant 발화 content 반환. 없으면 빈 문자열."""
    if not messages:
        return ""
    for m in reversed(messages):
        if m.get("role") == "assistant":
            return m.get("content", "") or ""
    return ""


async def template_response_node(state: ConversationState) -> dict:
    """
    B 그룹 반응/피드백: intent별 공용 템플릿(INTENT_RESPONSE_TEMPLATES)에서 랜덤 1문장 선택.
    설계 §4.1, §8.2. (테넌트별 오버라이드 §8.1은 미구현.)
    """
    intent = state.get("intent", "question")
    templates = INTENT_RESPONSE_TEMPLATES.get(intent)
    if not templates:
        response = "더 필요하시면 말씀해 주세요."
    else:
        response = random.choice(templates)
    return {
        "response": response,
        "response_chunks": [response],
        "confidence": 0.9,
    }


async def repeat_response_node(state: ConversationState) -> dict:
    """
    다시 말해줘: 마지막 assistant 발화를 그대로 반환. 없으면 기본 문장.
    설계 §4.2
    """
    messages = state.get("messages", [])
    last = _last_assistant_content(messages)
    if last:
        response = last
    else:
        response = DEFAULT_REPEAT_MESSAGE
    return {
        "response": response,
        "response_chunks": [response],
        "confidence": 0.9,
    }


async def clarification_response_node(state: ConversationState) -> dict:
    """
    무슨 뜻이에요: 직전 assistant 발화 요약 + 명확화 문장. 없으면 기본 문장.
    설계 §4.2 (요약은 단순화로 직전 발화 앞부분 재사용)
    """
    messages = state.get("messages", [])
    last = _last_assistant_content(messages)
    if last:
        preview = last[:80] + "..." if len(last) > 80 else last
        response = f"제가 {preview} 말씀드렸는데, 더 알고 싶으신 게 있으신가요?"
    else:
        response = DEFAULT_CLARIFICATION_MESSAGE
    return {
        "response": response,
        "response_chunks": [response],
        "confidence": 0.9,
    }


async def help_response_node(state: ConversationState) -> dict:
    """
    도와줘/뭘 할 수 있어요: org_manager.get_capabilities() 기반 안내 문장.
    설계 §4.2. 캐시가 비어 있으면 load_capabilities()로 로드 시도.
    """
    org_manager = state.get("_org_manager")
    if org_manager and hasattr(org_manager, "get_capabilities"):
        if hasattr(org_manager, "load_capabilities"):
            try:
                await org_manager.load_capabilities()
            except Exception:
                pass
        caps = org_manager.get_capabilities()
        if caps:
            cap_text = ", ".join(caps[:7])
            response = f"저는 {cap_text} 안내를 드릴 수 있어요. 무엇이 궁금하신가요?"
        else:
            response = DEFAULT_HELP_MESSAGE
    else:
        response = DEFAULT_HELP_MESSAGE
    return {
        "response": response,
        "response_chunks": [response],
        "confidence": 0.9,
    }


async def fallback_response_node(state: ConversationState) -> dict:
    """
    out_of_scope / nlu_fallback: 고정 멘트 + 설정에 따라 needs_human 설정.
    설계 §4.4, §5.3
    """
    response = DEFAULT_FALLBACK_MESSAGE
    needs_human = FALLBACK_NEEDS_HITL_DEFAULT
    hitl_reason = FALLBACK_HITL_REASON if needs_human else ""
    return {
        "response": response,
        "response_chunks": [response],
        "confidence": 0.0,
        "needs_human": needs_human,
        "hitl_reason": hitl_reason,
    }
