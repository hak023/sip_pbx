"""
연락처 지식 검색 모듈

지식베이스(ChromaDB)에서 category="contact"인 항목을 검색하여
호 전환에 필요한 전화번호 반환
"""

from typing import Optional, Dict, List, Any
import structlog

logger = structlog.get_logger(__name__)


class ContactKnowledgeExtractor:
    """
    연락처 지식 추출기
    
    지식베이스에서 category="contact"인 연락처를 검색하여
    호 전환에 필요한 전화번호 정보 반환
    """
    
    def __init__(self, vector_db: Any = None, embedder: Any = None):
        """
        Args:
            vector_db: ChromaDB vector database 인스턴스
            embedder: Text embedder (임베딩 생성용)
        """
        self.vector_db = vector_db
        self.embedder = embedder
        
        if not vector_db:
            logger.warning("contact_extractor_no_vector_db",
                          note="vector_db가 없으면 검색 불가")
        if not embedder:
            logger.warning("contact_extractor_no_embedder",
                          note="embedder가 없으면 검색 불가")
    
    def _get_embedding(self, text: str) -> Optional[List[float]]:
        """텍스트 임베딩 생성"""
        if not self.embedder:
            return None
        
        try:
            if hasattr(self.embedder, "embed_text"):
                return self.embedder.embed_text(text)
            elif hasattr(self.embedder, "embed"):
                result = self.embedder.embed(text)
                return result if isinstance(result, list) else None
            else:
                logger.warning("embedder_no_method",
                              methods=dir(self.embedder))
                return None
        except Exception as e:
            logger.error("embedding_generation_error", error=str(e))
            return None
    
    async def search_contact(
        self, 
        query: str, 
        tenant_id: str
    ) -> Optional[Dict[str, str]]:
        """
        연락처 검색
        
        Args:
            query: 사용자 질문 (예: "영업팀 연결해줘", "김철수 담당자")
            tenant_id: 테넌트 ID (owner)
        
        Returns:
            {
                "department": "영업팀",
                "phone_number": "010-1234-5678",
                "name": "김철수"
            }
            또는 None (찾지 못한 경우)
        """
        if not self.vector_db:
            logger.warning("contact_search_skip_no_vector_db")
            return None
        
        if not self.embedder:
            logger.warning("contact_search_skip_no_embedder")
            return None
        
        try:
            # 1. 쿼리 임베딩
            query_embedding = self._get_embedding(query)
            if not query_embedding:
                logger.warning("contact_search_embedding_failed",
                              query=query)
                return None
            
            # 2. ChromaDB 검색
            logger.info("contact_search_query",
                       query=query,
                       tenant_id=tenant_id)
            
            results = self.vector_db.collection.query(
                query_embeddings=[query_embedding],
                n_results=3,  # 상위 3개 검색 (확률 높임)
                where={
                    "$and": [
                        {"owner": tenant_id},
                        {"category": "contact"}
                    ]
                },
                include=["documents", "metadatas", "distances"]
            )
            
            # 3. 결과 확인
            if not results or not results.get('ids') or len(results['ids'][0]) == 0:
                logger.info("contact_search_no_results",
                           query=query,
                           tenant_id=tenant_id,
                           note="category='contact'인 지식 없음")
                return None
            
            # 4. 첫 번째 결과(가장 유사도 높음) 사용
            metadata = results['metadatas'][0][0]
            distance = results['distances'][0][0] if results.get('distances') else None
            
            # 5. 메타데이터에서 연락처 정보 추출
            contact = {
                "department": metadata.get("department", ""),
                "phone_number": metadata.get("phone_number", ""),
                "name": metadata.get("name", ""),
                "transfer_label": (metadata.get("transfer_label") or "").strip(),
            }
            
            # 6. 필수 필드(phone_number) 검증
            if not contact["phone_number"]:
                logger.warning("contact_search_no_phone_number",
                              department=contact["department"],
                              name=contact["name"],
                              note="phone_number 필드가 비어있음")
                return None
            
            # 7. 로그 (내선·fwd 참조는 짧게만 표시)
            pn = contact["phone_number"]
            if (pn or "").lower().startswith("fwd:"):
                masked_phone = "fwd:***"
            else:
                masked_phone = pn[:8] + "***" if len(pn) > 8 else "***"
            logger.info("contact_search_found",
                       query=query,
                       department=contact["department"],
                       name=contact["name"],
                       phone_masked=masked_phone,
                       distance=f"{distance:.4f}" if distance is not None else "N/A",
                       note="연락처 검색 성공")
            
            return contact
            
        except Exception as e:
            logger.error("contact_search_error",
                        query=query,
                        tenant_id=tenant_id,
                        error=str(e),
                        exc_info=True)
            return None
    
    def set_dependencies(self, vector_db: Any = None, embedder: Any = None) -> None:
        """
        의존성 설정 (나중에 주입 가능)
        
        Args:
            vector_db: ChromaDB vector database
            embedder: Text embedder
        """
        if vector_db:
            self.vector_db = vector_db
            logger.info("contact_extractor_vector_db_set")
        
        if embedder:
            self.embedder = embedder
            logger.info("contact_extractor_embedder_set")
