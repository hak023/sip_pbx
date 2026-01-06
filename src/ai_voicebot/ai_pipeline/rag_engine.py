"""
RAG (Retrieval-Augmented Generation) Engine

Vector DB 검색 및 컨텍스트 재순위화
"""

from typing import List, Dict, Optional
from dataclasses import dataclass
import asyncio
import structlog

logger = structlog.get_logger(__name__)


@dataclass
class Document:
    """검색된 문서"""
    id: str
    text: str
    score: float
    metadata: Dict


class RAGEngine:
    """
    RAG (Retrieval-Augmented Generation) Engine
    
    Vector DB 검색 및 컨텍스트 재순위화를 제공합니다.
    """
    
    def __init__(
        self, 
        vector_db,  # VectorDB 인스턴스
        embedder,   # TextEmbedder 인스턴스
        top_k: int = 3,
        similarity_threshold: float = 0.7,
        reranking_enabled: bool = False
    ):
        """
        Args:
            vector_db: Vector DB 클라이언트
            embedder: Text Embedder 인스턴스
            top_k: 검색할 문서 수
            similarity_threshold: 유사도 임계값
            reranking_enabled: 재순위화 활성화
        """
        self.vector_db = vector_db
        self.embedder = embedder
        self.top_k = top_k
        self.similarity_threshold = similarity_threshold
        self.reranking_enabled = reranking_enabled
        
        # 통계
        self.total_searches = 0
        self.total_results = 0
        
        logger.info("RAGEngine initialized", 
                   top_k=top_k,
                   threshold=similarity_threshold,
                   reranking=reranking_enabled)
    
    async def search(
        self, 
        query: str, 
        owner_filter: Optional[str] = None
    ) -> List[Document]:
        """
        질문에 대한 관련 문서 검색
        
        Args:
            query: 검색 질문
            owner_filter: 사용자 ID 필터 (착신자 전용 지식)
            
        Returns:
            관련 문서 리스트 (상위 top_k개)
        """
        try:
            # 1. 질문 임베딩
            query_embedding = await self.embedder.embed(query)
            
            # 2. Vector DB 검색
            filter_dict = {"owner": owner_filter} if owner_filter else None
            search_results = await self.vector_db.search(
                vector=query_embedding,
                top_k=self.top_k * 2,  # 재순위화를 위해 더 많이 검색
                filter=filter_dict
            )
            
            # 3. Document 객체 변환
            documents = [
                Document(
                    id=result["id"],
                    text=result["text"],
                    score=result["score"],
                    metadata=result.get("metadata", {})
                )
                for result in search_results
            ]
            
            # 4. 유사도 필터링
            documents = [
                doc for doc in documents
                if doc.score >= self.similarity_threshold
            ]
            
            # 5. 재순위화 (선택)
            if self.reranking_enabled and documents:
                documents = await self._rerank(query, documents)
            
            # 6. Top-K 반환
            documents = documents[:self.top_k]
            
            self.total_searches += 1
            self.total_results += len(documents)
            
            logger.info("RAG search completed",
                       query_length=len(query),
                       results_count=len(documents),
                       owner_filter=owner_filter)
            
            return documents
            
        except Exception as e:
            logger.error("RAG search error", error=str(e), exc_info=True)
            return []
    
    async def _rerank(
        self, 
        query: str, 
        documents: List[Document]
    ) -> List[Document]:
        """
        검색 결과 재순위화
        
        단순 벡터 유사도가 아닌 실제 관련성 기반 재순위화
        (키워드 매칭과 길이 기반)
        
        Args:
            query: 검색 질문
            documents: 검색 결과 문서들
            
        Returns:
            재순위화된 문서 리스트
        """
        try:
            # 질문의 주요 키워드 추출
            query_words = set(query.lower().split())
            
            # 각 문서의 재순위 점수 계산
            for doc in documents:
                doc_words = set(doc.text.lower().split())
                
                # 키워드 매칭 비율
                overlap = len(query_words & doc_words)
                keyword_score = overlap / len(query_words) if query_words else 0
                
                # 문서 길이 패널티 (너무 길면 감점)
                length_score = 1.0 if len(doc.text) < 300 else 0.8
                
                # 최종 점수 (원래 점수 70% + 키워드 20% + 길이 10%)
                doc.score = (
                    doc.score * 0.7 +
                    keyword_score * 0.2 +
                    length_score * 0.1
                )
            
            # 재정렬
            documents.sort(key=lambda d: d.score, reverse=True)
            
            logger.debug("Reranking completed", count=len(documents))
            return documents
            
        except Exception as e:
            logger.error("Reranking error", error=str(e))
            return documents
    
    async def search_with_expansion(
        self, 
        query: str, 
        owner_filter: Optional[str] = None
    ) -> List[Document]:
        """
        쿼리 확장을 사용한 검색 (고급)
        
        원본 쿼리 + 확장된 쿼리로 검색하여 더 많은 결과 확보
        
        Args:
            query: 검색 질문
            owner_filter: 사용자 ID 필터
            
        Returns:
            검색 결과 문서 리스트
        """
        # 원본 검색
        original_results = await self.search(query, owner_filter)
        
        # 쿼리 확장 (동의어, 관련어)
        expanded_query = self._expand_query(query)
        
        if expanded_query != query:
            # 확장된 쿼리로 검색
            expanded_results = await self.search(expanded_query, owner_filter)
            
            # 결과 병합 (중복 제거)
            seen_ids = {doc.id for doc in original_results}
            for doc in expanded_results:
                if doc.id not in seen_ids:
                    original_results.append(doc)
                    seen_ids.add(doc.id)
            
            # 재정렬
            original_results.sort(key=lambda d: d.score, reverse=True)
            original_results = original_results[:self.top_k]
        
        return original_results
    
    def _expand_query(self, query: str) -> str:
        """
        쿼리 확장 (간단한 동의어 치환)
        
        실제로는 LLM을 사용하거나 한국어 동의어 사전 활용 가능
        
        Args:
            query: 원본 질문
            
        Returns:
            확장된 질문
        """
        # 간단한 동의어 매핑
        synonyms = {
            "회의": ["미팅", "회의", "모임"],
            "시간": ["시간", "시각", "타임"],
            "장소": ["장소", "위치", "곳"],
            "언제": ["언제", "몇 시", "시간"],
            "어디": ["어디", "장소", "위치"],
        }
        
        expanded = query
        for word, syns in synonyms.items():
            if word in query:
                # 첫 번째 동의어로 치환
                expanded = query.replace(word, syns[0])
                break
        
        return expanded
    
    def get_stats(self) -> dict:
        """RAG 통계 반환"""
        avg_results = (
            self.total_results / self.total_searches 
            if self.total_searches > 0 else 0
        )
        
        return {
            "total_searches": self.total_searches,
            "total_results": self.total_results,
            "avg_results_per_search": avg_results,
            "top_k": self.top_k,
            "similarity_threshold": self.similarity_threshold,
            "reranking_enabled": self.reranking_enabled,
        }

