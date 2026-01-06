"""
ChromaDB Client

ChromaDB를 사용한 Vector DB 구현
"""

import chromadb
from chromadb.config import Settings
from typing import List, Dict, Optional
import asyncio
import structlog

from .vector_db import VectorDB

logger = structlog.get_logger(__name__)


class ChromaDBClient(VectorDB):
    """
    ChromaDB Vector Database 클라이언트
    
    로컬 또는 클라이언트/서버 모드로 ChromaDB를 사용합니다.
    """
    
    def __init__(
        self,
        collection_name: str = "knowledge_base",
        persist_directory: str = "./data/chromadb",
        client_mode: str = "local"  # "local" or "http"
    ):
        """
        Args:
            collection_name: 컬렉션 이름
            persist_directory: 로컬 저장 디렉토리
            client_mode: 클라이언트 모드
        """
        self.collection_name = collection_name
        self.persist_directory = persist_directory
        self.client_mode = client_mode
        
        self.client = None
        self.collection = None
        
        # 통계
        self.total_upserts = 0
        self.total_searches = 0
        self.total_deletes = 0
        
        logger.info("ChromaDBClient created", 
                   collection=collection_name,
                   mode=client_mode)
    
    async def initialize(self) -> None:
        """DB 초기화"""
        try:
            if self.client_mode == "local":
                # 로컬 영구 저장 모드
                self.client = chromadb.Client(Settings(
                    chroma_db_impl="duckdb+parquet",
                    persist_directory=self.persist_directory
                ))
            else:
                # HTTP 클라이언트 모드
                self.client = chromadb.HttpClient()
            
            # 컬렉션 생성 또는 가져오기
            self.collection = self.client.get_or_create_collection(
                name=self.collection_name,
                metadata={"hnsw:space": "cosine"}  # 코사인 유사도
            )
            
            logger.info("ChromaDB initialized", 
                       collection=self.collection_name,
                       count=self.collection.count())
            
        except Exception as e:
            logger.error("ChromaDB initialization failed", error=str(e), exc_info=True)
            raise
    
    async def upsert(
        self,
        doc_id: str,
        embedding: List[float],
        text: str,
        metadata: Dict
    ) -> None:
        """문서 저장 또는 업데이트"""
        try:
            # ChromaDB는 동기 API이므로 executor에서 실행
            loop = asyncio.get_event_loop()
            await loop.run_in_executor(
                None,
                lambda: self.collection.upsert(
                    ids=[doc_id],
                    embeddings=[embedding],
                    documents=[text],
                    metadatas=[metadata]
                )
            )
            
            self.total_upserts += 1
            logger.debug("Document upserted", doc_id=doc_id)
            
        except Exception as e:
            logger.error("Upsert failed", doc_id=doc_id, error=str(e))
            raise
    
    async def search(
        self,
        vector: List[float],
        top_k: int = 5,
        filter: Optional[Dict] = None
    ) -> List[Dict]:
        """유사도 검색"""
        try:
            # ChromaDB 쿼리
            loop = asyncio.get_event_loop()
            results = await loop.run_in_executor(
                None,
                lambda: self.collection.query(
                    query_embeddings=[vector],
                    n_results=top_k,
                    where=filter,
                    include=["documents", "metadatas", "distances"]
                )
            )
            
            self.total_searches += 1
            
            # 결과 변환
            documents = []
            if results['ids'] and results['ids'][0]:
                for i, doc_id in enumerate(results['ids'][0]):
                    # ChromaDB는 거리를 반환하므로 유사도로 변환
                    distance = results['distances'][0][i]
                    score = 1.0 / (1.0 + distance)  # 거리 → 유사도
                    
                    documents.append({
                        "id": doc_id,
                        "text": results['documents'][0][i],
                        "score": score,
                        "metadata": results['metadatas'][0][i] if results['metadatas'] else {}
                    })
            
            logger.debug("Search completed", 
                        top_k=top_k,
                        results_count=len(documents))
            
            return documents
            
        except Exception as e:
            logger.error("Search failed", error=str(e))
            return []
    
    async def delete(self, doc_id: str) -> None:
        """문서 삭제"""
        try:
            loop = asyncio.get_event_loop()
            await loop.run_in_executor(
                None,
                lambda: self.collection.delete(ids=[doc_id])
            )
            
            self.total_deletes += 1
            logger.debug("Document deleted", doc_id=doc_id)
            
        except Exception as e:
            logger.error("Delete failed", doc_id=doc_id, error=str(e))
    
    async def delete_by_filter(self, filter: Dict) -> int:
        """필터 조건으로 문서 삭제"""
        try:
            # ChromaDB에서 필터로 삭제
            loop = asyncio.get_event_loop()
            
            # 먼저 해당 문서들을 찾기
            results = await loop.run_in_executor(
                None,
                lambda: self.collection.get(where=filter)
            )
            
            if results['ids']:
                # 찾은 문서들 삭제
                await loop.run_in_executor(
                    None,
                    lambda: self.collection.delete(ids=results['ids'])
                )
                
                deleted_count = len(results['ids'])
                self.total_deletes += deleted_count
                
                logger.info("Documents deleted by filter", 
                          count=deleted_count,
                          filter=filter)
                
                return deleted_count
            
            return 0
            
        except Exception as e:
            logger.error("Delete by filter failed", filter=filter, error=str(e))
            return 0
    
    async def count(self, filter: Optional[Dict] = None) -> int:
        """문서 수 조회"""
        try:
            loop = asyncio.get_event_loop()
            
            if filter:
                # 필터가 있으면 get으로 조회
                results = await loop.run_in_executor(
                    None,
                    lambda: self.collection.get(where=filter)
                )
                return len(results['ids']) if results['ids'] else 0
            else:
                # 전체 수
                count = await loop.run_in_executor(
                    None,
                    lambda: self.collection.count()
                )
                return count
                
        except Exception as e:
            logger.error("Count failed", error=str(e))
            return 0
    
    def get_stats(self) -> Dict:
        """통계 반환"""
        return {
            "type": "chromadb",
            "collection_name": self.collection_name,
            "total_documents": self.collection.count() if self.collection else 0,
            "total_upserts": self.total_upserts,
            "total_searches": self.total_searches,
            "total_deletes": self.total_deletes,
        }

