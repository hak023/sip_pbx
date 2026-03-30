"""HITL → 지식베이스 적재 시 category 결정 (CHROMADB_CATEGORY_DESIGN 정합)."""

from typing import Optional

from src.ai_voicebot.knowledge.knowledge_service import VALID_CATEGORIES


def resolve_hitl_kb_category(explicit_category: Optional[str], intent: str) -> str:
    """
    운영자가 지정한 category가 유효하면 그대로 사용.
    아니면 intent 기반 기본값: complaint / transfer / question.
    """
    c = (explicit_category or "").strip()
    if c in VALID_CATEGORIES:
        return c
    intent_l = (intent or "").strip().lower()
    if intent_l == "complaint":
        return "complaint"
    if intent_l == "transfer":
        return "transfer"
    return "question"
