"""
Knowledge Service

지식 베이스 CRUD 및 검색 서비스
"""

import asyncio
import json
from typing import List, Dict, Optional, Any
from datetime import datetime
import structlog

logger = structlog.get_logger(__name__)

_global_knowledge_service = None


class KnowledgeService:
    """지식 베이스 서비스 (ChromaDB 기반)"""
    
    def __init__(self, vector_db, embedder, extraction_pending_file: str = None):
        """
        Args:
            vector_db: ChromaDB 클라이언트
            embedder: TextEmbedder
            extraction_pending_file: 추출 대기열 파일 경로 (HITL용)
        """
        self._vector_db = vector_db
        self._embedder = embedder
        self._extraction_pending_file = extraction_pending_file

    @property
    def vector_db(self):
        """OrganizationInfoManager 등 외부에서 vector_db 직접 접근 시 사용."""
        return self._vector_db

    @property
    def embedder(self):
        return self._embedder
    
    async def add_knowledge(
        self,
        text: str,
        category: str = "question",
        keywords: List[str] = None,
        metadata: Dict[str, Any] = None,
    ) -> Dict[str, Any]:
        """
        지식 추가
        
        Args:
            text: 지식 내용
            category: 카테고리
            keywords: 키워드 리스트
            metadata: 메타데이터 (owner, doc_type, source 등)
            
        Returns:
            {"id": "doc_id_123", "success": True}
        """
        try:
            # 임베딩 생성 (비동기 메서드 사용)
            embedding = await self._embedder.embed(text)
            
            # 메타데이터 기본값
            meta = metadata or {}
            meta.setdefault("category", category)
            meta.setdefault("created_at", datetime.now().isoformat())
            
            # ChromaDB 저장
            doc_id = f"kb_{datetime.now().strftime('%Y%m%d_%H%M%S_%f')}"
            
            # 동기 메서드이므로 asyncio.to_thread 사용
            await asyncio.to_thread(
                self._vector_db.add,
                ids=[doc_id],
                embeddings=[embedding],
                documents=[text],
                metadatas=[meta],
            )
            
            logger.info("knowledge_added",
                       doc_id=doc_id,
                       category=category,
                       text_preview=text[:50],
                       metadata_keys=list(meta.keys()),
                       note="지식 저장 완료")
            
            return {"id": doc_id, "success": True}
            
        except Exception as e:
            logger.error("knowledge_add_error",
                        text_preview=text[:50],
                        error=str(e),
                        exc_info=True)
            raise

    def _normalize_chroma_metadata_value(self, v: Any) -> Any:
        """Chroma 메타데이터에 넣을 수 있는 스칼라로 맞춘다."""
        if v is None:
            return ""
        if isinstance(v, (str, int, float, bool)):
            return v
        return str(v)

    async def add_from_hitl(
        self,
        question: str,
        answer: str,
        call_id: str,
        operator_id: str = "",
        category: str = "question",
        owner: Optional[str] = None,
        owner_id: Optional[str] = None,
        extra_metadata: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """
        HITL에서 확정한 Q&A를 지식 베이스에 추가.

        WebSocket `submit_hitl_response` 및 `flush_hitl_kb_for_call`에서 호출된다.
        """
        q = (question or "").strip()
        a = (answer or "").strip()
        if not q or not a:
            logger.warning(
                "knowledge_add_from_hitl_skipped_empty",
                call_id=call_id,
                has_question=bool(q),
                has_answer=bool(a),
            )
            return {
                "success": False,
                "error": "question과 answer가 비어 있으면 안 됩니다",
                "doc_id": None,
            }

        text = f"Q: {q}\nA: {a}"
        eff_owner = ((owner or owner_id) or "").strip() or None

        meta: Dict[str, Any] = {
            "source": "hitl",
            "doc_type": "knowledge",
            "call_id": str(call_id),
            "operator_id": str(operator_id or ""),
        }
        if eff_owner:
            meta["owner"] = eff_owner
        if extra_metadata:
            for k, v in extra_metadata.items():
                meta[str(k)] = self._normalize_chroma_metadata_value(v)

        try:
            result = await self.add_knowledge(
                text=text,
                category=category,
                keywords=[],
                metadata=meta,
            )
            doc_id = result.get("id")
            logger.info(
                "knowledge_added_from_hitl",
                call_id=call_id,
                doc_id=doc_id,
                category=category,
                owner_set=bool(eff_owner),
                kb_timing=(extra_metadata or {}).get("kb_timing"),
            )
            return {"success": True, "doc_id": doc_id, "error": None}
        except Exception as e:
            logger.error(
                "knowledge_add_from_hitl_failed",
                call_id=call_id,
                category=category,
                error=str(e),
                exc_info=True,
            )
            return {"success": False, "error": str(e), "doc_id": None}
    
    async def get_all_knowledge(
        self,
        category: Optional[str] = None,
        limit: int = 1000,
    ) -> List[Dict[str, Any]]:
        """
        모든 지식 조회
        
        Args:
            category: 필터링할 카테고리 (None이면 전체)
            limit: 최대 개수
            
        Returns:
            [{"id": "...", "text": "...", "metadata": {...}}, ...]
        """
        try:
            # ChromaDB get() 호출 (동기 메서드)
            where = {"category": {"$eq": category}} if category else None
            results = await asyncio.to_thread(
                self._vector_db.get,
                where=where,
                limit=limit,
            )
            
            # 결과 포맷 변환
            ids = results.get("ids", [])
            documents = results.get("documents", [])
            metadatas = results.get("metadatas", [])
            
            output = []
            for i, doc_id in enumerate(ids):
                meta = metadatas[i] if i < len(metadatas) else {}
                output.append({
                    "id": doc_id,
                    "text": documents[i] if i < len(documents) else "",
                    "category": meta.get("category", ""),
                    "metadata": meta,
                })
            
            return output
            
        except Exception as e:
            logger.error("knowledge_get_all_error", error=str(e))
            return []
    
    async def increment_hit_count(self, doc_id: str) -> int:
        """
        지식 문서의 hit_count를 1 증가시킨다.

        ChromaDB 메타데이터를 읽어 hit_count를 올린 뒤 upsert로 덮어씌운다.
        임베딩 재계산 없이 메타데이터만 교체하기 위해 collection.update()를 사용한다.

        Returns:
            갱신 후 hit_count (실패 시 -1)
        """
        try:
            def _run() -> int:
                res = self._vector_db.collection.get(
                    ids=[doc_id],
                    include=["metadatas"],
                )
                ids_out = res.get("ids") or []
                if not ids_out:
                    logger.warning("hit_count_doc_not_found", doc_id=doc_id)
                    return -1
                meta = (res.get("metadatas") or [{}])[0] or {}
                new_count = int(meta.get("hit_count") or 0) + 1
                meta["hit_count"] = new_count
                self._vector_db.collection.update(ids=[doc_id], metadatas=[meta])
                return new_count

            new_count = await asyncio.to_thread(_run)
            if new_count >= 0:
                logger.info(
                    "knowledge_hit_count_incremented",
                    doc_id=doc_id,
                    hit_count=new_count,
                )
            return new_count
        except Exception as e:
            logger.error("knowledge_hit_count_error", doc_id=doc_id, error=str(e))
            return -1

    async def delete_knowledge(self, doc_id: str) -> bool:
        """
        지식 삭제
        
        Args:
            doc_id: 문서 ID
            
        Returns:
            성공 여부
        """
        try:
            await asyncio.to_thread(self._vector_db.delete, ids=[doc_id])
            logger.info("knowledge_deleted", doc_id=doc_id)
            return True
        except Exception as e:
            logger.error("knowledge_delete_error", doc_id=doc_id, error=str(e))
            return False
    
    async def delete_by_source_file(self, source_file: str) -> int:
        """
        특정 source_file로 저장된 모든 문서 삭제
        
        Args:
            source_file: 원본 파일명 (예: "기상청_매뉴얼.txt")
            
        Returns:
            삭제된 문서 수
        """
        try:
            # 전체 문서 조회 (필터링 위해)
            all_docs = await self.get_all_knowledge(limit=10000)
            
            # source_file 일치하는 문서 찾기
            target_ids = []
            for doc in all_docs:
                metadata = doc.get("metadata", {})
                if metadata.get("source_file") == source_file:
                    target_ids.append(doc["id"])
            
            if not target_ids:
                logger.info("delete_by_source_file_none_found", 
                           source_file=source_file,
                           note="삭제할 문서 없음")
                return 0
            
            # 삭제
            await asyncio.to_thread(self._vector_db.delete, ids=target_ids)
            
            logger.info("delete_by_source_file_complete",
                       source_file=source_file,
                       deleted_count=len(target_ids),
                       note="source_file 기준 문서 일괄 삭제")
            
            return len(target_ids)
            
        except Exception as e:
            logger.error("delete_by_source_file_error",
                        source_file=source_file,
                        error=str(e))
            return 0

    # ------------------------------------------------------------------
    # Capability (doc_type=capability) — REST / 시드 / AI Phase2 가이드용
    # ------------------------------------------------------------------

    @staticmethod
    def _coerce_bool_active(v: Any, default: bool = True) -> bool:
        if v is True or v is False:
            return v
        if isinstance(v, str):
            return v.strip().lower() in ("true", "1", "yes")
        if v is None:
            return default
        return bool(v)

    def _parse_capability_keywords(self, meta: Dict[str, Any]) -> List[str]:
        kw = meta.get("keywords")
        if isinstance(kw, list):
            return [str(x) for x in kw if str(x).strip()]
        if isinstance(kw, str) and kw.strip():
            return [x.strip() for x in kw.split(",") if x.strip()]
        return []

    def _capability_chroma_to_dict(
        self,
        doc_id: str,
        document: str,
        meta: Dict[str, Any],
    ) -> Dict[str, Any]:
        """Chroma 행 → capabilities API / orchestrator 공통 dict."""
        m = meta or {}
        api_params: Optional[Dict[str, Any]] = None
        raw_ap = m.get("api_params")
        if isinstance(raw_ap, str) and raw_ap.strip():
            try:
                api_params = json.loads(raw_ap)
            except (json.JSONDecodeError, TypeError):
                api_params = None
        elif isinstance(raw_ap, dict):
            api_params = raw_ap

        collect_fields: Optional[List[Dict[str, Any]]] = None
        raw_cf = m.get("collect_fields")
        if isinstance(raw_cf, str) and raw_cf.strip():
            try:
                parsed = json.loads(raw_cf)
                if isinstance(parsed, list):
                    collect_fields = parsed
            except (json.JSONDecodeError, TypeError):
                collect_fields = None
        elif isinstance(raw_cf, list):
            collect_fields = raw_cf

        pr = m.get("priority", 50)
        try:
            priority = int(pr)
        except (TypeError, ValueError):
            priority = 50

        return {
            "id": doc_id,
            "display_name": str(m.get("display_name") or ""),
            "text": document if isinstance(document, str) else "",
            "category": str(m.get("category") or ""),
            "response_type": str(m.get("response_type") or "info"),
            "keywords": self._parse_capability_keywords(m),
            "priority": priority,
            "is_active": self._coerce_bool_active(m.get("is_active"), True),
            "owner": (
                str(_ow).strip()
                if (_ow := m.get("owner")) not in (None, "")
                else None
            ),
            "api_endpoint": (m.get("api_endpoint") or None) if m.get("api_endpoint") else None,
            "api_method": (m.get("api_method") or None) if m.get("api_method") else None,
            "api_params": api_params,
            "transfer_to": (m.get("transfer_to") or None) if m.get("transfer_to") else None,
            "phone_display": (m.get("phone_display") or None) if m.get("phone_display") else None,
            "collect_fields": collect_fields,
            "created_at": str(m.get("created_at") or ""),
            "updated_at": (str(m.get("updated_at")) if m.get("updated_at") else None),
        }

    async def get_all_capabilities(
        self,
        owner: Optional[str] = None,
        active_only: bool = False,
    ) -> List[Dict[str, Any]]:
        """doc_type=capability 문서 목록 (priority 오름차순)."""
        where: Dict[str, Any] = {"doc_type": "capability"}
        try:
            results = await asyncio.to_thread(
                self._vector_db.get,
                where=where,
                limit=5000,
            )
        except Exception as e:
            logger.error("get_all_capabilities_chroma_error", error=str(e), exc_info=True)
            return []

        ids = results.get("ids") or []
        documents = results.get("documents") or []
        metadatas = results.get("metadatas") or []

        out: List[Dict[str, Any]] = []
        owner_f = (owner or "").strip() or None

        for i, doc_id in enumerate(ids):
            meta = metadatas[i] if i < len(metadatas) else {}
            if not isinstance(meta, dict):
                meta = {}
            if (meta.get("doc_type") or "") != "capability":
                continue
            if owner_f:
                doc_owner = str(meta.get("owner") or "").strip()
                if doc_owner != owner_f:
                    continue
            if active_only and not self._coerce_bool_active(meta.get("is_active"), True):
                continue
            doc_text = documents[i] if i < len(documents) else ""
            out.append(
                self._capability_chroma_to_dict(doc_id, doc_text, meta)
            )

        out.sort(key=lambda x: (x.get("priority", 50), x.get("display_name", "")))
        return out

    async def count_capabilities(self, owner: Optional[str] = None) -> int:
        items = await self.get_all_capabilities(owner=owner, active_only=False)
        return len(items)

    async def add_capability(
        self,
        doc_id: str,
        display_name: str,
        text: str,
        category: str,
        response_type: str = "info",
        keywords: Optional[List[str]] = None,
        priority: int = 50,
        is_active: bool = True,
        owner: Optional[str] = None,
        source: str = "api",
        api_endpoint: Optional[str] = None,
        api_method: Optional[str] = None,
        api_params: Optional[Dict[str, Any]] = None,
        transfer_to: Optional[str] = None,
        phone_display: Optional[str] = None,
        collect_fields: Optional[List[Dict[str, Any]]] = None,
    ) -> Dict[str, Any]:
        """Capability 1건 추가 (임베딩 = display_name + 본문)."""
        now = datetime.now().isoformat()
        meta: Dict[str, Any] = {
            "doc_type": "capability",
            "display_name": display_name,
            "category": category,
            "response_type": response_type,
            "keywords": ",".join(keywords or []),
            "priority": int(priority),
            "is_active": bool(is_active),
            "source": source,
            "created_at": now,
            "updated_at": now,
        }
        if owner:
            meta["owner"] = owner
        if api_endpoint:
            meta["api_endpoint"] = api_endpoint
        if api_method:
            meta["api_method"] = api_method
        if api_params is not None:
            meta["api_params"] = json.dumps(api_params, ensure_ascii=False)
        if transfer_to:
            meta["transfer_to"] = transfer_to
        if phone_display:
            meta["phone_display"] = phone_display
        if collect_fields is not None:
            meta["collect_fields"] = json.dumps(collect_fields, ensure_ascii=False)

        embed_text = f"{display_name}\n{text}".strip()
        embedding = await self._embedder.embed(embed_text)

        await asyncio.to_thread(
            self._vector_db.add,
            ids=[doc_id],
            embeddings=[embedding],
            documents=[text],
            metadatas=[meta],
        )
        logger.info(
            "capability_added",
            doc_id=doc_id,
            owner=owner or "",
            display_name_preview=display_name[:40],
        )
        return self._capability_chroma_to_dict(doc_id, text, meta)

    async def update_capability(
        self,
        cap_id: str,
        updates: Dict[str, Any],
    ) -> Optional[Dict[str, Any]]:
        """메타데이터·본문 갱신. 본문/display_name 변경 시 임베딩 재계산."""

        def _get() -> Dict[str, Any]:
            return self._vector_db.collection.get(
                ids=[cap_id],
                include=["documents", "metadatas"],
            )

        res = await asyncio.to_thread(_get)
        ids_out = res.get("ids") or []
        if not ids_out:
            return None
        doc_text = (res.get("documents") or [""])[0] or ""
        meta = dict((res.get("metadatas") or [{}])[0] or {})
        if (meta.get("doc_type") or "") != "capability":
            return None

        new_body = doc_text
        if updates.get("text") is not None:
            new_body = str(updates["text"])

        new_display = str(
            updates["display_name"]
            if updates.get("display_name") is not None
            else meta.get("display_name") or ""
        )

        reembed = updates.get("text") is not None or updates.get("display_name") is not None

        field_map = (
            ("category", "category"),
            ("response_type", "response_type"),
            ("priority", "priority"),
            ("is_active", "is_active"),
            ("owner", "owner"),
            ("api_endpoint", "api_endpoint"),
            ("api_method", "api_method"),
            ("transfer_to", "transfer_to"),
            ("phone_display", "phone_display"),
        )
        for src, dst in field_map:
            if updates.get(src) is not None:
                val = updates[src]
                if dst == "priority":
                    try:
                        meta[dst] = int(val)
                    except (TypeError, ValueError):
                        meta[dst] = 50
                elif dst == "is_active":
                    meta[dst] = bool(val)
                else:
                    meta[dst] = val

        if updates.get("keywords") is not None:
            kw = updates["keywords"]
            meta["keywords"] = ",".join(kw) if isinstance(kw, list) else str(kw)

        if updates.get("api_params") is not None:
            ap = updates["api_params"]
            meta["api_params"] = json.dumps(ap, ensure_ascii=False) if ap is not None else ""

        if updates.get("collect_fields") is not None:
            cf = updates["collect_fields"]
            meta["collect_fields"] = (
                json.dumps(cf, ensure_ascii=False) if cf is not None else ""
            )

        meta["updated_at"] = datetime.now().isoformat()

        if updates.get("display_name") is not None:
            meta["display_name"] = str(updates["display_name"])

        if reembed:
            new_embedding = await self._embedder.embed(
                f"{new_display}\n{new_body}".strip()
            )

            def _upd_full():
                self._vector_db.collection.update(
                    ids=[cap_id],
                    embeddings=[new_embedding],
                    documents=[new_body],
                    metadatas=[meta],
                )

            await asyncio.to_thread(_upd_full)
        else:

            def _upd_meta():
                self._vector_db.collection.update(ids=[cap_id], metadatas=[meta])

            await asyncio.to_thread(_upd_meta)

        return self._capability_chroma_to_dict(cap_id, new_body, meta)

    async def toggle_capability(self, cap_id: str) -> Optional[Dict[str, Any]]:
        def _get() -> Dict[str, Any]:
            return self._vector_db.collection.get(
                ids=[cap_id],
                include=["documents", "metadatas"],
            )

        res = await asyncio.to_thread(_get)
        if not (res.get("ids") or []):
            return None
        doc_text = (res.get("documents") or [""])[0] or ""
        meta = dict((res.get("metadatas") or [{}])[0] or {})
        if (meta.get("doc_type") or "") != "capability":
            return None
        meta["is_active"] = not self._coerce_bool_active(meta.get("is_active"), True)
        meta["updated_at"] = datetime.now().isoformat()

        def _upd():
            self._vector_db.collection.update(ids=[cap_id], metadatas=[meta])

        await asyncio.to_thread(_upd)
        return self._capability_chroma_to_dict(cap_id, doc_text, meta)

    async def reorder_capabilities(self, ordered_ids: List[str]) -> bool:
        try:
            for i, cap_id in enumerate(ordered_ids):
                r = await self.update_capability(cap_id, {"priority": (i + 1) * 10})
                if r is None:
                    logger.warning("reorder_capability_missing", cap_id=cap_id)
                    return False
            return True
        except Exception as e:
            logger.error("reorder_capabilities_error", error=str(e), exc_info=True)
            return False


async def initialize_knowledge_service(vector_db, embedder, extraction_pending_file: str = None):
    """
    Knowledge Service 초기화 (Factory에서 호출)
    
    Args:
        vector_db: ChromaDB 클라이언트
        embedder: TextEmbedder
        extraction_pending_file: 추출 대기열 파일 경로
        
    Returns:
        KnowledgeService 인스턴스
    """
    global _global_knowledge_service
    
    try:
        service = KnowledgeService(vector_db, embedder, extraction_pending_file)
        _global_knowledge_service = service
        logger.info("knowledge_service_initialized",
                   note="KnowledgeService 싱글톤 생성 완료")
        return service
    except Exception as e:
        logger.error("knowledge_service_init_error", error=str(e), exc_info=True)
        raise


def set_knowledge_service(service: KnowledgeService):
    """
    전역 Knowledge Service 설정
    
    Args:
        service: KnowledgeService 인스턴스
    """
    global _global_knowledge_service
    _global_knowledge_service = service
    logger.info("knowledge_service_set_globally", note="KnowledgeService 전역 설정 완료")


def get_knowledge_service() -> Optional[KnowledgeService]:
    """
    전역 Knowledge Service 반환
    
    Returns:
        KnowledgeService 인스턴스 또는 None
    """
    global _global_knowledge_service
    return _global_knowledge_service
