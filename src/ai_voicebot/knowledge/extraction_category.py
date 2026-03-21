"""
통화 추출 파이프라인 category → Chroma/RAG(INTENT_CATEGORY_MAP) 정합.

LLM이 임의 라벨(정보, 기타 등)을 줄 수 있어, RAG 필터(complaint/transfer)에 걸리도록
표준 카테고리로 매핑한다.
"""

from __future__ import annotations

from typing import Optional

from src.ai_voicebot.knowledge.knowledge_service import VALID_CATEGORIES

# complaint/transfer intent 검색 시 포함되는 카테고리와 정렬
_DEFAULT_FOR_EXTRACTED = "question"


def normalize_extraction_category(category: Optional[str], doc_type: str) -> str:
    """
    저장용 category. 이미 VALID_CATEGORIES면 그대로, 아니면 doc_type별 기본값.

    Args:
        category: LLM/추출기 원본
        doc_type: knowledge | qa_pair | entity
    """
    c = (category or "").strip()
    if c in VALID_CATEGORIES:
        return c
    if doc_type in ("qa_pair", "knowledge", "entity"):
        return _DEFAULT_FOR_EXTRACTED
    return _DEFAULT_FOR_EXTRACTED if not c else c
