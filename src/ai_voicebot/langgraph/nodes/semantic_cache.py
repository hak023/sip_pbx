"""
Semantic Cache 노드.

유사한 질문이 이전에 응답된 적 있으면 캐시에서 즉시 응답.
유사도 0.95 이상, TTL 내에 있는 경우 캐시 히트.

컬렉션: qa_cache (ChromaDB)
"""

import time
from datetime import datetime
from typing import Optional

import structlog
from src.ai_voicebot.langgraph.state import ConversationState

logger = structlog.get_logger(__name__)

CACHE_COLLECTION = "qa_cache"
SIMILARITY_THRESHOLD = 0.92  # 캐시 히트 임계치 (코사인 유사도)


async def check_cache_node(state: ConversationState) -> dict:
    """
    Semantic Cache에서 유사 질문 검색.
    
    히트 시: rag_cache_hit=True, response 설정
    미스 시: rag_cache_hit=False
    """
    query = state.get("user_query", "")
    vector_db = state.get("_vector_db")
    embedder = state.get("_embedder")

    if not vector_db or not embedder or not query:
        return {"rag_cache_hit": False}

    try:
        # 쿼리 임베딩
        query_embedding = await embedder.embed(query)

        # qa_cache 컬렉션에서 검색
        results = await vector_db.search_collection(
            collection_name=CACHE_COLLECTION,
            vector=query_embedding,
            top_k=1,
        )

        if results and len(results) > 0:
            top = results[0]
            score = top.get("score", 0.0)

            if score >= SIMILARITY_THRESHOLD:
                metadata = top.get("metadata", {})
                # TTL 체크
                cached_at = metadata.get("cached_at", "")
                ttl = metadata.get("ttl", 3600)
                if cached_at and not _is_expired(cached_at, ttl):
                    cached_answer = metadata.get("answer", "")
                    if cached_answer:
                        logger.info("semantic_cache_hit",
                                   score=f"{score:.3f}",
                                   query=query[:60])
                        return {
                            "rag_cache_hit": True,
                            "response": cached_answer,
                            "confidence": metadata.get("confidence", 0.9),
                        }

        logger.debug("semantic_cache_miss", query=query[:60])
        return {"rag_cache_hit": False}

    except Exception as e:
        logger.warning("semantic_cache_check_error", error=str(e))
        return {"rag_cache_hit": False}


async def update_cache_node(state: ConversationState) -> dict:
    """
    새 응답을 Semantic Cache에 저장.
    캐시 히트였으면 업데이트 불필요.
    """
    if state.get("rag_cache_hit"):
        return {}

    query = state.get("rewritten_query") or state.get("user_query", "")
    response = state.get("response", "")
    vector_db = state.get("_vector_db")
    embedder = state.get("_embedder")

    if not vector_db or not embedder or not query or not response:
        return {}

    try:
        intent = state.get("intent", "question")
        is_faq = intent in ("question", "greeting")
        ttl = 86400 if is_faq else 3600  # FAQ: 24h, 동적: 1h

        query_embedding = await embedder.embed(query)

        doc_id = f"cache_{hash(query) % 10**10}"
        await vector_db.upsert_to_collection(
            collection_name=CACHE_COLLECTION,
            doc_id=doc_id,
            embedding=query_embedding,
            text=query,
            metadata={
                "answer": response,
                "confidence": state.get("confidence", 0.7),
                "intent": intent,
                "cached_at": datetime.now().isoformat(),
                "ttl": ttl,
            },
        )
        logger.info("semantic_cache_updated", query=query[:60], ttl=ttl)
    except Exception as e:
        logger.warning("semantic_cache_update_error", error=str(e))

    return {}


def _is_expired(cached_at_str: str, ttl_seconds: int) -> bool:
    """캐시 만료 여부 확인"""
    try:
        cached_at = datetime.fromisoformat(cached_at_str)
        elapsed = (datetime.now() - cached_at).total_seconds()
        return elapsed > ttl_seconds
    except Exception:
        return True
