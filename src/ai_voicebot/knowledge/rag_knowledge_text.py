"""
RAG 검색용 서술형 지식(`doc_type=knowledge`) 문서 문자열 정규화.

임베딩 공간을 고객 질의와 맞추기 위한 단일 접두(리포트 §10.3 권장 1번).
"""

from __future__ import annotations

# 문서에 명시된 규약과 동일하게 유지
RAG_KNOWLEDGE_TEXT_PREFIX = "고객이 알 수 있어야 할 정보: "


def apply_rag_knowledge_prefix(text: str) -> str:
    """
    서술형 지식 청크에 검색용 접두를 붙인다.
    이미 동일 접두로 시작하면 그대로 둔다.
    """
    if text is None:
        return ""
    t = str(text).strip()
    if not t:
        return ""
    if t.startswith(RAG_KNOWLEDGE_TEXT_PREFIX):
        return t
    return f"{RAG_KNOWLEDGE_TEXT_PREFIX}{t}"
