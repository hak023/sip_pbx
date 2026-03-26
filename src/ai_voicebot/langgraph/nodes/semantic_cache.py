"""
Semantic Cache 노드.

유사한 질문이 이전에 응답된 적 있으면 캐시에서 즉시 응답.
유사도 임계치(SIMILARITY_THRESHOLD) 이상, TTL 내, 저장 답변이 폴백/절단이 아닐 때 히트.

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
SEMANTIC_CACHE_TOP_K = 1


def _semantic_cache_criteria_ref(intent_filter: Optional[dict]) -> dict:
    """semantic_cache_miss / 히트 판정 시 로그에 넣는 기준 스냅샷."""
    return {
        "collection": CACHE_COLLECTION,
        "top_k": SEMANTIC_CACHE_TOP_K,
        "similarity_threshold": SIMILARITY_THRESHOLD,
        "intent_where_filter": intent_filter,
        "ttl_default_seconds_faq": TTL_FAQ_SECONDS,
        "ttl_default_seconds_other": TTL_OTHER_SECONDS,
        "hit_rules": [
            "top_1_score >= similarity_threshold",
            "metadata.cached_at 존재하고 TTL 미만료(metadata.ttl, 기본 TTL_OTHER_SECONDS)",
            "answer 비어 있지 않음",
            "answer가 폴백 멘트(_is_fallback_message) 아님",
            "answer가 완결 문장(_looks_complete_sentence)",
        ],
    }


def _cache_entry_age_seconds(cached_at_str: str) -> Optional[float]:
    if not cached_at_str:
        return None
    try:
        cached_at = datetime.fromisoformat(cached_at_str)
        return (datetime.now() - cached_at).total_seconds()
    except Exception:
        return None


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
    intent = state.get("intent", "")
    where_filter: Optional[dict] = {"intent": intent} if intent else None
    criteria = _semantic_cache_criteria_ref(where_filter)
    call_id = state.get("_call_id") or ""

    def _log_miss(
        *,
        miss_reason: str,
        miss_detail: Optional[dict] = None,
        top_candidate: Optional[dict] = None,
    ) -> dict:
        elapsed = time.time() - _start
        logger.info(
            "timing_segment",
            segment="check_cache",
            elapsed_sec=round(elapsed, 3),
            hit=False,
            miss_reason=miss_reason,
        )
        logger.info(
            "semantic_cache_miss",
            miss_reason=miss_reason,
            query_preview=query or "",
            intent=intent or "",
        )
        log_call_data(
            call_id,
            "rag",
            "semantic_cache_miss",
            query=query,
            query_full=query,
            query_len=len(query or ""),
            intent=intent,
            elapsed_sec=round(elapsed, 3),
            miss_reason=miss_reason,
            miss_detail=miss_detail or {},
            criteria=criteria,
            top_candidate=top_candidate,
        )
        return {"rag_cache_hit": False}

    if not vector_db or not embedder or not query:
        elapsed = time.time() - _start
        logger.info("timing_segment", segment="check_cache", elapsed_sec=round(elapsed, 3), skip="no_query_or_db")
        return _log_miss(
            miss_reason="skipped_no_vector_db_embedder_or_empty_query",
            miss_detail={
                "has_vector_db": bool(vector_db),
                "has_embedder": bool(embedder),
                "query_empty": not (query or "").strip(),
            },
        )

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
            return _log_miss(
                miss_reason="skipped_embedder_has_no_embed_method",
                miss_detail={"embedder_type": type(embedder).__name__},
            )

        if not query_embedding:
            return _log_miss(
                miss_reason="empty_query_embedding",
                miss_detail={"embedder_type": type(embedder).__name__},
            )

        # qa_cache 컬렉션에서 검색 (intent별 필터 — CHROMADB_CATEGORY_DESIGN §4.2)
        results = await vector_db.search_collection(
            collection_name=CACHE_COLLECTION,
            vector=query_embedding,
            top_k=SEMANTIC_CACHE_TOP_K,
            where=where_filter,
        )

        if not results:
            return _log_miss(
                miss_reason="no_search_results",
                miss_detail={"raw_result_count": 0},
            )

        top = results[0]
        try:
            score = float(top.get("score", 0.0))
        except (TypeError, ValueError):
            score = 0.0

        raw_meta = top.get("metadata")
        metadata = raw_meta if isinstance(raw_meta, dict) else {}
        cached_at = metadata.get("cached_at", "") or ""
        ttl = metadata.get("ttl", TTL_OTHER_SECONDS)
        try:
            ttl = int(ttl) if ttl is not None else TTL_OTHER_SECONDS
        except (TypeError, ValueError):
            ttl = TTL_OTHER_SECONDS
        cached_answer = metadata.get("answer", "") or ""

        top_candidate = {
            "score": round(score, 4),
            "doc_id_preview": str(top.get("id", "")),
            "has_cached_at": bool(cached_at),
            "ttl_effective": ttl,
            "answer_len": len(cached_answer),
            "metadata_intent": metadata.get("intent"),
        }

        if score < SIMILARITY_THRESHOLD:
            return _log_miss(
                miss_reason="score_below_threshold",
                miss_detail={
                    "top_score": round(score, 4),
                    "required_min_score": SIMILARITY_THRESHOLD,
                    "shortfall": round(SIMILARITY_THRESHOLD - score, 4),
                },
                top_candidate=top_candidate,
            )

        if not cached_at:
            return _log_miss(
                miss_reason="missing_cached_at_metadata",
                miss_detail={
                    "top_score": round(score, 4),
                    "metadata_keys": list(metadata.keys()),
                },
                top_candidate=top_candidate,
            )

        expired = _is_expired(cached_at, ttl)
        age_sec = _cache_entry_age_seconds(cached_at)
        if expired:
            return _log_miss(
                miss_reason="ttl_expired",
                miss_detail={
                    "top_score": round(score, 4),
                    "cached_at": cached_at,
                    "ttl_seconds": ttl,
                    "age_seconds": round(age_sec, 3) if age_sec is not None else None,
                },
                top_candidate=top_candidate,
            )

        if not cached_answer:
            logger.info(
                "semantic_cache_skip_empty_answer",
                query=query,
                score=f"{score:.3f}",
            )
            return _log_miss(
                miss_reason="empty_cached_answer",
                miss_detail={"top_score": round(score, 4)},
                top_candidate=top_candidate,
            )

        if _is_fallback_message(cached_answer):
            logger.info(
                "semantic_cache_skip_fallback_hit",
                query=query,
                score=f"{score:.3f}",
            )
            return _log_miss(
                miss_reason="rejected_stored_fallback_answer",
                miss_detail={
                    "top_score": round(score, 4),
                    "answer_preview": cached_answer,
                },
                top_candidate=top_candidate,
            )

        if not _looks_complete_sentence(cached_answer):
            logger.info(
                "semantic_cache_skip_truncated",
                query=query,
                answer_preview=cached_answer,
            )
            return _log_miss(
                miss_reason="rejected_incomplete_cached_answer",
                miss_detail={
                    "top_score": round(score, 4),
                    "answer_preview": cached_answer,
                },
                top_candidate=top_candidate,
            )

        elapsed = time.time() - _start
        logger.info("timing_segment", segment="check_cache", elapsed_sec=round(elapsed, 3), hit=True)
        logger.info("semantic_cache_hit", score=f"{score:.3f}", query=query)
        log_call_data(
            call_id,
            "rag",
            "semantic_cache_hit",
            query=query,
            query_full=query,
            query_len=len(query or ""),
            score=round(score, 3),
            elapsed_sec=round(elapsed, 3),
            criteria=criteria,
        )
        return {
            "rag_cache_hit": True,
            "response": cached_answer,
            "confidence": metadata.get("confidence", 0.9),
            "llm_rag_applied": [],
            "llm_rag_context_source": "semantic_cache",
            "semantic_cache_score": round(score, 3),
            "rag_search_trace": {},
        }

    except Exception as e:
        logger.warning("semantic_cache_check_error", error=str(e), exc_info=True)
        return _log_miss(
            miss_reason="check_cache_exception",
            miss_detail={"error_type": type(e).__name__, "error_message": str(e)},
        )


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
                     reason="truncated_or_error", response_preview=response)
        return {}
    # RAG 0건일 때의 폴백 응답은 캐시에 넣지 않음 (지식 추가 후에도 캐시로 잘못 나오는 것 방지)
    if _is_fallback_message(response):
        elapsed = time.time() - _start
        logger.info("timing_segment", segment="update_cache", elapsed_sec=round(elapsed, 3), skip="fallback_response")
        logger.debug("semantic_cache_skip_save", reason="fallback_response", response_preview=response)
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
        logger.info("semantic_cache_updated", query=query, ttl=ttl)
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
