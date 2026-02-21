"""
Step-back Prompting 노드.

RAG 결과가 부족(confidence < 0.4)하면 상위 개념 질문을 생성하여 재검색.
"상품 A의 할인율은?" → "상품 A의 가격 정책은?"
"""

import structlog
from src.ai_voicebot.langgraph.state import ConversationState

logger = structlog.get_logger(__name__)

CONFIDENCE_THRESHOLD = 0.4  # 이 이하면 Step-back 실행

STEP_BACK_PROMPT = """다음 질문에 대해 지식 베이스에 직접적인 답이 없을 수 있습니다.
이 질문의 상위 개념이나 일반적인 원칙에 대한 질문으로 바꿔주세요.

원본 질문: "{query}"

규칙:
1. 구체적 수치 → 해당 항목의 기본 정책
2. 특정 시점 → 일반적인 운영 시간/기간
3. 개별 사례 → 일반 원칙

상위 개념 질문 (한 문장):"""


async def step_back_node(state: ConversationState) -> dict:
    """
    Step-back Prompting.
    
    confidence가 낮으면:
    1. 상위 개념 질문 생성
    2. 그 질문으로 RAG 재검색
    3. 기존 결과와 병합
    """
    import time
    node_start = time.time()

    confidence = state.get("confidence", 0.0)
    if confidence >= CONFIDENCE_THRESHOLD:
        return {}  # 충분한 결과 → 스킵

    query = state.get("rewritten_query") or state.get("user_query", "")
    llm = state.get("_llm_client")
    rag_engine = state.get("_rag_engine")
    owner = state.get("_owner")  # 착신번호 기반 테넌트 격리

    if not llm or not rag_engine or not query:
        return {}

    try:
        # 1. 상위 개념 질문 생성
        llm_start = time.time()
        prompt = STEP_BACK_PROMPT.format(query=query)
        step_back_query = await llm.generate_response(
            prompt, context_docs=[], system_prompt="Step-back 변환기"
        )
        step_back_query = step_back_query.strip().strip('"').strip("'")
        llm_elapsed = time.time() - llm_start

        if not step_back_query or step_back_query == query:
            return {}

        logger.info("step_back_query_generated",
                   call=True,
                   original=query[:50], step_back=step_back_query[:50],
                   llm_elapsed=f"{llm_elapsed:.3f}s")

        # 2. 상위 개념 질문으로 RAG 재검색
        rag_start = time.time()
        step_back_results = await rag_engine.search(step_back_query, owner_filter=owner)
        rag_elapsed = time.time() - rag_start

        if not step_back_results:
            return {}

        # 3. 기존 결과와 병합
        existing = state.get("rag_results", [])
        merged = list(existing)
        seen_texts = {doc.get("text", "")[:100] for doc in existing}

        for doc in step_back_results:
            text = doc.text if hasattr(doc, "text") else doc.get("text", "")
            if text[:100] not in seen_texts:
                merged.append({
                    "text": text,
                    "score": doc.score if hasattr(doc, "score") else doc.get("score", 0),
                    "metadata": doc.metadata if hasattr(doc, "metadata") else doc.get("metadata", {}),
                    "source": "step_back",
                })
                seen_texts.add(text[:100])

        # confidence 재계산 (보너스 +0.15)
        new_confidence = min(1.0, confidence + 0.15)

        total_elapsed = time.time() - node_start
        logger.info("⏱️ [TIMING] step_back 완료",
                   new_results=len(merged) - len(existing),
                   new_confidence=f"{new_confidence:.3f}",
                   llm_elapsed=f"{llm_elapsed:.3f}s",
                   rag_elapsed=f"{rag_elapsed:.3f}s",
                   total_elapsed=f"{total_elapsed:.3f}s")

        return {
            "rag_results": merged,
            "confidence": new_confidence,
        }

    except Exception as e:
        logger.warning("step_back_error", error=str(e))
        return {}
