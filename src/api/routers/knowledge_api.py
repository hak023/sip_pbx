"""
프론트 호환: GET/POST /api/knowledge, DELETE /api/knowledge/{doc_id}

Chroma/임베딩 미구성 시 503과 안내 메시지.

⚠️ 지식베이스 분리 (2026-08-07): 이 API는 "고객 지식 베이스"(통화·문자 응대용 페르소나/
인사말/FAQ, doc_type='knowledge' 등) 전용이다. "도우미 지식 베이스"(AI 도우미 셀프서비스
매뉴얼/업로드 문서, doc_type in ASSISTANT_KB_DOC_TYPES)는 같은 ChromaDB 'knowledge'
컬렉션을 공유하지만 doc_type 메타데이터로 구분되는 별개 기능이므로, doc_type을 명시적으로
지정하지 않는 한 목록/카운트에서 항상 제외한다. 도우미 지식 베이스 조회는
/api/knowledge-base/documents, /api/settings/ai-assistant/knowledge-base/inventory를 사용할 것.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException, Query, UploadFile, File
from pydantic import BaseModel, Field

router = APIRouter(tags=["knowledge-api"])

# "도우미 지식 베이스"(AI 도우미 셀프서비스) 전용 doc_type — 고객 지식 베이스 목록/통계에서
# doc_type이 명시되지 않으면 기본적으로 제외한다(manual_indexer.py/knowledge_documents.py 참고).
ASSISTANT_KB_DOC_TYPES = frozenset({"self_service_manual", "knowledge_document"})


class KnowledgeCreateBody(BaseModel):
    text: str
    owner: str
    category: str
    doc_type: str = "knowledge"
    source: str = "api"
    # contact 카테고리 전용 필드 (category="contact"일 때 사용)
    department: str = Field(
        default="",
        description="레거시·비권장. TTS 맥락은 transfer_label 권장.",
    )
    phone_number: str = ""  # 내선 또는 Call Control 참조 `fwd:<uuid>`
    name: str = Field(default="", description="레거시·비권장.")
    transfer_label: str = Field(
        default="",
        description="contact: 착신 전환 대상 표시명 등 TTS 안내 맥락(자동·선택)",
    )


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
    sort_by: Optional[str] = Query(None, description="정렬 기준: 'hit_count' (히트수 내림차순)"),
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
        item_doc_type = str(md.get("doc_type", "")).strip()
        if owner_f and str(md.get("owner", "")).strip() != owner_f:
            continue
        if dt_f:
            if item_doc_type != dt_f:
                continue
        elif item_doc_type in ASSISTANT_KB_DOC_TYPES:
            # doc_type 미지정 조회는 "고객 지식 베이스"만 대상 — 도우미 지식 베이스는 별도 API로 조회.
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
                "hit_count": int(md.get("hit_count") or 0),
                "created_at": it.get("created_at") or md.get("created_at") or "",
            }
        )

    if (sort_by or "").strip() == "hit_count":
        items.sort(key=lambda x: x.get("hit_count", 0), reverse=True)

    return {"items": items}


@router.post("/knowledge/{doc_id}/hit")
async def knowledge_hit(doc_id: str) -> Dict[str, Any]:
    """지식 문서 hit_count를 수동으로 1 증가 (테스트·관리용)."""
    ks = _service()
    try:
        new_count = await ks.increment_hit_count(doc_id)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e)) from e
    if new_count < 0:
        raise HTTPException(status_code=404, detail="문서를 찾을 수 없습니다.")
    return {"ok": True, "doc_id": doc_id, "hit_count": new_count}


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
    # contact 등: department / phone_number / name / transfer_label 메타데이터
    if body.department:
        meta["department"] = body.department.strip()
    if body.phone_number:
        meta["phone_number"] = body.phone_number.strip()
    if body.name:
        meta["name"] = body.name.strip()
    if body.transfer_label and str(body.transfer_label).strip():
        meta["transfer_label"] = body.transfer_label.strip()
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
