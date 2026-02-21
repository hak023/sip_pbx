"""
End-to-End Tests - VectorDB Knowledge Extraction

통화 내용에서 지식 추출하여 VectorDB 저장 및 조회 E2E 테스트
"""

import pytest
import asyncio
import tempfile
from pathlib import Path
from typing import Dict, Any
import sys

# 프로젝트 루트를 Python 경로에 추가
project_root = Path(__file__).parent.parent.parent
if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))


class MockLLMClient:
    """테스트용 Mock LLM 클라이언트"""
    
    def __init__(self, usefulness_result: Dict[str, Any] = None):
        self.usefulness_result = usefulness_result or {
            "is_useful": True,
            "confidence": 0.9,
            "reason": "테스트 유용성 판단",
            "extracted_info": [
                {
                    "text": "다음 주 월요일 오후 2시에 본사 회의실에서 팀 미팅이 있습니다.",
                    "category": "일정",
                    "keywords": ["월요일", "오후 2시", "팀 미팅"]
                }
            ]
        }
    
    async def judge_usefulness(self, transcript: str, speaker: str) -> Dict[str, Any]:
        """유용성 판단 Mock"""
        return self.usefulness_result


class MockVectorDB:
    """테스트용 Mock VectorDB"""
    
    def __init__(self):
        self.storage = []  # {doc_id, embedding, text, metadata}
    
    async def upsert(self, doc_id: str, embedding, text: str, metadata: Dict):
        """문서 삽입"""
        self.storage.append({
            "id": doc_id,
            "embedding": embedding,
            "text": text,
            "metadata": metadata
        })
    
    async def search(self, vector, top_k: int = 3, filter: Dict = None):
        """벡터 검색"""
        results = []
        for doc in self.storage:
            # 필터 적용
            if filter:
                match = all(
                    doc["metadata"].get(k) == v 
                    for k, v in filter.items()
                )
                if not match:
                    continue
            
            # 간단한 유사도 계산 (코사인 유사도 근사)
            # 실제로는 벡터 간 유사도를 계산하지만, Mock에서는 랜덤 점수
            import random
            score = random.uniform(0.7, 0.95)
            
            results.append({
                "id": doc["id"],
                "text": doc["text"],
                "score": score,
                "metadata": doc["metadata"]
            })
        
        # 점수 기준 정렬 후 top_k 반환
        results.sort(key=lambda x: x["score"], reverse=True)
        return results[:top_k]
    
    def get_all_documents(self):
        """모든 문서 반환 (테스트용)"""
        return self.storage


class MockTextEmbedder:
    """테스트용 Mock TextEmbedder"""
    
    async def embed(self, text: str):
        """텍스트 임베딩 (Mock - 단순 배열 반환)"""
        # 실제로는 768차원 벡터이지만, Mock에서는 간단히 표현
        return [0.1] * 768


class TestE2EVectorDBKnowledge:
    """VectorDB 지식 추출 및 조회 E2E 테스트"""
    
    @pytest.fixture
    def mock_components(self):
        """Mock 컴포넌트 생성"""
        llm_client = MockLLMClient()
        embedder = MockTextEmbedder()
        vector_db = MockVectorDB()
        
        return {
            "llm": llm_client,
            "embedder": embedder,
            "vector_db": vector_db
        }
    
    @pytest.fixture
    def sample_transcript_file(self):
        """샘플 transcript 파일 생성"""
        with tempfile.NamedTemporaryFile(
            mode='w', 
            encoding='utf-8', 
            suffix='.txt', 
            delete=False
        ) as f:
            transcript_content = """발신자: 안녕하세요, 다음 주 미팅 일정 확인하고 싶어서 전화 드렸습니다.
착신자: 네, 안녕하세요. 다음 주 월요일 오후 2시에 본사 회의실에서 팀 미팅이 있습니다.
발신자: 아, 그렇군요. 몇 층 회의실인가요?
착신자: 3층 대회의실입니다. 참석 인원은 약 10명 정도 예상됩니다.
발신자: 알겠습니다. 미팅 자료는 언제까지 준비하면 될까요?
착신자: 금요일까지 공유 드라이브에 업로드해 주시면 됩니다. 폴더는 '2026년 1월 미팅' 입니다.
발신자: 네, 감사합니다!
착신자: 감사합니다. 좋은 하루 되세요."""
            f.write(transcript_content)
            temp_path = f.name
        
        yield temp_path
        
        # Cleanup
        Path(temp_path).unlink(missing_ok=True)
    
    @pytest.mark.e2e
    @pytest.mark.asyncio
    async def test_knowledge_extraction_to_vectordb(
        self, 
        mock_components, 
        sample_transcript_file
    ):
        """
        TC-KB-001: 통화 내용에서 지식 추출 → VectorDB 저장
        
        Given: 통화 transcript 파일 (STT 완료)
        When: KnowledgeExtractor.extract_from_call() 호출
        Then: 
          - LLM이 유용성 판단
          - 텍스트 청킹
          - 임베딩 생성
          - VectorDB에 저장
          - 저장된 문서 수 > 0
        """
        # Given
        from src.ai_voicebot.knowledge.knowledge_extractor import KnowledgeExtractor
        
        llm = mock_components["llm"]
        embedder = mock_components["embedder"]
        vector_db = mock_components["vector_db"]
        
        extractor = KnowledgeExtractor(
            llm_client=llm,
            embedder=embedder,
            vector_db=vector_db,
            min_confidence=0.7,
            chunk_size=200,
            chunk_overlap=50
        )
        
        # When - 지식 추출
        result = await extractor.extract_from_call(
            call_id="test_call_001",
            transcript_path=sample_transcript_file,
            owner_id="1004",  # 착신자 ID
            speaker="callee"  # 착신자 발화만 추출
        )
        
        # Then - 추출 성공
        assert result["success"] is True, "Knowledge extraction failed"
        assert result["extracted_count"] > 0, "No knowledge chunks stored"
        assert result["confidence"] >= 0.7, "Confidence too low"
        
        # Then - VectorDB에 저장 확인
        all_docs = vector_db.get_all_documents()
        assert len(all_docs) > 0, "No documents in VectorDB"
        
        # Then - 문서 메타데이터 검증
        first_doc = all_docs[0]
        assert first_doc["metadata"]["call_id"] == "test_call_001"
        assert first_doc["metadata"]["owner"] == "1004"
        assert first_doc["metadata"]["speaker"] == "callee"
        assert first_doc["metadata"]["confidence"] >= 0.7
        
        # Then - 문서 내용 검증 (착신자 발화만)
        stored_text = " ".join([doc["text"] for doc in all_docs])
        assert "월요일 오후 2시" in stored_text or "팀 미팅" in stored_text
        assert "안녕하세요, 다음 주 미팅" not in stored_text  # 발신자 발화는 제외
        
        print(f"[OK] Knowledge extraction successful: {result['extracted_count']} chunks stored")
    
    @pytest.mark.e2e
    @pytest.mark.asyncio
    async def test_knowledge_retrieval_from_vectordb(
        self, 
        mock_components, 
        sample_transcript_file
    ):
        """
        TC-KB-002: VectorDB에서 지식 조회 (RAG 검색)
        
        Given: VectorDB에 통화 지식 저장됨
        When: RAGEngine.search() 호출
        Then: 
          - 관련 문서 반환
          - 유사도 점수 > threshold
          - 메타데이터 포함
        """
        # Given - 먼저 지식 추출하여 VectorDB에 저장
        from src.ai_voicebot.knowledge.knowledge_extractor import KnowledgeExtractor
        from src.ai_voicebot.ai_pipeline.rag_engine import RAGEngine
        
        llm = mock_components["llm"]
        embedder = mock_components["embedder"]
        vector_db = mock_components["vector_db"]
        
        extractor = KnowledgeExtractor(
            llm_client=llm,
            embedder=embedder,
            vector_db=vector_db
        )
        
        # 지식 추출 및 저장
        extraction_result = await extractor.extract_from_call(
            call_id="test_call_002",
            transcript_path=sample_transcript_file,
            owner_id="1004",
            speaker="callee"
        )
        
        assert extraction_result["success"] is True
        
        # When - RAG 검색
        rag_engine = RAGEngine(
            vector_db=vector_db,
            embedder=embedder,
            top_k=3,
            similarity_threshold=0.7
        )
        
        query = "다음 주 미팅이 언제인가요?"
        search_results = await rag_engine.search(
            query=query,
            owner_filter="1004"  # 특정 착신자의 지식만 검색
        )
        
        # Then - 검색 결과 확인
        assert len(search_results) > 0, "No search results returned"
        
        # Then - 유사도 점수 검증
        for doc in search_results:
            assert doc.score >= 0.7, f"Document score {doc.score} below threshold"
        
        # Then - 메타데이터 검증
        first_result = search_results[0]
        assert first_result.metadata["call_id"] == "test_call_002"
        assert first_result.metadata["owner"] == "1004"
        assert first_result.metadata["speaker"] == "callee"
        
        # Then - 문서 내용 검증
        # Mock VectorDB는 간단한 검색이므로 저장된 문서를 반환
        assert len(first_result.text) > 0
        
        print(f"[OK] Knowledge retrieval successful: {len(search_results)} documents found")
        print(f"   Top result: score={first_result.score:.2f}, text={first_result.text[:50]}...")
    
    @pytest.mark.e2e
    @pytest.mark.asyncio
    async def test_knowledge_owner_filter(
        self, 
        mock_components, 
        sample_transcript_file
    ):
        """
        TC-KB-003: 소유자 필터링 테스트
        
        Given: 서로 다른 소유자의 지식이 VectorDB에 저장됨
        When: 특정 소유자로 필터링하여 검색
        Then: 해당 소유자의 지식만 반환
        """
        # Given
        from src.ai_voicebot.knowledge.knowledge_extractor import KnowledgeExtractor
        from src.ai_voicebot.ai_pipeline.rag_engine import RAGEngine
        
        llm = mock_components["llm"]
        embedder = mock_components["embedder"]
        vector_db = mock_components["vector_db"]
        
        extractor = KnowledgeExtractor(
            llm_client=llm,
            embedder=embedder,
            vector_db=vector_db
        )
        
        # 소유자 1004의 지식 저장
        await extractor.extract_from_call(
            call_id="call_owner_1004",
            transcript_path=sample_transcript_file,
            owner_id="1004",
            speaker="callee"
        )
        
        # 소유자 1005의 지식 저장 (다른 transcript로 가정)
        await extractor.extract_from_call(
            call_id="call_owner_1005",
            transcript_path=sample_transcript_file,
            owner_id="1005",
            speaker="callee"
        )
        
        # When - 1004로 필터링 검색
        rag_engine = RAGEngine(
            vector_db=vector_db,
            embedder=embedder,
            top_k=10,  # 충분히 많이 검색
            similarity_threshold=0.5  # 낮은 threshold
        )
        
        results_1004 = await rag_engine.search(
            query="미팅 일정",
            owner_filter="1004"
        )
        
        # Then - 1004의 문서만 반환
        for doc in results_1004:
            assert doc.metadata["owner"] == "1004", \
                f"Expected owner 1004, got {doc.metadata['owner']}"
        
        print(f"[OK] Owner filter test passed: {len(results_1004)} docs from owner 1004")
    
    @pytest.mark.e2e
    @pytest.mark.asyncio
    async def test_knowledge_not_useful_content(self, mock_components):
        """
        TC-KB-004: 유용하지 않은 내용은 저장하지 않음
        
        Given: LLM이 "유용하지 않음" 판단
        When: KnowledgeExtractor.extract_from_call() 호출
        Then: VectorDB에 저장되지 않음
        """
        # Given - 유용하지 않다고 판단하는 Mock LLM
        not_useful_llm = MockLLMClient(usefulness_result={
            "is_useful": False,
            "confidence": 0.2,
            "reason": "단순 인사말만 포함",
            "extracted_info": []
        })
        
        from src.ai_voicebot.knowledge.knowledge_extractor import KnowledgeExtractor
        
        embedder = mock_components["embedder"]
        vector_db = mock_components["vector_db"]
        
        extractor = KnowledgeExtractor(
            llm_client=not_useful_llm,
            embedder=embedder,
            vector_db=vector_db,
            min_text_length=30  # min_text_length를 낮춰서 LLM 판단까지 도달하도록 함
        )
        
        # 임시 transcript 파일 생성 (min_text_length=50 이상으로 만들기)
        with tempfile.NamedTemporaryFile(
            mode='w', 
            encoding='utf-8', 
            suffix='.txt', 
            delete=False
        ) as f:
            # 50자 이상의 텍스트로 LLM 판단이 실행되도록 함
            f.write("발신자: 안녕하세요.\n착신자: 안녕하세요. 네. 오늘 날씨가 정말 좋네요. 점심 뭐 드실 건가요?\n발신자: 감사합니다.")
            temp_path = f.name
        
        try:
            # When - 지식 추출 시도
            result = await extractor.extract_from_call(
                call_id="not_useful_call",
                transcript_path=temp_path,
                owner_id="1004",
                speaker="callee"
            )
            
            # Then - 추출은 성공하지만 저장은 0건 (LLM이 유용하지 않다고 판단)
            assert result["success"] is True
            assert result["extracted_count"] == 0, "Should not store useless content"
            assert result["confidence"] < 0.7
            
            # Then - VectorDB 확인
            all_docs = vector_db.get_all_documents()
            not_useful_docs = [
                doc for doc in all_docs 
                if doc["metadata"]["call_id"] == "not_useful_call"
            ]
            assert len(not_useful_docs) == 0, "Useless content was stored"
            
            print("[OK] Not useful content correctly filtered out")
        
        finally:
            Path(temp_path).unlink(missing_ok=True)
    
    @pytest.mark.e2e
    @pytest.mark.asyncio
    async def test_knowledge_extraction_statistics(
        self, 
        mock_components, 
        sample_transcript_file
    ):
        """
        TC-KB-005: 지식 추출 통계
        
        Given: 여러 통화에서 지식 추출
        When: get_stats() 호출
        Then: 올바른 통계 반환
        """
        # Given
        from src.ai_voicebot.knowledge.knowledge_extractor import KnowledgeExtractor
        
        llm = mock_components["llm"]
        embedder = mock_components["embedder"]
        vector_db = mock_components["vector_db"]
        
        extractor = KnowledgeExtractor(
            llm_client=llm,
            embedder=embedder,
            vector_db=vector_db
        )
        
        # When - 여러 통화 처리
        for i in range(3):
            await extractor.extract_from_call(
                call_id=f"call_{i}",
                transcript_path=sample_transcript_file,
                owner_id="1004",
                speaker="callee"
            )
        
        # Then - 통계 확인
        stats = extractor.get_stats()
        
        assert stats["total_extractions"] == 3
        assert stats["total_chunks_stored"] > 0
        assert stats["avg_chunks_per_extraction"] > 0
        assert stats["min_confidence"] == 0.7
        
        print(f"[OK] Statistics: {stats}")


if __name__ == "__main__":
    # 개별 실행
    pytest.main([__file__, "-v", "-s"])

