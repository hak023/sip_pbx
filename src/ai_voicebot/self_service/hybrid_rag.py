"""
유형 C(포괄적 도움 요청) 하이브리드 다중 도메인 RAG 검색 (Story 1.33, FR33-E).

기존 self_service RAG(`rag.py::get_self_service_rag_engine()`)는 단일 쿼리 임베딩으로 owner
전체 컬렉션을 검색하는 벡터 검색 1회 호출이다(도메인별 분리 검색 없음 — Story 1.33 Task 1에서
코드로 직접 확인). "뭘 도와줄 수 있어?" 류의 포괄적 질문은 특정 도메인 하나로 좁혀지지 않으므로,
카탈로그 도메인마다 소규모 결과를 **병렬**로 추가 조회해 특정 도메인에 치우치지 않는 답변 근거를
보강한다. GraphRAG Global Search의 "여러 커뮤니티 요약을 종합"하는 개념의 경량 버전(리서치 §3.11)
— 자동 커뮤니티 클러스터링·별도 벡터DB 네임스페이스는 Non-Goal이다.
"""

from __future__ import annotations

import asyncio
from typing import Any, List

import structlog

from src.ai_voicebot.self_service import settings_catalog
from src.ai_voicebot.self_service.knowledge_documents import KNOWLEDGE_DOCUMENT_DOC_TYPE
from src.ai_voicebot.self_service.manual_indexer import SELF_SERVICE_MANUAL_DOC_TYPE
from src.common.sip_owner import normalize_owner_username

logger = structlog.get_logger(__name__)

# 유형 C 트리거 예시(intellidecision_policy.py)와 동일한 어휘 기반 경량 휴리스틱 — 최종 유형
# 판정은 여전히 LLM이 담당하며, 이 휴리스틱은 하이브리드 다중 도메인 검색 실행 여부만 결정한다
# (오탐 시에도 결과에 문서를 몇 개 더 얹을 뿐 응대 로직을 바꾸지 않아 안전).
_BROAD_HELP_KEYWORDS = (
    "뭘 할 수", "뭐 할 수", "무엇을 도와", "어떤 도움", "사용법", "뭘 도와", "뭐가 되나요", "뭐 되나요",
)


def looks_like_broad_help_query(query: str) -> bool:
    """유형 C(포괄적 도움 요청) 후보 발화인지 저비용으로 사전 감지한다(AC2)."""
    q = (query or "").strip()
    if not q:
        return False
    return any(kw in q for kw in _BROAD_HELP_KEYWORDS)


async def search_hybrid_multi_domain(
    query: str, *, owner: str, vector_db: Any, embedder: Any, top_k_per_domain: int = 2,
) -> List[Any]:
    """카탈로그 도메인마다 소규모 결과를 병렬 조회해 도메인 편중 없는 매뉴얼 Q&A 목록을 반환한다.

    `asyncio.gather`로 도메인별 조회를 동시에 실행해 NFR1(지연 예산)을 지킨다(AC5). 개별 도메인
    조회 실패는 해당 도메인만 건너뛴다(best-effort, 전체 실패시키지 않음).
    """
    from src.ai_voicebot.ai_pipeline.rag_engine import Document

    if vector_db is None or embedder is None:
        return []
    normalized_owner = normalize_owner_username(owner) or owner
    domains = settings_catalog.list_domains(normalized_owner)
    if not domains:
        return []

    try:
        query_embedding = embedder.embed_text(query) if hasattr(embedder, "embed_text") else None
    except Exception as e:
        logger.warning("hybrid_rag_embed_failed", error=str(e))
        return []
    if not query_embedding:
        return []

    async def _query_domain(domain: str) -> List[Any]:
        # (2026-08-07) self_service_manual만 검색해 Story 1.26 업로드 문서(knowledge_document)가
        # 하이브리드 검색에서도 누락되던 문제를 rag.py와 동일하게 수정 — 두 doc_type 모두 조회.
        where = {
            "$and": [
                {"owner": normalized_owner},
                {"doc_type": {"$in": [SELF_SERVICE_MANUAL_DOC_TYPE, KNOWLEDGE_DOCUMENT_DOC_TYPE]}},
                {"related_domain": domain},
            ]
        }
        try:
            raw = await asyncio.to_thread(
                vector_db.query,
                query_embeddings=[query_embedding],
                n_results=top_k_per_domain,
                where=where,
            )
        except Exception as e:
            logger.warning("hybrid_rag_domain_query_failed", domain=domain, error=str(e))
            return []
        ids = raw.get("ids", [[]])[0] if raw.get("ids") else []
        docs_list = raw.get("documents", [[]])[0] if raw.get("documents") else []
        metadatas = raw.get("metadatas", [[]])[0] if raw.get("metadatas") else []
        distances = raw.get("distances", [[]])[0] if raw.get("distances") else []
        out: List[Any] = []
        for i, doc_id in enumerate(ids):
            text = docs_list[i] if i < len(docs_list) else ""
            meta = metadatas[i] if i < len(metadatas) else {}
            dist = distances[i] if i < len(distances) else 1.0
            score = 1.0 / (1.0 + float(dist)) if dist is not None else 0.0
            out.append(Document(
                id=doc_id or "", text=text if isinstance(text, str) else "", score=score, metadata=meta,
            ))
        return out

    per_domain_results = await asyncio.gather(
        *[_query_domain(d) for d in domains], return_exceptions=True
    )

    merged: List[Any] = []
    seen_ids: set[str] = set()
    for result in per_domain_results:
        if isinstance(result, BaseException):
            continue
        for doc in result:
            if doc.id and doc.id in seen_ids:
                continue
            if doc.id:
                seen_ids.add(doc.id)
            merged.append(doc)
    return merged
