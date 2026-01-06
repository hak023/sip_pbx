"""
Vector DB 추상화

Vector Database 인터페이스 정의
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import List, Dict, Optional
import structlog

logger = structlog.get_logger(__name__)


@dataclass
class Document:
    """검색된 문서"""
    id: str
    text: str
    score: float
    metadata: Dict


class VectorDB(ABC):
    """
    Vector Database 추상 인터페이스
    
    다양한 Vector DB 구현체를 위한 공통 인터페이스
    """
    
    @abstractmethod
    async def initialize(self) -> None:
        """DB 초기화"""
        pass
    
    @abstractmethod
    async def upsert(
        self,
        doc_id: str,
        embedding: List[float],
        text: str,
        metadata: Dict
    ) -> None:
        """
        문서 저장 또는 업데이트
        
        Args:
            doc_id: 문서 ID
            embedding: 임베딩 벡터
            text: 원본 텍스트
            metadata: 메타데이터
        """
        pass
    
    @abstractmethod
    async def search(
        self,
        vector: List[float],
        top_k: int = 5,
        filter: Optional[Dict] = None
    ) -> List[Dict]:
        """
        유사도 검색
        
        Args:
            vector: 쿼리 벡터
            top_k: 반환할 문서 수
            filter: 메타데이터 필터
            
        Returns:
            검색 결과 리스트
        """
        pass
    
    @abstractmethod
    async def delete(self, doc_id: str) -> None:
        """
        문서 삭제
        
        Args:
            doc_id: 문서 ID
        """
        pass
    
    @abstractmethod
    async def delete_by_filter(self, filter: Dict) -> int:
        """
        필터 조건으로 문서 삭제
        
        Args:
            filter: 메타데이터 필터
            
        Returns:
            삭제된 문서 수
        """
        pass
    
    @abstractmethod
    async def count(self, filter: Optional[Dict] = None) -> int:
        """
        문서 수 조회
        
        Args:
            filter: 메타데이터 필터
            
        Returns:
            문서 수
        """
        pass
    
    @abstractmethod
    def get_stats(self) -> Dict:
        """통계 반환"""
        pass

