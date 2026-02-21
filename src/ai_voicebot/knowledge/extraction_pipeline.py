"""
Extraction Pipeline v2

멀티스텝 지식 추출 파이프라인 오케스트레이터.
Chain-of-Interactions (EMNLP 2025) 참조.

파이프라인:
  Stage 1: 전처리 (transcript 로드)
  Stage 2: 멀티스텝 추출 (요약 → QA → 엔티티 → 유용성)
  Stage 3: 품질 검증 (환각 → 중복 → 품질 게이트)
  Stage 4: VectorDB 저장 (확장 메타데이터)
"""

import asyncio
import json
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional
from dataclasses import dataclass, field

import structlog

from .summarizer import ConversationSummarizer
from .qa_extractor import QAPairExtractor
from .entity_extractor import EntityExtractor
from .hallucination_checker import HallucinationChecker
from .semantic_deduplicator import SemanticDeduplicator
from .quality_gate import QualityGate

logger = structlog.get_logger(__name__)

# 파이프라인 버전
PIPELINE_VERSION = "v2"


@dataclass
class ExtractionItem:
    """추출된 개별 항목"""
    doc_type: str           # "knowledge" | "qa_pair" | "entity"
    text: str               # VectorDB에 저장할 텍스트 (검색용)
    category: str
    confidence: float
    keywords: List[str] = field(default_factory=list)
    # QA 전용
    question: Optional[str] = None
    answer: Optional[str] = None
    source_speaker: Optional[str] = None
    # Entity 전용
    entity_type: Optional[str] = None
    normalized_value: Optional[str] = None
    entity_speaker: Optional[str] = None
    # 품질 검증 결과
    hallucination_passed: bool = True
    dedup_status: str = "unique"       # "unique" | "duplicate" | "near_duplicate"
    merged_with: Optional[str] = None
    quality_passed: bool = True
    quality_warnings: List[str] = field(default_factory=list)


@dataclass
class ExtractionResult:
    """파이프라인 전체 결과"""
    call_id: str
    success: bool
    pipeline_version: str = PIPELINE_VERSION
    # 요약
    summary: str = ""
    main_topics: List[str] = field(default_factory=list)
    call_purpose: str = ""
    # 추출 항목
    items: List[ExtractionItem] = field(default_factory=list)
    # 저장 통계
    stored_count: int = 0
    skipped_duplicate: int = 0
    skipped_quality: int = 0
    skipped_hallucination: int = 0
    # 타이밍
    elapsed_ms: float = 0
    error: Optional[str] = None


class ExtractionPipeline:
    """멀티스텝 지식 추출 파이프라인 v2"""

    def __init__(
        self,
        llm_client,
        embedder,
        vector_db,
        config: Optional[Dict] = None,
    ):
        """
        Args:
            llm_client: LLMClient 인스턴스
            embedder: TextEmbedder 인스턴스
            vector_db: VectorDB 인스턴스
            config: knowledge_extraction 설정 (config.yaml)
        """
        self.llm = llm_client
        self.embedder = embedder
        self.vector_db = vector_db
        self.config = config or {}

        # 스텝 설정
        steps = self.config.get("steps", {})
        self.enable_summarize = steps.get("summarize", True)
        self.enable_qa_extract = steps.get("qa_extract", True)
        self.enable_entity_extract = steps.get("entity_extract", True)

        # 품질 설정
        quality_cfg = self.config.get("quality", {})
        self.min_confidence = quality_cfg.get("min_confidence", 0.7)
        self.enable_hallucination = quality_cfg.get("hallucination_check", True)
        self.enable_dedup = quality_cfg.get("deduplication", True)

        # 자동 승인
        auto_cfg = self.config.get("auto_approve", {})
        self.auto_approve_enabled = auto_cfg.get("enabled", True)
        self.auto_approve_confidence = auto_cfg.get("min_confidence", 0.9)

        # 비용 제어
        self.max_llm_calls = self.config.get("max_llm_calls_per_extraction", 6)
        self.skip_short_calls = self.config.get("skip_short_calls_seconds", 30)

        # 서브 컴포넌트
        self.summarizer = ConversationSummarizer(llm_client)
        self.qa_extractor = QAPairExtractor(llm_client)
        self.entity_extractor = EntityExtractor(llm_client)
        self.hallucination_checker = HallucinationChecker(embedder, llm_client)
        self.deduplicator = SemanticDeduplicator(vector_db, embedder)
        self.quality_gate = QualityGate(
            min_confidence=self.min_confidence,
            min_text_length=self.config.get("min_text_length", 10),
            max_text_length=self.config.get("max_text_length", 2000),
        )

        # 청킹 설정
        self.chunk_size = self.config.get("chunk_size", 500)
        self.chunk_overlap = self.config.get("chunk_overlap", 50)

        # 통계
        self.total_extractions = 0
        self.total_stored = 0

        logger.info(
            "ExtractionPipeline v2 initialized",
            steps=steps,
            quality=quality_cfg,
        )

    async def extract_from_call(
        self,
        call_id: str,
        transcript_path: str,
        owner_id: str,
        speaker: str = "both",
    ) -> ExtractionResult:
        """
        통화에서 지식 추출 (v2 파이프라인)

        Args:
            call_id: 통화 ID
            transcript_path: 전사 텍스트 파일 경로
            owner_id: 소유자 ID
            speaker: 화자 필터 (caller/callee/both)

        Returns:
            ExtractionResult
        """
        import time
        start_time = time.time()

        result = ExtractionResult(call_id=call_id, success=False)

        try:
            # ── Stage 1: 전처리 ──
            logger.info("📋 [Pipeline v2] Stage 1: 전처리", call_id=call_id)

            full_transcript = self._load_transcript(transcript_path)
            if not full_transcript or len(full_transcript.strip()) < 10:
                result.error = "Empty or too short transcript"
                logger.warning("pipeline_skip_empty", call_id=call_id)
                return result

            # 화자 필터 (QA/엔티티/요약용). 지식 정제(judge_usefulness)에는 전체 전사 전달(맥락)
            transcript = full_transcript
            if speaker not in ("both", "all"):
                transcript = self._filter_by_speaker(full_transcript, speaker)
                if not transcript:
                    result.error = "No content from target speaker"
                    return result

            # ── Stage 2: 멀티스텝 추출 ──
            logger.info("🔬 [Pipeline v2] Stage 2: 멀티스텝 추출", call_id=call_id)

            items: List[ExtractionItem] = []

            # Step 2-1: 요약 (병렬 시작)
            summary_task = None
            if self.enable_summarize:
                summary_task = asyncio.create_task(
                    self.summarizer.summarize(transcript, call_id)
                )

            # Step 2-2: QA 쌍 추출
            qa_pairs = []
            if self.enable_qa_extract:
                qa_pairs = await self.qa_extractor.extract(transcript, call_id)
                for qa in qa_pairs:
                    # QA 쌍은 "Q: ... A: ..." 형태로 VectorDB에 저장 (검색 최적화)
                    qa_text = f"Q: {qa['question']}\nA: {qa['answer']}"
                    items.append(ExtractionItem(
                        doc_type="qa_pair",
                        text=qa_text,
                        category=qa.get("category", "정보"),
                        confidence=0.85,  # QA 추출은 기본 0.85
                        keywords=self._extract_keywords(qa_text),
                        question=qa["question"],
                        answer=qa["answer"],
                        source_speaker=qa.get("source_speaker", ""),
                    ))

            # Step 2-3: 엔티티 추출
            entities = []
            if self.enable_entity_extract:
                entities = await self.entity_extractor.extract(transcript, call_id)
                for ent in entities:
                    ent_text = f"{ent['entity_type']}: {ent['value']}"
                    if ent.get("context"):
                        ent_text += f" ({ent['context']})"
                    items.append(ExtractionItem(
                        doc_type="entity",
                        text=ent_text,
                        category=ent["entity_type"],
                        confidence=ent.get("confidence", 0.8),
                        entity_type=ent["entity_type"],
                        normalized_value=ent.get("normalized"),
                        entity_speaker=ent.get("speaker", ""),
                    ))

            # Step 2-4: 지식 정제 — 설계서: 맥락 위해 전체 전사 전달, 저장은 착신자 발화만
            judgment = await self.llm.judge_usefulness(full_transcript, speaker, call_id=call_id)
            if judgment.get("is_useful") and judgment.get("confidence", 0) >= self.min_confidence:
                for info in judgment.get("extracted_info", []):
                    info_text = info.get("text", "")
                    if info_text and len(info_text) >= 10:
                        items.append(ExtractionItem(
                            doc_type="knowledge",
                            text=info_text,
                            category=info.get("category", "기타"),
                            confidence=judgment["confidence"],
                            keywords=info.get("keywords", []),
                        ))

            # 요약 결과 수집
            if summary_task:
                summary_data = await summary_task
                result.summary = summary_data.get("summary", "")
                result.main_topics = summary_data.get("main_topics", [])
                result.call_purpose = summary_data.get("call_purpose", "")

            logger.info(
                "🔬 [Pipeline v2] Stage 2 완료",
                call_id=call_id,
                qa_count=len(qa_pairs),
                entity_count=len(entities),
                knowledge_count=sum(1 for i in items if i.doc_type == "knowledge"),
                total_items=len(items),
            )

            if not items:
                result.success = True
                result.elapsed_ms = (time.time() - start_time) * 1000
                logger.info("pipeline_no_items", call_id=call_id)
                return result

            # ── Stage 3: 품질 검증 ──
            logger.info("✅ [Pipeline v2] Stage 3: 품질 검증", call_id=call_id)

            verified_items: List[ExtractionItem] = []

            for item in items:
                # 3-1: 환각 검증
                if self.enable_hallucination:
                    halluc = await self.hallucination_checker.check(
                        item.text,
                        transcript,
                        skip_entailment=(item.confidence >= 0.9),
                    )
                    item.hallucination_passed = halluc.passed
                    if not halluc.passed:
                        result.skipped_hallucination += 1
                        logger.debug(
                            "hallucination_skip",
                            text=item.text[:50],
                            reason=halluc.details,
                        )
                        continue

                # 3-2: 품질 게이트
                qr = self.quality_gate.check({
                    "text": item.text,
                    "confidence": item.confidence,
                    "category": item.category,
                    "hallucination_passed": item.hallucination_passed,
                })
                item.quality_passed = qr.passed
                item.quality_warnings = qr.warnings
                if not qr.passed:
                    result.skipped_quality += 1
                    logger.debug(
                        "quality_gate_skip",
                        text=item.text[:50],
                        rules=qr.failed_rules,
                    )
                    continue

                # 3-3: 중복 검증
                if self.enable_dedup:
                    embedding = await self.embedder.embed(item.text)
                    dedup = await self.deduplicator.check(item.text, embedding)
                    item.dedup_status = dedup.status
                    item.merged_with = dedup.similar_doc_id
                    if dedup.action == "skip":
                        result.skipped_duplicate += 1
                        logger.debug(
                            "dedup_skip",
                            text=item.text[:50],
                            similar=dedup.similar_doc_id,
                        )
                        continue

                verified_items.append(item)

            logger.info(
                "✅ [Pipeline v2] Stage 3 완료",
                call_id=call_id,
                verified=len(verified_items),
                skipped_halluc=result.skipped_hallucination,
                skipped_quality=result.skipped_quality,
                skipped_dedup=result.skipped_duplicate,
            )

            # ── Stage 4: VectorDB 저장 ──
            logger.info("💾 [Pipeline v2] Stage 4: 저장", call_id=call_id)

            now = datetime.now().isoformat()

            for idx, item in enumerate(verified_items):
                doc_id = f"{call_id}_{item.doc_type}_{idx}"
                embedding = await self.embedder.embed(item.text)

                # 자동 승인 판정
                review_status = "pending"
                if self.auto_approve_enabled and item.confidence >= self.auto_approve_confidence:
                    if item.hallucination_passed:
                        review_status = "approved"

                metadata = {
                    # 기본
                    "doc_type": item.doc_type,
                    "category": item.category,
                    "keywords": ",".join(item.keywords) if item.keywords else "",
                    # 추출 출처
                    "extraction_source": "call",
                    "extraction_call_id": call_id,
                    "extraction_timestamp": now,
                    "extraction_pipeline_version": PIPELINE_VERSION,
                    "owner": owner_id,
                    # 품질
                    "confidence_score": item.confidence,
                    "hallucination_check": "passed" if item.hallucination_passed else "failed",
                    "dedup_status": item.dedup_status,
                    "merged_with": item.merged_with or "",
                    # 리뷰
                    "review_status": review_status,
                    "reviewed_by": "",
                    "reviewed_at": "",
                    # 활용 추적
                    "usage_count": 0,
                    "last_used_at": "",
                    "useful_feedback_count": 0,
                }

                # QA 전용 필드
                if item.doc_type == "qa_pair":
                    metadata["question"] = item.question or ""
                    metadata["source_speaker"] = item.source_speaker or ""

                # Entity 전용 필드
                if item.doc_type == "entity":
                    metadata["entity_type"] = item.entity_type or ""
                    metadata["normalized_value"] = item.normalized_value or ""
                    metadata["entity_speaker"] = item.entity_speaker or ""

                await self.vector_db.upsert(
                    doc_id=doc_id,
                    embedding=embedding,
                    text=item.text,
                    metadata=metadata,
                )
                result.stored_count += 1

            result.items = verified_items
            result.success = True
            result.elapsed_ms = (time.time() - start_time) * 1000

            self.total_extractions += 1
            self.total_stored += result.stored_count

            logger.info(
                "🎉 [Pipeline v2] 추출 완료",
                call_id=call_id,
                stored=result.stored_count,
                elapsed_ms=f"{result.elapsed_ms:.0f}",
                summary_topics=result.main_topics,
            )

            return result

        except Exception as e:
            result.error = str(e)
            result.elapsed_ms = (time.time() - start_time) * 1000
            logger.error(
                "pipeline_error",
                call_id=call_id,
                error=str(e),
                exc_info=True,
            )
            return result

    # ── 유틸리티 ──

    def _load_transcript(self, path: str) -> str:
        try:
            return Path(path).read_text(encoding="utf-8")
        except Exception as e:
            logger.warning("transcript_load_error", path=path, error=str(e))
            return ""

    @staticmethod
    def _filter_by_speaker(transcript: str, speaker: str) -> str:
        label = "착신자" if speaker == "callee" else "발신자"
        lines = []
        for line in transcript.split("\n"):
            line = line.strip()
            if ":" in line:
                parts = line.split(":", 1)
                if parts[0].strip() == label:
                    text = parts[1].strip()
                    if text:
                        lines.append(text)
        return " ".join(lines)

    @staticmethod
    def _extract_keywords(text: str) -> List[str]:
        """간단한 키워드 추출 (2글자 이상 한글 명사 후보)"""
        import re
        tokens = re.findall(r'[가-힣]{2,}', text)
        # 빈도순 상위 5개
        freq: Dict[str, int] = {}
        for t in tokens:
            freq[t] = freq.get(t, 0) + 1
        sorted_tokens = sorted(freq.items(), key=lambda x: -x[1])
        return [t for t, _ in sorted_tokens[:5]]

    def get_stats(self) -> Dict:
        return {
            "total_extractions": self.total_extractions,
            "total_stored": self.total_stored,
            "pipeline_version": PIPELINE_VERSION,
            "steps": {
                "summarize": self.enable_summarize,
                "qa_extract": self.enable_qa_extract,
                "entity_extract": self.enable_entity_extract,
            },
        }
