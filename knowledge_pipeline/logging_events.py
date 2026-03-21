"""
지식베이스 저장·RAG 검색 시 사용할 로그 이벤트 이름 및 권장 페이로드.
실제 로그 출력은 호출 측에서 이 상수와 스펙을 참고해 구조화 로그에 포함.

설계: docs/design/KNOWLEDGE_STAGE3_AND_LOGGING.md
"""

# ----- Stage 3 품질 검증 -----
EVENT_STAGE3_START = "knowledge_stage3_start"
EVENT_STAGE3_TRANSCRIPT_RECONSTRUCTED = "knowledge_stage3_transcript_reconstructed"
EVENT_STAGE3_VERIFICATION_ITEM = "knowledge_stage3_verification_item"
EVENT_STAGE3_COMPLETE = "knowledge_stage3_complete"
EVENT_STAGE3_ERROR = "knowledge_stage3_error"

# ----- Stage 4 저장 -----
EVENT_STAGE4_START = "knowledge_stage4_start"
EVENT_STAGE4_DEDUP_CHECK = "knowledge_stage4_dedup_check"
EVENT_STAGE4_STORED_ITEM = "knowledge_stage4_stored_item"
EVENT_STAGE4_SKIP_DUPLICATE = "knowledge_stage4_skip_duplicate"
EVENT_STAGE4_COMPLETE = "knowledge_stage4_complete"

# ----- RAG 검색 -----
EVENT_RAG_SEARCH_START = "rag_search_start"
EVENT_RAG_SEARCH_VECTOR_DONE = "rag_search_vector_done"
EVENT_RAG_SEARCH_COMPLETED = "rag_search_completed"
EVENT_RAG_SEARCH_NO_RESULTS = "rag_search_no_results"
EVENT_RAG_SEARCH_ERROR = "rag_search_error"


def _log_struct(log_fn, event: str, **kwargs) -> None:
    """단일 dict로 구조화 로그. log_fn(dict) 또는 log_fn(**dict) 호환."""
    payload = {"event": event, **kwargs}
    if callable(log_fn):
        try:
            log_fn(payload)
        except TypeError:
            log_fn(**payload)


def rag_search_log_start(log_fn, call_id: str, query: str, owner_filter: str, top_k: int = 5) -> None:
    """RAG 검색 시작 시 호출."""
    _log_struct(log_fn, EVENT_RAG_SEARCH_START, call_id=call_id or "", query=query, owner_filter=owner_filter, top_k=top_k)


def rag_search_log_vector_done(log_fn, call_id: str, results_count: int, owner_filter: str, elapsed_ms: float) -> None:
    """벡터 검색 완료 시 호출."""
    _log_struct(
        log_fn, EVENT_RAG_SEARCH_VECTOR_DONE,
        call_id=call_id or "", results_count=results_count, owner_filter=owner_filter,
        elapsed_ms=round(elapsed_ms, 2),
    )


def rag_search_log_completed(log_fn, call_id: str, query: str, owner_filter: str, results_count: int, doc_ids=None) -> None:
    """RAG 검색 완료 시 호출 (기존 rag_search_completed와 호환)."""
    payload = {"event": EVENT_RAG_SEARCH_COMPLETED, "call_id": call_id or "", "query": query, "owner_filter": owner_filter, "results_count": results_count}
    if doc_ids is not None:
        payload["doc_ids"] = doc_ids
    if callable(log_fn):
        try:
            log_fn(payload)
        except TypeError:
            log_fn(**payload)


def rag_search_log_no_results(log_fn, call_id: str, query: str, owner_filter: str, reason: str = "zero_results") -> None:
    """RAG 검색 0건 시 호출."""
    _log_struct(log_fn, EVENT_RAG_SEARCH_NO_RESULTS, call_id=call_id or "", query=query, owner_filter=owner_filter, reason=reason)


def rag_search_log_error(log_fn, call_id: str, error: str, query: str = "", owner_filter: str = "") -> None:
    """RAG 검색 예외 시 호출."""
    _log_struct(log_fn, EVENT_RAG_SEARCH_ERROR, call_id=call_id or "", error=error, query=query, owner_filter=owner_filter)
