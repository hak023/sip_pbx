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
    # Story 1.34(FR34-A): 승인된 쓰기 메서드 목록
    try:
        d["approved_methods"] = json.loads(d.pop("approved_methods_json") or '["GET"]')
    except (json.JSONDecodeError, TypeError):
        d["approved_methods"] = ["GET"]
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
    base_url: str = "",
    auth_header_name: str = "",
    auth_header_value: str = "",
) -> Optional[Dict[str, Any]]:
    """신규 문서 레코드를 생성한다. 반환값은 생성된 레코드(dict), 실패 시 None.

    base_url/auth_header_*(Story 1.35 재개, FR34-A): 임의 외부 시스템 실행에 필요한 목적지·인증
    정보. auth_header_value는 평문 저장되나 API 응답/로그에는 항상 마스킹된다(OWASP).
    """
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
                "  chunk_doc_ids_json, version_no, is_active, uploaded_by,"
                "  base_url, auth_header_name, auth_header_value)"
                " VALUES (?, ?, ?, ?, ?, ?, 1, 1, ?, ?, ?, ?)",
                (
                    document_id,
                    owner,
                    title,
                    json.dumps(domain_tags, ensure_ascii=False),
                    source_type,
                    json.dumps(chunk_doc_ids, ensure_ascii=False),
                    uploaded_by,
                    base_url,
                    auth_header_name,
                    auth_header_value,
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


# ---------------------------------------------------------------------------
# Story 1.34 (FR34-A) — 쓰기 메서드 승인 관리
# GET은 기본 능동(승인 불필요), POST/PUT/PATCH/DELETE는 테넌트가 명시적으로 승인해야 활성화.
# "제외 목록" 대신 "화이트리스트" 방식을 택한 이유: 임의 외부 시스템 API는 신뢰도 미검증 —
# Epic 2와 달리 기본 거부 + 명시적 승인이 더 안전하다(NFR9).
# ---------------------------------------------------------------------------

_ALLOWED_WRITE_METHODS = frozenset({"POST", "PUT", "PATCH", "DELETE"})


def update_approved_methods(
    document_id: str,
    *,
    owner: str,
    approved_methods: List[str],
) -> Optional[Dict[str, Any]]:
    """쓰기 메서드 승인 목록을 갱신한다(Story 1.34, FR34-A).

    GET은 항상 포함된다(기본 능동). 나머지는 `_ALLOWED_WRITE_METHODS`에 속한 값만 허용하고
    목록에 없거나 알 수 없는 메서드는 조용히 무시한다(잘못된 입력이 실행 엔진에 전달되지 않도록).
    """
    if not _DB_AVAILABLE:
        return None
    get_db = _get_db()
    if get_db is None:
        return None

    # GET은 항상 포함, 허용된 쓰기 메서드만 필터링
    cleaned = ["GET"] + sorted(
        {m.upper() for m in approved_methods if m.upper() in _ALLOWED_WRITE_METHODS}
    )

    try:
        with get_db() as conn:
            cur = conn.execute(
                "UPDATE knowledge_documents"
                " SET approved_methods_json = ?, updated_at = datetime('now','localtime')"
                " WHERE document_id = ? AND owner = ? AND is_active = 1",
                (json.dumps(cleaned, ensure_ascii=False), document_id, owner),
            )
        if cur.rowcount == 0:
            return None
        return get_document(document_id, owner=owner)
    except Exception as exc:
        logger.warning(
            "knowledge_documents_update_approved_failed document_id=%s err=%s", document_id, exc
        )
        return None


# ---------------------------------------------------------------------------
# Story 1.35 재개 (FR34-A, 2026-08-06) — 엔드포인트 실행 메타데이터 영속화
# 색인 과정(question/answer 추출)에서 버려지던 method/path/parameters/request_body를
# 별도 테이블에 저장해, 실행 시점에 document_id+method+endpoint_path로 복원 가능하게 한다.
# ---------------------------------------------------------------------------

def save_document_endpoints(
    document_id: str,
    endpoints: List[Dict[str, Any]],
) -> bool:
    """어댑터가 만든 엔드포인트 메타 리스트를 일괄 저장한다.

    각 항목은 `endpoint_path`/`method`/`parameters`/`request_body` 키를 가진 dict여야 한다
    (`OpenApiSpecAdapter.load_pairs_with_meta()`가 만든 `_endpoint_path`/`_method`/
    `_parameters`/`_request_body` 필드를 그대로 전달하면 된다).
    """
    if not _DB_AVAILABLE or not endpoints:
        return False
    get_db = _get_db()
    if get_db is None:
        return False

    try:
        with get_db() as conn:
            for ep in endpoints:
                conn.execute(
                    "INSERT INTO knowledge_document_endpoints"
                    " (document_id, method, endpoint_path, parameters_json, request_body_json)"
                    " VALUES (?, ?, ?, ?, ?)",
                    (
                        document_id,
                        str(ep.get("method") or ep.get("_method") or ""),
                        str(ep.get("endpoint_path") or ep.get("_endpoint_path") or ""),
                        json.dumps(ep.get("parameters") or ep.get("_parameters") or [], ensure_ascii=False),
                        json.dumps(ep.get("request_body") or ep.get("_request_body")) if
                        (ep.get("request_body") or ep.get("_request_body")) is not None else None,
                    ),
                )
        return True
    except Exception as exc:
        logger.warning("knowledge_document_endpoints_save_failed document_id=%s err=%s", document_id, exc)
        return False


def get_document_endpoint(
    document_id: str, *, method: str, endpoint_path: str,
) -> Optional[Dict[str, Any]]:
    """특정 엔드포인트(method+path)의 실행 메타를 조회한다. 없으면 None."""
    if not _DB_AVAILABLE:
        return None
    get_db = _get_db()
    if get_db is None:
        return None

    try:
        with get_db() as conn:
            row = conn.execute(
                "SELECT * FROM knowledge_document_endpoints"
                " WHERE document_id = ? AND method = ? AND endpoint_path = ?"
                " ORDER BY id DESC LIMIT 1",
                (document_id, method.upper(), endpoint_path),
            ).fetchone()
        if row is None:
            return None
        d = dict(row)
        try:
            d["parameters"] = json.loads(d.pop("parameters_json") or "[]")
        except (json.JSONDecodeError, TypeError):
            d["parameters"] = []
        rb = d.pop("request_body_json", None)
        d["request_body"] = json.loads(rb) if rb else None
        return d
    except Exception as exc:
        logger.warning("knowledge_document_endpoint_get_failed document_id=%s err=%s", document_id, exc)
        return None


def list_document_endpoints(document_id: str) -> List[Dict[str, Any]]:
    """문서에 속한 모든 엔드포인트 메타를 반환한다(Story 1.37 카드 UI 등에서 재사용 가능)."""
    if not _DB_AVAILABLE:
        return []
    get_db = _get_db()
    if get_db is None:
        return []

    try:
        with get_db() as conn:
            rows = conn.execute(
                "SELECT * FROM knowledge_document_endpoints WHERE document_id = ? ORDER BY id ASC",
                (document_id,),
            ).fetchall()
        results = []
        for row in rows:
            d = dict(row)
            try:
                d["parameters"] = json.loads(d.pop("parameters_json") or "[]")
            except (json.JSONDecodeError, TypeError):
                d["parameters"] = []
            rb = d.pop("request_body_json", None)
            d["request_body"] = json.loads(rb) if rb else None
            results.append(d)
        return results
    except Exception as exc:
        logger.warning("knowledge_document_endpoints_list_failed document_id=%s err=%s", document_id, exc)
        return []

