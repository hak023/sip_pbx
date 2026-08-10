"""
도메인 비종속 지식베이스 문서 CRUD API (Story 1.26, FR32-A).

`settings_ai_assistant.py`(카탈로그/매뉴얼 조회 전용)와 별개의 신규 라우터다 — 이 API는
셀프서비스 매뉴얼에 국한되지 않는 범용 지식 문서(마크다운/PDF/OpenAPI)의 업로드·조회·수정·
삭제를 다룬다(설계: docs/design/SELF_SERVICE_RAG_INTELLIDECISION_ADVANCEMENT_RESEARCH.md §4).

엔드포인트
-----------
  POST   /api/knowledge-base/documents              업로드(멀티파트: 메타데이터 + 파일/텍스트,
                                                      openapi는 base_url/인증 헤더 포함 가능, Story 1.35)
  GET    /api/knowledge-base/documents               목록(owner/domain_tag/source_type 필터)
  GET    /api/knowledge-base/documents/{document_id} 단건 조회
  PUT    /api/knowledge-base/documents/{document_id} 메타데이터/본문 수정(재색인)
  DELETE /api/knowledge-base/documents/{document_id} 삭제(색인에서도 제거)
  PATCH  /api/knowledge-base/documents/{document_id}/approve-methods 쓰기 메서드 승인(Story 1.34)
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from fastapi import APIRouter, File, Form, HTTPException, Query, UploadFile
from pydantic import BaseModel

router = APIRouter(prefix="/api/knowledge-base", tags=["knowledge-base-documents"])


class KnowledgeDocumentItem(BaseModel):
    document_id: str
    owner: str
    title: str
    domain_tags: List[str]
    source_type: str
    approved_methods: List[str] = []
    # Story 1.35 재개(FR34-A): base_url은 그대로 노출(실행 대상 확인용), 인증 값은 마스킹만 노출
    base_url: str = ""
    has_auth: bool = False
    version_no: int
    uploaded_by: str
    uploaded_at: str
    updated_at: str
    chunk_count: int


class KnowledgeDocumentUploadResponse(BaseModel):
    ok: bool
    document_id: Optional[str] = None
    indexed_chunks: int = 0
    errors: List[str] = []
    error: Optional[str] = None


class KnowledgeDocumentListResponse(BaseModel):
    total: int
    items: List[KnowledgeDocumentItem]


class KnowledgeDocumentUpdateRequest(BaseModel):
    title: Optional[str] = None
    domain_tags: Optional[List[str]] = None
    text_body: Optional[str] = None


class KnowledgeDocumentUpdateResponse(BaseModel):
    ok: bool
    reindexed_chunks: int = 0
    error: Optional[str] = None


class KnowledgeDocumentDeleteResponse(BaseModel):
    ok: bool
    deleted_chunks: int = 0
    error: Optional[str] = None


class KnowledgeBaseResetResponse(BaseModel):
    ok: bool
    deleted_chunks: int = 0
    deleted_documents: int = 0
    deleted_endpoints: int = 0
    deleted_execution_logs: int = 0
    deleted_catalog_versions: int = 0
    error: Optional[str] = None


# Story 1.34(FR34-A) — 쓰기 메서드 승인 모델
class ApproveMethodsRequest(BaseModel):
    approved_methods: List[str]  # 승인할 쓰기 메서드 목록(GET은 자동 포함, POST/PUT/PATCH/DELETE만 허용)


class ApproveMethodsResponse(BaseModel):
    ok: bool
    approved_methods: List[str] = []
    error: Optional[str] = None


def _knowledge_service():
    """전역 KnowledgeService 반환. 없으면 503 (settings_ai_assistant.py와 동일 패턴)."""
    try:
        from src.services.knowledge_service import get_knowledge_service

        ks = get_knowledge_service()
        if ks is None:
            raise HTTPException(
                status_code=503,
                detail="KnowledgeService가 초기화되지 않았습니다. AI 서버가 기동 중인지 확인하세요.",
            )
        return ks
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=503, detail=f"KnowledgeService 접근 실패: {e}") from e


def _to_document_item(record: Dict[str, Any]) -> KnowledgeDocumentItem:
    return KnowledgeDocumentItem(
        document_id=record["document_id"],
        owner=record["owner"],
        title=record["title"],
        domain_tags=record["domain_tags"],
        source_type=record["source_type"],
        approved_methods=record.get("approved_methods") or ["GET"],
        base_url=record.get("base_url") or "",
        has_auth=bool(record.get("auth_header_value")),
        version_no=record["version_no"],
        uploaded_by=record["uploaded_by"],
        uploaded_at=record["uploaded_at"],
        updated_at=record["updated_at"],
        chunk_count=len(record["chunk_doc_ids"]),
    )


@router.post(
    "/documents", response_model=KnowledgeDocumentUploadResponse, summary="지식 문서 업로드",
)
def upload_knowledge_document(
    owner: str = Form(...),
    title: str = Form(...),
    domain_tags: str = Form("", description="콤마 구분 태그 목록"),
    source_type: str = Form(..., description="markdown | pdf | openapi"),
    text_body: Optional[str] = Form(None, description="markdown/openapi는 텍스트로 직접 입력 가능"),
    file: Optional[UploadFile] = File(None, description="pdf는 파일 업로드 필수"),
    base_url: str = Form("", description="openapi 대상 시스템의 전체 기본 URL(비워두면 스펙 servers에서 자동 추출 시도)"),
    auth_header_name: str = Form("", description="인증 헤더명(예: Authorization)"),
    auth_header_value: str = Form("", description="인증 헤더 값(평문 저장되나 응답/로그에는 항상 마스킹)"),
) -> KnowledgeDocumentUploadResponse:
    # (2026-08-06) 임베딩/색인 처리가 수십 초 걸릴 수 있는데 이 라우터가 유일하게 async def였던
    # 탓에 실행 중 SIP·WebSocket과 공유하는 이벤트 루프 전체가 블로킹됐다("Failed to fetch"의
    # 원인). 나머지 PUT/DELETE 엔드포인트처럼 동기 def로 바꿔 FastAPI 스레드풀에서 실행되게 한다.
    ks = _knowledge_service()
    tags = [t.strip() for t in domain_tags.split(",") if t.strip()]

    if source_type == "pdf":
        if file is None:
            raise HTTPException(status_code=400, detail="pdf source_type은 file 업로드가 필수입니다")
        content: Any = file.file.read()
    else:
        if text_body is None:
            raise HTTPException(status_code=400, detail=f"{source_type} source_type은 text_body가 필수입니다")
        content = text_body

    from src.ai_voicebot.self_service.knowledge_documents import register_document

    result = register_document(
        owner=owner,
        title=title,
        domain_tags=tags,
        source_type=source_type,
        content=content,
        vector_db=ks.vector_db,
        embedder=ks.embedder,
        base_url=base_url,
        auth_header_name=auth_header_name,
        auth_header_value=auth_header_value,
    )
    return KnowledgeDocumentUploadResponse(**result)


@router.get(
    "/documents", response_model=KnowledgeDocumentListResponse, summary="지식 문서 목록",
)
def list_knowledge_documents(
    owner: str = Query(...),
    domain_tag: Optional[str] = Query(None),
    source_type: Optional[str] = Query(None),
) -> KnowledgeDocumentListResponse:
    from src.ai_voicebot.self_service.knowledge_documents import list_documents

    result = list_documents(owner=owner, domain_tag=domain_tag, source_type=source_type)
    return KnowledgeDocumentListResponse(
        total=result["total"], items=[_to_document_item(it) for it in result["items"]]
    )


@router.get(
    "/documents/{document_id}", response_model=KnowledgeDocumentItem, summary="지식 문서 단건 조회",
)
def get_knowledge_document(document_id: str, owner: str = Query(...)) -> KnowledgeDocumentItem:
    from src.ai_voicebot.self_service.knowledge_documents import get_document

    record = get_document(document_id=document_id, owner=owner)
    if record is None:
        raise HTTPException(status_code=404, detail="문서를 찾을 수 없습니다")
    return _to_document_item(record)


@router.put(
    "/documents/{document_id}", response_model=KnowledgeDocumentUpdateResponse, summary="지식 문서 수정",
)
def update_knowledge_document(
    document_id: str, payload: KnowledgeDocumentUpdateRequest, owner: str = Query(...),
) -> KnowledgeDocumentUpdateResponse:
    ks = _knowledge_service()
    from src.ai_voicebot.self_service.knowledge_documents import update_document

    result = update_document(
        document_id=document_id,
        owner=owner,
        vector_db=ks.vector_db,
        embedder=ks.embedder,
        title=payload.title,
        domain_tags=payload.domain_tags,
        text_body=payload.text_body,
    )
    return KnowledgeDocumentUpdateResponse(
        ok=bool(result.get("ok")),
        reindexed_chunks=int(result.get("reindexed_chunks") or 0),
        error=result.get("error"),
    )


@router.delete(
    "/documents/{document_id}", response_model=KnowledgeDocumentDeleteResponse, summary="지식 문서 삭제",
)
def delete_knowledge_document(document_id: str, owner: str = Query(...)) -> KnowledgeDocumentDeleteResponse:
    ks = _knowledge_service()
    from src.ai_voicebot.self_service.knowledge_documents import delete_document

    result = delete_document(document_id=document_id, owner=owner, vector_db=ks.vector_db)
    return KnowledgeDocumentDeleteResponse(
        ok=bool(result.get("ok")),
        deleted_chunks=int(result.get("deleted_chunks") or 0),
        error=result.get("error"),
    )


@router.delete(
    "/documents", response_model=KnowledgeBaseResetResponse,
    summary="도우미 지식베이스 전체 초기화(Story 1.52)",
)
def reset_knowledge_base(owner: str = Query(...)) -> KnowledgeBaseResetResponse:
    """owner의 도우미 지식베이스 전체를 삭제한다.

    `DELETE /documents/{document_id}`와 달리 업로드 이력(`knowledge_documents` 레코드)이
    없는 기존 데이터(Story 1.3/2.8 매뉴얼 자동색인 등)도 함께 지운다 — 사용자가
    "업로드한 적 없는 기존 데이터는 삭제할 수 없다"고 보고한 공백을 메우는 전용 API다.
    (2026-08-07) 단순 비활성화가 아니라 `knowledge_document_endpoints`(REST-API 엔드포인트
    메타)/`tool_execution_log`(승인·실행·Undo 이력)까지 하드 삭제해 원격 시스템 실행 설정
    잔재가 남지 않도록 보완함(테넌트별 원격 REST-API 설정이 완전히 초기화되어야 한다는
    요구사항 반영). 위험한 일괄 삭제이므로 프론트는 반드시 확인 다이얼로그 후 호출해야 한다.
    """
    ks = _knowledge_service()
    from src.ai_voicebot.self_service.knowledge_documents import reset_knowledge_base as _reset

    result = _reset(owner=owner, vector_db=ks.vector_db)
    return KnowledgeBaseResetResponse(
        ok=bool(result.get("ok")),
        deleted_chunks=int(result.get("deleted_chunks") or 0),
        deleted_documents=int(result.get("deleted_documents") or 0),
        deleted_endpoints=int(result.get("deleted_endpoints") or 0),
        deleted_execution_logs=int(result.get("deleted_execution_logs") or 0),
        deleted_catalog_versions=int(result.get("deleted_catalog_versions") or 0),
        error=result.get("error"),
    )


@router.patch(
    "/documents/{document_id}/approve-methods",
    response_model=ApproveMethodsResponse,
    summary="쓰기 메서드 승인(Story 1.34, FR34-A)",
)
def approve_document_methods(
    document_id: str,
    payload: ApproveMethodsRequest,
    owner: str = Query(...),
) -> ApproveMethodsResponse:
    """업로드된 OpenAPI 스펙의 엔드포인트 중 쓰기 메서드(POST/PUT/PATCH/DELETE)를 테넌트가 명시적으로 승인한다.

    GET은 항상 능동 상태이며 이 API로 제거할 수 없다. 알 수 없는 메서드는 조용히 무시한다(NFR9 — 화이트리스트).
    실제 API 호출 실행 엔진(Story 1.35)은 이 승인 목록이 있는 경우에만 쓰기 요청을 허용한다.
    """
    from src.common.knowledge_documents_db import update_approved_methods

    result = update_approved_methods(
        document_id=document_id, owner=owner, approved_methods=payload.approved_methods
    )
    if result is None:
        raise HTTPException(status_code=404, detail="문서를 찾을 수 없거나 owner가 일치하지 않습니다.")
    return ApproveMethodsResponse(ok=True, approved_methods=result.get("approved_methods") or ["GET"])
