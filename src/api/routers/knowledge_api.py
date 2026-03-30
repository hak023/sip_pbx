"""
프론트 호환: GET/POST /api/knowledge, DELETE /api/knowledge/{doc_id}

Chroma/임베딩 미구성 시 503과 안내 메시지.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException, Query, UploadFile, File
from pydantic import BaseModel, Field

router = APIRouter(tags=["knowledge-api"])


class KnowledgeCreateBody(BaseModel):
    text: str
    owner: str
    category: str
    doc_type: str = "knowledge"
    source: str = "api"


class ManualUploadResponse(BaseModel):
    success: bool
    faqs_extracted: int
    faqs_saved: int
    source_file: str
    elapsed_sec: float
    error: Optional[str] = None


def _service():
    try:
        from src.services.knowledge_service import get_knowledge_service

        return get_knowledge_service()
    except Exception as e:
        raise HTTPException(
            status_code=503,
            detail=f"KnowledgeService를 불러올 수 없습니다: {e}",
        ) from e


@router.get("/knowledge")
async def knowledge_list(
    owner: Optional[str] = Query(None),
    category: Optional[str] = Query(None),
    doc_type: Optional[str] = Query(None),
    source: Optional[str] = Query(None),
) -> Dict[str, Any]:
    ks = _service()
    try:
        cat = (category or "").strip() or None
        raw: List[Dict[str, Any]] = await ks.get_all_knowledge(category=cat, limit=8000)
    except Exception as e:
        raise HTTPException(status_code=503, detail=str(e)) from e

    owner_f = (owner or "").strip()
    dt_f = (doc_type or "").strip()
    src_f = (source or "").strip()

    items: List[Dict[str, Any]] = []
    for it in raw:
        md = dict(it.get("metadata") or {})
        if owner_f and str(md.get("owner", "")).strip() != owner_f:
            continue
        if dt_f and str(md.get("doc_type", "")).strip() != dt_f:
            continue
        if src_f and str(md.get("source", "")).strip() != src_f:
            continue
        items.append(
            {
                "id": it.get("id"),
                "text": it.get("text") or "",
                "category": it.get("category") or md.get("category") or "",
                "keywords": it.get("keywords") or [],
                "metadata": md,
                "created_at": it.get("created_at") or md.get("created_at") or "",
            }
        )

    return {"items": items}


@router.post("/knowledge")
async def knowledge_create(body: KnowledgeCreateBody) -> Dict[str, Any]:
    if not body.text.strip():
        raise HTTPException(status_code=400, detail="text가 비어 있습니다.")
    ks = _service()
    meta = {
        "owner": body.owner.strip(),
        "doc_type": (body.doc_type or "knowledge").strip(),
        "source": (body.source or "api").strip(),
    }
    try:
        result = await ks.add_knowledge(
            text=body.text.strip(),
            category=(body.category or "question").strip(),
            keywords=[],
            metadata=meta,
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e)) from e
    doc_id = result.get("id") if isinstance(result, dict) else None
    if not doc_id:
        raise HTTPException(status_code=500, detail="저장 결과에 id가 없습니다.")
    return {"ok": True, "doc_id": doc_id, "cached": False}


@router.delete("/knowledge/{doc_id}")
async def knowledge_delete(doc_id: str) -> Dict[str, Any]:
    ks = _service()
    try:
        ok = await ks.delete_knowledge(doc_id)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e)) from e
    if not ok:
        raise HTTPException(status_code=404, detail="삭제할 문서를 찾을 수 없습니다.")
    return {"ok": True}


@router.post("/knowledge/upload-manual", response_model=ManualUploadResponse, summary="TXT 매뉴얼 업로드 → FAQ 자동 추출")
async def upload_manual_txt(
    file: UploadFile = File(...),
    owner: str = Query(..., description="Owner ID (착신번호, 예: 1004)"),
    replace_existing: bool = Query(False, description="동일 파일명 기존 FAQ 삭제 후 업로드"),
) -> ManualUploadResponse:
    """
    TXT 매뉴얼 파일을 업로드하여 LLM으로 FAQ 자동 추출 후 ChromaDB 저장
    
    - 파일 크기 제한: 500KB
    - TXT 파일만 허용
    - LLM으로 Q&A 쌍 추출 → ChromaDB FAQ 컬렉션 저장
    - replace_existing=True 시 동일 파일명의 기존 FAQ 삭제 후 업로드
    """
    import structlog
    logger = structlog.get_logger(__name__)
    
    # 1. 파일 형식 검증
    if not file.filename.endswith('.txt'):
        raise HTTPException(status_code=400, detail="TXT 파일만 업로드 가능합니다.")
    
    # 2. 파일 크기 제한 (500KB)
    MAX_FILE_SIZE = 500 * 1024  # 500KB
    contents = await file.read()
    
    if len(contents) > MAX_FILE_SIZE:
        raise HTTPException(
            status_code=400,
            detail=f"파일 크기가 너무 큽니다. (최대 500KB, 현재: {len(contents) // 1024}KB)"
        )
    
    # 3. UTF-8 디코딩
    try:
        text = contents.decode('utf-8')
    except UnicodeDecodeError:
        try:
            # 한글 파일 CP949 시도
            text = contents.decode('cp949')
        except UnicodeDecodeError:
            raise HTTPException(
                status_code=400,
                detail="텍스트 파일 디코딩 실패 (UTF-8 또는 CP949 필요)"
            )
    
    if not text.strip():
        raise HTTPException(status_code=400, detail="파일이 비어 있습니다.")
    
    logger.info("manual_upload_received",
               owner=owner,
               filename=file.filename,
               size_kb=len(contents) // 1024,
               text_length=len(text),
               replace_existing=replace_existing,
               note="매뉴얼 TXT 업로드 시작")
    
    # 4. LLM + Knowledge Service 가져오기
    try:
        from src.ai_voicebot.factory import get_llm_client
        from src.services.knowledge_service import get_knowledge_service
        from src.ai_voicebot.knowledge.manual_to_faq_extractor import (
            extract_and_save_faqs_from_txt,
        )
        
        llm_client = get_llm_client()
        knowledge_service = get_knowledge_service()
        
        if not llm_client:
            raise HTTPException(status_code=503, detail="LLM 서비스를 사용할 수 없습니다.")
        if not knowledge_service:
            raise HTTPException(status_code=503, detail="Knowledge 서비스를 사용할 수 없습니다.")
        
    except Exception as e:
        logger.error("manual_upload_service_init_error", error=str(e))
        raise HTTPException(status_code=503, detail=f"서비스 초기화 실패: {e}")
    
    # 5. 기존 FAQ 삭제 (replace_existing=True 시)
    deleted_count = 0
    if replace_existing:
        deleted_count = await knowledge_service.delete_by_source_file(file.filename)
        logger.info("manual_upload_old_faqs_deleted",
                   filename=file.filename,
                   deleted_count=deleted_count,
                   note="동일 파일명 기존 FAQ 삭제 완료")
    
    # 6. FAQ 추출 및 저장
    result = await extract_and_save_faqs_from_txt(
        text=text,
        owner=owner,
        source_filename=file.filename,
        llm_client=llm_client,
        knowledge_service=knowledge_service,
    )
    
    if not result["success"]:
        raise HTTPException(status_code=500, detail=result.get("error", "FAQ 추출 실패"))
    
    return ManualUploadResponse(
        success=True,
        faqs_extracted=result["faqs_extracted"],
        faqs_saved=result["faqs_saved"],
        source_file=result["source_file"],
        elapsed_sec=result.get("elapsed_sec", 0),
    )
