"""
셀프서비스 매뉴얼 RAG(ChromaDB) 색인 현황 — 읽기 전용 인벤토리 집계 (Story 1.23, FR31-A).

"지식베이스에 실제로 무엇이 얼마나 색인되어 있는지"를 코드/스크립트(`_check_emb_meta.py` 등)를
직접 열어보지 않고도 API/화면에서 확인할 수 있도록, `self_service_manual` doc_type의
owner별 색인 항목을 집계한다.

**중요**: 이 모듈은 색인(`manual_indexer.py`)·검색(RAG 조회) 로직을 전혀 수정하지 않고 기존
ChromaDB 데이터를 조회만 하는 순수 관측 유틸리티다. 응대 로직에는 어떤 영향도 주지 않는다
(리서치 §2.2, PRD FR31-A, architecture §RAG·IntelliDecision 고도화 설계 방향).
"""

from __future__ import annotations

from typing import Any, Dict, List

from src.common.sip_owner import normalize_owner_username

_SELF_SERVICE_MANUAL_DOC_TYPE = "self_service_manual"


def summarize_inventory(raw_items: List[Dict[str, Any]], owner: str) -> Dict[str, Any]:
    """이미 조회된 raw 항목 리스트(ChromaDB get 결과를 dict 리스트로 정규화한 것)를 받아
    지정 owner의 `self_service_manual` 색인 현황을 집계한다.

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
        if item_doc_type != _SELF_SERVICE_MANUAL_DOC_TYPE:
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
        "doc_type": _SELF_SERVICE_MANUAL_DOC_TYPE,
    }
