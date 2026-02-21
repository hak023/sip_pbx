"""Knowledge Service

VectorDB와 연동된 지식 베이스 관리 서비스
"""

from typing import List, Dict, Optional
import json
import structlog
from datetime import datetime

from src.ai_voicebot.knowledge.vector_db import VectorDB
from src.ai_voicebot.knowledge.chromadb_client import get_chromadb_client, DEFAULT_PERSIST_DIRECTORY
from src.ai_voicebot.knowledge.embedder import TextEmbedder

logger = structlog.get_logger(__name__)


class KnowledgeService:
    """지식 베이스 관리 서비스
    
    VectorDB와 Embedder를 통합하여 지식 항목을 관리합니다.
    """
    
    def __init__(
        self,
        vector_db: Optional[VectorDB] = None,
        embedder: Optional[TextEmbedder] = None,
        extraction_pending_file: Optional[str] = None,
    ):
        """초기화
        
        Args:
            vector_db: VectorDB 인스턴스 (None이면 ChromaDB 생성)
            embedder: TextEmbedder 인스턴스 (None이면 생성)
            extraction_pending_file: 검토 대기열 JSONL 경로 (§7 PII/검토 워크플로)
        """
        # VectorDB 초기화 (단일 DB: get_chromadb_client 사용)
        if vector_db is None:
            self.vector_db = get_chromadb_client(
                persist_directory=DEFAULT_PERSIST_DIRECTORY,
                collection_name="knowledge_base",
                client_mode="local",
            )
        else:
            self.vector_db = vector_db
        
        # Embedder 초기화
        if embedder is None:
            self.embedder = TextEmbedder(
                model_name="paraphrase-multilingual-mpnet-base-v2",
                dimension=768
            )
        else:
            self.embedder = embedder
        
        self._extraction_pending_file = extraction_pending_file or "data/extraction_pending_review.jsonl"
        self._initialized = False
        
        logger.info("KnowledgeService created")
    
    async def initialize(self) -> None:
        """서비스 초기화"""
        if self._initialized:
            return
        
        try:
            # VectorDB 초기화
            await self.vector_db.initialize()
            
            self._initialized = True
            logger.info("KnowledgeService initialized")
            
        except Exception as e:
            logger.error("KnowledgeService initialization failed", error=str(e), exc_info=True)
            raise
    
    async def add_knowledge(
        self,
        text: str,
        category: str,
        keywords: List[str],
        metadata: Optional[Dict] = None
    ) -> Dict:
        """지식 항목 추가
        
        Args:
            text: 지식 내용
            category: 카테고리
            keywords: 키워드 리스트
            metadata: 추가 메타데이터
            
        Returns:
            생성된 항목 정보
        """
        try:
            if not self._initialized:
                await self.initialize()
            
            # 임베딩 생성
            embedding = await self.embedder.embed(text)
            
            # 문서 ID 생성
            doc_id = f"kb_{datetime.now().strftime('%Y%m%d_%H%M%S_%f')}"
            
            # 메타데이터 구성
            doc_metadata = {
                "category": category,
                "keywords": ",".join(keywords),  # ChromaDB는 문자열만 지원
                "created_at": datetime.now().isoformat(),
            }
            
            if metadata:
                # 추가 메타데이터 (문자열 변환)
                for key, value in metadata.items():
                    doc_metadata[key] = str(value)
            
            # VectorDB에 저장
            await self.vector_db.upsert(
                doc_id=doc_id,
                embedding=embedding,
                text=text,
                metadata=doc_metadata
            )
            
            logger.info("Knowledge added", 
                       doc_id=doc_id,
                       category=category,
                       text_length=len(text))
            
            return {
                "id": doc_id,
                "text": text,
                "category": category,
                "keywords": keywords,
                "metadata": doc_metadata,
                "created_at": doc_metadata["created_at"]
            }
            
        except Exception as e:
            logger.error("Failed to add knowledge", error=str(e), exc_info=True)
            raise
    
    async def add_from_hitl(
        self,
        question: str,
        answer: str,
        call_id: str,
        operator_id: str,
        category: str = "faq",
        owner_id: Optional[str] = None,
    ) -> Dict:
        """HITL(사람 개입)로 운영자가 알려준 Q&A를 지식 베이스에 저장.
        
        Args:
            question: 발신자 질문(또는 HITL 요청 시 질문)
            answer: 운영자가 입력한 답변
            call_id: 통화 ID
            operator_id: 운영자 ID
            category: 카테고리 (기본 faq)
            owner_id: 착신자/소유자 ID (착신자별 지식 분리용)
            
        Returns:
            {"success": True, "doc_id": str, "category": str} 또는
            {"success": False, "error": str}
        """
        try:
            if not self._initialized:
                await self.initialize()
            # 검색에 활용되도록 질문+답변을 한 텍스트로 저장
            text = f"Q: {question}\nA: {answer}"
            embedding = await self.embedder.embed(text)
            doc_id = f"hitl_{datetime.now().strftime('%Y%m%d_%H%M%S_%f')}"
            doc_metadata = {
                "category": category,
                "keywords": "",
                "created_at": datetime.now().isoformat(),
                "source": "hitl",
                "call_id": call_id,
                "operator_id": operator_id,
            }
            if owner_id:
                doc_metadata["owner_id"] = owner_id
            await self.vector_db.upsert(
                doc_id=doc_id,
                embedding=embedding,
                text=text,
                metadata=doc_metadata,
            )
            logger.info(
                "HITL knowledge added",
                doc_id=doc_id,
                category=category,
                call_id=call_id,
            )
            return {"success": True, "doc_id": doc_id, "category": category}
        except Exception as e:
            logger.error(
                "Failed to add HITL knowledge",
                error=str(e),
                call_id=call_id,
                exc_info=True,
            )
            return {"success": False, "error": str(e)}
    
    async def search_knowledge(
        self,
        query: str,
        top_k: int = 5,
        category: Optional[str] = None
    ) -> List[Dict]:
        """지식 검색
        
        Args:
            query: 검색 쿼리
            top_k: 반환할 결과 수
            category: 카테고리 필터 (Optional)
            
        Returns:
            검색 결과 리스트
        """
        try:
            if not self._initialized:
                await self.initialize()
            
            # 쿼리 임베딩 생성
            query_embedding = await self.embedder.embed(query)
            
            # VectorDB 검색
            filter_dict = {"category": category} if category else None
            results = await self.vector_db.search(
                vector=query_embedding,
                top_k=top_k,
                filter=filter_dict
            )
            
            # 결과 변환
            knowledge_list = []
            for result in results:
                metadata = result.get("metadata", {})
                keywords = metadata.get("keywords", "").split(",")
                
                knowledge_list.append({
                    "id": result["id"],
                    "text": result["text"],
                    "category": metadata.get("category", ""),
                    "keywords": [kw for kw in keywords if kw],
                    "score": result["score"],
                    "metadata": metadata
                })
            
            logger.info("Knowledge search completed", 
                       query_length=len(query),
                       results=len(knowledge_list))
            
            return knowledge_list
            
        except Exception as e:
            logger.error("Knowledge search failed", error=str(e), exc_info=True)
            return []
    
    async def get_all_knowledge(
        self,
        category: Optional[str] = None,
        limit: int = 100
    ) -> List[Dict]:
        """모든 지식 항목 조회
        
        Args:
            category: 카테고리 필터 (Optional)
            limit: 최대 결과 수
            
        Returns:
            지식 항목 리스트
        """
        try:
            if not self._initialized:
                await self.initialize()
            
            # ChromaDB에서 직접 조회
            import asyncio
            loop = asyncio.get_event_loop()
            
            filter_dict = {"category": category} if category else None
            
            results = await loop.run_in_executor(
                None,
                lambda: self.vector_db.collection.get(
                    where=filter_dict,
                    limit=limit,
                    include=["documents", "metadatas"]
                )
            )
            
            # 결과 변환
            knowledge_list = []
            if results['ids']:
                for i, doc_id in enumerate(results['ids']):
                    metadata = results['metadatas'][i] if results['metadatas'] else {}
                    keywords = metadata.get("keywords", "").split(",")
                    
                    knowledge_list.append({
                        "id": doc_id,
                        "text": results['documents'][i],
                        "category": metadata.get("category", ""),
                        "keywords": [kw for kw in keywords if kw],
                        "metadata": metadata,
                        "created_at": metadata.get("created_at", "")
                    })
            
            logger.info("All knowledge retrieved", 
                       count=len(knowledge_list),
                       category=category)
            
            return knowledge_list
            
        except Exception as e:
            logger.error("Failed to get all knowledge", error=str(e), exc_info=True)
            return []
    
    async def delete_knowledge(self, doc_id: str) -> bool:
        """지식 항목 삭제
        
        Args:
            doc_id: 문서 ID
            
        Returns:
            성공 여부
        """
        try:
            if not self._initialized:
                await self.initialize()
            
            await self.vector_db.delete(doc_id)
            
            logger.info("Knowledge deleted", doc_id=doc_id)
            return True
            
        except Exception as e:
            logger.error("Failed to delete knowledge", 
                        doc_id=doc_id,
                        error=str(e))
            return False
    
    # =========================================================================
    # Capability (AI 서비스) 관리
    # =========================================================================

    async def add_capability(
        self,
        doc_id: str,
        display_name: str,
        text: str,
        category: str,
        response_type: str = "info",
        keywords: List[str] = None,
        priority: int = 50,
        is_active: bool = True,
        owner: Optional[str] = None,
        api_endpoint: Optional[str] = None,
        api_method: Optional[str] = None,
        api_params: Optional[Dict] = None,
        transfer_to: Optional[str] = None,
        phone_display: Optional[str] = None,
        collect_fields: Optional[List[Dict]] = None,
        source: str = "manual",
    ) -> Dict:
        """Capability 추가 (VectorDB에 doc_type=capability로 저장)"""
        try:
            if not self._initialized:
                await self.initialize()

            embedding = await self.embedder.embed(text)

            metadata = {
                "doc_type": "capability",
                "category": category,
                "display_name": display_name,
                "response_type": response_type,
                "keywords": ",".join(keywords or []),
                "priority": priority,
                "is_active": is_active,
                "owner": owner or "",
                "source": source,
                "created_at": datetime.now().isoformat(),
                "updated_at": datetime.now().isoformat(),
            }
            if api_endpoint:
                metadata["api_endpoint"] = api_endpoint
            if api_method:
                metadata["api_method"] = api_method
            if api_params:
                metadata["api_params"] = json.dumps(api_params, ensure_ascii=False)
            if transfer_to:
                metadata["transfer_to"] = transfer_to
            if phone_display:
                metadata["phone_display"] = phone_display
            if collect_fields:
                metadata["collect_fields"] = json.dumps(collect_fields, ensure_ascii=False)

            await self.vector_db.upsert(
                doc_id=doc_id,
                embedding=embedding,
                text=text,
                metadata=metadata,
            )

            logger.info("capability_added", doc_id=doc_id, display_name=display_name)
            return {"id": doc_id, **metadata, "text": text}

        except Exception as e:
            logger.error("add_capability_failed", error=str(e), exc_info=True)
            raise

    async def get_all_capabilities(
        self,
        owner: Optional[str] = None,
        active_only: bool = False,
    ) -> List[Dict]:
        """모든 Capability 조회 (priority 순 정렬)"""
        try:
            if not self._initialized:
                await self.initialize()

            import asyncio
            loop = asyncio.get_event_loop()

            where_filter: Dict = {"doc_type": "capability"}
            if owner:
                where_filter = {"$and": [{"doc_type": "capability"}, {"owner": owner}]}
            if active_only:
                base = where_filter
                where_filter = {"$and": [base, {"is_active": True}]} if "$and" not in base else {
                    "$and": base["$and"] + [{"is_active": True}]
                }

            results = await loop.run_in_executor(
                None,
                lambda: self.vector_db.collection.get(
                    where=where_filter,
                    limit=200,
                    include=["documents", "metadatas"],
                ),
            )

            items = []
            if results["ids"]:
                for i, doc_id in enumerate(results["ids"]):
                    meta = results["metadatas"][i] if results["metadatas"] else {}
                    items.append(self._capability_from_raw(doc_id, results["documents"][i], meta))

            items.sort(key=lambda x: x.get("priority", 50))
            return items

        except Exception as e:
            logger.error("get_all_capabilities_failed", error=str(e), exc_info=True)
            return []

    async def get_capability(self, doc_id: str) -> Optional[Dict]:
        """단일 Capability 조회"""
        try:
            if not self._initialized:
                await self.initialize()

            import asyncio
            loop = asyncio.get_event_loop()
            results = await loop.run_in_executor(
                None,
                lambda: self.vector_db.collection.get(
                    ids=[doc_id],
                    include=["documents", "metadatas"],
                ),
            )
            if results["ids"]:
                meta = results["metadatas"][0] if results["metadatas"] else {}
                return self._capability_from_raw(results["ids"][0], results["documents"][0], meta)
            return None
        except Exception as e:
            logger.error("get_capability_failed", doc_id=doc_id, error=str(e))
            return None

    async def update_capability(self, doc_id: str, updates: Dict) -> Optional[Dict]:
        """Capability 수정 (삭제 후 재생성)"""
        try:
            existing = await self.get_capability(doc_id)
            if not existing:
                return None

            await self.delete_knowledge(doc_id)

            merged = {**existing, **{k: v for k, v in updates.items() if v is not None}}
            merged["updated_at"] = datetime.now().isoformat()

            new_id = doc_id
            return await self.add_capability(
                doc_id=new_id,
                display_name=merged["display_name"],
                text=merged["text"],
                category=merged["category"],
                response_type=merged.get("response_type", "info"),
                keywords=merged.get("keywords", []) if isinstance(merged.get("keywords"), list) else (merged.get("keywords", "") or "").split(","),
                priority=merged.get("priority", 50),
                is_active=merged.get("is_active", True),
                owner=merged.get("owner"),
                api_endpoint=merged.get("api_endpoint"),
                api_method=merged.get("api_method"),
                api_params=merged.get("api_params") if isinstance(merged.get("api_params"), dict) else None,
                transfer_to=merged.get("transfer_to"),
                collect_fields=merged.get("collect_fields") if isinstance(merged.get("collect_fields"), list) else None,
                source=merged.get("source", "manual"),
            )
        except Exception as e:
            logger.error("update_capability_failed", doc_id=doc_id, error=str(e), exc_info=True)
            raise

    async def toggle_capability(self, doc_id: str) -> Optional[Dict]:
        """Capability 활성/비활성 토글"""
        existing = await self.get_capability(doc_id)
        if not existing:
            return None
        return await self.update_capability(doc_id, {"is_active": not existing["is_active"]})

    async def reorder_capabilities(self, ordered_ids: List[str]) -> bool:
        """Capability 순서 일괄 변경"""
        try:
            for idx, doc_id in enumerate(ordered_ids, start=1):
                await self.update_capability(doc_id, {"priority": idx})
            logger.info("capabilities_reordered", count=len(ordered_ids))
            return True
        except Exception as e:
            logger.error("reorder_capabilities_failed", error=str(e))
            return False

    async def count_capabilities(self) -> int:
        """Capability 수 조회"""
        try:
            if not self._initialized:
                await self.initialize()
            import asyncio
            loop = asyncio.get_event_loop()
            results = await loop.run_in_executor(
                None,
                lambda: self.vector_db.collection.get(
                    where={"doc_type": "capability"},
                    limit=1,
                    include=[],
                ),
            )
            return len(results["ids"]) if results["ids"] else 0
        except Exception:
            return 0

    @staticmethod
    def _capability_from_raw(doc_id: str, text: str, meta: Dict) -> Dict:
        """ChromaDB raw 결과를 Capability dict로 변환"""
        keywords_raw = meta.get("keywords", "")
        keywords = [k for k in keywords_raw.split(",") if k] if isinstance(keywords_raw, str) else []

        api_params = None
        if meta.get("api_params"):
            try:
                api_params = json.loads(meta["api_params"])
            except (json.JSONDecodeError, TypeError):
                api_params = None

        collect_fields = None
        if meta.get("collect_fields"):
            try:
                collect_fields = json.loads(meta["collect_fields"])
            except (json.JSONDecodeError, TypeError):
                collect_fields = None

        return {
            "id": doc_id,
            "display_name": meta.get("display_name", ""),
            "text": text,
            "category": meta.get("category", ""),
            "response_type": meta.get("response_type", "info"),
            "keywords": keywords,
            "priority": meta.get("priority", 50),
            "is_active": meta.get("is_active", True),
            "owner": meta.get("owner", ""),
            "api_endpoint": meta.get("api_endpoint"),
            "api_method": meta.get("api_method"),
            "api_params": api_params,
            "transfer_to": meta.get("transfer_to"),
            "phone_display": meta.get("phone_display"),
            "collect_fields": collect_fields,
            "source": meta.get("source", "manual"),
            "created_at": meta.get("created_at", ""),
            "updated_at": meta.get("updated_at"),
        }

    # =========================================================================
    # Extraction Review (지식 추출 리뷰)
    # =========================================================================

    async def get_extractions(
        self,
        review_status: Optional[str] = None,
        doc_type: Optional[str] = None,
        owner: Optional[str] = None,
        limit: int = 100,
    ) -> List[Dict]:
        """추출된 지식 항목 조회 (review_status 필터)"""
        try:
            if not self._initialized:
                await self.initialize()

            import asyncio
            loop = asyncio.get_event_loop()

            # extraction_source가 "call"인 것만 조회
            where_parts = [{"extraction_source": "call"}]
            if review_status:
                where_parts.append({"review_status": review_status})
            if doc_type:
                where_parts.append({"doc_type": doc_type})
            if owner:
                where_parts.append({"owner": owner})

            if len(where_parts) == 1:
                where_filter = where_parts[0]
            else:
                where_filter = {"$and": where_parts}

            results = await loop.run_in_executor(
                None,
                lambda: self.vector_db.collection.get(
                    where=where_filter,
                    limit=limit,
                    include=["documents", "metadatas"],
                ),
            )

            items = []
            if results["ids"]:
                for i, doc_id in enumerate(results["ids"]):
                    meta = results["metadatas"][i] if results["metadatas"] else {}
                    text = results["documents"][i] if results["documents"] else ""
                    items.append({
                        "id": doc_id,
                        "text": text,
                        **meta,
                    })

            # extraction_timestamp 역순 정렬
            items.sort(key=lambda x: x.get("extraction_timestamp", ""), reverse=True)
            return items

        except Exception as e:
            logger.error("get_extractions_failed", error=str(e), exc_info=True)
            return []

    async def review_extraction(
        self,
        doc_id: str,
        action: str,
        reviewer: str = "operator",
        edited_text: Optional[str] = None,
        edited_category: Optional[str] = None,
    ) -> Optional[Dict]:
        """추출 항목 리뷰 (approve/reject/edit)"""
        try:
            if not self._initialized:
                await self.initialize()

            import asyncio
            loop = asyncio.get_event_loop()

            # 기존 항목 조회
            results = await loop.run_in_executor(
                None,
                lambda: self.vector_db.collection.get(
                    ids=[doc_id],
                    include=["documents", "metadatas"],
                ),
            )
            if not results["ids"]:
                return None

            meta = results["metadatas"][0] if results["metadatas"] else {}
            text = results["documents"][0] if results["documents"] else ""

            now = datetime.now().isoformat()

            if action == "reject":
                meta["review_status"] = "rejected"
                meta["reviewed_by"] = reviewer
                meta["reviewed_at"] = now
            elif action == "approve":
                meta["review_status"] = "approved"
                meta["reviewed_by"] = reviewer
                meta["reviewed_at"] = now
            elif action == "edit":
                if edited_text:
                    text = edited_text
                if edited_category:
                    meta["category"] = edited_category
                meta["review_status"] = "edited"
                meta["reviewed_by"] = reviewer
                meta["reviewed_at"] = now

            # 업데이트 (text 변경 시 임베딩도 재생성)
            embedding = await self.embedder.embed(text)
            await self.vector_db.upsert(
                doc_id=doc_id,
                embedding=embedding,
                text=text,
                metadata=meta,
            )

            logger.info("extraction_reviewed", doc_id=doc_id, action=action)
            return {"id": doc_id, "text": text, **meta}

        except Exception as e:
            logger.error("review_extraction_failed", doc_id=doc_id, error=str(e), exc_info=True)
            raise

    async def get_extraction_stats(self, owner: Optional[str] = None) -> Dict:
        """추출 통계 (owner별 격리)"""
        try:
            all_items = await self.get_extractions(owner=owner, limit=1000)

            total = len(all_items)
            pending = sum(1 for i in all_items if i.get("review_status") == "pending")
            approved = sum(1 for i in all_items if i.get("review_status") in ("approved", "edited"))
            rejected = sum(1 for i in all_items if i.get("review_status") == "rejected")
            auto_approved = sum(
                1 for i in all_items
                if i.get("review_status") == "approved" and not i.get("reviewed_by")
            )

            by_doc_type: Dict[str, int] = {}
            by_category: Dict[str, int] = {}
            total_conf = 0.0

            for item in all_items:
                dt = item.get("doc_type", "unknown")
                by_doc_type[dt] = by_doc_type.get(dt, 0) + 1
                cat = item.get("category", "unknown")
                by_category[cat] = by_category.get(cat, 0) + 1
                try:
                    total_conf += float(item.get("confidence_score", 0))
                except (ValueError, TypeError):
                    pass

            return {
                "total": total,
                "pending": pending,
                "approved": approved,
                "rejected": rejected,
                "auto_approved": auto_approved,
                "by_doc_type": by_doc_type,
                "by_category": by_category,
                "avg_confidence": total_conf / total if total > 0 else 0.0,
            }

        except Exception as e:
            logger.error("extraction_stats_failed", error=str(e))
            return {
                "total": 0, "pending": 0, "approved": 0, "rejected": 0,
                "auto_approved": 0, "by_doc_type": {}, "by_category": {},
                "avg_confidence": 0.0,
            }

    # -------------------------------------------------------------------------
    # 검토 대기열 (§7 PII 파이프라인 / 검토 워크플로)
    # -------------------------------------------------------------------------

    async def get_pending_review_extractions(
        self,
        owner: Optional[str] = None,
        status: str = "pending",
        limit: int = 100,
    ) -> List[Dict]:
        """검토 대기열(JSONL) 항목 목록 조회"""
        try:
            from src.services.extraction_review_store import get_extraction_review_store
            store = get_extraction_review_store(self._extraction_pending_file)
            items = await store.list_pending(owner=owner, status=status, limit=limit)
            return items
        except Exception as e:
            logger.error("get_pending_review_extractions_failed", error=str(e), exc_info=True)
            return []

    async def review_pending_extraction(
        self,
        pending_id: str,
        action: str,
        reviewer: str = "operator",
        edited_text: Optional[str] = None,
        edited_category: Optional[str] = None,
    ) -> Optional[Dict]:
        """검토 대기열 항목 승인/거절/편집. 승인 시 VectorDB에 반영 후 대기열에서 상태 갱신."""
        try:
            from src.services.extraction_review_store import get_extraction_review_store
            store = get_extraction_review_store(self._extraction_pending_file)
            item = await store.get(pending_id)
            if not item:
                return None
            if action in ("approve", "edit"):
                text = edited_text if edited_text is not None else item["text"]
                category = edited_category if edited_category is not None else item.get("category", "기타")
                if not self._initialized:
                    await self.initialize()
                embedding = await self.embedder.embed(text)
                doc_id = f"approved_{pending_id}" if action == "approve" else f"edited_{pending_id}"
                meta = {
                    "call_id": item.get("call_id", ""),
                    "owner": item.get("owner", ""),
                    "speaker": item.get("speaker", "callee"),
                    "category": category,
                    "keywords": item.get("keywords", []),
                    "chunk_index": item.get("chunk_index", 0),
                    "confidence": item.get("confidence", 0.0),
                    "contains_pii": item.get("contains_pii", False),
                    "extraction_source": "call",
                    "review_status": "approved" if action == "approve" else "edited",
                    "reviewed_by": reviewer,
                    "reviewed_at": datetime.now().isoformat(),
                }
                await self.vector_db.upsert(
                    doc_id=doc_id,
                    embedding=embedding,
                    text=text,
                    metadata=meta,
                )
            new_status = "approved" if action == "approve" else ("edited" if action == "edit" else "rejected")
            await store.update_status(
                pending_id,
                new_status,
                reviewer=reviewer,
                edited_text=edited_text,
                edited_category=edited_category,
            )
            return await store.get(pending_id)
        except Exception as e:
            logger.error("review_pending_extraction_failed", pending_id=pending_id, error=str(e), exc_info=True)
            raise

    # -------------------------------------------------------------------------
    # §7 누적 기반 추출: 클러스터·중복 제거
    # -------------------------------------------------------------------------

    async def run_batch_dedup(
        self,
        owner: Optional[str] = None,
        similarity_threshold: float = 0.92,
        limit: int = 500,
        apply: bool = False,
    ) -> Dict:
        """
        여러 통화 추출 결과를 카테고리별로 묶고, 임베딩 유사도로 클러스터링 후
        클러스터당 대표 1건만 유지(중복 제거). apply=True 시 비대표 항목 메타데이터에
        dedup_status=merged, merged_into=대표id 반영.
        """
        import asyncio
        import math

        try:
            if not self._initialized:
                await self.initialize()
            loop = asyncio.get_event_loop()

            # owner만 있으면 해당 owner 문서만; 없으면 extraction_source=call인 문서만 (구 데이터는 call_id 있는 것 포함)
            where_parts = []
            if owner:
                where_parts.append({"owner": owner})
            if not owner:
                where_parts.append({"extraction_source": "call"})
            where_filter = where_parts[0] if len(where_parts) == 1 else {"$and": where_parts}

            results = await loop.run_in_executor(
                None,
                lambda: self.vector_db.collection.get(
                    where=where_filter,
                    limit=limit,
                    include=["documents", "metadatas", "embeddings"],
                ),
            )
            ids = results.get("ids") or []
            documents = results.get("documents") or []
            metadatas = results.get("metadatas") or [{}] * len(ids)
            embeddings = results.get("embeddings")
            if not ids or not embeddings:
                return {
                    "total": 0,
                    "clusters": 0,
                    "representative_ids": [],
                    "merged_count": 0,
                    "by_category": {},
                }

            def _norm(v):
                s = sum(x * x for x in v) ** 0.5
                return [x / s for x in v] if s > 0 else v

            def _cosine(a, b):
                an, bn = _norm(a), _norm(b)
                return sum(an[i] * bn[i] for i in range(len(an)))

            # (owner, category)별로 그룹
            by_key: Dict[tuple, List[int]] = {}
            for i, doc_id in enumerate(ids):
                meta = metadatas[i] if i < len(metadatas) else {}
                key = (meta.get("owner", ""), meta.get("category", "기타"))
                by_key.setdefault(key, []).append(i)

            total_merged = 0
            rep_ids = []
            by_category: Dict[str, int] = {}

            for (own, cat), indices in by_key.items():
                if len(indices) <= 1:
                    rep_ids.append(ids[indices[0]])
                    by_category[cat] = by_category.get(cat, 0) + 1
                    continue
                # 유사도 기반 클러스터링 (그리디: 첫 항목 기준으로 threshold 이상이면 같은 클러스터)
                used = set()
                clusters: List[List[int]] = []
                for start in indices:
                    if start in used:
                        continue
                    cluster = [start]
                    used.add(start)
                    for j in indices:
                        if j in used:
                            continue
                        if _cosine(embeddings[start], embeddings[j]) >= similarity_threshold:
                            cluster.append(j)
                            used.add(j)
                    clusters.append(cluster)
                for cluster in clusters:
                    # 대표: 텍스트가 가장 긴 항목
                    rep_idx = max(cluster, key=lambda idx: len(documents[idx]) if idx < len(documents) else 0)
                    rep_id = ids[rep_idx]
                    rep_ids.append(rep_id)
                    by_category[cat] = by_category.get(cat, 0) + 1
                    merged_in_cluster = len(cluster) - 1
                    total_merged += merged_in_cluster
                    if apply and merged_in_cluster > 0:
                        for idx in cluster:
                            if idx == rep_idx:
                                continue
                            doc_id = ids[idx]
                            meta = dict(metadatas[idx] if idx < len(metadatas) else {})
                            meta["dedup_status"] = "merged"
                            meta["merged_into"] = rep_id
                            # ChromaDB는 upsert로 메타데이터만 갱신 가능
                            await self.vector_db.upsert(
                                doc_id=doc_id,
                                embedding=embeddings[idx],
                                text=documents[idx] if idx < len(documents) else "",
                                metadata=meta,
                            )
            return {
                "total": len(ids),
                "clusters": len(rep_ids),
                "representative_ids": rep_ids,
                "merged_count": total_merged,
                "by_category": by_category,
            }
        except Exception as e:
            logger.error("run_batch_dedup_failed", error=str(e), exc_info=True)
            raise

    async def get_stats(self) -> Dict:
        """통계 조회
        
        Returns:
            통계 정보
        """
        try:
            if not self._initialized:
                await self.initialize()
            
            total_count = await self.vector_db.count()
            vectordb_stats = self.vector_db.get_stats()
            embedder_stats = self.embedder.get_stats()
            
            return {
                "total_documents": total_count,
                "vectordb": vectordb_stats,
                "embedder": embedder_stats
            }
            
        except Exception as e:
            logger.error("Failed to get stats", error=str(e))
            return {}


# 싱글톤 인스턴스
_knowledge_service_instance: Optional[KnowledgeService] = None


def get_knowledge_service() -> KnowledgeService:
    """Knowledge Service 싱글톤 인스턴스 반환"""
    global _knowledge_service_instance
    
    if _knowledge_service_instance is None:
        _knowledge_service_instance = KnowledgeService()
    
    return _knowledge_service_instance


def set_knowledge_service(service: KnowledgeService) -> None:
    """Knowledge Service 싱글톤 인스턴스 설정
    
    Args:
        service: KnowledgeService 인스턴스
    """
    global _knowledge_service_instance
    _knowledge_service_instance = service
    logger.info("Knowledge Service singleton set")
