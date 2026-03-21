"""
⚠️ DEPRECATED - 이 파일은 사용하지 않습니다 ⚠️

이 knowledge router는 src/api/knowledge_router.py로 대체되었습니다.
src/api/main.py에서 이 파일을 로드하지 않도록 설정되어 있습니다.

대체 파일: src/api/knowledge_router.py
이유: Pydantic v2 호환성 및 tenant_id 중복 제거

---

원본 설명 (참고용):

Knowledge Base API

- 연락처 관리 (AI 동적 호 전환용): /contacts (JSON 파일 기반)
- 통화 지식 관리 (RAG 기반 ChromaDB): GET/POST "", GET /stats, POST /search

지식 목록이 비어 보일 때 점검:
1. ChromaDB 초기화: get_vector_db()가 None이면 lazy init(initialize()) 시도. 실패 시 목록은 빈 배열.
2. 컬렉션 비어 있음: ChromaDB "knowledge" 컬렉션에 문서가 없으면 당연히 0건. POST "" 로 지식 추가 가능.
3. tenant 불일치: 목록은 where={"owner": tenant_id 정규화값}으로 필터. 저장 시 metadata.owner를 테넌트(예: 1004)와 맞춰야 함.
4. Chroma 경로: src.ai_voicebot.knowledge.chromadb_client.get_chroma_persist_path() 로 동일 경로 사용 권장.
"""

# ⚠️ 이 파일은 더 이상 사용되지 않습니다
# 새 구현: src/api/knowledge_router.py

from fastapi import APIRouter, HTTPException, Query
from typing import List, Optional, Dict, Any
from pydantic import BaseModel
import json
from pathlib import Path
from datetime import datetime, timedelta
import logging

router = APIRouter(prefix="/api/knowledge_OLD_DEPRECATED", tags=["knowledge-deprecated"])
logger = logging.getLogger(__name__)

logger.warning("⚠️ DEPRECATED: src/api/routers/knowledge.py is loaded but should not be used. Use src/api/knowledge_router.py instead.")


def _embed_text(embedder: Any, text: str) -> List[float]:
    """embedder에서 embed_text / embed / encode 중 사용 가능한 것으로 임베딩 벡터 반환."""
    if not text or not text.strip():
        return []
    if hasattr(embedder, "embed_text"):
        out = embedder.embed_text(text)
        return out if isinstance(out, list) and out and isinstance(out[0], (int, float)) else []
    if hasattr(embedder, "embed"):
        out = embedder.embed(text)
        return out if isinstance(out, list) and out and isinstance(out[0], (int, float)) else []
    if hasattr(embedder, "encode"):
        out = embedder.encode(text)
        if hasattr(out, "tolist"):
            return out.tolist()
        if isinstance(out, list):
            return out
        return []
    return []


def _tenant_id_to_owner(tenant_id: str) -> str:
    """
    테넌트 ID를 ChromaDB owner 값으로 정규화.
    프론트는 'sip:1004@unknown', RAG/파이프라인은 확장자 '1004'를 사용.
    """
    if not tenant_id or not isinstance(tenant_id, str):
        return tenant_id or ""
    t = tenant_id.strip()
    if not t:
        return ""
    # sip:1004@... → 1004
    if "sip:" in t.lower():
        import re
        m = re.match(r"sip:([^@;>\s]+)@", t, re.I)
        if m:
            return m.group(1).strip()
    return t


# ========================================
# Models - 통화 지식
# ========================================

class KnowledgeItem(BaseModel):
    """지식 항목"""
    id: str
    text: str
    category: str
    keywords: List[str]
    confidence: float
    call_id: str
    created_at: str
    owner: str


class KnowledgeListResponse(BaseModel):
    """지식 목록 응답"""
    total: int
    page: int
    limit: int
    items: List[KnowledgeItem]


class KnowledgeStats(BaseModel):
    """지식 통계"""
    total_knowledge: int
    this_week: int
    categories: Dict[str, int]
    avg_confidence: float
    recent_extractions: List[Dict[str, Any]]


class KnowledgeSearchRequest(BaseModel):
    """지식 검색 요청"""
    tenant_id: str
    query: str
    top_k: int = 10


class KnowledgeSearchResponse(BaseModel):
    """지식 검색 응답"""
    query: str
    results: List[Dict[str, Any]]


class KnowledgeCreate(BaseModel):
    """지식 추가 요청 (API로 지식 DB에 삽입)"""
    tenant_id: str
    text: str
    category: str = "기타"
    keywords: List[str] = []
    confidence: float = 0.8
    call_id: str = ""


# ========================================
# Models - 연락처
# ========================================


class ContactCreate(BaseModel):
    """연락처 생성 요청"""
    department: str
    keywords: List[str]
    phone_number: str
    description: str
    available_hours: str = "09:00-18:00"
    auto_transfer: bool = True
    priority: str = "medium"


class ContactUpdate(BaseModel):
    """연락처 수정 요청"""
    department: Optional[str] = None
    keywords: Optional[List[str]] = None
    phone_number: Optional[str] = None
    description: Optional[str] = None
    available_hours: Optional[str] = None
    auto_transfer: Optional[bool] = None
    priority: Optional[str] = None


class ContactResponse(BaseModel):
    """연락처 응답"""
    id: str
    tenant_id: str
    department: str
    keywords: List[str]
    phone_number: str
    description: str
    available_hours: str
    auto_transfer: bool
    priority: str


def get_contacts_file_path(tenant_id: str) -> Path:
    """연락처 파일 경로 반환"""
    base_dir = Path("data/knowledge_base")
    base_dir.mkdir(parents=True, exist_ok=True)
    return base_dir / f"{tenant_id}_contacts.json"


def load_contacts(tenant_id: str) -> dict:
    """연락처 데이터 로드"""
    contacts_file = get_contacts_file_path(tenant_id)
    
    if not contacts_file.exists():
        return {
            "tenant_id": tenant_id,
            "tenant_name": "",
            "contacts": []
        }
    
    try:
        with open(contacts_file, 'r', encoding='utf-8') as f:
            return json.load(f)
    except Exception as e:
        logger.error(f"Failed to load contacts for tenant {tenant_id}: {e}")
        return {
            "tenant_id": tenant_id,
            "tenant_name": "",
            "contacts": []
        }


def save_contacts(tenant_id: str, data: dict):
    """연락처 데이터 저장"""
    contacts_file = get_contacts_file_path(tenant_id)
    
    try:
        with open(contacts_file, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        logger.info(f"Contacts saved for tenant {tenant_id}")
    except Exception as e:
        logger.error(f"Failed to save contacts for tenant {tenant_id}: {e}")
        raise HTTPException(status_code=500, detail="Failed to save contacts")


@router.get("/contacts", response_model=List[ContactResponse])
async def get_contacts(tenant_id: str):
    """
    연락처 목록 조회
    
    Args:
        tenant_id: 테넌트 ID (예: "1004")
    
    Returns:
        List[ContactResponse]: 연락처 목록
    """
    logger.info(f"GET /api/knowledge/contacts - tenant_id: {tenant_id}")
    
    data = load_contacts(tenant_id)
    
    contacts = [
        ContactResponse(
            id=c['id'],
            tenant_id=data['tenant_id'],
            department=c['department'],
            keywords=c['keywords'],
            phone_number=c['phone_number'],
            description=c['description'],
            available_hours=c.get('available_hours', '09:00-18:00'),
            auto_transfer=c.get('auto_transfer', True),
            priority=c.get('priority', 'medium')
        )
        for c in data.get('contacts', [])
    ]
    
    logger.info(f"Returning {len(contacts)} contacts for tenant {tenant_id}")
    return contacts


@router.post("/contacts", response_model=ContactResponse)
async def create_contact(
    tenant_id: str,
    contact: ContactCreate
):
    """
    연락처 추가
    
    Args:
        tenant_id: 테넌트 ID
        contact: 연락처 정보
    
    Returns:
        ContactResponse: 생성된 연락처
    """
    logger.info(f"POST /api/knowledge/contacts - tenant_id: {tenant_id}, department: {contact.department}")
    
    data = load_contacts(tenant_id)
    
    # ID 생성
    existing_ids = [c['id'] for c in data['contacts']]
    new_id_num = len(existing_ids) + 1
    new_id = f"contact_{new_id_num:03d}"
    
    # 중복 ID 방지
    while new_id in existing_ids:
        new_id_num += 1
        new_id = f"contact_{new_id_num:03d}"
    
    # 연락처 추가
    new_contact = {
        "id": new_id,
        "department": contact.department,
        "keywords": contact.keywords,
        "phone_number": contact.phone_number,
        "description": contact.description,
        "available_hours": contact.available_hours,
        "auto_transfer": contact.auto_transfer,
        "priority": contact.priority
    }
    data['contacts'].append(new_contact)
    
    save_contacts(tenant_id, data)
    
    logger.info(f"Contact created: {new_id} - {contact.department}")
    
    return ContactResponse(
        id=new_id,
        tenant_id=tenant_id,
        **new_contact
    )


@router.put("/contacts/{contact_id}", response_model=ContactResponse)
async def update_contact(
    tenant_id: str,
    contact_id: str,
    contact: ContactUpdate
):
    """
    연락처 수정
    
    Args:
        tenant_id: 테넌트 ID
        contact_id: 연락처 ID
        contact: 수정할 정보
    
    Returns:
        ContactResponse: 수정된 연락처
    """
    logger.info(f"PUT /api/knowledge/contacts/{contact_id} - tenant_id: {tenant_id}")
    
    data = load_contacts(tenant_id)
    
    # 연락처 찾기
    target_contact = None
    for c in data['contacts']:
        if c['id'] == contact_id:
            target_contact = c
            break
    
    if not target_contact:
        logger.warning(f"Contact not found: {contact_id}")
        raise HTTPException(status_code=404, detail="Contact not found")
    
    # 수정 (None이 아닌 값만)
    update_data = contact.dict(exclude_unset=True)
    target_contact.update(update_data)
    
    save_contacts(tenant_id, data)
    
    logger.info(f"Contact updated: {contact_id}")
    
    return ContactResponse(
        id=contact_id,
        tenant_id=tenant_id,
        **target_contact
    )


@router.delete("/contacts/{contact_id}")
async def delete_contact(tenant_id: str, contact_id: str):
    """
    연락처 삭제
    
    Args:
        tenant_id: 테넌트 ID
        contact_id: 연락처 ID
    
    Returns:
        dict: 삭제 성공 메시지
    """
    logger.info(f"DELETE /api/knowledge/contacts/{contact_id} - tenant_id: {tenant_id}")
    
    data = load_contacts(tenant_id)
    
    # 연락처 찾기 및 삭제
    original_length = len(data['contacts'])
    data['contacts'] = [c for c in data['contacts'] if c['id'] != contact_id]
    
    if len(data['contacts']) == original_length:
        logger.warning(f"Contact not found for deletion: {contact_id}")
        raise HTTPException(status_code=404, detail="Contact not found")
    
    save_contacts(tenant_id, data)
    
    logger.info(f"Contact deleted: {contact_id}")
    
    return {
        "message": "Contact deleted successfully",
        "contact_id": contact_id
    }


# ========================================
# API 엔드포인트 - 통화 지식
# ========================================

@router.get("", response_model=KnowledgeListResponse)
async def get_knowledge_list(
    tenant_id: str = Query(..., description="테넌트 ID"),
    page: int = Query(1, ge=1, description="페이지 번호"),
    limit: int = Query(20, ge=1, le=100, description="페이지당 항목 수")
):
    """
    통화 지식 목록 조회 (ChromaDB에서)
    
    Args:
        tenant_id: 테넌트 ID (예: "sip:1004@unknown")
        page: 페이지 번호
        limit: 페이지당 항목 수
    
    Returns:
        KnowledgeListResponse: 지식 목록
    """
    try:
        # ChromaDB에서 조회 (미초기화 시 lazy init 시도 — API 단독 실행 시에도 목록 노출)
        from src.ai_voicebot.knowledge.chromadb_client import get_vector_db, get_chromadb_client

        vector_db = get_vector_db()
        if not vector_db:
            try:
                client = get_chromadb_client()
                await client.initialize()
                vector_db = get_vector_db()
            except Exception as init_err:
                err_msg = str(init_err)
                hint = ""
                if "collections.topic" in err_msg:
                    hint = " [해결: pip install 'chromadb>=0.5.0' 또는 data/chroma 삭제 후 재시작. docs/reports/CHROMA_COLLECTIONS_TOPIC_ERROR.md]"
                logger.warning(f"ChromaDB lazy init failed (knowledge list): {init_err}{hint}")
            if not vector_db:
                logger.info("knowledge_list_empty_reason", reason="vector_db_unavailable", tenant_id=tenant_id)
                return KnowledgeListResponse(
                    total=0,
                    page=page,
                    limit=limit,
                    items=[]
                )
        
        # 테넌트 필터로 모든 지식 조회 (owner는 확장자 1004 형태로 저장됨)
        owner_filter = _tenant_id_to_owner(tenant_id)
        raw = vector_db.get(
            where={"owner": owner_filter},
            limit=1000,
        )
        ids = raw.get("ids", [])
        documents = raw.get("documents", [])
        metadatas = raw.get("metadatas", [])
        # 진단: 목록이 비었을 때 컬렉션 전체가 비었는지, 해당 tenant만 없는지 구분
        if len(ids) == 0:
            raw_any = vector_db.get(where=None, limit=1)
            total_in_collection = len(raw_any.get("ids", []))
            if total_in_collection == 0:
                logger.info("knowledge_list_empty_reason", reason="collection_empty", tenant_id=tenant_id, owner_filter=owner_filter,
                            note="ChromaDB 지식 컬렉션이 비어 있음. 지식 추출 파이프라인 또는 POST /api/knowledge 로 데이터 추가 필요.")
            else:
                logger.info("knowledge_list_empty_reason", reason="no_docs_for_tenant", tenant_id=tenant_id, owner_filter=owner_filter,
                            note="해당 tenant(owner)로 저장된 지식이 없음. 저장 시 metadata.owner 값을 owner_filter와 일치시키세요.")
        
        # KnowledgeItem 변환 (ids/documents/metadatas 병렬 리스트). keywords는 DB에서 문자열로 저장된 경우 리스트로 변환
        def _keywords_list(v) -> List[str]:
            if v is None:
                return []
            if isinstance(v, list):
                return v
            if isinstance(v, str):
                return [k.strip() for k in v.split(",") if k.strip()]
            return []

        items = []
        for i, doc_id in enumerate(ids):
            doc_text = documents[i] if i < len(documents) else ""
            metadata = metadatas[i] if i < len(metadatas) else {}
            items.append(KnowledgeItem(
                id=doc_id or "",
                text=doc_text if isinstance(doc_text, str) else "",
                category=metadata.get("category", "기타"),
                keywords=_keywords_list(metadata.get("keywords")),
                confidence=float(metadata.get("confidence", 0) or 0),
                call_id=metadata.get("call_id", "") or "",
                created_at=metadata.get("created_at", datetime.now().isoformat()) or datetime.now().isoformat(),
                owner=metadata.get("owner", tenant_id) or tenant_id
            ))
        
        # 최신순 정렬
        items.sort(key=lambda x: x.created_at, reverse=True)
        
        # 페이지네이션
        total = len(items)
        start_idx = (page - 1) * limit
        end_idx = start_idx + limit
        paginated_items = items[start_idx:end_idx]
        
        logger.info("knowledge_list_retrieved", tenant_id=tenant_id, owner_filter=owner_filter, total=total, page=page)
        
        return KnowledgeListResponse(
            total=total,
            page=page,
            limit=limit,
            items=paginated_items
        )
    
    except Exception as e:
        logger.error(f"Failed to get knowledge list: {e}", exc_info=True)
        # 에러 시 빈 리스트 반환
        return KnowledgeListResponse(
            total=0,
            page=page,
            limit=limit,
            items=[]
        )


@router.get("/debug/tenant/{tenant_id}")
async def get_knowledge_debug(tenant_id: str):
    """
    지식베이스·ChromaDB 진단용. 해당 테넌트로 목록이 비어 보일 때 원인 확인.
    - vector_db_available: ChromaDB 초기화 여부
    - chroma_path: 사용 중인 DB 경로 (시드 스크립트와 동일해야 함)
    - owner_filter: tenant_id 정규화 값 (저장 시 metadata.owner와 일치해야 목록에 표시됨)
    - total_in_collection: 컬렉션 전체 문서 수
    - total_for_owner: 해당 owner 문서 수
    """
    from src.ai_voicebot.knowledge.chromadb_client import (
        get_vector_db,
        get_chromadb_client,
        get_chroma_persist_path,
    )
    owner_filter = _tenant_id_to_owner(tenant_id)
    chroma_path = get_chroma_persist_path()
    result = {
        "tenant_id": tenant_id,
        "owner_filter": owner_filter,
        "chroma_path": chroma_path,
        "vector_db_available": False,
        "total_in_collection": 0,
        "total_for_owner": 0,
    }
    try:
        vector_db = get_vector_db()
        if not vector_db:
            try:
                client = get_chromadb_client()
                await client.initialize()
                vector_db = get_vector_db()
            except Exception:
                pass
        if vector_db:
            result["vector_db_available"] = True
            raw_any = vector_db.get(where=None, limit=10000)
            result["total_in_collection"] = len(raw_any.get("ids", []))
            raw_owner = vector_db.get(where={"owner": owner_filter}, limit=10000)
            result["total_for_owner"] = len(raw_owner.get("ids", []))
    except Exception as e:
        result["error"] = str(e)
    return result


@router.post("", response_model=KnowledgeItem, status_code=201)
async def create_knowledge_item(body: KnowledgeCreate):
    """
    지식 1건 추가 (ChromaDB 지식 컬렉션).
    목록이 비어 있을 때 시드 데이터로 사용하거나, 수동 지식 입력용.
    """
    try:
        from src.ai_voicebot.knowledge.chromadb_client import get_vector_db, get_chromadb_client
        from src.ai_voicebot.knowledge.embedder import get_text_embedder

        vector_db = get_vector_db()
        if not vector_db:
            try:
                client = get_chromadb_client()
                await client.initialize()
                vector_db = get_vector_db()
            except Exception as init_err:
                err_msg = str(init_err)
                hint = ""
                if "collections.topic" in err_msg:
                    hint = " [해결: pip install 'chromadb>=0.5.0' 또는 data/chroma 삭제 후 재시작. docs/reports/CHROMA_COLLECTIONS_TOPIC_ERROR.md]"
                logger.warning(f"ChromaDB lazy init failed (knowledge create): {init_err}{hint}")
        embedder = get_text_embedder()
        if not vector_db or not embedder:
            raise HTTPException(
                status_code=503,
                detail="ChromaDB or embedder not available. Ensure AI voicebot dependencies are loaded."
            )
        owner = _tenant_id_to_owner(body.tenant_id)
        embedding = _embed_text(embedder, body.text)
        if not embedding:
            raise HTTPException(status_code=400, detail="Failed to compute embedding for text")
        import uuid
        doc_id = f"kb_{datetime.now().strftime('%Y%m%d%H%M%S')}_{uuid.uuid4().hex[:8]}"
        metadata = {
            "owner": owner,
            "category": body.category or "기타",
            "keywords": ",".join(body.keywords) if isinstance(body.keywords, list) else str(body.keywords),
            "confidence": body.confidence,
            "call_id": body.call_id or "",
            "created_at": datetime.now().isoformat(),
        }
        vector_db.add(
            ids=[doc_id],
            embeddings=[embedding],
            documents=[body.text],
            metadatas=[metadata],
        )
        logger.info(f"Knowledge item created: id={doc_id}, owner={owner}, category={body.category}")
        return KnowledgeItem(
            id=doc_id,
            text=body.text,
            category=metadata["category"],
            keywords=body.keywords if isinstance(body.keywords, list) else [],
            confidence=body.confidence,
            call_id=metadata["call_id"],
            created_at=metadata["created_at"],
            owner=owner,
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to create knowledge item: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/stats", response_model=KnowledgeStats)
async def get_knowledge_stats(
    tenant_id: str = Query(..., description="테넌트 ID")
):
    """
    지식 통계 조회
    
    Args:
        tenant_id: 테넌트 ID
    
    Returns:
        KnowledgeStats: 통계 정보
    """
    try:
        from src.ai_voicebot.knowledge.chromadb_client import get_vector_db, get_chromadb_client

        vector_db = get_vector_db()
        if not vector_db:
            try:
                client = get_chromadb_client()
                await client.initialize()
                vector_db = get_vector_db()
            except Exception as init_err:
                err_msg = str(init_err)
                hint = ""
                if "collections.topic" in err_msg:
                    hint = " [해결: pip install 'chromadb>=0.5.0' 또는 data/chroma 삭제 후 재시작. docs/reports/CHROMA_COLLECTIONS_TOPIC_ERROR.md]"
                logger.warning(f"ChromaDB lazy init failed (stats): {init_err}{hint}")
            if not vector_db:
                return KnowledgeStats(
                    total_knowledge=0,
                    this_week=0,
                    categories={},
                    avg_confidence=0.0,
                    recent_extractions=[]
                )
        
        # 모든 지식 조회 (owner는 확장자 형태로 저장됨)
        owner_filter = _tenant_id_to_owner(tenant_id)
        raw = vector_db.get(where={"owner": owner_filter}, limit=10000)
        ids = raw.get("ids", [])
        metadatas = raw.get("metadatas", [])
        total_knowledge = len(ids)
        
        # 이번 주 추가된 지식
        week_ago = (datetime.now() - timedelta(days=7)).isoformat()
        this_week = 0
        categories: Dict[str, int] = {}
        confidence_sum = 0.0
        call_extractions: Dict[str, Dict] = {}
        
        for i, meta in enumerate(metadatas):
            if not isinstance(meta, dict):
                continue
            created_at = meta.get("created_at", "") or ""
            if created_at >= week_ago:
                this_week += 1
            category = meta.get("category", "기타")
            categories[category] = categories.get(category, 0) + 1
            confidence_sum += float(meta.get("confidence", 0) or 0)
            call_id = meta.get("call_id", "") or ""
            if call_id:
                if call_id not in call_extractions:
                    call_extractions[call_id] = {
                        "call_id": call_id,
                        "extracted_count": 0,
                        "timestamp": created_at
                    }
                call_extractions[call_id]["extracted_count"] += 1
        
        avg_confidence = confidence_sum / total_knowledge if total_knowledge > 0 else 0.0
        recent_extractions = sorted(
            call_extractions.values(),
            key=lambda x: x["timestamp"],
            reverse=True
        )[:5]
        
        logger.info(f"Knowledge stats: tenant={tenant_id}, total={total_knowledge}")
        
        return KnowledgeStats(
            total_knowledge=total_knowledge,
            this_week=this_week,
            categories=categories,
            avg_confidence=avg_confidence,
            recent_extractions=recent_extractions
        )
    
    except Exception as e:
        logger.error(f"Failed to get knowledge stats: {e}", exc_info=True)
        return KnowledgeStats(
            total_knowledge=0,
            this_week=0,
            categories={},
            avg_confidence=0.0,
            recent_extractions=[]
        )


@router.post("/search", response_model=KnowledgeSearchResponse)
async def search_knowledge(request: KnowledgeSearchRequest):
    """
    지식 검색 (벡터 검색)
    
    Args:
        request: 검색 요청
    
    Returns:
        KnowledgeSearchResponse: 검색 결과
    """
    try:
        from src.ai_voicebot.knowledge.chromadb_client import get_vector_db, get_chromadb_client
        from src.ai_voicebot.knowledge.embedder import get_text_embedder

        vector_db = get_vector_db()
        if not vector_db:
            try:
                client = get_chromadb_client()
                await client.initialize()
                vector_db = get_vector_db()
            except Exception:
                pass
        embedder = get_text_embedder()
        
        if not vector_db or not embedder:
            return KnowledgeSearchResponse(
                query=request.query,
                results=[]
            )
        
        # 쿼리 임베딩 (embed_text / embed / encode 공통)
        try:
            query_embedding = _embed_text(embedder, request.query)
        except Exception as emb_err:
            logger.warning(f"Knowledge search embed failed: {emb_err}")
            return KnowledgeSearchResponse(query=request.query, results=[])
        if not query_embedding:
            return KnowledgeSearchResponse(query=request.query, results=[])
        if isinstance(query_embedding[0], (int, float)):
            query_embedding = [query_embedding]
        
        # 벡터 검색 (owner는 확장자 형태로 저장됨)
        owner_filter = _tenant_id_to_owner(request.tenant_id)
        raw = vector_db.query(
            query_embeddings=query_embedding,
            n_results=request.top_k,
            where={"owner": owner_filter}
        )
        ids = raw.get("ids", [[]])[0] if raw.get("ids") else []
        documents = raw.get("documents", [[]])[0] if raw.get("documents") else []
        metadatas = raw.get("metadatas", [[]])[0] if raw.get("metadatas") else []
        distances = raw.get("distances", [[]])[0] if raw.get("distances") else []
        
        search_results = []
        for i, doc_id in enumerate(ids):
            doc_text = documents[i] if i < len(documents) else ""
            metadata = metadatas[i] if i < len(metadatas) else {}
            dist = distances[i] if i < len(distances) else 0.0
            search_results.append({
                "id": doc_id or "",
                "text": doc_text if isinstance(doc_text, str) else "",
                "score": 1.0 - (dist / 2.0) if dist else 0.0,
                "category": metadata.get("category", "기타"),
                "metadata": {
                    "call_id": metadata.get("call_id", ""),
                    "confidence": metadata.get("confidence", 0.0)
                }
            })
        
        logger.info(f"Knowledge search: query='{request.query}', results={len(search_results)}")
        
        return KnowledgeSearchResponse(
            query=request.query,
            results=search_results
        )
    
    except Exception as e:
        logger.error(f"Failed to search knowledge: {e}", exc_info=True)
        return KnowledgeSearchResponse(
            query=request.query,
            results=[]
        )
