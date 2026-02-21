"""
의도 분류 노드.

사용자 발화에서 의도(intent)를 분류한다.
가능한 의도: greeting, question, complaint, transfer, farewell, unknown
"""

import structlog
from src.ai_voicebot.langgraph.state import ConversationState

logger = structlog.get_logger(__name__)

# 키워드 기반 빠른 분류 (LLM 호출 없이)
INTENT_KEYWORDS = {
    "greeting": ["안녕", "여보세요", "반갑", "처음"],
    "farewell": ["감사합니다", "고마워", "끊을게", "그만", "종료", "바이바이"],
    "complaint": ["불만", "화나", "짜증", "항의", "문제가", "왜 이래"],
    "transfer": ["사람", "담당자", "직원", "연결해", "상담원", "전화 돌려"],
}

# 인사말과 함께 나올 수 있는 질문/요청 패턴. 이 패턴이 있으면 greeting보다 question 우선.
QUESTION_PATTERNS = [
    "어떻게", "문의", "알려", "되나요", "인가요", "뭐", "무엇", "있어요",
    "해요", "해주", "하고 싶", "알고 싶", "궁금", "주차", "예약", "영업",
    "시간", "가격", "비용", "위치", "연락처", "예약", "취소",
]


async def classify_intent_node(state: ConversationState) -> dict:
    """
    사용자 발화의 의도를 분류.
    
    1차: 키워드 기반 빠른 매칭 (<1ms)
    2차: 인사+질문 동시 존재 시 question 우선 (짧은 인사만 greeting)
    3차: LLM 기반 분류 (키워드 매칭 실패 시)
    """
    import time
    node_start = time.time()
    
    query = state.get("user_query", "").strip()
    if not query:
        return {"intent": "unknown", "slots": {}}

    query_lower = query.lower()

    # 1차: 키워드 기반 빠른 분류
    for intent, keywords in INTENT_KEYWORDS.items():
        if any(kw in query_lower for kw in keywords):
            # 인사(greeting)인데 질문/요청 패턴도 있으면 → question으로 처리 (RAG 경로 타서 본문 답변)
            if intent == "greeting" and any(p in query_lower for p in QUESTION_PATTERNS):
                elapsed = time.time() - node_start
                logger.info("⏱️ [TIMING] classify_intent (keyword, greeting+question→question)",
                           intent="question", query=query[:60], elapsed=f"{elapsed:.3f}s")
                return {"intent": "question", "slots": {}}
            elapsed = time.time() - node_start
            logger.info("⏱️ [TIMING] classify_intent (keyword)",
                       intent=intent, query=query[:60], elapsed=f"{elapsed:.3f}s")
            return {"intent": intent, "slots": {}}

    # 2차: 짧은 발화는 question으로 간주
    llm = state.get("_llm_client")
    if not llm:
        return {"intent": "question", "slots": {}}

    # 3차: LLM 기반 분류 (복잡한 발화)
    try:
        classify_prompt = (
            "다음 고객 발화의 의도를 분류하세요.\n"
            "가능한 의도: greeting, question, complaint, transfer, farewell\n"
            f'고객: "{query}"\n'
            "의도 (한 단어만):"
        )
        result = await llm.generate_response(
            classify_prompt, context_docs=[], system_prompt="의도 분류기"
        )
        intent = result.strip().lower().replace('"', '').replace("'", "")
        
        valid_intents = {"greeting", "question", "complaint", "transfer", "farewell"}
        if intent not in valid_intents:
            intent = "question"  # 기본값

        elapsed = time.time() - node_start
        logger.info("⏱️ [TIMING] classify_intent (LLM)",
                   intent=intent, query=query[:60], elapsed=f"{elapsed:.3f}s")
        return {"intent": intent, "slots": {}}
    except Exception as e:
        logger.warning("intent_classification_error", error=str(e))
        return {"intent": "question", "slots": {}}
