"""
HITL 에스컬레이션 억제 규칙.

LangGraph `hitl_alert`·`generate_response`에서 공통으로 사용한다.
설계: docs/reports/2026-03/2026-03-28_2015_HITL_PRE_ROUTER_DUAL_THRESHOLD_DESIGN.md
"""

from typing import Any, Mapping

SOCIAL_OR_LIGHT_INTENTS = frozenset(
    {
        "chitchat",
        "out_of_scope",
        "greeting",
        "farewell",
    }
)


def is_social_direct_path(state: Mapping[str, Any]) -> bool:
    """RAG 스킵·일상 직행 레인."""
    return bool(
        state.get("utterance_lane") == "social_direct"
        or state.get("rag_mode") == "skip"
    )


def suppress_hitl_low_confidence(state: Mapping[str, Any]) -> bool:
    """저신뢰도만으로는 HITL 하지 않음 (잡담·소셜 경로)."""
    if is_social_direct_path(state):
        return True
    intent = state.get("intent") or ""
    if intent in SOCIAL_OR_LIGHT_INTENTS:
        return True
    return False


def suppress_hitl_needs_followup(state: Mapping[str, Any]) -> bool:
    """
    needs_follow_up=True여도 운영자 큐(HITL)로 보내지 않음.

    - 소셜 직행·잡담 계열
    - 업무 신호 없는 question (가벼운 질문으로 보이는 경우)
    complaint·transfer 등은 억제하지 않는다.
    """
    if suppress_hitl_low_confidence(state):
        return True
    intent = state.get("intent") or ""
    if intent == "question" and not state.get("domain_question_signal", False):
        return True
    return False
