"""
발화 레인 라우팅 (검색 전).

chitchat·out_of_scope → RAG 생략·generate_response 직행.
question → domain_question_signal 산출 (HITL 억제 여부 결정).
"""

import time
from typing import Mapping, Any

import structlog

from src.ai_voicebot.ai_pipeline.query_hints import should_treat_as_question_not_transfer
from src.ai_voicebot.langgraph.nodes.classify_intent import QUESTION_PATTERNS
from src.ai_voicebot.langgraph.state import ConversationState

logger = structlog.get_logger(__name__)


def compute_domain_question_signal(
    intent: str, query: str, org_context: str,
    state: "Mapping[str, Any] | None" = None,
) -> bool:
    """
    업무·지식 답변이 기대되는 question 여부.

    True:  도메인 질문 → HITL 억제 없음 (RAG miss 시 HITL 발동)
    False: 비도메인·가벼운 question → RAG miss여도 HITL 억제

    판단 우선순위:
    1. classify_intent에서 페르소나 scope_keywords 매칭 (_persona_scope_matched)
       → 페르소나 업무 범위 내 질문임이 이미 확인됨 → True
    2. should_treat_as_question_not_transfer 패턴
    3. 범용 QUESTION_PATTERNS 키워드
    4. org_context 기관명·식별 토큰 포함 여부
    """
    if intent != "question":
        return False
    q = (query or "").strip().lower()
    if not q:
        return False

    # 1. 페르소나 scope_keywords 매칭 결과 재사용 (classify_intent에서 이미 판단)
    #    → 추가 DB 조회 없이 O(1) 판단
    if state and state.get("_persona_scope_matched"):
        return True

    if should_treat_as_question_not_transfer(query):
        return True
    if any(p in q for p in QUESTION_PATTERNS):
        return True
    # org_context에서 기관명·식별 토큰이 발화에 포함되면 도메인 질의로 간주
    for raw_line in (org_context or "").split("\n"):
        line = raw_line.strip()
        if not line or ":" not in line:
            continue
        _label, value = line.split(":", 1)
        token = value.strip().lower()
        if len(token) >= 2 and token in q:
            return True
    return False


async def route_utterance_node(state: ConversationState) -> dict:
    """
    classify_intent 직후 호출.

    출력:
      - utterance_lane, rag_mode, domain_question_signal
      - 매 턴 rag_results·rag_cache_hit 초기화 (이전 턴 잔존 방지)
    """
    _start = time.perf_counter()
    intent = state.get("intent") or "nlu_fallback"
    query = (state.get("user_query") or "").strip()
    org_context = state.get("org_context") or ""

    base_clear = {
        "rag_results": [],
        "rag_cache_hit": False,
    }

    # 예약 의도 → booking_agent 직행 (RAG/캐시 불필요)
    if intent == "booking":
        elapsed = time.perf_counter() - _start
        logger.info(
            "route_utterance_booking_direct",
            intent=intent,
            utterance_lane="booking",
            elapsed_sec=round(elapsed, 4),
            note="예약 의도 → booking_agent 직행 (RAG 스킵)",
        )
        return {
            **base_clear,
            "utterance_lane": "booking",
            "rag_mode": "skip",
            "domain_question_signal": False,
            "confidence": 0.95,
            "rewritten_query": query,
        }

    if intent in ("chitchat", "out_of_scope"):
        elapsed = time.perf_counter() - _start
        logger.info(
            "route_utterance_social_direct",
            intent=intent,
            utterance_lane="social_direct",
            elapsed_sec=round(elapsed, 4),
        )
        return {
            **base_clear,
            "utterance_lane": "social_direct",
            "rag_mode": "skip",
            "domain_question_signal": False,
            "confidence": 0.85,
            "rewritten_query": query,
        }

    # 아웃바운드 모드: affirm/deny/doubt/gratitude 는 RAG 불필요
    # 착신자의 짧은 응답(예, 아니요, 감사 등)을 LLM으로 자연스럽게 처리
    _outbound_purpose = state.get("outbound_purpose", "") if hasattr(state, "get") else ""
    if _outbound_purpose and intent in ("affirm", "deny", "doubt", "gratitude",
                                        "positive_reaction", "negative_reaction"):
        elapsed = time.perf_counter() - _start
        logger.info(
            "route_utterance_outbound_answer_direct",
            intent=intent,
            utterance_lane="social_direct",
            outbound_purpose_preview=_outbound_purpose[:40],
            elapsed_sec=round(elapsed, 4),
            note="아웃바운드 모드: 착신자 답변 의도 → RAG 스킵, LLM 직행",
        )
        return {
            **base_clear,
            "utterance_lane": "social_direct",
            "rag_mode": "skip",
            "domain_question_signal": False,
            "confidence": 0.9,
            "rewritten_query": query,
        }

    domain = compute_domain_question_signal(intent, query, org_context, state=state)
    elapsed = time.perf_counter() - _start
    logger.info(
        "route_utterance_knowledge",
        intent=intent,
        utterance_lane="knowledge",
        domain_question_signal=domain,
        persona_scope_matched=bool(state.get("_persona_scope_matched")),
        elapsed_sec=round(elapsed, 4),
    )
    return {
        **base_clear,
        "utterance_lane": "knowledge",
        "rag_mode": "full",
        "domain_question_signal": domain,
    }
