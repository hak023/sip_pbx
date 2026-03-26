"""
지식 API 라우터 (CHROMADB_CATEGORY_DESIGN).

- POST   /api/knowledge — 지식 추가 (text, owner, category 필수; answer는 greeting/farewell 시 즉시 캐시용)
- GET    /api/knowledge — 목록 (owner, category 쿼리 선택)
- DELETE /api/knowledge/{doc_id} — 지식 1건 삭제

마운트: app.include_router(knowledge_router, prefix="/api")

🔥 VERSION: v2_no_tenant_id (2026-03-16)
"""

from typing import Any, Optional
from datetime import datetime
import structlog

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, Field

from src.ai_voicebot.knowledge.chromadb_client import get_vector_db
from src.ai_voicebot.knowledge.knowledge_service import (
    add_knowledge,
    delete_knowledge,
    immediate_cache_for_knowledge,
    list_knowledge,
    VALID_CATEGORIES,
)

router = APIRouter(tags=["knowledge"])
logger = structlog.get_logger(__name__)

# 🔥 모듈 로드 시 로그
logger.info("🔥 knowledge_router MODULE LOADED", 
            version="v2_no_tenant_id",
            timestamp=datetime.now().isoformat())


class KnowledgeCreateRequest(BaseModel):
    """지식 생성 요청 모델"""
    text: str = Field(..., description="지식 내용 (필수)", min_length=1)
    owner: str = Field(..., description="소유자 ID (필수)")
    category: str = Field(..., description="카테고리 (필수)")
    doc_type: Optional[str] = Field("knowledge", description="문서 유형 (knowledge|faq)")
    answer: Optional[str] = Field(None, description="답변 (greeting/farewell 시 즉시 캐시용)")
    source: Optional[str] = Field("api", description="출처 (api|hitl|call|seed)")
    call_id: Optional[str] = Field(None, description="통화 ID")
    # contact category용 추가 필드
    phone_number: Optional[str] = Field(None, description="전화번호 (contact 메타데이터, 선택)")
    department: Optional[str] = Field(None, description="부서명")
    name: Optional[str] = Field(None, description="담당자명")


# 메인 앱에서 설정. embedder 미설정 시 POST add는 503 반환
_knowledge_embedder: Any = None


def set_knowledge_embedder(embedder: Any) -> None:
    global _knowledge_embedder
    _knowledge_embedder = embedder


def get_knowledge_embedder() -> Any:
    return _knowledge_embedder


def get_vector_db_dep() -> Any:
    db = get_vector_db()
    if not db:
        raise HTTPException(status_code=503, detail="Vector DB not initialized")
    return db


@router.post("/knowledge")
async def post_knowledge(
    request: Request,
    body: KnowledgeCreateRequest,
    vector_db: Any = Depends(get_vector_db_dep),
):
    """
    지식 1건 추가.
    
    🔍 DEBUG: 이 핸들러가 실행되면 로그에 "HANDLER_V2_EXECUTED" 표시됨
    
    Request Body (JSON):
    {
        "text": "지식 내용 (필수)",
        "owner": "소유자 ID (필수)",
        "category": "카테고리 (필수)",
        "answer": "답변 (선택, greeting/farewell용)",
        "source": "출처 (기본값: api)",
        "call_id": "통화 ID (선택)"
    }
    
    ⚠️ 주의: query parameter (tenant_id 등)는 사용하지 않음
    """
    # 🚨 이 로그가 보이면 새 코드가 실행된 것
    logger.info("🔥 HANDLER_V2_EXECUTED - NEW CODE RUNNING",
                handler_version="v2_no_tenant_id",
                timestamp=datetime.now().isoformat())
    
    # 🔍 디버그: 실제 요청 URL 및 query parameters 로깅
    query_params = dict(request.query_params)
    logger.info("knowledge_api_request",
                method="POST",
                full_url=str(request.url),
                path=str(request.url.path),
                query_params=query_params,
                has_query=bool(query_params),
                body_text_len=len(body.text),
                body_text=body.text,
                body_owner=body.owner,
                body_category=body.category,
                has_answer=bool(body.answer),
                body_answer=body.answer,
                source=body.source)
    
    text = body.text.strip()
    owner = body.owner.strip()
    category = body.category.strip()
    doc_type = body.doc_type or "knowledge"
    answer = body.answer
    source = body.source or "api"
    call_id = body.call_id
    # contact 필드
    phone_number = body.phone_number
    department = body.department
    name = body.name

    if not text:
        logger.warning("knowledge_api_validation_failed", reason="empty_text")
        raise HTTPException(status_code=400, detail="text는 비어있을 수 없습니다")
    
    if not owner:
        logger.warning("knowledge_api_validation_failed", reason="empty_owner")
        raise HTTPException(status_code=400, detail="owner는 필수입니다")

    if not category or category not in VALID_CATEGORIES:
        logger.warning("knowledge_api_validation_failed", 
                      reason="invalid_category",
                      category=category,
                      valid_categories=sorted(VALID_CATEGORIES))
        raise HTTPException(
            status_code=400,
            detail=f"category 필수이며 다음 중 하나: {sorted(VALID_CATEGORIES)}",
        )
    
    # doc_type 유효성 검증 추가
    valid_doc_types = ["knowledge", "faq"]
    if doc_type not in valid_doc_types:
        logger.warning("knowledge_api_validation_failed",
                      reason="invalid_doc_type",
                      doc_type=doc_type,
                      valid_doc_types=valid_doc_types)
        raise HTTPException(
            status_code=400,
            detail=f"doc_type은 다음 중 하나: {valid_doc_types}",
        )
    
    embedder = get_knowledge_embedder()
    if not embedder:
        logger.error("knowledge_api_embedder_not_configured")
        raise HTTPException(status_code=503, detail="Embedder not configured for knowledge API")

    logger.info("knowledge_api_adding",
                owner=owner,
                category=category,
                doc_type=doc_type,
                source=source,
                has_contact_info=bool(phone_number),
                text=text,
                answer=answer)

    result = add_knowledge(
        vector_db=vector_db,
        embedder=embedder,
        text=text,
        owner=owner,
        category=category,
        doc_type=doc_type,
        source=source,
        answer=answer,
        call_id=call_id,
        # contact 필드 추가
        phone_number=phone_number,
        department=department,
        name=name,
    )
    
    if not result.get("ok"):
        logger.warning("knowledge_api_add_failed",
                      error=result.get("error"),
                      owner=owner,
                      category=category)
        raise HTTPException(status_code=400, detail=result.get("error", "add failed"))

    logger.info("knowledge_api_added",
                doc_id=result.get("doc_id"),
                owner=owner,
                category=category,
                needs_cache=result.get("needs_immediate_cache", False))

    # 즉시 캐싱 (async)
    if result.get("needs_immediate_cache") and result.get("_cache_query_text"):
        try:
            logger.info("knowledge_api_caching",
                       owner=owner,
                       category=category)
            await immediate_cache_for_knowledge(
                vector_db=vector_db,
                embedder=embedder,
                query_text=result["_cache_query_text"],
                answer_text=result["_cache_answer_text"],
                category=category,
                owner=owner,
            )
            result["cached"] = True
            logger.info("knowledge_api_cached",
                       owner=owner,
                       category=category)
        except Exception as e:
            result["cached"] = False
            result["cache_error"] = str(e)
            logger.warning("knowledge_api_cache_failed",
                          error=str(e),
                          owner=owner,
                          category=category)
    
    for k in list(result.keys()):
        if k.startswith("_"):
            result.pop(k, None)
    
    return result


@router.get("/knowledge")
def get_knowledge_list(
    owner: Optional[str] = None,
    tenant_id: Optional[str] = Query(None, description="테넌트 ID (owner 대체)"),
    category: Optional[str] = None,
    doc_type: Optional[str] = Query(None, description="문서 유형 필터 (knowledge|faq)"),
    source: Optional[str] = Query(None, description="출처 필터 (api|hitl|call|seed)"),
    limit: int = 500,
    vector_db: Any = Depends(get_vector_db_dep),
):
    """지식 목록. owner, category, doc_type, source 쿼리로 필터."""
    effective_owner = (owner or "").strip() or (tenant_id or "").strip()
    return list_knowledge(
        vector_db=vector_db,
        owner=effective_owner or None,
        category=category,
        doc_type=doc_type,
        source=source,
        limit=limit
    )


@router.delete("/knowledge/{doc_id}")
def delete_knowledge_by_id(
    doc_id: str,
    vector_db: Any = Depends(get_vector_db_dep),
):
    """지식 1건 삭제. doc_id는 목록 조회 시 각 항목의 id."""
    if not doc_id or not doc_id.strip():
        raise HTTPException(status_code=400, detail="doc_id required")
    result = delete_knowledge(vector_db=vector_db, doc_id=doc_id.strip())
    if not result.get("ok"):
        raise HTTPException(status_code=400, detail=result.get("error", "delete failed"))
    return result
