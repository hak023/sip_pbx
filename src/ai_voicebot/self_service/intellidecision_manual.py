"""
IntelliDecision 설명 매뉴얼 — 지식베이스 기반 정적 사례 (Story 1.40, FR34-D).

실시간 LLM 호출 없이(임베딩 벡터 검색 + 지식 그래프 조회만 사용), 각 유형(A~I)의 트리거
예시 하나로 실제 지식베이스를 검색해 "이 질문 → 이 문서가 매칭 → 이 hop이 확장" 사례를
정적으로 구성한다. `self_service_agent.py`의 실제 응대 판단 로직에는 전혀 관여하지 않는
순수 조회 전용 기능이며, 매칭 문서가 없으면 임의로 지어내지 않고 has_case=False로 표시한다
(AC2/AC3/AC4).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, List, Optional

import structlog

from src.ai_voicebot.self_service.rag import get_self_service_rag_engine

logger = structlog.get_logger(__name__)

_MAX_CASE_DOCUMENTS = 3
_MAX_HOP_EDGES = 20
_EXCERPT_MAX_LEN = 200


@dataclass
class CaseDocument:
    doc_id: str
    score: float
    related_domain: str
    excerpt: str


@dataclass
class HopEdgeOut:
    hop: int
    edge_type: str
    source_type: str
    source_id: str
    target_type: str
    target_id: str


@dataclass
class TypeCaseExample:
    code: str
    has_case: bool
    trigger_example: Optional[str] = None
    matched_documents: List[CaseDocument] = field(default_factory=list)
    hop_path: List[HopEdgeOut] = field(default_factory=list)


def _collect_hop_path(related_domains: List[str], owner: str) -> List[HopEdgeOut]:
    """매칭 문서의 related_domain에서 시작해 `traverse_graph()`로 hop 경로를 수집한다.

    개별 도메인 조회 실패는 다른 도메인 수집을 막지 않는다(best-effort, Story 1.32와 동일 패턴).
    """
    from src.ai_voicebot.self_service.knowledge_graph import traverse_graph

    edges: List[HopEdgeOut] = []
    seen: set = set()
    for domain in sorted({d for d in related_domains if d}):
        try:
            raw_edges = traverse_graph("catalog_domain", domain, max_hops=3, owner=owner)
        except Exception as exc:  # noqa: BLE001 - 순수 조회 전용, 한 도메인 실패로 전체를 막지 않음
            logger.warning("intellidecision_manual_hop_path_failed", domain=domain, error=str(exc))
            continue
        for e in raw_edges:
            key = (e["hop"], e["edge_type"], str(e["source_id"]), str(e["target_id"]))
            if key in seen:
                continue
            seen.add(key)
            edges.append(
                HopEdgeOut(
                    hop=e["hop"], edge_type=e["edge_type"],
                    source_type=e["source_type"], source_id=str(e["source_id"]),
                    target_type=e["target_type"], target_id=str(e["target_id"]),
                )
            )
            if len(edges) >= _MAX_HOP_EDGES:
                return edges
    return edges


async def build_case_example_for_type(spec: Any, owner: str) -> TypeCaseExample:
    """단일 유형(spec)에 대해 지식베이스 기반 정적 사례를 산출한다(AC2/AC3, LLM 호출 없음).

    rag_enabled=False이거나 trigger_examples가 없으면(정책상 RAG 자체가 무관한 유형) 애초에
    사례를 만들지 않는다. 검색 결과가 없으면 has_case=False로 반환한다(AC4 — 임의 생성 금지).
    """
    if not getattr(spec, "rag_enabled", False) or not spec.trigger_examples:
        return TypeCaseExample(code=spec.code, has_case=False)
    return await build_case_example_for_query(spec, owner, spec.trigger_examples[0])


async def build_case_example_for_query(spec: Any, owner: str, query: str) -> TypeCaseExample:
    """`build_case_example_for_type`과 동일한 로직이되, 유형의 첫 번째 trigger_example 대신
    임의의 질문(사용자가 선택한 질문 예시 포함)으로 조회한다(Story 1.44, FR35-D — 응대 유형
    탐색기가 "이 질문을 고르면 이렇게 매칭될 것"을 미리 보여주기 위해 사용). 이 함수도 벡터
    검색·지식 그래프 조회만 수행하며 LLM 응답 텍스트는 생성하지 않는다.
    """
    example = query.strip()
    if not getattr(spec, "rag_enabled", False) or not example:
        return TypeCaseExample(code=spec.code, has_case=False, trigger_example=example or None)

    rag_engine = get_self_service_rag_engine()
    if rag_engine is None:
        return TypeCaseExample(code=spec.code, has_case=False, trigger_example=example)

    try:
        result = await rag_engine.search(example, owner_filter=owner, intent="question")
    except Exception as exc:  # noqa: BLE001
        logger.warning("intellidecision_manual_rag_search_failed", code=spec.code, error=str(exc))
        return TypeCaseExample(code=spec.code, has_case=False, trigger_example=example)

    docs = list(getattr(result, "documents", None) or [])[:_MAX_CASE_DOCUMENTS]
    if not docs:
        return TypeCaseExample(code=spec.code, has_case=False, trigger_example=example)

    case_docs = [
        CaseDocument(
            doc_id=str(getattr(d, "id", "") or ""),
            score=round(float(getattr(d, "score", 0.0) or 0.0), 4),
            related_domain=str((getattr(d, "metadata", None) or {}).get("related_domain") or ""),
            excerpt=(getattr(d, "text", "") or "")[:_EXCERPT_MAX_LEN],
        )
        for d in docs
    ]
    hop_path = _collect_hop_path([c.related_domain for c in case_docs], owner)

    return TypeCaseExample(
        code=spec.code, has_case=True, trigger_example=example,
        matched_documents=case_docs, hop_path=hop_path,
    )
