"""
셀프서비스 전용 RAGEngine 싱글턴 (Story 1.3 Task 3).

RAGEngine.doc_type_allowlist는 생성자 시점에만 설정 가능하고 검색 호출마다
바꿀 수 없다(sip-pbx/src/ai_voicebot/ai_pipeline/rag_engine.py 참고).
따라서 메인 파이프라인(doc_type 제한 없음)과는 별도로,
doc_type_allowlist=["self_service_manual"] 로 고정된 전용 인스턴스를 둔다.

embedder/vector_db는 call_context(ContextVar)에서 공유해 재사용하고,
RAGEngine 자체는 프로세스 전역에 지연 초기화 후 캐시하여
매 통화·매 턴마다 재생성하는 비용을 없앤다.
"""

from __future__ import annotations

from typing import Any, Optional

import structlog

from src.ai_voicebot.langgraph.call_context import get_embedder, get_vector_db
from src.ai_voicebot.self_service.knowledge_documents import KNOWLEDGE_DOCUMENT_DOC_TYPE
from src.ai_voicebot.self_service.manual_indexer import SELF_SERVICE_MANUAL_DOC_TYPE

logger = structlog.get_logger(__name__)

# (2026-08-07) 이 학이자 self_service_manual만 검색 대상으로 삼아, Story 1.26로
# 업로드한 문서(doc_type=knowledge_document)가 색인은 되지만 실제 대화 RAG 검색에는
# 절대 잡히지 않는 치명적 버그가 있었다(사용자 보고: "업로드한 게 도우미
# 지식베이스에서 검색되지 않는다"). 두 doc_type 모두를 허용리스트에 포함해야 한다.
_SELF_SERVICE_KB_DOC_TYPES = [SELF_SERVICE_MANUAL_DOC_TYPE, KNOWLEDGE_DOCUMENT_DOC_TYPE]

_self_service_rag_engine: Optional[Any] = None
_cached_embedder_id: Optional[int] = None
_cached_vector_db_id: Optional[int] = None


def get_self_service_rag_engine() -> Optional[Any]:
    """셀프서비스 전용 RAGEngine을 반환한다(없으면 지연 생성 후 캐시).

    call_context에 embedder/vector_db가 아직 설정되지 않은 호출 초기 시점에는
    None을 반환할 수 있다(메인 파이프라인 초기화 이전 등) — 호출부에서 None 체크 필요.
    """
    global _self_service_rag_engine, _cached_embedder_id, _cached_vector_db_id

    embedder = get_embedder()
    vector_db = get_vector_db()
    if embedder is None or vector_db is None:
        return None

    # embedder/vector_db 인스턴스가 (재시작 등으로) 바뀌면 캐시를 무효화하고 재생성한다.
    if (
        _self_service_rag_engine is not None
        and _cached_embedder_id == id(embedder)
        and _cached_vector_db_id == id(vector_db)
    ):
        return _self_service_rag_engine

    from src.ai_voicebot.ai_pipeline.rag_engine import RAGEngine

    _self_service_rag_engine = RAGEngine(
        vector_db=vector_db,
        embedder=embedder,
        top_k=5,
        similarity_threshold=0.35,
        reranking_enabled=False,
        doc_type_allowlist=_SELF_SERVICE_KB_DOC_TYPES,
    )
    _cached_embedder_id = id(embedder)
    _cached_vector_db_id = id(vector_db)
    logger.info(
        "self_service_rag_engine_created",
        doc_type_allowlist=_SELF_SERVICE_KB_DOC_TYPES,
    )
    return _self_service_rag_engine


def reset_self_service_rag_engine_cache() -> None:
    """테스트 전용: 캐시된 싱글턴을 초기화한다."""
    global _self_service_rag_engine, _cached_embedder_id, _cached_vector_db_id
    _self_service_rag_engine = None
    _cached_embedder_id = None
    _cached_vector_db_id = None
