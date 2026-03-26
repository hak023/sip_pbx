"""
Semantic Deduplicator

VectorDB 기반 의미적 중복 검사.
비교에 쓰는 점수는 `_VectorDbWrapper.search`가 Chroma 거리 d를 1/(1+d)로 바꾼 값(상한 1)이다.
(순수 코사인 유사도와 동일하지 않을 수 있음 — extraction_pipeline.md / 리포트 §9 참고)
"""

import structlog
from typing import Dict, List, Optional
from dataclasses import dataclass

logger = structlog.get_logger(__name__)

# 기본값: 통화 전사·구어체는 문장 겹침이 드물어 0.92는 사실상 “거의 동일 문장”에 가까움.
# 대화 기반 중복 완화 기본안: duplicate 낮춤, near는 duplicate보다 충분히 낮게 유지.
DEFAULT_DUPLICATE_THRESHOLD = 0.82
DEFAULT_NEAR_DUPLICATE_THRESHOLD = 0.74


@dataclass
class DeduplicationResult:
    """중복 검사 결과"""
    status: str                 # "unique" | "duplicate" | "near_duplicate"
    similar_doc_id: Optional[str]   # 유사 문서 ID (있을 경우)
    similarity_score: float     # 최고 유사도 점수
    action: str                 # "insert" | "skip" | "merge_candidate"


class SemanticDeduplicator:
    """VectorDB 기반 의미적 중복 검사"""

    def __init__(
        self,
        vector_db,
        embedder,
        duplicate_threshold: float = DEFAULT_DUPLICATE_THRESHOLD,
        near_duplicate_threshold: float = DEFAULT_NEAR_DUPLICATE_THRESHOLD,
    ):
        """
        Args:
            vector_db: VectorDB 인스턴스 (ChromaDBClient)
            embedder: TextEmbedder 인스턴스
            duplicate_threshold: 이 점수 이상이면 기존 문서와 중복으로 보고 skip
            near_duplicate_threshold: duplicate 미만이면서 이 값 이상이면 merge_candidate (파이프라인은 여전히 저장)
        """
        self.vector_db = vector_db
        self.embedder = embedder
        dup = float(duplicate_threshold)
        near = float(near_duplicate_threshold)
        if near >= dup:
            logger.warning(
                "dedup_threshold_invalid_near_gte_duplicate",
                duplicate_threshold=dup,
                near_duplicate_threshold=near,
                note="near_duplicate_threshold를 duplicate보다 낮게 조정합니다.",
            )
            near = max(0.0, dup - 0.05)
        self.duplicate_threshold = dup
        self.near_duplicate_threshold = near

    async def check(
        self,
        text: str,
        embedding: Optional[List[float]] = None,
        exclude_doc_ids: Optional[List[str]] = None,
        owner_filter: Optional[str] = None,
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

            # VectorDB에서 유사 문서 검색 (top-3). 테넌트 격리: owner 일치 문서만
            fltr = {"owner": owner_filter} if (owner_filter or "").strip() else None
            results = await self.vector_db.search(
                vector=embedding,
                top_k=3,
                filter=fltr,
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

                if similarity >= self.duplicate_threshold:
                    logger.info(
                        "duplicate_detected",
                        similar_doc_id=doc_id,
                        similarity=similarity,
                        duplicate_threshold=self.duplicate_threshold,
                    )
                    return DeduplicationResult(
                        status="duplicate",
                        similar_doc_id=doc_id,
                        similarity_score=similarity,
                        action="skip",
                    )

                if similarity >= self.near_duplicate_threshold:
                    logger.info(
                        "near_duplicate_detected",
                        similar_doc_id=doc_id,
                        similarity=similarity,
                        near_duplicate_threshold=self.near_duplicate_threshold,
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
