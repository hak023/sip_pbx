"""
RAG (Retrieval-Augmented Generation) Engine

Vector DB 검색 및 컨텍스트 재순위화
"""

from typing import List, Dict, Optional
from dataclasses import dataclass
import asyncio
import structlog

from src.ai_voicebot.ai_pipeline.query_hints import looks_like_visit_or_direction_info_query
from src.common.sip_owner import normalize_owner_username

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
    
    # intent → knowledge category 검색 조건 (CHROMADB_CATEGORY_DESIGN)
    # question/transfer/unknown: category 제한 없음(owner만 필터) — 지식 카테고리가 테넌트별로 다름(weather_forecast, menu 등)
    # complaint/transfer 시에도 대시보드에 넣은 잡담·연락처 지식이 검색되도록 카테고리 확장
    _COMPLAINT_TRANSFER_CATS = [
        "question", "complaint", "transfer", "chitchat", "contact",
    ]
    INTENT_CATEGORY_MAP = {
        "greeting": ["greeting_phase1", "greeting_phase2"],
        "farewell": ["farewell"],
        "question": None,   # 전체 지식 검색 (owner만 적용)
        "complaint": _COMPLAINT_TRANSFER_CATS,
        "transfer": _COMPLAINT_TRANSFER_CATS,
        "unknown": None,   # 전체 지식 검색 (owner만 적용)
    }

    async def search(
        self, 
        query: str, 
        owner_filter: Optional[str] = None,
        call_id: Optional[str] = None,  # DB 로깅용
        top_k_override: Optional[int] = None,
        intent: Optional[str] = None,  # intent별 category 필터 (설계 §4.1)
    ) -> List[Document]:
        """
        질문에 대한 관련 문서 검색
        
        Args:
            query: 검색 질문
            owner_filter: 사용자 ID 필터 (착신자 전용 지식)
            call_id: 통화 ID (DB 로깅용, 선택)
            intent: 의도 — 이에 따라 category 조건 추가 (greeting/farewell/question 등)
            
        Returns:
            관련 문서 리스트 (상위 top_k개)
        """
        import time
        start_time = time.time()
        owner_for_query = normalize_owner_username(owner_filter) if owner_filter else None
        if owner_filter and owner_for_query != (owner_filter or "").strip():
            logger.info(
                "rag_search_owner_normalized",
                call_id=call_id or "",
                owner_filter_raw_preview=(owner_filter or "")[:80],
                owner_filter_normalized=owner_for_query or "",
            )

        try:
            # 1. 질문 임베딩 (TextEmbedder.embed_text sync — embed 메서드 없음)
            if hasattr(self.embedder, "embed_text"):
                query_embedding = self.embedder.embed_text(query)
            elif hasattr(self.embedder, "embed"):
                fn = self.embedder.embed
                query_embedding = await fn(query) if asyncio.iscoroutinefunction(fn) else fn(query)
            else:
                raise RuntimeError("Embedder has no embed_text or embed method")
            if not query_embedding:
                return []
            
            # 2. Vector DB 검색 (intent → category 필터, 설계 §4.1). question/unknown은 category 미적용(테넌트 지식 전체 검색)
            effective_top_k = top_k_override if top_k_override else self.top_k
            # transfer로 분류됐어도 방문·길 안내 질의면 카테고리 제한 없이 검색 (오시는 길 FAQ가 question 외 category일 수 있음)
            search_intent = intent
            if intent == "transfer" and looks_like_visit_or_direction_info_query(query):
                search_intent = None
                logger.info(
                    "rag_search_intent_relaxed_for_visit_query",
                    call_id=call_id or "",
                    original_intent=intent,
                    query_preview=(query or "")[:100],
                    note="transfer+방문/교통류 질의 → category 필터 해제(전체 지식)",
                )
            filter_dict = None
            if owner_for_query or search_intent:
                and_conditions = []
                if owner_for_query:
                    and_conditions.append({"owner": owner_for_query})
                cats = self.INTENT_CATEGORY_MAP.get(search_intent) if search_intent else None
                if cats is not None and cats:
                    and_conditions.append({"category": {"$in": cats}})
                if and_conditions:
                    filter_dict = {"$and": and_conditions} if len(and_conditions) > 1 else and_conditions[0]
            raw = self.vector_db.query(
                query_embeddings=[query_embedding],
                n_results=effective_top_k * 2,
                where=filter_dict
            )
            ids = raw.get("ids", [[]])[0] if raw.get("ids") else []
            docs_list = raw.get("documents", [[]])[0] if raw.get("documents") else []
            metadatas = raw.get("metadatas", [[]])[0] if raw.get("metadatas") else []
            distances = raw.get("distances", [[]])[0] if raw.get("distances") else []
            raw_count = len(ids)
            first_distance = float(distances[0]) if distances else None
            
            # 3. Document 객체 변환 (Chroma 거리 → 유사도 스코어: 1/(1+d) 또는 1 - norm(d))
            documents = []
            for i, doc_id in enumerate(ids):
                text = docs_list[i] if i < len(docs_list) else ""
                meta = metadatas[i] if i < len(metadatas) else {}
                dist = distances[i] if i < len(distances) else 1.0
                score = 1.0 / (1.0 + float(dist)) if dist is not None else 0.0
                documents.append(Document(id=doc_id or "", text=text if isinstance(text, str) else "", score=score, metadata=meta))
            
            # 4. 유사도 필터링
            before_filter = list(documents)
            documents = [
                doc for doc in documents
                if doc.score >= self.similarity_threshold
            ]
            after_threshold_count = len(documents)
            # 하드 컷으로 0건이나 Chroma 상위 후보가 있으면 완화 후보 반환 (짧은 STT·거리 스코어 특성)
            if not documents and before_filter:
                soft_floor = max(0.22, min(self.similarity_threshold * 0.5, 0.42))
                soft = [d for d in before_filter if d.score >= soft_floor]
                if not soft:
                    soft = sorted(before_filter, key=lambda d: d.score, reverse=True)[
                        : min(2, len(before_filter))
                    ]
                documents = soft
                after_threshold_count = len(documents)
                logger.info(
                    "rag_search_soft_fallback_applied",
                    call_id=call_id or "",
                    soft_floor=round(soft_floor, 4),
                    returned=len(documents),
                    top_score=round(documents[0].score, 4) if documents else 0.0,
                    note="임계값 미달 0건 → 완화 후보 사용 (config threshold 유지, 검색만 완화)",
                )
            logger.info("rag_search_debug",
                        call=True,
                        call_id=call_id or "",
                        category="rag",
                        raw_count_before_threshold=raw_count,
                        after_threshold_count=after_threshold_count,
                        filter_where=filter_dict,
                        intent=intent,
                        search_intent_used=search_intent,
                        first_raw_distance=round(first_distance, 4) if first_distance is not None else None,
                        note="raw_count>0, after_threshold=0 이면 similarity_threshold 또는 category 불일치 의심")
            
            # 5. 재순위화 (선택)
            if self.reranking_enabled and documents:
                documents = await self._rerank(query, documents)
            
            # 6. Top-K 반환
            documents = documents[:effective_top_k]
            
            self.total_searches += 1
            self.total_results += len(documents)
            
            # 검색 시간 계산
            search_latency_ms = int((time.time() - start_time) * 1000)
            top_k_used = top_k_override if top_k_override else self.top_k
            top_score = documents[0].score if documents else 0.0
            top_text_preview = (documents[0].text[:150] + "...") if documents and len(documents[0].text) > 150 else (documents[0].text if documents else "")

            logger.info("rag_search_completed",
                       call=True,
                       call_id=call_id or "",
                       category="rag",
                       progress="rag",
                       query=query,
                       query_length=len(query),
                       results_count=len(documents),
                       top_k=top_k_used,
                       similarity_threshold=self.similarity_threshold,
                       reranking=self.reranking_enabled,
                       owner_filter=owner_for_query,
                       latency_ms=search_latency_ms,
                       top_score=round(top_score, 4),
                       top_doc_preview=top_text_preview,
                       note="Vector 검색 완료, call_id로 통화별 필터")
            
            # DB 로깅 (신규)
            if call_id:
                try:
                    from ..logging.ai_logger import log_rag_search_sync
                    
                    # 검색 결과를 직렬화 가능한 형태로 변환
                    search_results_dict = [
                        {
                            "id": doc.id,
                            "text": doc.text[:200],  # 최대 200자
                            "score": doc.score
                        }
                        for doc in documents
                    ]
                    
                    # RAG 컨텍스트 (실제 사용된 문서)
                    rag_context = "\n\n".join([doc.text for doc in documents])
                    
                    # 최고 점수
                    top_score = documents[0].score if documents else 0.0
                    
                    # 비동기 로깅
                    log_rag_search_sync(
                        call_id=call_id,
                        user_question=query,
                        search_results=search_results_dict,
                        top_score=top_score,
                        rag_context_used=rag_context[:1000],  # 최대 1000자
                        search_latency_ms=search_latency_ms
                    )
                    
                    # 지식 매칭 로깅 (각 문서마다)
                    from ..logging.ai_logger import log_knowledge_match_sync
                    for doc in documents:
                        log_knowledge_match_sync(
                            call_id=call_id,
                            matched_knowledge_id=doc.id,
                            similarity_score=doc.score,
                            knowledge_text=doc.text,
                            category=doc.metadata.get("category", "unknown")
                        )
                except ImportError:
                    logger.debug("AI logger not available, skipping DB logging")
                except Exception as e:
                    logger.error("rag_db_log_failed", call=True, category="rag", error=str(e))
            
            return documents
            
        except Exception as e:
            logger.error("rag_search_error", call=True, category="rag", error=str(e), exc_info=True)
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
            
            logger.debug("rag_reranking_completed", category="rag", count=len(documents))
            return documents
            
        except Exception as e:
            logger.error("rag_reranking_error", category="rag", error=str(e))
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

