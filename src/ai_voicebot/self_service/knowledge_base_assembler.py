"""
업로드 데이터 기반 지식베이스 자동 구성 집계 (Story 1.31, FR33-B).

Story 1.26 업로드 문서(source_type=markdown/pdf/openapi)의 ChromaDB 색인 결과를 도메인
비종속적으로 재분류해 (1) 이용 매뉴얼 Q&A (2) AI 변경 가능 설정 항목 후보 (3) 화면/문서 안내
노드 3종으로 집계한다.

**중요(Non-Goal, PRD FR33-B)**: 여기서 "설정 항목 후보"로 분류하는 것은 어디까지나 지식
구조화일 뿐이며, 실제 설정을 변경하는 get_fn/update_fn 콜러블과 연결·실행하지 않는다. 분류는
OpenAPI 스펙 파싱 시 생성된 질문 문구의 구조(HTTP 메서드+경로)만으로 판단하므로 SIP PBX 등
특정 도메인 키워드에 의존하지 않는다(AC2, 도메인 비종속).
"""

from __future__ import annotations

import re
from typing import Any, Dict, List, Optional

from src.common.sip_owner import normalize_owner_username

# knowledge_documents.py::KNOWLEDGE_DOCUMENT_DOC_TYPE과 동일 값(순환 임포트 회피를 위해 리터럴 재사용)
_KNOWLEDGE_DOCUMENT_DOC_TYPE = "knowledge_document"

# 쓰기 가능성이 있다고 볼 수 있는 HTTP 메서드(REST 관례 기반, 도메인 비종속)
_WRITABLE_METHODS = frozenset({"POST", "PUT", "PATCH", "DELETE"})

# document_adapters.py::OpenApiSpecAdapter가 생성하는 질문 문구 포맷과 정확히 일치해야 한다.
_ENDPOINT_QUESTION_RE = re.compile(
    r"^(GET|POST|PUT|PATCH|DELETE|OPTIONS|HEAD) (\S+) 엔드포인트는 무엇을 하나요\?$"
)


def _split_qa_text(text: str) -> tuple[str, str]:
    """`knowledge_documents.py::_index_pairs`가 만든 "Q: ...\\nA: ..." 원문에서 질문/답변을 복원한다."""
    if not text.startswith("Q: "):
        return "", ""
    parts = text.split("\n", 1)
    question = parts[0][len("Q: "):].strip()
    answer = parts[1][len("A: "):].strip() if len(parts) > 1 and parts[1].startswith("A: ") else ""
    return question, answer


def classify_setting_item(question: str, answer: str) -> Optional[Dict[str, Any]]:
    """OpenAPI 엔드포인트 Q&A를 "AI 변경 가능 설정" 후보로 분류한다.

    질문 문구가 `OpenApiSpecAdapter`의 엔드포인트 질문 포맷(예: "POST /orders 엔드포인트는
    무엇을 하나요?")과 일치하지 않으면 일반 매뉴얼 Q&A로 간주해 ``None``을 반환한다.
    """
    match = _ENDPOINT_QUESTION_RE.match((question or "").strip())
    if match is None:
        return None
    method, endpoint_path = match.group(1), match.group(2)
    return {
        "label": endpoint_path,
        "method": method,
        "writable": method in _WRITABLE_METHODS,
        "description": answer,
    }


def summarize_auto_assembled_knowledge_base(
    raw_items: List[Dict[str, Any]],
    owner: str,
    *,
    document_records: Optional[List[Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    """이미 조회된 raw ChromaDB 항목(``knowledge_service.get_all_knowledge()`` 반환 형식)에서
    owner의 업로드 지식(``doc_type=knowledge_document``)을 매뉴얼 Q&A/설정 항목 후보로
    자동 분류·집계한다(AC1, AC3).

    Args:
        raw_items: ``{"id": str, "text": str, "metadata": dict}`` 형태의 항목 리스트.
        owner: 집계 대상 테넌트 owner(정규화 전 원본 문자열 허용).
        document_records: ``knowledge_documents_db.list_documents(owner=owner)`` 결과(선택).
            제공되면 업로드 문서 수를 "화면/문서 안내 노드" 개수로 함께 집계한다(AC1-c는
            `knowledge_graph.py`의 별도 그래프 엣지로 활용되며, 이 값은 그 대상 문서 수 요약이다).
    """
    normalized_owner = normalize_owner_username(owner) or ""

    manual_qa_count = 0
    setting_items: List[Dict[str, Any]] = []

    for item in raw_items or []:
        meta = (item or {}).get("metadata") or {}
        if str(meta.get("doc_type") or "").strip() != _KNOWLEDGE_DOCUMENT_DOC_TYPE:
            continue
        if normalized_owner and str(meta.get("owner") or "").strip() != normalized_owner:
            continue

        question, answer = _split_qa_text(str((item or {}).get("text") or ""))
        setting_item = classify_setting_item(question, answer)
        if setting_item is not None:
            setting_items.append(setting_item)
        else:
            manual_qa_count += 1

    return {
        "owner": normalized_owner,
        "manual_qa_count": manual_qa_count,
        "setting_item_count": len(setting_items),
        "writable_setting_item_count": sum(1 for s in setting_items if s["writable"]),
        "setting_items": setting_items,
        "screen_node_count": len(document_records or []),
        "doc_type": _KNOWLEDGE_DOCUMENT_DOC_TYPE,
    }
