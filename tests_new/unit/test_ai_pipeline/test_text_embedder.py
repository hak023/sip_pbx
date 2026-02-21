"""
AI Pipeline Unit Tests - Text Embedder

텍스트를 벡터로 변환하는 Embedder 테스트
실제 구현에 맞춰 작성됨
"""

import pytest
import numpy as np
from unittest.mock import Mock, patch, AsyncMock

from src.ai_voicebot.knowledge.embedder import TextEmbedder, SimpleEmbedder


class TestTextEmbedder:
    """TextEmbedder 단위 테스트"""
    
    @pytest.fixture
    def mock_model(self):
        """SentenceTransformer Mock"""
        mock = Mock()
        # 768차원 벡터 반환하도록 설정
        mock.encode.return_value = np.array([0.1] * 768)
        return mock
    
    @pytest.fixture
    def embedder(self, mock_model):
        """TextEmbedder 인스턴스 (모델 모킹)"""
        with patch('src.ai_voicebot.knowledge.embedder.SentenceTransformer', return_value=mock_model):
            return TextEmbedder(
                model_name="test-model",
                dimension=768
            )
    
    @pytest.mark.asyncio
    async def test_embed_single_text_returns_vector(self, embedder):
        """
        Given: 단일 텍스트 "안녕하세요"
        When: embed() 호출
        Then: 768차원 벡터 반환
        """
        # Given
        text = "안녕하세요"
        
        # When
        embedding = await embedder.embed(text)
        
        # Then
        assert isinstance(embedding, list)
        assert len(embedding) == 768
        assert all(isinstance(x, float) for x in embedding)
    
    @pytest.mark.asyncio
    async def test_embed_batch_texts(self, embedder, mock_model):
        """
        Given: 여러 텍스트 리스트
        When: embed_batch() 호출
        Then: 각 텍스트에 대한 벡터 리스트 반환
        """
        # Given
        texts = ["안녕하세요", "예약 확인", "취소"]
        mock_model.encode.return_value = np.array([[0.1] * 768] * 3)
        
        # When
        embeddings = await embedder.embed_batch(texts)
        
        # Then
        assert len(embeddings) == 3
        assert all(len(emb) == 768 for emb in embeddings)
        mock_model.encode.assert_called_once()
    
    @pytest.mark.asyncio
    async def test_embed_error_returns_zero_vector(self, embedder, mock_model):
        """
        Given: 모델에서 에러 발생
        When: embed() 호출
        Then: 제로 벡터 반환
        """
        # Given
        mock_model.encode.side_effect = Exception("Model error")
        text = "테스트"
        
        # When
        embedding = await embedder.embed(text)
        
        # Then
        assert embedding == [0.0] * 768
    
    def test_embed_sync_returns_vector(self, embedder):
        """
        Given: 동기 임베딩 요청
        When: embed_sync() 호출
        Then: 벡터 반환
        """
        # Given
        text = "동기 테스트"
        
        # When
        embedding = embedder.embed_sync(text)
        
        # Then
        assert isinstance(embedding, list)
        assert len(embedding) == 768
    
    def test_get_stats_returns_statistics(self, embedder):
        """
        Given: 임베딩 몇 번 수행 후
        When: get_stats() 호출
        Then: 통계 정보 반환
        """
        # Given
        embedder.total_embeddings = 10
        embedder.total_texts = 100
        
        # When
        stats = embedder.get_stats()
        
        # Then
        assert stats["total_embeddings"] == 10
        assert stats["total_texts"] == 100
        assert stats["model_name"] == "test-model"
        assert stats["dimension"] == 768
        assert stats["avg_text_length"] == 10.0


class TestSimpleEmbedder:
    """SimpleEmbedder 단위 테스트 (테스트용 임베더)"""
    
    @pytest.fixture
    def simple_embedder(self):
        """SimpleEmbedder 인스턴스"""
        return SimpleEmbedder(dimension=768)
    
    @pytest.mark.asyncio
    async def test_simple_embed_returns_deterministic_vector(self, simple_embedder):
        """
        Given: 동일한 텍스트
        When: 두 번 embed() 호출
        Then: 동일한 벡터 반환 (결정적)
        """
        # Given
        text = "테스트 텍스트"
        
        # When
        embedding1 = await simple_embedder.embed(text)
        embedding2 = await simple_embedder.embed(text)
        
        # Then
        assert embedding1 == embedding2
        assert len(embedding1) == 768
    
    @pytest.mark.asyncio
    async def test_simple_embed_different_texts_different_vectors(self, simple_embedder):
        """
        Given: 다른 텍스트 두 개
        When: embed() 호출
        Then: 다른 벡터 반환
        """
        # Given
        text1 = "텍스트 A"
        text2 = "텍스트 B"
        
        # When
        embedding1 = await simple_embedder.embed(text1)
        embedding2 = await simple_embedder.embed(text2)
        
        # Then
        assert embedding1 != embedding2
    
    @pytest.mark.asyncio
    async def test_simple_embed_batch(self, simple_embedder):
        """
        Given: 텍스트 배열
        When: embed_batch() 호출
        Then: 각 텍스트에 대한 벡터 반환
        """
        # Given
        texts = ["A", "B", "C"]
        
        # When
        embeddings = await simple_embedder.embed_batch(texts)
        
        # Then
        assert len(embeddings) == 3
        assert all(len(emb) == 768 for emb in embeddings)
        # 각 벡터는 달라야 함
        assert embeddings[0] != embeddings[1]
        assert embeddings[1] != embeddings[2]
