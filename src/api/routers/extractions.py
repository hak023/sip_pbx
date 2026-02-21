"""지식 추출 리뷰 API

통화에서 자동 추출된 지식의 리뷰(승인/거절/편집) 관리
"""
from fastapi import APIRouter, HTTPException
from typing import Optional
import structlog

from ..models import (
    ExtractionEntry,
    ExtractionListResponse,
    ExtractionReviewRequest,
    ExtractionStatsResponse,
    BatchDedupRequest,
    BatchDedupResponse,
)
from src.services.knowledge_service import get_knowledge_service

logger = structlog.get_logger(__name__)
router = APIRouter()

knowledge_service = get_knowledge_service()


def _to_entry(data: dict) -> ExtractionEntry:
    """dict → ExtractionEntry 변환 (ChromaDB 메타데이터)"""
    kw = data.get("keywords", "")
    if isinstance(kw, list):
        kw = ", ".join(kw) if kw else ""
    return ExtractionEntry(
        id=data.get("id", ""),
        doc_type=data.get("doc_type", "knowledge"),
        text=data.get("text", ""),
        category=data.get("category", ""),
        confidence_score=float(data.get("confidence_score") or data.get("confidence", 0)),
        review_status=data.get("review_status", "pending"),
        hallucination_check=data.get("hallucination_check", ""),
        dedup_status=data.get("dedup_status", "unique"),
        extraction_source=data.get("extraction_source", "call"),
        extraction_call_id=data.get("extraction_call_id", ""),
        extraction_timestamp=data.get("extraction_timestamp", ""),
        pipeline_version=data.get("extraction_pipeline_version", ""),
        owner=data.get("owner", ""),
        question=data.get("question"),
        source_speaker=data.get("source_speaker"),
        entity_type=data.get("entity_type"),
        normalized_value=data.get("normalized_value"),
        usage_count=int(data.get("usage_count", 0)),
        keywords=kw,
        reviewed_by=data.get("reviewed_by"),
        reviewed_at=data.get("reviewed_at"),
    )


def _pending_to_entry(data: dict) -> ExtractionEntry:
    """검토 대기열(JSONL) 항목 → ExtractionEntry 변환"""
    kw = data.get("keywords", [])
    if isinstance(kw, list):
        kw = ", ".join(kw) if kw else ""
    else:
        kw = str(kw) if kw else ""
    return ExtractionEntry(
        id=data.get("id", ""),
        doc_type="knowledge",
        text=data.get("text", ""),
        category=data.get("category", ""),
        confidence_score=float(data.get("confidence", 0)),
        review_status=data.get("status", "pending"),
        hallucination_check="",
        dedup_status="unique",
        extraction_source="call",
        extraction_call_id=data.get("call_id", ""),
        extraction_timestamp=data.get("created_at", ""),
        pipeline_version="",
        owner=data.get("owner", ""),
        question=None,
        source_speaker=data.get("speaker"),
        entity_type=None,
        normalized_value=None,
        usage_count=0,
        keywords=kw,
        reviewed_by=data.get("reviewed_by"),
        reviewed_at=data.get("reviewed_at"),
    )


@router.get("/", response_model=ExtractionListResponse)
async def list_extractions(
    review_status: Optional[str] = None,
    doc_type: Optional[str] = None,
    owner: Optional[str] = None,
    limit: int = 100,
):
    """추출 항목 목록 조회"""
    try:
        items = await knowledge_service.get_extractions(
            review_status=review_status,
            doc_type=doc_type,
            owner=owner,
            limit=limit,
        )
        entries = [_to_entry(item) for item in items]
        return ExtractionListResponse(items=entries, total=len(entries))
    except Exception as e:
        logger.error("list_extractions_failed", error=str(e), exc_info=True)
        return ExtractionListResponse(items=[], total=0)


@router.get("/stats", response_model=ExtractionStatsResponse)
async def get_extraction_stats(owner: Optional[str] = None):
    """추출 통계 조회 (owner별 격리)"""
    try:
        stats = await knowledge_service.get_extraction_stats(owner=owner)
        return ExtractionStatsResponse(**stats)
    except Exception as e:
        logger.error("extraction_stats_failed", error=str(e), exc_info=True)
        return ExtractionStatsResponse(
            total=0, pending=0, approved=0, rejected=0, auto_approved=0,
            by_doc_type={}, by_category={}, avg_confidence=0.0,
        )


@router.patch("/{doc_id}/review", response_model=ExtractionEntry)
async def review_extraction(doc_id: str, body: ExtractionReviewRequest):
    """추출 항목 리뷰 (approve/reject/edit)"""
    try:
        result = await knowledge_service.review_extraction(
            doc_id=doc_id,
            action=body.action,
            reviewer=body.reviewer,
            edited_text=body.edited_text,
            edited_category=body.edited_category,
        )
        if not result:
            raise HTTPException(status_code=404, detail="항목을 찾을 수 없습니다")
        return _to_entry(result)
    except HTTPException:
        raise
    except Exception as e:
        logger.error("review_failed", doc_id=doc_id, error=str(e), exc_info=True)
        raise HTTPException(status_code=500, detail="리뷰 처리 실패")


@router.delete("/{doc_id}")
async def delete_extraction(doc_id: str):
    """추출 항목 삭제"""
    try:
        success = await knowledge_service.delete_knowledge(doc_id)
        if not success:
            raise HTTPException(status_code=404, detail="항목을 찾을 수 없습니다")
        return {"success": True, "id": doc_id}
    except HTTPException:
        raise
    except Exception as e:
        logger.error("delete_extraction_failed", error=str(e), exc_info=True)
        raise HTTPException(status_code=500, detail="삭제 실패")


# -----------------------------------------------------------------------------
# §7 검토 대기열 (PII 파이프라인) API
# -----------------------------------------------------------------------------

@router.get("/pending", response_model=ExtractionListResponse)
async def list_pending_extractions(
    owner: Optional[str] = None,
    status: Optional[str] = "pending",
    limit: int = 100,
):
    """검토 대기열 항목 목록 (contains_pii 등 검토 후 반영 대상)"""
    try:
        items = await knowledge_service.get_pending_review_extractions(
            owner=owner,
            status=status or "pending",
            limit=limit,
        )
        entries = [_pending_to_entry(item) for item in items]
        return ExtractionListResponse(items=entries, total=len(entries))
    except Exception as e:
        logger.error("list_pending_extractions_failed", error=str(e), exc_info=True)
        return ExtractionListResponse(items=[], total=0)


@router.patch("/pending/{pending_id}/review", response_model=ExtractionEntry)
async def review_pending_extraction(pending_id: str, body: ExtractionReviewRequest):
    """검토 대기열 항목 승인/거절/편집 (승인 시 VectorDB 반영)"""
    try:
        result = await knowledge_service.review_pending_extraction(
            pending_id=pending_id,
            action=body.action,
            reviewer=body.reviewer,
            edited_text=body.edited_text,
            edited_category=body.edited_category,
        )
        if not result:
            raise HTTPException(status_code=404, detail="대기열 항목을 찾을 수 없습니다")
        return _pending_to_entry(result)
    except HTTPException:
        raise
    except Exception as e:
        logger.error("review_pending_failed", pending_id=pending_id, error=str(e), exc_info=True)
        raise HTTPException(status_code=500, detail="검토 처리 실패")


@router.post("/batch-dedup", response_model=BatchDedupResponse)
async def batch_dedup(body: BatchDedupRequest):
    """§7 누적 기반 추출: 여러 통화 추출 결과 클러스터·중복 제거 (카테고리·유사도 기준)"""
    try:
        result = await knowledge_service.run_batch_dedup(
            owner=body.owner,
            similarity_threshold=body.similarity_threshold,
            limit=body.limit,
            apply=body.apply,
        )
        return BatchDedupResponse(**result)
    except Exception as e:
        logger.error("batch_dedup_failed", error=str(e), exc_info=True)
        raise HTTPException(status_code=500, detail="배치 중복 제거 실패")
