"""
AI Pipeline Unit Tests - RAG Engine

RAG (Retrieval Augmented Generation) 엔진 테스트
"""

import pytest
from unittest.mock import Mock, AsyncMock, patch
from typing import List

from src.ai_voicebot.ai_pipeline.rag_engine import RAGEngine
from src.ai_voicebot.knowledge.models import Document


class TestRAGEngine:
    """RAGEngine 단위 테스트"""
    
    @pytest.fixture
    def mock_vector_db(self):
        """VectorDB Mock 객체"""
        mock_db = Mock()
        mock_db.search = AsyncMock()
        return mock_db
    
    @pytest.fixture
    def mock_embedder(self):
        """Embedder Mock 객체"""
        mock_emb = Mock()
        mock_emb.embed = AsyncMock(return_value=[0.1] * 768)
        return mock_emb
    
    @pytest.fixture
    def rag_engine(self, mock_vector_db, mock_embedder):
        """RAGEngine 인스턴스"""
        return RAGEngine(
            vector_db=mock_vector_db,
            embedder=mock_embedder,
            top_k=3,
            similarity_threshold=0.7
        )
    
    @pytest.mark.asyncio
    async def test_search_returns_top_k_documents(self, rag_engine, mock_vector_db):
        """
        Given: Vector DB에 지식 5개 저장
        When: search("예약 취소", top_k=3) 호출
        Then: 유사도 높은 순서로 3개 반환
        """
        # Given
        mock_docs = [
            Document(id="doc1", text="예약 취소 방법", score=0.95, metadata={}),
            Document(id="doc2", text="예약 변경 방법", score=0.85, metadata={}),
            Document(id="doc3", text="예약 확인 방법", score=0.75, metadata={}),
        ]
        mock_vector_db.search.return_value = mock_docs
        
        # When
        results = await rag_engine.search("예약 취소", call_id="test-call")
        
        # Then
        assert len(results) == 3
        assert results[0].score >= results[1].score >= results[2].score
        assert results[0].text == "예약 취소 방법"
    
    @pytest.mark.asyncio
    async def test_search_filters_by_similarity_threshold(self, rag_engine, mock_vector_db):
        """
        Given: similarity_threshold=0.7
        When: 검색 결과 중 일부가 0.7 미만
        Then: 임계값 이상만 반환
        """
        # Given
        mock_docs = [
            Document(id="doc1", text="관련 문서 1", score=0.9, metadata={}),
            Document(id="doc2", text="관련 문서 2", score=0.75, metadata={}),
            Document(id="doc3", text="관련 없는 문서", score=0.5, metadata={}),
        ]
        mock_vector_db.search.return_value = mock_docs
        
        # When
        results = await rag_engine.search("테스트 쿼리", call_id="test-call")
        
        # Then
        assert len(results) == 2  # 0.9, 0.75만 통과
        assert all(doc.score >= 0.7 for doc in results)
    
    @pytest.mark.asyncio
    async def test_search_with_owner_filter(self, rag_engine, mock_vector_db):
        """
        Given: owner_filter="user123"
        When: search() 호출
        Then: Vector DB에 owner_filter 전달
        """
        # Given
        owner_filter = "user123"
        mock_vector_db.search.return_value = []
        
        # When
        await rag_engine.search("쿼리", call_id="test-call", owner_filter=owner_filter)
        
        # Then
        mock_vector_db.search.assert_called_once()
        call_kwargs = mock_vector_db.search.call_args.kwargs
        assert call_kwargs.get("owner_filter") == owner_filter
    
    @pytest.mark.asyncio
    async def test_search_no_results(self, rag_engine, mock_vector_db):
        """
        Given: Vector DB에 관련 문서 없음
        When: search() 호출
        Then: 빈 리스트 반환
        """
        # Given
        mock_vector_db.search.return_value = []
        
        # When
        results = await rag_engine.search("존재하지 않는 키워드", call_id="test-call")
        
        # Then
        assert results == []
    
    @pytest.mark.asyncio
    async def test_search_with_reranking(self, rag_engine, mock_vector_db):
        """
        Given: reranking_enabled=True
        When: search() 호출
        Then: 재순위화 후 결과 반환
        """
        # Given
        rag_engine.reranking_enabled = True
        mock_docs = [
            Document(id="doc1", text="문서 1", score=0.85, metadata={}),
            Document(id="doc2", text="문서 2", score=0.80, metadata={}),
        ]
        mock_vector_db.search.return_value = mock_docs
        
        # When
        with patch.object(rag_engine, '_rerank', new=AsyncMock(return_value=mock_docs[::-1])):
            results = await rag_engine.search("쿼리", call_id="test-call")
        
        # Then
        assert len(results) == 2
        # 재순위화 호출 확인
        rag_engine._rerank.assert_called_once()
    
    @pytest.mark.asyncio
    async def test_search_embedder_error(self, rag_engine, mock_embedder):
        """
        Given: Embedder 실패
        When: search() 호출
        Then: RuntimeError 발생
        """
        # Given
        mock_embedder.embed.side_effect = Exception("Embedding failed")
        
        # When/Then
        with pytest.raises(RuntimeError, match="RAG 검색 실패"):
            await rag_engine.search("쿼리", call_id="test-call")
    
    @pytest.mark.asyncio
    async def test_search_logs_to_database(self, rag_engine, mock_vector_db):
        """
        Given: RAG 검색 수행
        When: search() 호출
        Then: 검색 기록이 DB에 로깅됨
        """
        # Given
        mock_docs = [Document(id="doc1", text="문서", score=0.9, metadata={})]
        mock_vector_db.search.return_value = mock_docs
        
        # When
        with patch('src.ai_voicebot.logging.ai_logger.log_rag_search', new=AsyncMock()) as mock_log:
            await rag_engine.search("쿼리", call_id="test-call", owner_filter="user123")
        
        # Then
        mock_log.assert_called_once()
        call_args = mock_log.call_args.kwargs
        assert call_args["call_id"] == "test-call"
        assert call_args["user_question"] == "쿼리"
        assert call_args["top_score"] == 0.9

