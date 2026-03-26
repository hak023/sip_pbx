"""
지식 추가/조회 서비스 (CHROMADB_CATEGORY_DESIGN).

- add_knowledge: knowledge 컬렉션에 category 메타데이터로 저장.
- greeting_phase1/2, farewell 인 경우 qa_cache 즉시 upsert (TTL 7일).
"""

import asyncio
import logging
import uuid
from datetime import datetime
from typing import Any, Dict, List, Optional

from .chromadb_client import (
    KNOWLEDGE_COLLECTION,
    QA_CACHE_COLLECTION,
    get_vector_db,
)
from src.common.sip_owner import normalize_owner_username

logger = logging.getLogger(__name__)

VALID_CATEGORIES = frozenset({
    "question", "greeting_phase1", "greeting_phase2", "farewell",
    "chitchat", "complaint", "transfer",
    "contact",  # 호 전환용 연락처
})
IMMEDIATE_CACHE_CATEGORIES = frozenset({"greeting_phase1", "greeting_phase2", "farewell"})
TTL_CACHE_DAYS = 7
TTL_CACHE_SECONDS = TTL_CACHE_DAYS * 86400


def _get_embedding(embedder: Any, text: str) -> Optional[List[float]]:
    """embedder로 text 임베딩 (동기)."""
    if not embedder:
        return None
    if hasattr(embedder, "embed_text"):
        return embedder.embed_text(text)
    if hasattr(embedder, "embed"):
        out = embedder.embed(text)
        return out if isinstance(out, list) else None
    return None


def add_knowledge(
    vector_db: Any,
    embedder: Any,
    text: str,
    owner: str,
    category: str,
    doc_type: str = "knowledge",  # 추가
    source: str = "api",
    answer: Optional[str] = None,
    call_id: Optional[str] = None,
    # contact category용 추가 필드
    phone_number: Optional[str] = None,
    department: Optional[str] = None,
    name: Optional[str] = None,
) -> Dict[str, Any]:
    """
    지식 1건 추가. category 필수 (설계 §3.2).
    greeting_phase1/2, farewell 이면 qa_cache 즉시 upsert (answer 우선, 없으면 text를 응답 문구로 사용).
    doc_type: knowledge | faq (KNOWLEDGE_DOC_TYPE_DESIGN)
    source: api | hitl | call | seed
    
    contact category 추가 필드 (선택, 메타데이터·호전환용):
        phone_number, department, name
    """
    if not text or not owner or not category:
        return {"ok": False, "error": "text, owner, category 필수"}
    owner = normalize_owner_username(owner)
    if not owner:
        return {"ok": False, "error": "owner가 비었거나 정규화 후 비어 있습니다"}
    if category not in VALID_CATEGORIES:
        return {"ok": False, "error": f"category must be one of {sorted(VALID_CATEGORIES)}"}

    embedding = _get_embedding(embedder, text)
    if not embedding:
        return {"ok": False, "error": "embedder not available or embedding failed"}

    doc_id = f"kb_{uuid.uuid4().hex[:16]}"
    _ts = datetime.now().isoformat()
    metadata = {
        "owner": owner,
        "category": category,
        "doc_type": doc_type,
        "source": source,
        "created_at": _ts,
        "extraction_source": source,
        "extraction_timestamp": _ts,
    }
    if call_id:
        metadata["call_id"] = call_id
        metadata["extraction_call_id"] = call_id
    
    # contact category 메타데이터 추가
    if category == "contact":
        if phone_number:
            metadata["phone_number"] = phone_number
        if department:
            metadata["department"] = department
        if name:
            metadata["name"] = name

    try:
        vector_db.add(
            ids=[doc_id],
            embeddings=[embedding],
            documents=[text],
            metadatas=[metadata],
        )
    except Exception as e:
        logger.warning("knowledge_add_failed", doc_id=doc_id, error=str(e))
        return {"ok": False, "error": str(e), "doc_id": doc_id}

    result = {"ok": True, "doc_id": doc_id, "category": category}

    # 즉시 캐싱 — API에서 needs_immediate_cache True일 때 immediate_cache_for_knowledge 호출
    if category in IMMEDIATE_CACHE_CATEGORIES:
        ans = (answer or "").strip()
        response_text = (ans if ans else text).strip()
        if len(response_text) >= 2:
            result["needs_immediate_cache"] = True
            result["_cache_query_text"] = text
            result["_cache_answer_text"] = response_text

    return result


async def immediate_cache_for_knowledge(
    vector_db: Any,
    embedder: Any,
    query_text: str,
    answer_text: str,
    category: str,
    owner: str,
) -> None:
    """greeting/farewell 지식 추가 후 qa_cache 즉시 upsert (async, API에서 호출)."""
    embedding = _get_embedding(embedder, query_text)
    if not embedding:
        raise ValueError("embedding failed")
    intent = "greeting" if category in ("greeting_phase1", "greeting_phase2") else "farewell"
    doc_id = f"cache_kb_{category}_{owner}_{hash(query_text) % 10**10}"
    metadata = {
        "answer": answer_text,
        "confidence": 0.95,
        "intent": intent,
        "category": category,
        "cached_at": datetime.now().isoformat(),
        "ttl": TTL_CACHE_SECONDS,
        "owner": owner,
    }
    await vector_db.upsert_to_collection(
        collection_name=QA_CACHE_COLLECTION,
        doc_id=doc_id,
        embedding=embedding,
        text=query_text,
        metadata=metadata,
    )


def get_knowledge_greeting_text(
    vector_db: Any,
    owner: str,
    category: str,
) -> Optional[str]:
    """
    지식 컬렉션에서 owner + category(greeting_phase1|greeting_phase2) 문서 본문 1건.

    - CHROMADB_CATEGORY_DESIGN: 인사/안내 문구는 `documents` 본문에 저장됨.
    - 여러 건이면 metadata.created_at 기준 최신 1건.
    """
    if not vector_db or not owner:
        return None
    if category not in ("greeting_phase1", "greeting_phase2"):
        return None
    try:
        res = list_knowledge(
            vector_db,
            owner=owner,
            category=category,
            doc_type=None,
            limit=80,
        )
        items = res.get("items") or []
        if not items:
            return None

        def _created_at(it: Dict[str, Any]) -> str:
            m = it.get("metadata") or {}
            return str(m.get("created_at") or "")

        items_sorted = sorted(items, key=_created_at, reverse=True)
        for it in items_sorted:
            t = (it.get("text") or "").strip()
            if len(t) >= 2:
                return t
        return None
    except Exception as e:
        logger.debug("get_knowledge_greeting_text_failed", owner=owner, category=category, error=str(e))
        return None


def delete_knowledge(vector_db: Any, doc_id: str) -> Dict[str, Any]:
    """지식 1건 삭제 (doc_id로)."""
    if not vector_db or not doc_id:
        return {"ok": False, "error": "vector_db and doc_id required"}
    try:
        vector_db.delete(ids=[doc_id])
        return {"ok": True, "deleted_id": doc_id}
    except Exception as e:
        logger.warning("knowledge_delete_failed", doc_id=doc_id, error=str(e))
        return {"ok": False, "error": str(e)}


def list_knowledge(
    vector_db: Any,
    owner: Optional[str] = None,
    category: Optional[str] = None,
    doc_type: Optional[str] = None,  # 추가
    source: Optional[str] = None,  # 추가
    limit: int = 500,
) -> Dict[str, Any]:
    """지식 목록 조회. owner/category/doc_type/source 필터."""
    if not vector_db:
        return {"items": [], "total": 0}
    owner = normalize_owner_username(owner) if owner else ""
    where = None
    and_cond = []
    if owner:
        and_cond.append({"owner": owner})
    if category:
        and_cond.append({"category": category})
    if doc_type:  # 추가
        and_cond.append({"doc_type": doc_type})
    if source:  # 추가
        and_cond.append({"source": source})
    
    if len(and_cond) > 1:
        where = {"$and": and_cond}
    elif len(and_cond) == 1:
        where = and_cond[0]
    
    try:
        res = vector_db.get(where=where, limit=limit)
        ids = res.get("ids") or []
        documents = res.get("documents") or []
        metadatas = res.get("metadatas") or []
        items = []
        for i, doc_id in enumerate(ids):
            items.append({
                "id": doc_id,
                "text": documents[i] if i < len(documents) else "",
                "metadata": metadatas[i] if i < len(metadatas) else {},
            })
        return {"items": items, "total": len(items)}
    except Exception as e:
        logger.warning("knowledge_list_failed", error=str(e))
        return {"items": [], "total": 0}
