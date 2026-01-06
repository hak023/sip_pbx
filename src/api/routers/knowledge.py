"""지식 베이스 관련 API"""
from fastapi import APIRouter, HTTPException
from typing import Optional
import structlog
from datetime import datetime

from ..models import (
    KnowledgeEntry,
    KnowledgeEntryCreate,
    KnowledgeEntryUpdate,
    KnowledgeListResponse
)

logger = structlog.get_logger(__name__)

router = APIRouter()

# Mock 데이터 저장소
mock_knowledge_db: dict[str, KnowledgeEntry] = {}


@router.get("/", response_model=KnowledgeListResponse)
async def list_knowledge(
    page: int = 1,
    limit: int = 50,
    category: Optional[str] = None,
    search: Optional[str] = None
):
    """
    지식 베이스 목록 조회
    
    추후 실제 Vector DB와 연동
    """
    # Mock 데이터
    mock_entries = [
        KnowledgeEntry(
            id="kb_001",
            text="영업시간은 평일 오전 9시부터 오후 6시까지입니다.",
            category="faq",
            keywords=["영업시간", "운영시간", "오픈"],
            metadata={"source": "manual", "usageCount": 15},
            created_at=datetime.now()
        ),
        KnowledgeEntry(
            id="kb_002",
            text="주말에는 운영하지 않습니다.",
            category="faq",
            keywords=["주말", "휴무", "토요일", "일요일"],
            metadata={"source": "manual", "usageCount": 8},
            created_at=datetime.now()
        )
    ]
    
    return KnowledgeListResponse(
        items=mock_entries,
        total=len(mock_entries),
        page=page,
        limit=limit
    )


@router.post("/", response_model=KnowledgeEntry)
async def create_knowledge(entry: KnowledgeEntryCreate):
    """새 지식 항목 추가"""
    new_id = f"kb_{len(mock_knowledge_db) + 1:03d}"
    
    new_entry = KnowledgeEntry(
        id=new_id,
        text=entry.text,
        category=entry.category,
        keywords=entry.keywords,
        metadata=entry.metadata,
        created_at=datetime.now()
    )
    
    mock_knowledge_db[new_id] = new_entry
    
    logger.info("Knowledge entry created", entry_id=new_id)
    
    return new_entry


@router.put("/{entry_id}", response_model=KnowledgeEntry)
async def update_knowledge(entry_id: str, update: KnowledgeEntryUpdate):
    """지식 항목 수정"""
    if entry_id not in mock_knowledge_db:
        raise HTTPException(status_code=404, detail="Knowledge entry not found")
    
    entry = mock_knowledge_db[entry_id]
    
    if update.text:
        entry.text = update.text
    if update.category:
        entry.category = update.category
    if update.keywords:
        entry.keywords = update.keywords
    if update.metadata:
        entry.metadata.update(update.metadata)
    
    entry.updated_at = datetime.now()
    
    logger.info("Knowledge entry updated", entry_id=entry_id)
    
    return entry


@router.delete("/{entry_id}")
async def delete_knowledge(entry_id: str):
    """지식 항목 삭제"""
    if entry_id not in mock_knowledge_db:
        raise HTTPException(status_code=404, detail="Knowledge entry not found")
    
    del mock_knowledge_db[entry_id]
    
    logger.info("Knowledge entry deleted", entry_id=entry_id)
    
    return {"success": True, "id": entry_id}

