"""
Query Transformation 노드.

짧은 쿼리(<5단어) 또는 대명사 포함 시 LLM으로 구어체 -> 검색 쿼리 변환.
"""

import structlog
from src.ai_voicebot.langgraph.state import ConversationState

logger = structlog.get_logger(__name__)

# 대명사 및 모호 표현 패턴
AMBIGUOUS_PATTERNS = ["이거", "그거", "저거", "뭐", "아까", "그때", "거기"]

REWRITE_PROMPT = """다음 고객의 구어체 발화를 검색에 적합한 문장으로 변환하세요.

대화 기록:
{history}

현재 발화: "{query}"

변환 규칙:
1. 대명사를 구체적인 명사로 대체
2. 구어체를 문어체로 변환
3. 핵심 의도를 명확하게 표현
4. 한 문장으로만 출력

변환된 검색 쿼리:"""


async def rewrite_query_node(state: ConversationState) -> dict:
    """
    사용자 발화를 검색에 적합한 쿼리로 변환.
    
    필요 조건 (OR):
    - 5단어 미만의 짧은 쿼리
    - 대명사/모호 표현 포함
    
    불필요 시 원본 쿼리 그대로 사용.
    """
    import time
    node_start = time.time()

    query = state.get("user_query", "").strip()
    if not query:
        return {"rewritten_query": query}

    words = query.split()
    needs_rewrite = (
        len(words) < 5
        or any(p in query for p in AMBIGUOUS_PATTERNS)
    )

    if not needs_rewrite:
        logger.debug("query_rewrite_skipped", query=query[:60])
        return {"rewritten_query": query}

    llm = state.get("_llm_client")
    if not llm:
        return {"rewritten_query": query}

    try:
        # 최근 대화 3턴 포맷
        messages = state.get("messages", [])
        history = _format_recent(messages, max_turns=3)

        prompt = REWRITE_PROMPT.format(history=history, query=query)
        rewritten = await llm.generate_response(
            prompt, context_docs=[], system_prompt="쿼리 변환기"
        )
        rewritten = rewritten.strip().strip('"').strip("'")

        elapsed = time.time() - node_start
        if rewritten and len(rewritten) > 2:
            logger.info("⏱️ [TIMING] rewrite_query (LLM)",
                       original=query[:50], rewritten=rewritten[:50],
                       elapsed=f"{elapsed:.3f}s")
            return {"rewritten_query": rewritten}
    except Exception as e:
        logger.warning("query_rewrite_error", error=str(e))

    return {"rewritten_query": query}


def _format_recent(messages: list, max_turns: int = 3) -> str:
    recent = messages[-(max_turns * 2):]
    lines = []
    for msg in recent:
        role = "사용자" if msg.get("role") == "user" else "AI"
        lines.append(f"{role}: {msg.get('content', '')}")
    return "\n".join(lines) if lines else "(첫 대화)"
