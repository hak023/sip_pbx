"""
Greeting / Farewell 전용 캐시 검색 노드.

intent=greeting 또는 farewell 일 때 qa_cache를 intent로 필터해 검색.
히트 시 해당 인사/종료 문장으로 즉시 응답 (설계 CHROMADB_CATEGORY_DESIGN §4.2).
"""

import asyncio
import time
from datetime import datetime
from typing import Optional

import structlog
from src.ai_voicebot.langgraph.state import ConversationState
from src.common.call_data_record_logger import log_call_data

logger = structlog.get_logger(__name__)

CACHE_COLLECTION = "qa_cache"
SIMILARITY_THRESHOLD = 0.85  # 인사/종료는 문구가 비슷하면 히트
TTL_DAYS = 7
TTL_SECONDS = TTL_DAYS * 86400


def _is_expired(cached_at_str: str, ttl_seconds: int = TTL_SECONDS) -> bool:
    """ttl_seconds <= 0 이면 만료 없음(False)."""
    if ttl_seconds <= 0:
        return False
    try:
        cached_at = datetime.fromisoformat(cached_at_str)
        return (datetime.now() - cached_at).total_seconds() > ttl_seconds
    except Exception:
        return True


async def check_greeting_farewell_cache_node(state: ConversationState) -> dict:
    """
    intent=greeting 또는 farewell 일 때만 호출됨.
    qa_cache에서 해당 intent로 필터 검색 → 히트 시 response 반환, rag_cache_hit=True.
    """
    _start = time.time()
    intent = state.get("intent", "")
    if intent not in ("greeting", "farewell"):
        return {}

    query = state.get("user_query", "")
    vector_db = state.get("_vector_db")
    embedder = state.get("_embedder")
    if not vector_db or not embedder:
        return {}

    try:
        if hasattr(embedder, "embed_text"):
            fn = embedder.embed_text
            query_embedding = await fn(query) if asyncio.iscoroutinefunction(fn) else fn(query)
        elif hasattr(embedder, "embed"):
            query_embedding = await embedder.embed(query)
        else:
            return {}

        if not query_embedding:
            return {}

        results = await vector_db.search_collection(
            collection_name=CACHE_COLLECTION,
            vector=query_embedding,
            top_k=1,
            where={"intent": intent},
        )
        if not results:
            elapsed = time.time() - _start
            logger.info("timing_segment", segment="greeting_farewell_cache", elapsed_sec=round(elapsed, 3), hit=False)
            return {}

        top = results[0]
        score = top.get("score", 0.0)
        if score < SIMILARITY_THRESHOLD:
            elapsed = time.time() - _start
            logger.info("timing_segment", segment="greeting_farewell_cache", elapsed_sec=round(elapsed, 3), hit=False, score=round(score, 3))
            return {}

        metadata = top.get("metadata", {})
        cached_at = metadata.get("cached_at", "")
        ttl = metadata.get("ttl", TTL_SECONDS)
        if cached_at and _is_expired(cached_at, ttl):
            return {}

        cached_answer = metadata.get("answer", "")
        if not cached_answer or len(cached_answer.strip()) < 2:
            return {}

        elapsed = time.time() - _start
        call_id = state.get("_call_id") or ""
        logger.info("timing_segment", segment="greeting_farewell_cache", elapsed_sec=round(elapsed, 3), hit=True)
        logger.info("greeting_farewell_cache_hit", intent=intent, score=round(score, 3))
        log_call_data(
            call_id,
            "rag",
            "greeting_farewell_cache_hit",
            query=query,
            score=round(score, 3),
            elapsed_sec=round(elapsed, 3),
            intent=intent,
        )
        return {
            "rag_cache_hit": True,
            "response": cached_answer.strip(),
            "confidence": metadata.get("confidence", 0.9),
            "llm_rag_applied": [],
            "llm_rag_context_source": "greeting_farewell_cache",
            "greeting_farewell_cache_score": round(score, 3),
            "rag_search_trace": {},
        }
    except Exception as e:
        logger.warning("greeting_farewell_cache_error", error=str(e))
        return {}
