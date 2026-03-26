"""
RAG 검색 결과를 call_data_record / WebSocket(call_debug_trace)용으로 직렬화.

- knowledge 베이스(Chroma) 메타데이터 중 디버깅에 유용한 키만 포함
- 본문은 기본 전체(text_preview 키 유지, 디버깅 시 잘라내지 않음). 필요 시 preview_len으로만 제한.
"""

from __future__ import annotations

from typing import Any, Dict, List

# Chroma / 지식 파이프라인에서 흔히 쓰는 메타 키 (없으면 생략)
_META_KEYS = (
    "owner",
    "category",
    "doc_type",
    "parent_id",
    "source",
    "title",
    "chunk_index",
    "knowledge_id",
    "intent",
    "normalized_value",
    "entity_type",
)


def _copy_meta(metadata: Any) -> Dict[str, Any]:
    if not isinstance(metadata, dict):
        return {}
    out: Dict[str, Any] = {}
    for k in _META_KEYS:
        if k not in metadata or metadata[k] is None:
            continue
        v = metadata[k]
        if isinstance(v, (str, int, float, bool)):
            out[k] = v
        else:
            out[k] = str(v)
    return out


def _preview(text: str, n: int | None) -> str:
    t = (text or "").strip()
    if n is None or len(t) <= n:
        return t
    return t[:n] + "…"


def serialize_document_for_call_data(doc: Any, *, rank: int, preview_len: int | None = None) -> Dict[str, Any]:
    """RAGEngine.Document 또는 유사 객체 → JSON-safe dict."""
    text = getattr(doc, "text", None)
    if text is None and isinstance(doc, dict):
        text = doc.get("text", "")
    score = getattr(doc, "score", None)
    if score is None and isinstance(doc, dict):
        score = doc.get("score", 0.0)
    did = getattr(doc, "id", None)
    if did is None and isinstance(doc, dict):
        did = doc.get("id", "")
    meta = getattr(doc, "metadata", None)
    if meta is None and isinstance(doc, dict):
        meta = doc.get("metadata") or {}
    try:
        score_f = float(score or 0.0)
    except (TypeError, ValueError):
        score_f = 0.0
    row: Dict[str, Any] = {
        "rank": rank,
        "doc_id": str(did or ""),
        "score": round(score_f, 4),
        "text_preview": _preview(str(text or ""), preview_len),
    }
    row.update(_copy_meta(meta))
    return row


def build_rag_hits_retrieval(
    search_results: Any,
    *,
    max_items: int = 8,
    preview_len: int | None = None,
) -> List[Dict[str, Any]]:
    """벡터 검색 직후(문장/청크 단위) 상위 히트."""
    if not search_results:
        return []
    out: List[Dict[str, Any]] = []
    for i, doc in enumerate(search_results[:max_items]):
        out.append(serialize_document_for_call_data(doc, rank=i + 1, preview_len=preview_len))
    return out


def build_rag_hits_llm_context(
    compressed: Any,
    *,
    max_items: int = 8,
    preview_len: int | None = None,
) -> List[Dict[str, Any]]:
    """Small-to-Big·압축 후 LLM에 실제로 넘어가는 문맥 스니펫."""
    if not compressed:
        return []
    out: List[Dict[str, Any]] = []
    for i, item in enumerate(compressed[:max_items]):
        if isinstance(item, dict):
            text = item.get("text", "") or ""
            score = item.get("score", 0.0)
            meta = item.get("metadata") or {}
            src = item.get("source", "") or ""
        else:
            text = getattr(item, "text", "") or ""
            score = getattr(item, "score", 0.0)
            meta = getattr(item, "metadata", None) or {}
            src = getattr(item, "source", "") or ""
        try:
            score_f = float(score or 0.0)
        except (TypeError, ValueError):
            score_f = 0.0
        mid = ""
        if isinstance(meta, dict):
            mid = str(meta.get("parent_id") or meta.get("chunk_id") or meta.get("id") or "")
        row: Dict[str, Any] = {
            "rank": i + 1,
            "doc_id": mid,
            "score": round(score_f, 4),
            "text_preview": _preview(str(text), preview_len),
            "source": str(src) if src else "",
        }
        for k, v in _copy_meta(meta).items():
            if k not in row or row[k] in ("", None):
                row[k] = v
        out.append(row)
    return out
