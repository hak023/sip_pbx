"""
Organization Persona Service

조직 페르소나 관리 및 Chitchat vs Question 분류.

설계:
- ChromaDB `persona` collection에 owner별 페르소나 저장
- 사용자 질문과 persona.description 유사도 계산
- 유사도 기준으로 chitchat vs question 분류
"""

import time
from typing import Optional, Dict, Any, List
from datetime import datetime
import structlog

from src.config.models import OrganizationPersona

logger = structlog.get_logger(__name__)

# 질의 vs 페르소나 description 임베딩 유사도 하한 (cosine distance → 1/(1+d) 스케일)
DEFAULT_PERSONA_SIMILARITY_THRESHOLD: float = 0.6


class PersonaService:
    """조직 페르소나 관리 서비스"""
    
    def __init__(self, chroma_client, embedder):
        """
        Args:
            chroma_client: ChromaDB 클라이언트
            embedder: Embedding 서비스
        """
        self._chroma = chroma_client
        self._embedder = embedder
        self._collection_name = "persona"
        self._collection = None
        self._cache: Dict[str, OrganizationPersona] = {}  # owner → persona 메모리 캐시
        self._cache_ttl_sec = 300  # 5분
        self._cache_timestamps: Dict[str, float] = {}
    
    async def initialize(self):
        """Persona collection 초기화"""
        try:
            self._collection = self._chroma.get_or_create_collection(
                name=self._collection_name,
                metadata={"description": "Organization personas for chitchat classification"}
            )
            logger.info("persona_collection_initialized",
                       collection=self._collection_name,
                       note="조직 페르소나 컬렉션 초기화 완료")
        except Exception as e:
            logger.error("persona_collection_init_error", error=str(e))
            raise
    
    async def save_persona(self, persona: OrganizationPersona) -> bool:
        """
        Persona 저장 (생성 또는 업데이트)
        
        Args:
            persona: OrganizationPersona 객체
            
        Returns:
            성공 여부
        """
        try:
            if not self._collection:
                await self.initialize()
            
            # description 임베딩 (비동기)
            embedding = await self._embedder.embed(persona.description)
            
            # ChromaDB 저장
            doc_id = f"persona_{persona.owner}"
            metadata = {
                "owner": persona.owner,
                "name": persona.name,
                "scope_keywords": ",".join(persona.scope_keywords) if persona.scope_keywords else "",
                "chitchat_template": persona.chitchat_response_template or "",
                "enabled": persona.enabled,
                "escalation_mode": getattr(persona, "escalation_mode", None) or "hitl",
                "transfer_extension": (getattr(persona, "transfer_extension", None) or "") or "",
                "sip_message_ai_reply_enabled": bool(
                    getattr(persona, "sip_message_ai_reply_enabled", False)
                ),
                "sip_message_ai_reply_prefix": (
                    getattr(persona, "sip_message_ai_reply_prefix", None) or ""
                ),
                "created_at": persona.created_at or datetime.now().isoformat(),
                "updated_at": datetime.now().isoformat(),
            }
            
            self._collection.upsert(
                ids=[doc_id],
                embeddings=[embedding],
                documents=[persona.description],
                metadatas=[metadata]
            )
            
            # 캐시 업데이트
            self._cache[persona.owner] = persona
            self._cache_timestamps[persona.owner] = time.time()
            
            logger.info("persona_saved",
                       owner=persona.owner,
                       name=persona.name,
                       desc_len=len(persona.description),
                       scope_keywords_count=len(persona.scope_keywords))
            
            return True
            
        except Exception as e:
            logger.error("persona_save_error",
                        owner=persona.owner,
                        error=str(e))
            return False
    
    async def get_persona(self, owner: str) -> Optional[OrganizationPersona]:
        """
        Owner의 Persona 조회
        
        Args:
            owner: Owner ID (착신번호)
            
        Returns:
            OrganizationPersona 또는 None
        """
        # 캐시 확인
        if owner in self._cache:
            cached_at = self._cache_timestamps.get(owner, 0)
            if time.time() - cached_at < self._cache_ttl_sec:
                return self._cache[owner]
        
        try:
            if not self._collection:
                await self.initialize()
            
            doc_id = f"persona_{owner}"
            result = self._collection.get(
                ids=[doc_id],
                include=["documents", "metadatas"]
            )
            
            if not result["ids"]:
                logger.debug("persona_not_found", owner=owner)
                return None
            
            metadata = result["metadatas"][0]
            description = result["documents"][0]

            def _meta_bool(key: str, default: bool = False) -> bool:
                v = metadata.get(key, default)
                if isinstance(v, bool):
                    return v
                if isinstance(v, (int, float)):
                    return bool(v)
                s = str(v).strip().lower()
                return s in ("true", "1", "yes", "on")

            _sip_pref = metadata.get("sip_message_ai_reply_prefix")
            if isinstance(_sip_pref, str) and not _sip_pref.strip():
                _sip_pref = None

            persona = OrganizationPersona(
                owner=owner,
                name=metadata["name"],
                description=description,
                scope_keywords=metadata.get("scope_keywords", "").split(",") if metadata.get("scope_keywords") else [],
                chitchat_response_template=metadata.get("chitchat_template") or None,
                escalation_mode=str(metadata.get("escalation_mode") or "hitl").strip() or "hitl",
                transfer_extension=(str(metadata.get("transfer_extension") or "").strip() or None),
                enabled=metadata.get("enabled", True),
                sip_message_ai_reply_enabled=_meta_bool("sip_message_ai_reply_enabled", False),
                sip_message_ai_reply_prefix=_sip_pref,
                created_at=metadata.get("created_at"),
                updated_at=metadata.get("updated_at"),
            )
            
            # 캐시 저장
            self._cache[owner] = persona
            self._cache_timestamps[owner] = time.time()
            
            return persona
            
        except Exception as e:
            logger.error("persona_get_error", owner=owner, error=str(e))
            return None
    
    async def delete_persona(self, owner: str) -> bool:
        """Persona 삭제"""
        try:
            if not self._collection:
                await self.initialize()
            
            doc_id = f"persona_{owner}"
            self._collection.delete(ids=[doc_id])
            
            # 캐시 제거
            self._cache.pop(owner, None)
            self._cache_timestamps.pop(owner, None)
            
            logger.info("persona_deleted", owner=owner)
            return True
            
        except Exception as e:
            logger.error("persona_delete_error", owner=owner, error=str(e))
            return False
    
    async def check_query_relevance(
        self, 
        query: str, 
        owner: str,
        similarity_threshold: float = DEFAULT_PERSONA_SIMILARITY_THRESHOLD,
    ) -> Dict[str, Any]:
        """
        Query가 조직 페르소나와 관련되는지 확인
        
        Args:
            query: 사용자 질문
            owner: Owner ID
            similarity_threshold: 유사도 임계값 (기본 0.6)
            
        Returns:
            {
                "is_relevant": bool,  # 업무 관련 질문인가
                "similarity": float,  # 유사도 점수
                "persona_found": bool,  # Persona 설정됨
                "chitchat_template": str,  # Chitchat 시 사용할 템플릿
            }
        """
        try:
            persona = await self.get_persona(owner)
            
            if not persona or not persona.enabled:
                # Persona 미설정 → 기본 동작 (모든 질문을 question으로 처리)
                return {
                    "is_relevant": True,
                    "similarity": 1.0,
                    "persona_found": False,
                    "chitchat_template": None,
                }
            
            # Query 임베딩 (비동기)
            query_embedding = await self._embedder.embed(query)
            
            # Persona description과 유사도 계산
            doc_id = f"persona_{owner}"
            results = self._collection.query(
                query_embeddings=[query_embedding],
                n_results=1,
                where={"owner": owner},
                include=["distances", "metadatas"]
            )
            
            if not results["ids"] or not results["ids"][0]:
                return {
                    "is_relevant": True,
                    "similarity": 1.0,
                    "persona_found": False,
                    "chitchat_template": None,
                }
            
            # Chroma distance → similarity
            distance = results["distances"][0][0]
            similarity = 1.0 / (1.0 + distance)
            
            is_relevant = similarity >= similarity_threshold
            
            logger.info("persona_query_relevance_check",
                       owner=owner,
                       query_preview=query[:50],
                       similarity=round(similarity, 4),
                       threshold=similarity_threshold,
                       is_relevant=is_relevant,
                       persona_name=persona.name,
                       note="Query와 조직 페르소나 관련성 — 낮으면 chitchat")
            
            return {
                "is_relevant": is_relevant,
                "similarity": similarity,
                "persona_found": True,
                "chitchat_template": persona.chitchat_response_template,
            }
            
        except Exception as e:
            logger.error("persona_relevance_check_error",
                        owner=owner,
                        query_preview=query[:50],
                        error=str(e))
            # 에러 시 안전하게 question으로 처리 (HITL 경로로 가도록)
            return {
                "is_relevant": True,
                "similarity": 0.0,
                "persona_found": False,
                "chitchat_template": None,
            }
    
    async def list_personas(self) -> List[Dict[str, Any]]:
        """모든 Persona 목록 조회 (관리 UI용)"""
        try:
            if not self._collection:
                await self.initialize()
            
            result = self._collection.get(
                include=["documents", "metadatas"]
            )
            
            personas = []
            for i, doc_id in enumerate(result["ids"]):
                metadata = result["metadatas"][i]
                md = metadata
                personas.append({
                    "owner": md["owner"],
                    "name": md["name"],
                    "description": result["documents"][i],
                    "scope_keywords": md.get("scope_keywords", "").split(",") if md.get("scope_keywords") else [],
                    "enabled": md.get("enabled", True),
                    "escalation_mode": str(md.get("escalation_mode") or "hitl"),
                    "transfer_extension": (str(md.get("transfer_extension") or "").strip() or None),
                    "sip_message_ai_reply_enabled": str(md.get("sip_message_ai_reply_enabled", "")).lower()
                    in ("true", "1", "yes"),
                    "sip_message_ai_reply_prefix": (md.get("sip_message_ai_reply_prefix") or None) or None,
                    "created_at": md.get("created_at"),
                    "updated_at": md.get("updated_at"),
                })
            
            return personas
            
        except Exception as e:
            logger.error("persona_list_error", error=str(e))
            return []


# Singleton 인스턴스 (초기화는 app startup 시)
_persona_service: Optional[PersonaService] = None


def get_persona_service() -> Optional[PersonaService]:
    """PersonaService 싱글톤 인스턴스 반환"""
    return _persona_service


async def ensure_persona_service() -> Optional[PersonaService]:
    """PersonaService가 없으면 KnowledgeService의 vector_db·embedder로 지연 초기화한다.

    API 앱에서 lifespan으로 persona를 올리지 않은 경우에도, 가사 생성 등에서
    `/api/persona`와 동일한 Chroma `persona` 컬렉션을 읽을 수 있게 한다.
    """
    global _persona_service
    if _persona_service is not None:
        return _persona_service
    try:
        from src.services.knowledge_service import get_knowledge_service

        ks = get_knowledge_service()
        if not ks:
            logger.debug("ensure_persona_service_no_knowledge_service")
            return None
        _persona_service = PersonaService(ks.vector_db, ks.embedder)
        await _persona_service.initialize()
        logger.info("persona_service_lazy_initialized")
        return _persona_service
    except Exception as e:
        logger.warning("persona_service_lazy_init_failed", error=str(e))
        return None


async def initialize_persona_service(chroma_client, embedder) -> PersonaService:
    """PersonaService 초기화 (app startup 시 호출)"""
    global _persona_service
    _persona_service = PersonaService(chroma_client, embedder)
    await _persona_service.initialize()
    logger.info("persona_service_initialized")
    return _persona_service
