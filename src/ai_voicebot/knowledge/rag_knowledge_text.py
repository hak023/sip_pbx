"""
RAG 검색용 서술형 지식(`doc_type=knowledge`) 문서 문자열 정규화.

접두는 비활성화(빈 문자열). 과거 저장분은 `strip_rag_knowledge_prefix`로 제거 가능.
"""

from __future__ import annotations

# 비어 있으면 접두를 붙이지 않음 (레거시 호환용 상수만 유지)
RAG_KNOWLEDGE_TEXT_PREFIX = ""

# 과거 파이프라인이 붙이던 접두 — strip 시에만 사용
_LEGACY_RAG_KNOWLEDGE_PREFIX = "고객이 알 수 있어야 할 정보: "


def apply_rag_knowledge_prefix(text: str) -> str:
    """서술형 지식 청크 정규화. 접두가 설정된 경우에만 붙인다."""
    if text is None:
        return ""
    t = str(text).strip()
    if not t:
        return ""
    prefix = RAG_KNOWLEDGE_TEXT_PREFIX
    if not prefix:
        return t
    if t.startswith(prefix):
        return t
    return f"{prefix}{t}"


def strip_rag_knowledge_prefix(text: str) -> str:
    """레거시 접두 제거. 환각 검증(전사 대비) 등 원문 근거 판단 시 사용."""
    if text is None:
        return ""
    t = str(text).strip()
    if t.startswith(_LEGACY_RAG_KNOWLEDGE_PREFIX):
        return t[len(_LEGACY_RAG_KNOWLEDGE_PREFIX) :].strip()
    return t
