"""지식 추출 / Chroma 저장 결과를 call_data_record에 넣기 위한 직렬화 헬퍼."""

from __future__ import annotations

from typing import Any, Dict, List


def chroma_context_for_call_data() -> Dict[str, Any]:
    """Chroma 영속 경로·컬렉션명 (로그 필드 공통)."""
    try:
        from src.ai_voicebot.knowledge.chromadb_client import (
            KNOWLEDGE_COLLECTION,
            get_chroma_persist_path,
        )

        return {
            "chromadb_collection": KNOWLEDGE_COLLECTION,
            "chromadb_persist_path": get_chroma_persist_path(),
        }
    except Exception:
        return {"chromadb_collection": "knowledge", "chromadb_persist_path": ""}


def judgment_summary_for_call_data(judgment: Dict[str, Any]) -> Dict[str, Any]:
    """LLM judge_usefulness 결과를 JSON-safe 요약."""
    ei = judgment.get("extracted_info") or []
    preview: List[Dict[str, Any]] = []
    if isinstance(ei, list):
        for x in ei[:8]:
            if not isinstance(x, dict):
                continue
            preview.append(
                {
                    "category": x.get("category"),
                    "contains_pii": x.get("contains_pii"),
                    "text_preview": str(x.get("text", "")),
                }
            )
    return {
        "is_useful": judgment.get("is_useful"),
        "confidence": judgment.get("confidence"),
        "reason": str(judgment.get("reason", "") or ""),
        "extracted_info_count": len(ei) if isinstance(ei, list) else 0,
        "extracted_info_preview": preview,
    }
