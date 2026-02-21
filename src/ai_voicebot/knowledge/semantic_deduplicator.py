"""
Semantic Deduplicator

VectorDB 기반 의미적 중복 검사
코사인 유사도로 중복/유사 문서를 검출합니다.
"""

import structlog
from typing import Dict, List, Optional
from dataclasses import dataclass

logger = structlog.get_logger(__name__)


@dataclass
class DeduplicationResult:
    """중복 검사 결과"""
    status: str                 # "unique" | "duplicate" | "near_duplicate"
    similar_doc_id: Optional[str]   # 유사 문서 ID (있을 경우)
    similarity_score: float     # 최고 유사도 점수
    action: str                 # "insert" | "skip" | "merge_candidate"


class SemanticDeduplicator:
    """VectorDB 기반 의미적 중복 검사"""

    DUPLICATE_THRESHOLD = 0.92        # cosine ≥ 0.92 → 중복
    NEAR_DUPLICATE_THRESHOLD = 0.85   # 0.85 ≤ sim < 0.92 → 유사 (병합 후보)

    def __init__(self, vector_db, embedder):
        """
        Args:
            vector_db: VectorDB 인스턴스 (ChromaDBClient)
            embedder: TextEmbedder 인스턴스
        """
        self.vector_db = vector_db
        self.embedder = embedder

    async def check(
        self,
        text: str,
        embedding: Optional[List[float]] = None,
        exclude_doc_ids: Optional[List[str]] = None,
    ) -> DeduplicationResult:
        """
        텍스트의 의미적 중복 검사

        Args:
            text: 검사할 텍스트
            embedding: 미리 생성된 임베딩 (없으면 자동 생성)
            exclude_doc_ids: 검사에서 제외할 doc_id 목록

        Returns:
            DeduplicationResult
        """
        try:
            # 임베딩 생성
            if embedding is None:
                embedding = await self.embedder.embed(text)

            if not embedding:
                return DeduplicationResult(
                    status="unique",
                    similar_doc_id=None,
                    similarity_score=0.0,
                    action="insert",
                )

            # VectorDB에서 유사 문서 검색 (top-3)
            results = await self.vector_db.search(
                vector=embedding,
                top_k=3,
            )

            if not results:
                return DeduplicationResult(
                    status="unique",
                    similar_doc_id=None,
                    similarity_score=0.0,
                    action="insert",
                )

            # 유사도 기반 판정 (ChromaDB는 distance를 반환, cosine distance = 1 - cosine_similarity)
            for doc in results:
                doc_id = doc.id
                # exclude list 확인
                if exclude_doc_ids and doc_id in exclude_doc_ids:
                    continue

                # ChromaDB score는 거리(distance). cosine distance라면 similarity = 1 - distance
                # 하지만 일부 구현에서는 직접 similarity를 반환하므로 범위로 판단
                score = doc.score
                if score > 1.0:
                    # distance 형식 (0=같음, 2=반대)
                    similarity = 1.0 - (score / 2.0)
                else:
                    # similarity 형식 (1=같음, 0=무관)
                    similarity = score

                if similarity >= self.DUPLICATE_THRESHOLD:
                    logger.info(
                        "duplicate_detected",
                        similar_doc_id=doc_id,
                        similarity=similarity,
                    )
                    return DeduplicationResult(
                        status="duplicate",
                        similar_doc_id=doc_id,
                        similarity_score=similarity,
                        action="skip",
                    )

                if similarity >= self.NEAR_DUPLICATE_THRESHOLD:
                    logger.info(
                        "near_duplicate_detected",
                        similar_doc_id=doc_id,
                        similarity=similarity,
                    )
                    return DeduplicationResult(
                        status="near_duplicate",
                        similar_doc_id=doc_id,
                        similarity_score=similarity,
                        action="merge_candidate",
                    )

            # 유사 문서 없음
            best_score = 0.0
            if results:
                s = results[0].score
                best_score = s if s <= 1.0 else 1.0 - (s / 2.0)

            return DeduplicationResult(
                status="unique",
                similar_doc_id=None,
                similarity_score=best_score,
                action="insert",
            )

        except Exception as e:
            logger.warning("deduplication_check_failed", error=str(e))
            # 실패 시 저장 진행 (안전 우선)
            return DeduplicationResult(
                status="unique",
                similar_doc_id=None,
                similarity_score=0.0,
                action="insert",
            )
