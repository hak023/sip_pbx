"""
지식 추가/조회 서비스 (CHROMADB_CATEGORY_DESIGN).

- add_knowledge: knowledge 컬렉션에 category 메타데이터로 저장.
- greeting_phase1/2, farewell 인 경우 qa_cache 즉시 upsert (TTL 7일).
- help 카테고리 직접 등록 시 qa_cache(intent=help) 즉시 upsert.
- build_help_cache_on_startup(): 서버 기동 시 호출.
    1. help 카테고리 KB가 있으면 → 해당 내용으로 qa_cache(intent=help) 구성.
    2. help 카테고리 KB가 없으면 → question(질의/FAQ) 목록에서 LLM으로
       안내 제목을 추출해 qa_cache(intent=help) 최대 5개 구성.
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
    "help",     # "뭘 도와드릴 수 있어요?" 안내 멘트 직접 입력 전용
                # — 등록 시 qa_cache(intent=help) 즉시 upsert
                # — 없으면 서버 기동 시 question KB에서 자동 구성
})
IMMEDIATE_CACHE_CATEGORIES = frozenset({"greeting_phase1", "greeting_phase2", "farewell"})
# help 캐시 상한: qa_cache에서 intent=help 항목 최대 개수
HELP_CACHE_MAX_ITEMS = 5
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
    doc_type: str = "knowledge",
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
    question 이면 KB 등록 후 LLM으로 항목 제목을 추출해 qa_cache(intent=help) upsert 신호를 반환
    (API에서 비동기로 immediate_cache_for_help 호출).
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

    # greeting/farewell 즉시 캐싱 신호 — API에서 immediate_cache_for_knowledge 호출
    if category in IMMEDIATE_CACHE_CATEGORIES:
        ans = (answer or "").strip()
        response_text = (ans if ans else text).strip()
        if len(response_text) >= 2:
            result["needs_immediate_cache"] = True
            result["_cache_query_text"] = text
            result["_cache_answer_text"] = response_text

    # help 카테고리 직접 등록 시 qa_cache(intent=help) 즉시 upsert 신호
    # — API에서 immediate_cache_for_help_direct 호출
    if category == "help":
        ans = (answer or "").strip()
        response_text = (ans if ans else text).strip()
        if len(response_text) >= 2:
            result["needs_help_direct_cache"] = True
            result["_help_cache_text"] = text          # 검색 키 문구
            result["_help_cache_answer"] = response_text  # 실제 안내 내용

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


async def immediate_cache_for_help_direct(
    vector_db: Any,
    embedder: Any,
    help_text: str,
    help_answer: str,
    owner: str,
) -> None:
    """help 카테고리 KB 직접 등록 시 qa_cache(intent=help)에 즉시 upsert.

    help_text  : 검색 키 문구 (예: "주차 방법 안내", "영업시간 문의")
    help_answer: 실제 안내 멘트 (예: "화요일부터 일요일까지 영업합니다.")
    """
    if not help_text or not help_answer:
        raise ValueError("help_text와 help_answer 필수")

    loop = asyncio.get_event_loop()
    embedding = await loop.run_in_executor(
        None, lambda: _get_embedding(embedder, help_text)
    )
    if not embedding:
        raise ValueError("embedding failed")

    doc_id = f"cache_help_direct_{owner}_{hash(help_text) % 10**10}"
    metadata = {
        "answer": help_answer,
        "confidence": 0.95,
        "intent": "help",
        "category": "help",
        "cached_at": datetime.now().isoformat(),
        "ttl": TTL_CACHE_SECONDS,
        "owner": owner,
        "cache_label": help_text,
        "source": "direct",
    }
    await vector_db.upsert_to_collection(
        collection_name=QA_CACHE_COLLECTION,
        doc_id=doc_id,
        embedding=embedding,
        text=help_text,
        metadata=metadata,
    )
    logger.info(
        "help_cache_direct_upserted",
        owner=owner,
        help_text=help_text,
        answer_preview=help_answer[:60],
    )


async def _extract_help_label_via_llm(
    llm: Any,
    kb_text: str,
    owner: str,
) -> str:
    """LLM으로 KB 내용에서 짧은 안내 제목 추출. 실패 시 kb_text[:15] + ' 안내' 폴백."""
    import json as _json
    import re as _re

    label_prompt = (
        "아래 지식 내용을 보고, 이 정보를 찾는 사람이 물어볼 만한 짧은 안내 제목을 만들어줘.\n"
        "형식: 반드시 '제목' 필드 하나만 포함된 JSON 한 줄로 답해.\n"
        '예시: {"제목": "주차 방법 안내"}\n\n'
        f"[지식 내용]\n{kb_text[:400]}"
    )
    try:
        if hasattr(llm, "generate_simple"):
            raw = await llm.generate_simple(label_prompt, max_tokens=64, timeout_seconds=10.0)
        elif hasattr(llm, "generate_response"):
            raw = await llm.generate_response(label_prompt, context_docs=[])
        else:
            raw = ""

        if raw:
            m = _re.search(r'\{[^}]+\}', raw)
            if m:
                parsed = _json.loads(m.group())
                label = (parsed.get("제목") or "").strip()
                if label:
                    return label

        fallback = kb_text.strip()[:15].rstrip() + " 안내"
        logger.warning("help_label_llm_fallback", owner=owner, fallback=fallback, raw_preview=(raw or "")[:80])
        return fallback
    except Exception as e:
        fallback = kb_text.strip()[:15].rstrip() + " 안내"
        logger.warning("help_label_llm_error", owner=owner, error=str(e), fallback=fallback)
        return fallback


async def build_help_cache_on_startup(
    vector_db: Any,
    embedder: Any,
    llm: Any,
    owner: str,
) -> None:
    """서버 기동 시 owner별 qa_cache(intent=help)를 구성.

    우선순위:
    1. help 카테고리 KB가 있으면 → 해당 항목들로 qa_cache(intent=help) upsert.
       (운영자가 직접 작성한 안내 멘트 우선)
    2. help 카테고리 KB가 없으면 → question(질의/FAQ) KB 목록에서 LLM으로
       안내 제목을 추출해 qa_cache(intent=help) 최대 HELP_CACHE_MAX_ITEMS개 구성.

    CLEAR_QA_CACHE_ON_START=1(기본값)이면 기동 시 qa_cache가 초기화되므로
    이 함수는 그 이후에 호출해야 한다.
    """
    if not vector_db or not embedder or not owner:
        logger.warning("build_help_cache_skipped", owner=owner, reason="missing dependencies")
        return

    _owner = normalize_owner_username(owner)
    if not _owner:
        return

    # ── 1단계: help 카테고리 KB 확인 ──────────────────────────────────────
    try:
        help_kb = list_knowledge(vector_db, owner=_owner, category="help", limit=HELP_CACHE_MAX_ITEMS + 5)
        help_items = (help_kb or {}).get("items") or []
    except Exception as e:
        logger.warning("build_help_cache_list_help_failed", owner=_owner, error=str(e))
        help_items = []

    if help_items:
        # help 직접 입력 항목이 있음 → 해당 내용으로 qa_cache 구성
        logger.info(
            "build_help_cache_from_help_kb",
            owner=_owner,
            count=len(help_items),
            note="help 카테고리 KB 발견 → 직접 입력 멘트로 qa_cache(intent=help) 구성",
        )
        for item in help_items[:HELP_CACHE_MAX_ITEMS]:
            item_text = (item.get("text") or "").strip()
            if len(item_text) < 2:
                continue
            try:
                await immediate_cache_for_help_direct(
                    vector_db=vector_db,
                    embedder=embedder,
                    help_text=item_text,
                    help_answer=item_text,
                    owner=_owner,
                )
            except Exception as e:
                logger.warning("build_help_cache_item_failed", owner=_owner, error=str(e))
        logger.info("build_help_cache_done_from_help_kb", owner=_owner)
        return

    # ── 2단계: help KB 없음 → question KB에서 자동 추출 ───────────────────
    if not llm:
        logger.info(
            "build_help_cache_skipped_no_llm",
            owner=_owner,
            note="help KB 없고 LLM 미설정 — help 캐시 구성 불가",
        )
        return

    try:
        question_kb = list_knowledge(
            vector_db, owner=_owner, category="question",
            limit=HELP_CACHE_MAX_ITEMS * 4,  # 후보를 넉넉히 가져와서 상위 N개 선정
        )
        question_items = (question_kb or {}).get("items") or []
    except Exception as e:
        logger.warning("build_help_cache_list_question_failed", owner=_owner, error=str(e))
        return

    if not question_items:
        logger.info("build_help_cache_no_question_kb", owner=_owner, note="question KB도 없음 — 스킵")
        return

    logger.info(
        "build_help_cache_from_question_kb",
        owner=_owner,
        question_count=len(question_items),
        max_labels=HELP_CACHE_MAX_ITEMS,
        note="help KB 없음 → question KB에서 LLM으로 안내 제목 추출",
    )

    loop = asyncio.get_event_loop()
    inserted = 0
    for item in question_items:
        if inserted >= HELP_CACHE_MAX_ITEMS:
            break
        kb_text = (item.get("text") or "").strip()
        if len(kb_text) < 2:
            continue
        try:
            label = await _extract_help_label_via_llm(llm, kb_text, _owner)
            embedding = await loop.run_in_executor(
                None, lambda lbl=label: _get_embedding(embedder, lbl)
            )
            if not embedding:
                continue

            doc_id = f"cache_help_auto_{_owner}_{hash(label) % 10**10}"
            metadata = {
                "answer": kb_text,
                "confidence": 0.88,
                "intent": "help",
                "category": "question",
                "cached_at": datetime.now().isoformat(),
                "ttl": TTL_CACHE_SECONDS,
                "owner": _owner,
                "cache_label": label,
                "source": "auto",
            }
            await vector_db.upsert_to_collection(
                collection_name=QA_CACHE_COLLECTION,
                doc_id=doc_id,
                embedding=embedding,
                text=label,
                metadata=metadata,
            )
            logger.info("build_help_cache_label_inserted", owner=_owner, label=label, inserted=inserted + 1)
            inserted += 1
        except Exception as e:
            logger.warning("build_help_cache_label_failed", owner=_owner, error=str(e))

    logger.info(
        "build_help_cache_done_from_question_kb",
        owner=_owner,
        inserted=inserted,
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
