"""
셀프서비스 매뉴얼 RAG(ChromaDB) 색인 현황 — 읽기 전용 인벤토리 집계 (Story 1.23, FR31-A).

"지식베이스에 실제로 무엇이 얼마나 색인되어 있는지"를 코드/스크립트(`_check_emb_meta.py` 등)를
직접 열어보지 않고도 API/화면에서 확인할 수 있도록, 도우미 지식 베이스 doc_type의 owner별
색인 항목을 집계한다.

**중요**: 이 모듈은 색인(`manual_indexer.py`)·검색(RAG 조회) 로직을 전혀 수정하지 않고 기존
ChromaDB 데이터를 조회만 하는 순수 관측 유틸리티다. 응대 로직에는 어떤 영향도 주지 않는다
(리서치 §2.2, PRD FR31-A, architecture §RAG·IntelliDecision 고도화 설계 방향).
"""

from __future__ import annotations

from typing import Any, Dict, List

from src.common.sip_owner import normalize_owner_username

_SELF_SERVICE_MANUAL_DOC_TYPE = "self_service_manual"
# (2026-08-07) Story 1.26 업로드 문서(source_type=markdown/pdf/openapi)는 `knowledge_document`
# doc_type으로 색인되는데, 이 함수가 `self_service_manual`만 세도록 만들어져 있어 업로드 직후
# "지식베이스 현황" 화면의 총 청크 수/도메인 분포에 전혀 반영되지 않는 버그가 있었다(사용자가
# "업로드한 데이터가 안 보인다"고 보고, `knowledge_document_registered` 로그로 색인 자체는
# 정상 성공했음을 확인 — 집계 필터 누락이 근본 원인). 두 doc_type을 모두 도우미 지식 베이스로
# 집계 대상에 포함한다(고객 지식 베이스 doc_type인 "knowledge"/"faq"는 여전히 제외).
_KNOWLEDGE_DOCUMENT_DOC_TYPE = "knowledge_document"
_ASSISTANT_KB_DOC_TYPES = frozenset({_SELF_SERVICE_MANUAL_DOC_TYPE, _KNOWLEDGE_DOCUMENT_DOC_TYPE})


def summarize_inventory(raw_items: List[Dict[str, Any]], owner: str) -> Dict[str, Any]:
    """이미 조회된 raw 항목 리스트(ChromaDB get 결과를 dict 리스트로 정규화한 것)를 받아
    지정 owner의 도우미 지식 베이스(매뉴얼 자동색인 + Story 1.26 업로드 문서) 색인 현황을
    집계한다.

    Args:
        raw_items: ``{"id": str, "text": str, "metadata": dict}`` 형태의 항목 리스트
            (`knowledge_service.list_knowledge()`/`get_all_knowledge()` 반환 형식과 동일).
        owner: 집계 대상 테넌트 owner(정규화 전 원본 문자열 허용).

    Returns:
        빈 컬렉션/미매칭 owner인 경우에도 예외 없이 0건 인벤토리를 반환한다(AC2).
    """
    normalized_owner = normalize_owner_username(owner) or ""

    domain_counts: Dict[str, int] = {}
    section_titles: set[str] = set()
    latest_indexed_at = ""
    total_chunks = 0

    for item in raw_items or []:
        meta = (item or {}).get("metadata") or {}
        item_owner = str(meta.get("owner") or "").strip()
        item_doc_type = str(meta.get("doc_type") or "").strip()
        if item_doc_type not in _ASSISTANT_KB_DOC_TYPES:
            continue
        if normalized_owner and item_owner != normalized_owner:
            continue

        total_chunks += 1

        domain = str(meta.get("related_domain") or "").strip() or "(미분류)"
        domain_counts[domain] = domain_counts.get(domain, 0) + 1

        section_title = str(meta.get("section_title") or "").strip()
        if section_title:
            section_titles.add(section_title)

        created_at = str(meta.get("created_at") or "").strip()
        if created_at and created_at > latest_indexed_at:
            latest_indexed_at = created_at

    domain_distribution = [
        {"domain": domain, "count": count}
        for domain, count in sorted(domain_counts.items(), key=lambda kv: (-kv[1], kv[0]))
    ]

    return {
        "owner": normalized_owner,
        "total_chunks": total_chunks,
        "source_document_count": len(section_titles),
        "domain_distribution": domain_distribution,
        "last_indexed_at": latest_indexed_at,
        "doc_type": ",".join(sorted(_ASSISTANT_KB_DOC_TYPES)),
    }

