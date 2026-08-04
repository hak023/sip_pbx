"""
도메인 비종속 지식베이스 문서 CRUD API (Story 1.26, FR32-A).

`settings_ai_assistant.py`(카탈로그/매뉴얼 조회 전용)와 별개의 신규 라우터다 — 이 API는
셀프서비스 매뉴얼에 국한되지 않는 범용 지식 문서(마크다운/PDF/OpenAPI)의 업로드·조회·수정·
삭제를 다룬다(설계: docs/design/SELF_SERVICE_RAG_INTELLIDECISION_ADVANCEMENT_RESEARCH.md §4).

엔드포인트
-----------
  POST   /api/knowledge-base/documents              업로드(멀티파트: 메타데이터 + 파일/텍스트)
  GET    /api/knowledge-base/documents               목록(owner/domain_tag/source_type 필터)
  GET    /api/knowledge-base/documents/{document_id} 단건 조회
  PUT    /api/knowledge-base/documents/{document_id} 메타데이터/본문 수정(재색인)
  DELETE /api/knowledge-base/documents/{document_id} 삭제(색인에서도 제거)
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
        version_no=record["version_no"],
        uploaded_by=record["uploaded_by"],
        uploaded_at=record["uploaded_at"],
        updated_at=record["updated_at"],
        chunk_count=len(record["chunk_doc_ids"]),
    )


@router.post(
    "/documents", response_model=KnowledgeDocumentUploadResponse, summary="지식 문서 업로드",
)
async def upload_knowledge_document(
    owner: str = Form(...),
    title: str = Form(...),
    domain_tags: str = Form("", description="콤마 구분 태그 목록"),
    source_type: str = Form(..., description="markdown | pdf | openapi"),
    text_body: Optional[str] = Form(None, description="markdown/openapi는 텍스트로 직접 입력 가능"),
    file: Optional[UploadFile] = File(None, description="pdf는 파일 업로드 필수"),
) -> KnowledgeDocumentUploadResponse:
    ks = _knowledge_service()
    tags = [t.strip() for t in domain_tags.split(",") if t.strip()]

    if source_type == "pdf":
        if file is None:
            raise HTTPException(status_code=400, detail="pdf source_type은 file 업로드가 필수입니다")
        content: Any = await file.read()
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
