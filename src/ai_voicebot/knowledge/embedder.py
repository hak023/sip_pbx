"""
Text Embedder

텍스트를 벡터 임베딩으로 변환
"""

from sentence_transformers import SentenceTransformer
import asyncio
from typing import List, Union
import structlog

logger = structlog.get_logger(__name__)


class TextEmbedder:
    """
    텍스트 임베딩 생성기
    
    Sentence Transformers를 사용하여 텍스트를 벡터로 변환합니다.
    """
    
    def __init__(
        self,
        model_name: str = "paraphrase-multilingual-mpnet-base-v2",
        dimension: int = 768,
        batch_size: int = 32
    ):
        """
        Args:
            model_name: Sentence Transformers 모델 이름
            dimension: 임베딩 차원
            batch_size: 배치 크기
        """
        self.model_name = model_name
        self.dimension = dimension
        self.batch_size = batch_size
        
        # 모델 로드
        logger.info("Loading embedding model", model=model_name)
        self.model = SentenceTransformer(model_name)
        
        # 통계
        self.total_embeddings = 0
        self.total_texts = 0
        
        logger.info("TextEmbedder initialized", 
                   model=model_name,
                   dimension=dimension)
    
    async def embed(self, text: str) -> List[float]:
        """
        단일 텍스트 임베딩
        
        Args:
            text: 임베딩할 텍스트
            
        Returns:
            임베딩 벡터
        """
        try:
            # CPU 바운드 작업이므로 executor에서 실행
            loop = asyncio.get_event_loop()
            embedding = await loop.run_in_executor(
                None,
                lambda: self.model.encode(text, convert_to_numpy=True)
            )
            
            self.total_embeddings += 1
            self.total_texts += len(text)
            
            return embedding.tolist()
            
        except Exception as e:
            logger.error("Embedding failed", text_length=len(text), error=str(e))
            # 오류 시 제로 벡터 반환
            return [0.0] * self.dimension
    
    async def embed_batch(self, texts: List[str]) -> List[List[float]]:
        """
        배치 텍스트 임베딩
        
        Args:
            texts: 임베딩할 텍스트 리스트
            
        Returns:
            임베딩 벡터 리스트
        """
        try:
            # 배치 처리
            loop = asyncio.get_event_loop()
            embeddings = await loop.run_in_executor(
                None,
                lambda: self.model.encode(
                    texts, 
                    batch_size=self.batch_size,
                    convert_to_numpy=True
                )
            )
            
            self.total_embeddings += len(texts)
            self.total_texts += sum(len(t) for t in texts)
            
            return [emb.tolist() for emb in embeddings]
            
        except Exception as e:
            logger.error("Batch embedding failed", 
                        batch_size=len(texts), 
                        error=str(e))
            # 오류 시 제로 벡터 리스트 반환
            return [[0.0] * self.dimension for _ in texts]
    
    def embed_sync(self, text: str) -> List[float]:
        """
        동기 임베딩 (필요한 경우)
        
        Args:
            text: 임베딩할 텍스트
            
        Returns:
            임베딩 벡터
        """
        try:
            embedding = self.model.encode(text, convert_to_numpy=True)
            self.total_embeddings += 1
            self.total_texts += len(text)
            return embedding.tolist()
        except Exception as e:
            logger.error("Sync embedding failed", error=str(e))
            return [0.0] * self.dimension
    
    def get_stats(self) -> dict:
        """임베딩 통계 반환"""
        return {
            "total_embeddings": self.total_embeddings,
            "total_texts": self.total_texts,
            "model_name": self.model_name,
            "dimension": self.dimension,
            "avg_text_length": (
                self.total_texts / self.total_embeddings 
                if self.total_embeddings > 0 else 0
            ),
        }


class SimpleEmbedder:
    """
    간단한 임베더 (테스트용)
    
    실제 모델 없이 해시 기반 임베딩을 생성합니다.
    """
    
    def __init__(self, dimension: int = 768):
        """
        Args:
            dimension: 임베딩 차원
        """
        self.dimension = dimension
        logger.info("SimpleEmbedder initialized", dimension=dimension)
    
    async def embed(self, text: str) -> List[float]:
        """
        해시 기반 임베딩
        
        Args:
            text: 임베딩할 텍스트
            
        Returns:
            임베딩 벡터
        """
        import hashlib
        
        # 텍스트 해시
        hash_obj = hashlib.sha256(text.encode())
        hash_bytes = hash_obj.digest()
        
        # 해시를 벡터로 변환
        embedding = []
        for i in range(0, min(len(hash_bytes), self.dimension), 2):
            if i + 1 < len(hash_bytes):
                value = (hash_bytes[i] * 256 + hash_bytes[i + 1]) / 65535.0
            else:
                value = hash_bytes[i] / 255.0
            embedding.append(value)
        
        # 차원 맞추기
        while len(embedding) < self.dimension:
            embedding.append(0.0)
        
        return embedding[:self.dimension]
    
    async def embed_batch(self, texts: List[str]) -> List[List[float]]:
        """배치 임베딩"""
        return [await self.embed(t) for t in texts]
    
    def get_stats(self) -> dict:
        """통계 반환"""
        return {
            "embedder_type": "simple",
            "dimension": self.dimension,
        }

