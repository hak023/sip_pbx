"""
도메인 비종속 지식베이스 문서 CRUD 서비스 (Story 1.26, FR32-A).

`document_adapters.py`(소스 파싱) + `knowledge_service.py`(ChromaDB 청크 색인, 무수정 재사용) +
`knowledge_documents_db.py`(SQLite lifecycle 메타데이터)를 조합하는 오케스트레이션 레이어.
벡터 스토어를 직접 조작하는 코드는 여기 없다 — 항상 `knowledge_service`를 경유한다.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

import structlog

from src.ai_voicebot.knowledge.knowledge_service import add_knowledge, delete_knowledge
from src.ai_voicebot.self_service.document_adapters import (
    MarkdownContentAdapter,
    OpenApiSpecAdapter,
    PdfDocumentAdapter,
)
from src.ai_voicebot.self_service.manual_indexer import SELF_SERVICE_MANUAL_DOC_TYPE
from src.common import knowledge_documents_db as db
from src.common.sip_owner import normalize_owner_username

logger = structlog.get_logger(__name__)

# self_service_agent.py / knowledge_base_inventory.py 등에서 doc_type 필터로 재사용 가능
KNOWLEDGE_DOCUMENT_DOC_TYPE = "knowledge_document"

_VALID_SOURCE_TYPES = frozenset({"markdown", "pdf", "openapi"})


def _build_adapter(source_type: str, *, content: Any, title: str):
    if source_type == "markdown":
        # (2026-08-06) MarkdownManualAdapter()는 인자를 받지 않고 항상 내장 매뉴얼 파일만 읽어,
        # 업로드된 content가 완전히 무시된 채 항상 내장 매뉴얼이 재색인되는 버그가 있었다.
        return MarkdownContentAdapter(content, title=title)
    if source_type == "pdf":
        return PdfDocumentAdapter(content, title=title)
    if source_type == "openapi":
        return OpenApiSpecAdapter(content, title=title)
    raise ValueError(f"지원하지 않는 source_type: {source_type}")


def _index_pairs(
    *, pairs_with_meta: List[Dict[str, str]], owner: str, vector_db: Any, embedder: Any,
) -> tuple[List[str], List[str]]:
    """어댑터가 만든 Q&A 페어를 ChromaDB에 색인한다. (chunk_doc_ids, errors) 반환."""
    chunk_doc_ids: List[str] = []
    errors: List[str] = []
    for item in pairs_with_meta:
        doc_content = f"Q: {item['question']}\nA: {item['answer']}"
        result = add_knowledge(
            vector_db=vector_db,
            embedder=embedder,
            text=doc_content,
            owner=owner,
            category="question",
            doc_type=KNOWLEDGE_DOCUMENT_DOC_TYPE,
            source="api",
            answer=item["answer"],
        )
        if result.get("ok"):
            doc_id = result["doc_id"]
            chunk_doc_ids.append(doc_id)
            # (2026-08-07 버그 수정) add_knowledge()는 section_title/related_domain을 받지
            # 않아 어댑터가 파싱한 도메인 메타데이터가 그대로 버려지고 있었다 — manual_indexer.py의
            # 매뉴얼 재색인 경로와 동일하게 색인 직후 메타데이터를 backfill해야 업로드 문서도
            # 도메인별로 정상 그룹핑된다("(도메인 미지정)"으로만 나오던 원인).
            section_title = item.get("section_title", "")
            related_domain = item.get("related_domain", "")
            if section_title or related_domain:
                try:
                    current = vector_db.collection.get(ids=[doc_id], include=["metadatas"])
                    cur_meta = ((current.get("metadatas") or [{}])[0]) or {}
                    cur_meta["section_title"] = section_title
                    cur_meta["related_domain"] = related_domain
                    vector_db.collection.update(ids=[doc_id], metadatas=[cur_meta])
                except Exception as e:
                    logger.warning(
                        "knowledge_document_meta_update_failed", doc_id=doc_id, error=str(e)
                    )
        else:
            errors.append(result.get("error", "unknown_error"))
    return chunk_doc_ids, errors


def register_document(
    *,
    owner: str,
    title: str,
    domain_tags: List[str],
    source_type: str,
    content: Any,
    vector_db: Any,
    embedder: Any,
    uploaded_by: str = "",
    base_url: str = "",
    auth_header_name: str = "",
    auth_header_value: str = "",
) -> Dict[str, Any]:
    """신규 문서를 업로드·색인하고 lifecycle 메타데이터를 저장한다.

    base_url/auth_header_*(Story 1.35 재개, FR34-A): source_type="openapi"이고 base_url이
    비어있으면 어대터가 스펙의 `servers[0].url`을 자동 추출해 사용한다(테넌트 직접
    입력값이 우선). 이 값이 없으면 실행 엔진이 목적지를 모르므로 실행 자체가 불가능하다.

    Returns:
        {"ok": bool, "document_id": str, "indexed_chunks": int, "errors": [...]}
    """
    normalized_owner = normalize_owner_username(owner)
    if not normalized_owner:
        return {"ok": False, "error": "owner가 비었거나 정규화 후 비어 있습니다"}
    if source_type not in _VALID_SOURCE_TYPES:
        return {"ok": False, "error": f"source_type must be one of {sorted(_VALID_SOURCE_TYPES)}"}
    if vector_db is None or embedder is None:
        return {"ok": False, "error": "vector_db/embedder가 필요합니다"}

    try:
        adapter = _build_adapter(source_type, content=content, title=title)
        pairs_with_meta = adapter.load_pairs_with_meta()
    except Exception as exc:
        logger.warning(
            "knowledge_document_parse_failed", owner=normalized_owner, source_type=source_type, error=str(exc)
        )
        return {"ok": False, "error": f"문서 파싱 실패: {exc}"}

    if not pairs_with_meta:
        return {"ok": False, "error": "문서에서 색인 가능한 내용을 추출하지 못했습니다"}

    resolved_base_url = base_url
    if source_type == "openapi" and not resolved_base_url and hasattr(adapter, "extract_base_url"):
        resolved_base_url = adapter.extract_base_url()

    chunk_doc_ids, errors = _index_pairs(
        pairs_with_meta=pairs_with_meta, owner=normalized_owner, vector_db=vector_db, embedder=embedder
    )
    if not chunk_doc_ids:
        return {"ok": False, "error": "색인 실패(청크 0건)", "errors": errors}

    record = db.create_document(
        owner=normalized_owner,
        title=title,
        domain_tags=domain_tags,
        source_type=source_type,
        chunk_doc_ids=chunk_doc_ids,
        uploaded_by=uploaded_by,
        base_url=resolved_base_url,
        auth_header_name=auth_header_name,
        auth_header_value=auth_header_value,
    )
    if record is None:
        # DB 레코드 생성 실패 시 이미 색인된 청크를 롤백해 정합성을 지킨다.
        for chunk_id in chunk_doc_ids:
            delete_knowledge(vector_db, chunk_id)
        return {"ok": False, "error": "문서 메타데이터 저장 실패(색인은 롤백됨)"}

    # Story 1.35 재개(FR34-A): 색인 과정에서 버려지던 엔드포인트 실행 메타를 영속화(best-effort,
    # 실패해도 문서 등록 자체는 이미 성공했으므로 롤백하지 않음 — 실행 시점에 메타가 없으면
    # "정보 없음"으로 처리되는 수준).
    if source_type == "openapi":
        endpoint_meta = [
            item for item in pairs_with_meta
            if item.get("_endpoint_path") and item.get("_method")
        ]
        if endpoint_meta:
            db.save_document_endpoints(record["document_id"], endpoint_meta)

    logger.info(
        "knowledge_document_registered",
        owner=normalized_owner,
        document_id=record["document_id"],
        source_type=source_type,
        indexed_chunks=len(chunk_doc_ids),
    )
    return {
        "ok": True,
        "document_id": record["document_id"],
        "indexed_chunks": len(chunk_doc_ids),
        "errors": errors,
    }


def list_documents(
    *, owner: str, domain_tag: Optional[str] = None, source_type: Optional[str] = None,
) -> Dict[str, Any]:
    normalized_owner = normalize_owner_username(owner)
    if not normalized_owner:
        return {"total": 0, "items": []}
    items = db.list_documents(owner=normalized_owner, domain_tag=domain_tag, source_type=source_type)
    return {"total": len(items), "items": items}


def get_document(*, document_id: str, owner: str) -> Optional[Dict[str, Any]]:
    normalized_owner = normalize_owner_username(owner)
    if not normalized_owner:
        return None
    return db.get_document(document_id, owner=normalized_owner)


def update_document(
    *,
    document_id: str,
    owner: str,
    vector_db: Any,
    embedder: Any,
    title: Optional[str] = None,
    domain_tags: Optional[List[str]] = None,
    text_body: Optional[str] = None,
) -> Dict[str, Any]:
    """메타데이터/본문을 수정한다. `text_body`가 주어지면 기존 청크를 삭제하고 재색인한다."""
    normalized_owner = normalize_owner_username(owner)
    if not normalized_owner:
        return {"ok": False, "error": "owner가 비었거나 정규화 후 비어 있습니다"}

    existing = db.get_document(document_id, owner=normalized_owner)
    if existing is None:
        return {"ok": False, "error": "문서를 찾을 수 없습니다"}

    new_chunk_ids: Optional[List[str]] = None
    reindexed_count = 0
    if text_body is not None:
        if vector_db is None or embedder is None:
            return {"ok": False, "error": "본문 재색인에는 vector_db/embedder가 필요합니다"}
        # 재색인: (마크다운으로 취급 — 업로드 문서의 본문 텍스트는 그 자체를 1개 청크로 색인)
        for chunk_id in existing["chunk_doc_ids"]:
            delete_knowledge(vector_db, chunk_id)
        result = add_knowledge(
            vector_db=vector_db,
            embedder=embedder,
            text=text_body,
            owner=normalized_owner,
            category="question",
            doc_type=KNOWLEDGE_DOCUMENT_DOC_TYPE,
            source="api",
        )
        if not result.get("ok"):
            return {"ok": False, "error": f"재색인 실패: {result.get('error')}"}
        new_chunk_ids = [result["doc_id"]]
        reindexed_count = 1

    updated = db.update_document(
        document_id,
        owner=normalized_owner,
        title=title,
        domain_tags=domain_tags,
        chunk_doc_ids=new_chunk_ids,
    )
    if updated is None:
        return {"ok": False, "error": "메타데이터 갱신 실패"}
    return {"ok": True, "reindexed_chunks": reindexed_count, "document": updated}


def delete_document(*, document_id: str, owner: str, vector_db: Any) -> Dict[str, Any]:
    normalized_owner = normalize_owner_username(owner)
    if not normalized_owner:
        return {"ok": False, "error": "owner가 비었거나 정규화 후 비어 있습니다"}

    existing = db.get_document(document_id, owner=normalized_owner)
    if existing is None:
        return {"ok": False, "error": "문서를 찾을 수 없습니다"}

    deleted_count = 0
    for chunk_id in existing["chunk_doc_ids"]:
        result = delete_knowledge(vector_db, chunk_id)
        if result.get("ok"):
            deleted_count += 1

    ok = db.deactivate_document(document_id, owner=normalized_owner)
    if not ok:
        return {"ok": False, "error": "DB 비활성화 실패(청크는 이미 삭제됨)"}
    logger.info(
        "knowledge_document_deleted", owner=normalized_owner, document_id=document_id, deleted_chunks=deleted_count
    )
    return {"ok": True, "deleted_chunks": deleted_count}


def reset_knowledge_base(*, owner: str, vector_db: Any) -> Dict[str, Any]:
    """owner의 도우미 지식베이스를 전량 초기화한다(Story 1.52).

    Story 1.26 업로드 문서(`knowledge_documents` 테이블에 레코드가 있는 경우)뿐만아니라,
    Story 1.3/2.8 매뉴얼 자동색인(`self_service_manual`, 레코드 없이 ChromaDB에만 존재)까지
    함께 삭제한다 — 기존 단건 삭제 API(`delete_document`)는 document_id가 있는 문서만
    다룰 수 있어, 업로드 없이 자동 색인된 기존 데이터는 삭제할 수 없다는 사용자 지적을 반영.

    (2026-08-07 버그 수정) 처음에는 `knowledge_documents` 행을 소프트 삭제(is_active=0)만
    했는데, 이 시스템의 목적상 "테넌트마다 별개로 업로드한 원격 REST-API 설정(base_url/인증/
    승인된 쓰기 메서드/엔드포인트 메타)"까지 완전히 초기화되어야 한다는 지적을 반영해
    `knowledge_documents`/`knowledge_document_endpoints`/`tool_execution_log`를 실제로 하드
    삭제하도록 변경(`purge_all_documents()`) — 소프트 삭제로는 이 REST-API 실행 설정 잔재가
    DB에 그대로 남아 "전체 삭제해도 일부가 남아있다"는 버그로 이어졌다.

    Returns:
        {"ok": bool, "deleted_chunks": int, "deleted_documents": int, "deleted_endpoints": int,
         "deleted_execution_logs": int, "error": str | None}
    """
    normalized_owner = normalize_owner_username(owner)
    if not normalized_owner:
        return {"ok": False, "error": "owner가 비었거나 정규화 후 비어 있습니다"}
    if vector_db is None:
        return {"ok": False, "error": "vector_db가 필요합니다"}

    where = {
        "$and": [
            {"owner": normalized_owner},
            {"doc_type": {"$in": [KNOWLEDGE_DOCUMENT_DOC_TYPE, SELF_SERVICE_MANUAL_DOC_TYPE]}},
        ]
    }
    try:
        existing = vector_db.get(where=where, limit=100000)
        chunk_ids = list(existing.get("ids") or [])
    except Exception as exc:
        logger.warning("knowledge_base_reset_list_failed", owner=normalized_owner, error=str(exc))
        return {"ok": False, "error": f"기존 청크 조회 실패: {exc}"}

    deleted_chunks = 0
    if chunk_ids:
        try:
            vector_db.delete(ids=chunk_ids)
            deleted_chunks = len(chunk_ids)
        except Exception as exc:
            logger.warning("knowledge_base_reset_delete_failed", owner=normalized_owner, error=str(exc))
            return {"ok": False, "error": f"청크 삭제 실패: {exc}"}

    purge_result = db.purge_all_documents(normalized_owner)

    # NFR11(2026-08-07): 테넌트가 커스터마이즈한 카탈로그/screen_graph 버전(owner-scoped)도
    # 함께 초기화한다 — 전역 기본값(owner='')은 다른 테넌트에 영향을 주므로 여기서 지우지 않는다.
    # (2026-08-07 재수정) 단순 삭제(purge)만 하면 owner 전용 행이 사라진 직후 전역 기본값으로
    # 폴백해버려 "삭제했는데 그대로 보인다"는 문제가 있었다 — clear_owner_catalog()가 삭제 후
    # owner 전용 빈 버전을 활성화해 실제로 0건으로 보이게 한다.
    deleted_catalog_versions = 0
    try:
        from src.common.self_service_catalog_config_db import clear_owner_catalog

        deleted_catalog_versions = clear_owner_catalog(normalized_owner)
    except Exception as exc:
        logger.warning("knowledge_base_reset_catalog_purge_failed", owner=normalized_owner, error=str(exc))

    logger.info(
        "knowledge_base_reset_done",
        owner=normalized_owner,
        deleted_chunks=deleted_chunks,
        deleted_catalog_versions=deleted_catalog_versions,
        **purge_result,
    )
    return {
        "ok": True,
        "deleted_chunks": deleted_chunks,
        "deleted_catalog_versions": deleted_catalog_versions,
        **purge_result,
    }

