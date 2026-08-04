"""
도메인 비종속 지식베이스 문서 lifecycle SQLite 헬퍼 (Story 1.26, FR32-A).

booking.db와 동일 파일을 공유한다(src.booking.database). 청크(임베딩)는 ChromaDB가 소유하며,
이 모듈은 "어떤 문서가 어떤 청크로 색인됐는지"만 추적하는 순수 lifecycle CRUD다 — 벡터 스토어
조작은 포함하지 않는다(호출측인 `knowledge_documents.py` 서비스 레이어가 담당).
"""

from __future__ import annotations

import json
import logging
import uuid
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

_DB_AVAILABLE = True


def _row_to_dict(row) -> Dict[str, Any]:
    d = dict(row)
    try:
        d["domain_tags"] = json.loads(d.pop("domain_tags_json") or "[]")
    except (json.JSONDecodeError, TypeError):
        d["domain_tags"] = []
    try:
        d["chunk_doc_ids"] = json.loads(d.pop("chunk_doc_ids_json") or "[]")
    except (json.JSONDecodeError, TypeError):
        d["chunk_doc_ids"] = []
    d["is_active"] = bool(d.get("is_active"))
    return d


def _get_db():
    global _DB_AVAILABLE
    try:
        from src.booking.database import get_db

        return get_db
    except ImportError:
        _DB_AVAILABLE = False
        logger.debug("knowledge_documents_db_import_failed")
        return None


def create_document(
    *,
    owner: str,
    title: str,
    domain_tags: List[str],
    source_type: str,
    chunk_doc_ids: List[str],
    uploaded_by: str = "",
) -> Optional[Dict[str, Any]]:
    """신규 문서 레코드를 생성한다. 반환값은 생성된 레코드(dict), 실패 시 None."""
    if not _DB_AVAILABLE:
        return None
    get_db = _get_db()
    if get_db is None:
        return None

    document_id = uuid.uuid4().hex
    try:
        with get_db() as conn:
            conn.execute(
                "INSERT INTO knowledge_documents"
                " (document_id, owner, title, domain_tags_json, source_type,"
                "  chunk_doc_ids_json, version_no, is_active, uploaded_by)"
                " VALUES (?, ?, ?, ?, ?, ?, 1, 1, ?)",
                (
                    document_id,
                    owner,
                    title,
                    json.dumps(domain_tags, ensure_ascii=False),
                    source_type,
                    json.dumps(chunk_doc_ids, ensure_ascii=False),
                    uploaded_by,
                ),
            )
        return get_document(document_id, owner=owner)
    except Exception as exc:
        logger.warning("knowledge_documents_create_failed owner=%s err=%s", owner, exc)
        return None


def get_document(document_id: str, *, owner: Optional[str] = None) -> Optional[Dict[str, Any]]:
    """단건 조회(활성 상태만). owner가 주어지면 테넌트 격리를 검사한다."""
    if not _DB_AVAILABLE:
        return None
    get_db = _get_db()
    if get_db is None:
        return None

    try:
        with get_db() as conn:
            if owner is not None:
                row = conn.execute(
                    "SELECT * FROM knowledge_documents"
                    " WHERE document_id = ? AND owner = ? AND is_active = 1",
                    (document_id, owner),
                ).fetchone()
            else:
                row = conn.execute(
                    "SELECT * FROM knowledge_documents WHERE document_id = ? AND is_active = 1",
                    (document_id,),
                ).fetchone()
        return _row_to_dict(row) if row is not None else None
    except Exception as exc:
        logger.warning("knowledge_documents_get_failed document_id=%s err=%s", document_id, exc)
        return None


def list_documents(
    *,
    owner: str,
    domain_tag: Optional[str] = None,
    source_type: Optional[str] = None,
    limit: int = 500,
) -> List[Dict[str, Any]]:
    """owner의 활성 문서 목록을 최신순으로 조회한다(domain_tag는 파이썬 레벨 필터링)."""
    if not _DB_AVAILABLE:
        return []
    get_db = _get_db()
    if get_db is None:
        return []

    try:
        with get_db() as conn:
            if source_type:
                rows = conn.execute(
                    "SELECT * FROM knowledge_documents"
                    " WHERE owner = ? AND is_active = 1 AND source_type = ?"
                    " ORDER BY uploaded_at DESC LIMIT ?",
                    (owner, source_type, limit),
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT * FROM knowledge_documents"
                    " WHERE owner = ? AND is_active = 1"
                    " ORDER BY uploaded_at DESC LIMIT ?",
                    (owner, limit),
                ).fetchall()
        items = [_row_to_dict(r) for r in rows]
        if domain_tag:
            items = [it for it in items if domain_tag in it.get("domain_tags", [])]
        return items
    except Exception as exc:
        logger.warning("knowledge_documents_list_failed owner=%s err=%s", owner, exc)
        return []


def update_document(
    document_id: str,
    *,
    owner: str,
    title: Optional[str] = None,
    domain_tags: Optional[List[str]] = None,
    chunk_doc_ids: Optional[List[str]] = None,
) -> Optional[Dict[str, Any]]:
    """메타데이터/청크 목록을 갱신한다(전달된 필드만 변경, version_no+1)."""
    if not _DB_AVAILABLE:
        return None
    get_db = _get_db()
    if get_db is None:
        return None

    existing = get_document(document_id, owner=owner)
    if existing is None:
        return None

    new_title = title if title is not None else existing["title"]
    new_tags = domain_tags if domain_tags is not None else existing["domain_tags"]
    new_chunks = chunk_doc_ids if chunk_doc_ids is not None else existing["chunk_doc_ids"]

    try:
        with get_db() as conn:
            conn.execute(
                "UPDATE knowledge_documents"
                " SET title = ?, domain_tags_json = ?, chunk_doc_ids_json = ?,"
                "     version_no = version_no + 1, updated_at = datetime('now','localtime')"
                " WHERE document_id = ? AND owner = ? AND is_active = 1",
                (
                    new_title,
                    json.dumps(new_tags, ensure_ascii=False),
                    json.dumps(new_chunks, ensure_ascii=False),
                    document_id,
                    owner,
                ),
            )
        return get_document(document_id, owner=owner)
    except Exception as exc:
        logger.warning("knowledge_documents_update_failed document_id=%s err=%s", document_id, exc)
        return None


def deactivate_document(document_id: str, *, owner: str) -> bool:
    """소프트 삭제(is_active=0). 실제 청크 삭제는 호출측(서비스 레이어)이 담당한다."""
    if not _DB_AVAILABLE:
        return False
    get_db = _get_db()
    if get_db is None:
        return False

    try:
        with get_db() as conn:
            cur = conn.execute(
                "UPDATE knowledge_documents SET is_active = 0,"
                " updated_at = datetime('now','localtime')"
                " WHERE document_id = ? AND owner = ? AND is_active = 1",
                (document_id, owner),
            )
        return cur.rowcount > 0
    except Exception as exc:
        logger.warning("knowledge_documents_deactivate_failed document_id=%s err=%s", document_id, exc)
        return False
