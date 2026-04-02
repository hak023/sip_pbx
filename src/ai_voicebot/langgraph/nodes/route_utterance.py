"""
발화 레인 라우팅 (검색 전).

chitchat·out_of_scope → RAG 생략·generate_response 직행.
question → domain_question_signal 산출 (step_back·HITL 임계치용).
"""

import time

import structlog

from src.ai_voicebot.ai_pipeline.query_hints import should_treat_as_question_not_transfer
from src.ai_voicebot.langgraph.nodes.classify_intent import QUESTION_PATTERNS
from src.ai_voicebot.langgraph.state import ConversationState

logger = structlog.get_logger(__name__)

# adaptive_rag → step_back 분기: 도메인 질의는 기존에 가깝게, 비도메인 question은 완화
STEP_BACK_THRESHOLD_DOMAIN_QUESTION = 0.40
STEP_BACK_THRESHOLD_LIGHT_QUESTION = 0.22


def compute_domain_question_signal(
    intent: str, query: str, org_context: str
) -> bool:
    """
    업무·지식 답변이 기대되는 question 여부.

    True: 엄격한 RAG/step_back·HITL 신뢰도 구간 적용.
    False: 가벼운 question — step_back·저신뢰 HITL 완화.
    """
    if intent != "question":
        return False
    q = (query or "").strip().lower()
    if not q:
        return False
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

    domain = compute_domain_question_signal(intent, query, org_context)
    elapsed = time.perf_counter() - _start
    logger.info(
        "route_utterance_knowledge",
        intent=intent,
        utterance_lane="knowledge",
        domain_question_signal=domain,
        elapsed_sec=round(elapsed, 4),
    )
    return {
        **base_clear,
        "utterance_lane": "knowledge",
        "rag_mode": "full",
        "domain_question_signal": domain,
    }
