"""
Semantic Cache 노드.

유사한 질문이 이전에 응답된 적 있으면 캐시에서 즉시 응답.
유사도 0.95 이상, TTL 내에 있는 경우 캐시 히트.

컬렉션: qa_cache (ChromaDB)
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
SIMILARITY_THRESHOLD = 0.92  # 캐시 히트 임계치 (코사인 유사도)
TTL_FAQ_SECONDS = 86400   # question/greeting: 24h (필요 시 43200으로 단축)
TTL_OTHER_SECONDS = 3600  # 그 외: 1h
MIN_CONFIDENCE_TO_CACHE = 0.6  # 이 값 미만이면 캐시 저장 스킵 (선택 적용)


async def check_cache_node(state: ConversationState) -> dict:
    """
    Semantic Cache에서 유사 질문 검색.
    
    히트 시: rag_cache_hit=True, response 설정
    미스 시: rag_cache_hit=False
    """
    _start = time.time()
    query = state.get("user_query", "")
    vector_db = state.get("_vector_db")
    embedder = state.get("_embedder")

    if not vector_db or not embedder or not query:
        elapsed = time.time() - _start
        logger.info("timing_segment", segment="check_cache", elapsed_sec=round(elapsed, 3), skip="no_query_or_db")
        return {"rag_cache_hit": False}

    try:
        # 쿼리 임베딩 (TextEmbedder는 embed_text 사용 — embed 메서드 없음)
        if hasattr(embedder, "embed_text"):
            fn = embedder.embed_text
            query_embedding = await fn(query) if asyncio.iscoroutinefunction(fn) else fn(query)
        elif hasattr(embedder, "embed"):
            query_embedding = await embedder.embed(query)
        else:
            elapsed = time.time() - _start
            logger.warning("semantic_cache_no_embedder", elapsed_sec=round(elapsed, 3))
            return {"rag_cache_hit": False}

        # qa_cache 컬렉션에서 검색 (intent별 필터 — CHROMADB_CATEGORY_DESIGN §4.2)
        intent = state.get("intent", "")
        where_filter = {"intent": intent} if intent else None
        results = await vector_db.search_collection(
            collection_name=CACHE_COLLECTION,
            vector=query_embedding,
            top_k=1,
            where=where_filter,
        )

        if results and len(results) > 0:
            top = results[0]
            score = top.get("score", 0.0)

            if score >= SIMILARITY_THRESHOLD:
                metadata = top.get("metadata", {})
                # TTL 체크
                cached_at = metadata.get("cached_at", "")
                ttl = metadata.get("ttl", TTL_OTHER_SECONDS)
                if cached_at and not _is_expired(cached_at, ttl):
                    cached_answer = metadata.get("answer", "")
                    # 저장된 폴백 응답은 히트로 쓰지 않음 → RAG 경로로 진행
                    if cached_answer and _is_fallback_message(cached_answer):
                        logger.info("semantic_cache_skip_fallback_hit",
                                    query=query[:60], score=f"{score:.3f}")
                    elif cached_answer and _looks_complete_sentence(cached_answer):
                        elapsed = time.time() - _start
                        logger.info("timing_segment", segment="check_cache", elapsed_sec=round(elapsed, 3), hit=True)
                        logger.info("semantic_cache_hit",
                                   score=f"{score:.3f}",
                                   query=query[:60])
                        call_id = state.get("_call_id") or ""
                        log_call_data(
                            call_id,
                            "rag",
                            "semantic_cache_hit",
                            query=query[:300],
                            score=round(score, 3),
                            elapsed_sec=round(elapsed, 3),
                        )
                        return {
                            "rag_cache_hit": True,
                            "response": cached_answer,
                            "confidence": metadata.get("confidence", 0.9),
                        }
                    if cached_answer and not _looks_complete_sentence(cached_answer):
                        logger.info("semantic_cache_skip_truncated",
                                    query=query[:60], answer_preview=cached_answer[-30:])

        elapsed = time.time() - _start
        logger.info("timing_segment", segment="check_cache", elapsed_sec=round(elapsed, 3), hit=False)
        logger.debug("semantic_cache_miss", query=query[:60])
        call_id = state.get("_call_id") or ""
        log_call_data(
            call_id,
            "rag",
            "semantic_cache_miss",
            query=query[:300],
            elapsed_sec=round(elapsed, 3),
        )
        return {"rag_cache_hit": False}

    except Exception as e:
        elapsed = time.time() - _start
        logger.info("timing_segment", segment="check_cache", elapsed_sec=round(elapsed, 3), error=str(e))
        logger.warning("semantic_cache_check_error", error=str(e))
        return {"rag_cache_hit": False}


async def update_cache_node(state: ConversationState) -> dict:
    """
    새 응답을 Semantic Cache에 저장.
    캐시 히트였으면 업데이트 불필요.
    """
    _start = time.time()
    if state.get("rag_cache_hit"):
        elapsed = time.time() - _start
        logger.info("timing_segment", segment="update_cache", elapsed_sec=round(elapsed, 3), skip="cache_hit")
        return {}

    query = state.get("rewritten_query") or state.get("user_query", "")
    response = state.get("response", "")
    vector_db = state.get("_vector_db")
    embedder = state.get("_embedder")

    if not vector_db or not embedder or not query or not response:
        elapsed = time.time() - _start
        logger.info("timing_segment", segment="update_cache", elapsed_sec=round(elapsed, 3), skip="no_input")
        return {}
    if not _looks_complete_sentence(response) or _is_error_message(response):
        elapsed = time.time() - _start
        logger.info("timing_segment", segment="update_cache", elapsed_sec=round(elapsed, 3), skip="truncated_or_error")
        logger.debug("semantic_cache_skip_save",
                     reason="truncated_or_error", response_preview=response[:80])
        return {}
    # RAG 0건일 때의 폴백 응답은 캐시에 넣지 않음 (지식 추가 후에도 캐시로 잘못 나오는 것 방지)
    if _is_fallback_message(response):
        elapsed = time.time() - _start
        logger.info("timing_segment", segment="update_cache", elapsed_sec=round(elapsed, 3), skip="fallback_response")
        logger.debug("semantic_cache_skip_save", reason="fallback_response", response_preview=response[:80])
        return {}
    # question 의도인데 RAG 결과 0건이면 저장하지 않음
    intent = state.get("intent", "question")
    rag_results = state.get("rag_results") or []
    if intent == "question" and len(rag_results) == 0:
        elapsed = time.time() - _start
        logger.info("timing_segment", segment="update_cache", elapsed_sec=round(elapsed, 3), skip="rag_zero_no_store")
        logger.debug("semantic_cache_skip_save", reason="rag_zero_no_store", intent=intent, rag_count=0)
        return {}
    # confidence가 state에 설정된 경우에만 하한 적용 (미설정 시에는 저장 허용)
    conf = state.get("confidence")
    if conf is not None and conf < MIN_CONFIDENCE_TO_CACHE:
        elapsed = time.time() - _start
        logger.info("timing_segment", segment="update_cache", elapsed_sec=round(elapsed, 3), skip="low_confidence")
        logger.debug("semantic_cache_skip_save", reason="low_confidence", confidence=conf)
        return {}

    try:
        is_faq = intent in ("question", "greeting")
        ttl = TTL_FAQ_SECONDS if is_faq else TTL_OTHER_SECONDS

        # 쿼리 임베딩 (TextEmbedder는 embed_text 사용 — embed 메서드 없음)
        if hasattr(embedder, "embed_text"):
            fn = embedder.embed_text
            query_embedding = await fn(query) if asyncio.iscoroutinefunction(fn) else fn(query)
        elif hasattr(embedder, "embed"):
            query_embedding = await embedder.embed(query)
        else:
            logger.warning("semantic_cache_update_no_embedder")
            return {}

        # intent → category (캐시 메타데이터, 설계 §2.2)
        intent_to_category = {
            "greeting": "greeting_phase2",
            "farewell": "farewell",
            "question": "question",
            "complaint": "complaint",
            "transfer": "transfer",
        }
        category = intent_to_category.get(intent, intent if intent else "question")
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
                "category": category,
                "cached_at": datetime.now().isoformat(),
                "ttl": ttl,
            },
        )
        elapsed = time.time() - _start
        logger.info("timing_segment", segment="update_cache", elapsed_sec=round(elapsed, 3))
        logger.info("semantic_cache_updated", query=query[:60], ttl=ttl)
    except Exception as e:
        elapsed = time.time() - _start
        logger.info("timing_segment", segment="update_cache", elapsed_sec=round(elapsed, 3), error=str(e))
        logger.warning("semantic_cache_update_error", error=str(e))

    return {}


def _is_expired(cached_at_str: str, ttl_seconds: int) -> bool:
    """캐시 만료 여부 확인. ttl_seconds <= 0 이면 만료 없음(False)."""
    if ttl_seconds <= 0:
        return False
    try:
        cached_at = datetime.fromisoformat(cached_at_str)
        elapsed = (datetime.now() - cached_at).total_seconds()
        return elapsed > ttl_seconds
    except Exception:
        return True


def _looks_complete_sentence(text: str) -> bool:
    """문장이 완결된 형태로 끝나는지 (캐시 저장/히트 시 절단 응답 제외용)."""
    if not text or len(text) < 10:
        return False
    t = text.strip()
    # 마침표, 물음표, 느낌표로 끝나면 완결로 간주
    if t.endswith(".") or t.endswith("?") or t.endswith("!"):
        return True
    # 한국어 조사로 끝나면 불완전 가능성 (예: "어떤 지역의")
    if len(t) <= 50 and (t.endswith("의") or t.endswith("를") or t.endswith("을")):
        return False
    # 길이가 충분하고 마지막이 한글 완결형이면 허용 (예: "드릴게요")
    if len(t) >= 30:
        return True
    return False


def _is_error_message(text: str) -> bool:
    """오류 메시지 여부 (캐시에 저장하면 안 됨)."""
    if not text or len(text) > 200:
        return False
    t = text.strip()
    return "오류가 발생했습니다" in t or "답변을 생성하는 중 오류" in t


def _is_fallback_message(text: str) -> bool:
    """RAG 0건 등으로 인한 폴백 응답 여부. 캐시 저장/히트 모두 제외 대상."""
    if not text or len(text) > 300:
        return False
    t = text.strip()
    return (
        "해당 내용은 확인이 필요합니다" in t
        or "잠시만 기다려 주세요" in t
        or ("알지 못하는 내용" in t and "죄송" in t)
    )
