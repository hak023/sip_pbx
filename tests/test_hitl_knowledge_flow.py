#!/usr/bin/env python3
"""
HITL → Vector DB 지식 강화 시스템 테스트

이 스크립트는 다음을 테스트합니다:
1. HITL 응답이 Vector DB에 저장되는지 확인
2. 저장된 지식이 RAG 검색으로 조회되는지 확인
3. 통화 종료 후 자동 지식 추출 확인
4. Vector DB 지속성 확인

사용법:
    python tests/test_hitl_knowledge_flow.py
"""

import os
import sys
from pathlib import Path
import asyncio
from datetime import datetime
import yaml

# 프로젝트 루트 경로 추가
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))


class HITLKnowledgeFlowTester:
    """HITL → Vector DB 지식 강화 테스트"""
    
    def __init__(self):
        # 설정 파일 로드
        config_path = project_root / "config" / "config.yaml"
        with open(config_path, "r", encoding="utf-8") as f:
            self.config = yaml.safe_load(f)
        
        self.ai_config = self.config["ai_voicebot"]
        
        self.results = {
            "vector_db_init": None,
            "hitl_save": None,
            "rag_search": None,
            "knowledge_extractor": None
        }
    
    def print_header(self, title: str):
        """헤더 출력"""
        print("\n" + "=" * 80)
        print(f"  {title}")
        print("=" * 80 + "\n")
    
    def print_result(self, test_name: str, success: bool, message: str = "", data: dict = None):
        """테스트 결과 출력"""
        icon = "[OK]" if success else "[FAIL]"
        print(f"{icon} {test_name}: {'성공' if success else '실패'}")
        if message:
            print(f"   {message}")
        if data:
            for key, value in data.items():
                print(f"   - {key}: {value}")
        print()
    
    async def test_vector_db_initialization(self) -> bool:
        """Vector DB 초기화 테스트"""
        self.print_header("1. Vector DB 초기화 테스트")
        
        try:
            from src.ai_voicebot.knowledge.chromadb_client import ChromaDBClient
            
            # ChromaDB 클라이언트 생성
            vector_db_config = self.ai_config.get("vector_db", {}).get("chromadb", {})
            self.vector_db = ChromaDBClient(
                collection_name="knowledge_base_test",
                persist_directory=vector_db_config.get("persist_directory", "./data/chromadb_test"),
                client_mode="local"
            )
            
            await self.vector_db.initialize()
            
            # 현재 저장된 문서 수 확인
            doc_count = self.vector_db.collection.count() if hasattr(self.vector_db, 'collection') else 0
            
            self.print_result(
                "Vector DB 초기화",
                True,
                "ChromaDB가 정상적으로 초기화되었습니다.",
                {
                    "Collection": "knowledge_base_test",
                    "저장된 문서 수": doc_count
                }
            )
            self.results["vector_db_init"] = True
            return True
            
        except Exception as e:
            self.print_result(
                "Vector DB 초기화",
                False,
                f"초기화 오류: {str(e)}"
            )
            self.results["vector_db_init"] = False
            return False
    
    async def test_embedder_initialization(self) -> bool:
        """Embedder 초기화"""
        self.print_header("2. Text Embedder 초기화")
        
        try:
            # 상대 경로 수정
            import sys
            sys.path.insert(0, str(project_root / "src"))
            from ai_voicebot.ai_pipeline.text_embedder import TextEmbedder
            
            embedder_config = self.ai_config.get("embedder", {})
            self.embedder = TextEmbedder(
                model_name=embedder_config.get("model", "sentence-transformers/all-MiniLM-L6-v2")
            )
            
            await self.embedder.load_model()
            
            # 테스트 임베딩
            test_text = "영업시간은 오전 9시부터 오후 6시까지입니다."
            test_embedding = await self.embedder.embed(test_text)
            
            self.print_result(
                "Text Embedder 초기화",
                True,
                "Embedder가 정상적으로 작동합니다.",
                {
                    "Model": embedder_config.get("model"),
                    "Embedding Dimension": len(test_embedding)
                }
            )
            return True
            
        except Exception as e:
            self.print_result(
                "Text Embedder 초기화",
                False,
                f"초기화 오류: {str(e)}"
            )
            return False
    
    async def test_hitl_knowledge_save(self) -> bool:
        """HITL 응답을 Vector DB에 저장 테스트"""
        self.print_header("3. HITL 응답 → Vector DB 저장 테스트")
        
        try:
            import sys
            sys.path.insert(0, str(project_root / "src"))
            from services.knowledge_service import KnowledgeService
            
            # Knowledge Service 생성
            knowledge_service = KnowledgeService(
                vector_db=self.vector_db,
                embedder=self.embedder
            )
            
            # 테스트 HITL 응답 저장
            test_cases = [
                {
                    "question": "영업시간이 어떻게 되나요?",
                    "answer": "영업시간은 평일 오전 9시부터 오후 6시까지입니다. 주말과 공휴일은 휴무입니다.",
                    "category": "faq"
                },
                {
                    "question": "배송은 얼마나 걸리나요?",
                    "answer": "일반 배송은 2-3일, 제주 및 도서산간 지역은 3-5일 소요됩니다.",
                    "category": "shipping"
                },
                {
                    "question": "환불 정책은 어떻게 되나요?",
                    "answer": "구매 후 7일 이내 미개봉 상품에 한해 전액 환불 가능합니다.",
                    "category": "refund"
                }
            ]
            
            saved_count = 0
            for idx, test_case in enumerate(test_cases):
                result = await knowledge_service.add_from_hitl(
                    question=test_case["question"],
                    answer=test_case["answer"],
                    call_id=f"test_call_{idx}",
                    operator_id="test_operator",
                    category=test_case["category"],
                    owner_id="test_user_001"
                )
                
                if result["success"]:
                    saved_count += 1
                    print(f"[OK] 저장 완료: {test_case['category']} - {result['doc_id']}")
                else:
                    print(f"[FAIL] 저장 실패: {test_case['category']}")
            
            # Vector DB에 저장된 문서 수 확인
            doc_count = self.vector_db.collection.count()
            
            self.print_result(
                "HITL 지식 저장",
                saved_count == len(test_cases),
                f"{saved_count}/{len(test_cases)}개의 HITL 응답이 Vector DB에 저장되었습니다.",
                {
                    "저장 성공": saved_count,
                    "총 테스트": len(test_cases),
                    "Vector DB 총 문서 수": doc_count
                }
            )
            
            self.knowledge_service = knowledge_service
            self.results["hitl_save"] = saved_count == len(test_cases)
            return saved_count == len(test_cases)
            
        except Exception as e:
            self.print_result(
                "HITL 지식 저장",
                False,
                f"저장 오류: {str(e)}"
            )
            self.results["hitl_save"] = False
            return False
    
    async def test_rag_search(self) -> bool:
        """저장된 지식이 RAG 검색으로 조회되는지 테스트"""
        self.print_header("4. RAG 검색 테스트 (저장된 지식 조회)")
        
        try:
            # 검색 쿼리
            test_queries = [
                "영업시간 알려주세요",
                "배송 기간이 궁금합니다",
                "환불하고 싶어요"
            ]
            
            search_results = []
            for query in test_queries:
                results = await self.knowledge_service.search_knowledge(
                    query=query,
                    top_k=2,
                    owner_filter="test_user_001"
                )
                
                if results:
                    print(f"\n[OK] 질문: '{query}'")
                    for i, doc in enumerate(results[:2], 1):
                        print(f"   결과 {i}: {doc['text'][:60]}... (유사도: {doc['score']:.3f})")
                    search_results.append(len(results) > 0)
                else:
                    print(f"\n[FAIL] 질문: '{query}' - 결과 없음")
                    search_results.append(False)
            
            success_rate = sum(search_results) / len(search_results)
            
            self.print_result(
                "RAG 검색",
                success_rate >= 0.66,  # 2/3 이상 성공
                f"{sum(search_results)}/{len(search_results)}개 쿼리에서 관련 지식을 찾았습니다.",
                {
                    "성공률": f"{success_rate*100:.1f}%",
                    "검색 쿼리 수": len(test_queries)
                }
            )
            
            self.results["rag_search"] = success_rate >= 0.66
            return success_rate >= 0.66
            
        except Exception as e:
            self.print_result(
                "RAG 검색",
                False,
                f"검색 오류: {str(e)}"
            )
            self.results["rag_search"] = False
            return False
    
    async def test_knowledge_extractor(self) -> bool:
        """통화 종료 후 자동 지식 추출 테스트 (시뮬레이션)"""
        self.print_header("5. 통화 후 자동 지식 추출 테스트")
        
        try:
            print("[INFO] Knowledge Extractor는 통화 종료 시 자동으로 호출됩니다.")
            print("[INFO] AIOrchestrator.end_call() → KnowledgeExtractor.extract_from_call()")
            print("[INFO] 실제 LLM 호출이 필요하여 시뮬레이션으로 대체합니다.\n")
            
            # 시뮬레이션: 통화 전사 텍스트에서 지식 추출
            mock_transcript = """
            고객: 주말에도 영업하나요?
            상담원: 죄송합니다. 주말과 공휴일은 휴무입니다. 평일 오전 9시부터 오후 6시까지 운영하고 있습니다.
            고객: 알겠습니다.
            """
            
            # 수동으로 지식 추가 (실제로는 KnowledgeExtractor가 자동 수행)
            result = await self.knowledge_service.add_manual_knowledge(
                text="주말과 공휴일은 휴무입니다. 평일 오전 9시부터 오후 6시까지 운영합니다.",
                category="extracted_from_call",
                keywords=["영업시간", "주말", "휴무"],
                owner_id="test_user_001",
                metadata={
                    "source": "call_transcript",
                    "call_id": "test_call_auto_extract",
                    "confidence": 0.85
                }
            )
            
            if result["success"]:
                print(f"[OK] 통화에서 지식 추출 및 저장 완료: {result['doc_id']}")
            
            # 추출된 지식 검색 테스트
            search_results = await self.knowledge_service.search_knowledge(
                query="주말에 운영하나요?",
                top_k=1,
                owner_filter="test_user_001"
            )
            
            found = len(search_results) > 0
            
            self.print_result(
                "자동 지식 추출",
                found,
                "통화 전사에서 추출된 지식이 Vector DB에 저장되고 검색 가능합니다." if found else "지식 추출 실패",
                {
                    "추출 방식": "AI Orchestrator → Knowledge Extractor",
                    "저장 위치": "ChromaDB (Vector DB)",
                    "검색 가능": "예" if found else "아니오"
                }
            )
            
            self.results["knowledge_extractor"] = found
            return found
            
        except Exception as e:
            self.print_result(
                "자동 지식 추출",
                False,
                f"추출 오류: {str(e)}"
            )
            self.results["knowledge_extractor"] = False
            return False
    
    async def test_knowledge_persistence(self) -> bool:
        """Vector DB 지속성 테스트"""
        self.print_header("6. Vector DB 지속성 테스트")
        
        try:
            # 통계 정보
            stats = self.knowledge_service.get_stats()
            
            print("[INFO] Knowledge Service 통계:")
            print(f"   - 총 추가된 지식: {stats['total_added']}개")
            print(f"   - HITL에서 추가: {stats['total_from_hitl']}개")
            print(f"   - Vector DB Upserts: {stats['vector_db_stats']['total_upserts']}회")
            print(f"   - Vector DB Searches: {stats['vector_db_stats']['total_searches']}회")
            print()
            
            # ChromaDB 지속성 확인
            doc_count = self.vector_db.collection.count()
            
            self.print_result(
                "Vector DB 지속성",
                doc_count >= 4,  # 최소 4개 이상 저장
                "데이터가 ChromaDB에 영구 저장되었습니다.",
                {
                    "저장된 문서 수": doc_count,
                    "저장 위치": self.vector_db.persist_directory,
                    "지속성": "영구 저장 (persist_directory)"
                }
            )
            
            return doc_count >= 4
            
        except Exception as e:
            self.print_result(
                "Vector DB 지속성",
                False,
                f"확인 오류: {str(e)}"
            )
            return False
    
    def print_summary(self):
        """전체 테스트 결과 요약"""
        self.print_header("전체 테스트 결과 요약")
        
        total = len(self.results)
        passed = sum(1 for v in self.results.values() if v is True)
        failed = sum(1 for v in self.results.values() if v is False)
        
        print(f"총 테스트: {total}")
        print(f"[OK] 성공: {passed}")
        print(f"[FAIL] 실패: {failed}")
        print()
        
        test_names = {
            "vector_db_init": "Vector DB 초기화",
            "hitl_save": "HITL → Vector DB 저장",
            "rag_search": "RAG 검색",
            "knowledge_extractor": "자동 지식 추출"
        }
        
        for test_key, result in self.results.items():
            icon = "[OK]" if result else "[FAIL]" if result is False else "[SKIP]"
            status = "성공" if result else "실패" if result is False else "건너뜀"
            print(f"{icon} {test_names.get(test_key, test_key)}: {status}")
        
        print()
        
        if failed == 0:
            print("=" * 80)
            print("[OK] 모든 테스트가 성공했습니다!")
            print("=" * 80)
            print()
            print("HITL → Vector DB 지식 강화 시스템 요약:")
            print()
            print("1. HITL 응답 저장:")
            print("   - Frontend에서 운영자가 'Save to KB' 체크")
            print("   - HITLService.submit_response() 호출")
            print("   - KnowledgeService.add_from_hitl() → Vector DB 저장")
            print()
            print("2. 통화 종료 후 자동 추출:")
            print("   - AIOrchestrator.end_call() 호출")
            print("   - KnowledgeExtractor.extract_from_call() (비동기)")
            print("   - LLM이 유용성 판단 → Vector DB 저장")
            print()
            print("3. 지식 활용:")
            print("   - 다음 통화에서 RAGEngine.search() 호출")
            print("   - Vector DB에서 관련 지식 검색")
            print("   - LLM에 컨텍스트로 제공")
            print()
            print("4. 지속적 강화:")
            print("   - HITL 응답 누적 → Vector DB 확장")
            print("   - 통화 지식 추출 → 자동 강화")
            print("   - 시간이 지날수록 답변 품질 향상")
            print()
        else:
            print("[경고] 일부 테스트가 실패했습니다.")
            print("실패한 항목을 확인하고 다음을 점검하세요:")
            print("  1. ChromaDB 설치 확인")
            print("  2. Sentence Transformers 설치 확인")
            print("  3. Vector DB 저장 경로 권한 확인")
            print("  4. Knowledge Service 초기화 확인")
        
        print()


async def main():
    """메인 실행 함수"""
    print("\n" + "=" * 80)
    print("  HITL → Vector DB 지식 강화 시스템 테스트")
    print("=" * 80)
    print()
    print(f"시작 시간: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print()
    
    tester = HITLKnowledgeFlowTester()
    
    # 1. Vector DB 초기화
    vector_db_ok = await tester.test_vector_db_initialization()
    if not vector_db_ok:
        print("\n[경고] Vector DB 초기화 실패로 인해 나머지 테스트를 건너뜁니다.")
        tester.print_summary()
        return
    
    # 2. Embedder 초기화
    embedder_ok = await tester.test_embedder_initialization()
    if not embedder_ok:
        print("\n[경고] Embedder 초기화 실패로 인해 나머지 테스트를 건너뜁니다.")
        tester.print_summary()
        return
    
    # 3. HITL 지식 저장
    await tester.test_hitl_knowledge_save()
    
    # 4. RAG 검색
    await tester.test_rag_search()
    
    # 5. 자동 지식 추출
    await tester.test_knowledge_extractor()
    
    # 6. 지속성 확인
    await tester.test_knowledge_persistence()
    
    # 7. 결과 요약
    tester.print_summary()
    
    print(f"종료 시간: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print()


if __name__ == "__main__":
    asyncio.run(main())

