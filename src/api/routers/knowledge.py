"""지식 베이스 관련 API

멀티테넌트 지원: owner(착신번호) 기반 데이터 격리.
모든 조회/생성 API에 owner 파라미터를 지원한다.
"""
from fastapi import APIRouter, HTTPException, Query
from typing import Optional
import structlog
from datetime import datetime

from ..models import (
    KnowledgeEntry,
    KnowledgeEntryCreate,
    KnowledgeEntryUpdate,
    KnowledgeListResponse
)
from src.services.knowledge_service import get_knowledge_service

logger = structlog.get_logger(__name__)

router = APIRouter()

# Knowledge Service (VectorDB 사용)
knowledge_service = get_knowledge_service()


@router.get("/", response_model=KnowledgeListResponse)
async def list_knowledge(
    page: int = 1,
    limit: int = 50,
    category: Optional[str] = None,
    search: Optional[str] = None,
    owner: Optional[str] = Query(None, description="착신번호(테넌트 ID)로 필터링"),
):
    """
    지식 베이스 목록 조회

    owner가 지정되면 해당 테넌트의 데이터만 반환한다.
    """
    try:
        # 검색 쿼리가 있으면 벡터 검색
        if search:
            results = await knowledge_service.search_knowledge(
                query=search,
                top_k=limit,
                category=category
            )
            # owner 필터 적용 (벡터 검색 후)
            if owner:
                results = [r for r in results if r.get("metadata", {}).get("owner") == owner]
        else:
            # 전체 조회
            results = await knowledge_service.get_all_knowledge(
                category=category,
                limit=limit * 5  # owner 필터 적용 전 여유분
            )
            # owner 필터 적용
            if owner:
                results = [r for r in results if r.get("metadata", {}).get("owner") == owner]

            # capability, tenant_config 등은 제외 (knowledge만)
            results = [
                r for r in results
                if r.get("metadata", {}).get("doc_type", "") not in ("capability", "tenant_config")
            ]

        # 결과를 KnowledgeEntry 모델로 변환
        items = []
        for result in results:
            entry = KnowledgeEntry(
                id=result["id"],
                text=result["text"],
                category=result["category"],
                keywords=result["keywords"],
                metadata=result.get("metadata", {}),
                created_at=result.get("created_at", datetime.now().isoformat())
            )
            items.append(entry)

        # 페이지네이션
        total = len(items)
        start = (page - 1) * limit
        end = start + limit
        paginated_items = items[start:end]

        logger.info("Knowledge list retrieved from VectorDB",
                    total=total,
                    page=page,
                    limit=limit,
                    category=category,
                    search=search,
                    owner=owner)

        return KnowledgeListResponse(
            items=paginated_items,
            total=total,
            page=page,
            limit=limit
        )

    except Exception as e:
        logger.error("Failed to list knowledge", error=str(e), exc_info=True)
        return KnowledgeListResponse(
            items=[],
            total=0,
            page=page,
            limit=limit
        )


@router.get("/{entry_id}", response_model=KnowledgeEntry)
async def get_knowledge(entry_id: str):
    """지식 항목 단건 조회"""
    try:
        # ChromaDB에서 ID로 직접 조회
        import asyncio
        loop = asyncio.get_event_loop()
        results = await loop.run_in_executor(
            None,
            lambda: knowledge_service.vector_db.collection.get(
                ids=[entry_id],
                include=["documents", "metadatas"],
            ),
        )
        if results["ids"]:
            metadata = results["metadatas"][0] if results["metadatas"] else {}
            keywords = metadata.get("keywords", "").split(",")
            return KnowledgeEntry(
                id=results["ids"][0],
                text=results["documents"][0],
                category=metadata.get("category", ""),
                keywords=[kw for kw in keywords if kw],
                metadata=metadata,
                created_at=metadata.get("created_at", datetime.now().isoformat()),
            )

        raise HTTPException(status_code=404, detail="Knowledge entry not found")

    except HTTPException:
        raise
    except Exception as e:
        logger.error("Failed to get knowledge entry", entry_id=entry_id, error=str(e))
        raise HTTPException(status_code=500, detail="Failed to get knowledge entry")


@router.post("/", response_model=KnowledgeEntry)
async def create_knowledge(
    entry: KnowledgeEntryCreate,
    owner: Optional[str] = Query(None, description="착신번호(테넌트 ID)"),
):
    """새 지식 항목 추가

    owner가 지정되면 해당 테넌트의 데이터로 저장된다.
    """
    try:
        # metadata에 owner 추가
        metadata = entry.metadata if entry.metadata else {}
        if owner:
            metadata["owner"] = owner
        metadata["source"] = metadata.get("source", "manual")

        result = await knowledge_service.add_knowledge(
            text=entry.text,
            category=entry.category,
            keywords=entry.keywords,
            metadata=metadata,
        )

        new_entry = KnowledgeEntry(
            id=result["id"],
            text=result["text"],
            category=result["category"],
            keywords=result["keywords"],
            metadata=result.get("metadata", {}),
            created_at=result.get("created_at", datetime.now().isoformat())
        )

        logger.info("Knowledge entry created in VectorDB",
                    entry_id=new_entry.id,
                    category=entry.category,
                    owner=owner,
                    keywords_count=len(entry.keywords))

        return new_entry

    except Exception as e:
        logger.error("Failed to create knowledge", error=str(e), exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to create knowledge entry")


@router.put("/{entry_id}", response_model=KnowledgeEntry)
async def update_knowledge(
    entry_id: str,
    update: KnowledgeEntryUpdate,
    owner: Optional[str] = Query(None, description="착신번호(테넌트 ID)"),
):
    """지식 항목 수정"""
    try:
        delete_success = await knowledge_service.delete_knowledge(entry_id)

        if not delete_success:
            raise HTTPException(status_code=404, detail="Knowledge entry not found")

        metadata = update.metadata if update.metadata else {}
        if owner:
            metadata["owner"] = owner

        result = await knowledge_service.add_knowledge(
            text=update.text if update.text else "",
            category=update.category if update.category else "manual",
            keywords=update.keywords if update.keywords else [],
            metadata=metadata,
        )

        updated_entry = KnowledgeEntry(
            id=result["id"],
            text=result["text"],
            category=result["category"],
            keywords=result["keywords"],
            metadata=result.get("metadata", {}),
            created_at=result.get("created_at", datetime.now().isoformat()),
            updated_at=datetime.now()
        )

        logger.info("Knowledge entry updated in VectorDB",
                    entry_id=entry_id, owner=owner)

        return updated_entry

    except HTTPException:
        raise
    except Exception as e:
        logger.error("Failed to update knowledge",
                    entry_id=entry_id,
                    error=str(e),
                    exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to update knowledge entry")


@router.delete("/{entry_id}")
async def delete_knowledge(entry_id: str):
    """지식 항목 삭제"""
    try:
        success = await knowledge_service.delete_knowledge(entry_id)

        if not success:
            raise HTTPException(status_code=404, detail="Knowledge entry not found")

        logger.info("Knowledge entry deleted from VectorDB", entry_id=entry_id)

        return {"success": True, "id": entry_id}

    except HTTPException:
        raise
    except Exception as e:
        logger.error("Failed to delete knowledge",
                    entry_id=entry_id,
                    error=str(e),
                    exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to delete knowledge entry")
