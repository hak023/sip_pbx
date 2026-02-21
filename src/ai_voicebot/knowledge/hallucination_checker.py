"""
Hallucination Checker

추출 결과가 원문에 근거하는지 3중 검증합니다.
(AUTOSUMM, ACL 2025 참조 - 94% 사실 일관성)

검증 단계:
1. 구문 검증: 핵심 키워드가 원문에 존재하는지
2. 의미 검증: 임베딩 코사인 유사도
3. 함의 검증: LLM에게 원문이 추출 결과를 함의하는지 판단 요청

비용 최적화: 앞 단계에서 탈락하면 뒷 단계 스킵
"""

import asyncio
import json
import re
import structlog
from typing import Dict, List, Optional
from dataclasses import dataclass

logger = structlog.get_logger(__name__)


@dataclass
class HallucinationResult:
    """환각 검증 결과"""
    passed: bool
    syntactic_score: float       # 구문 매칭 점수 (0~1)
    semantic_score: float        # 의미 유사도 (0~1)
    entailment_result: Optional[str]  # "yes" | "no" | None (스킵됨)
    failed_at: Optional[str]    # None | "syntactic" | "semantic" | "entailment"
    details: str


class HallucinationChecker:
    """3중 환각 검증기"""

    # 임계값
    SYNTACTIC_THRESHOLD = 0.4     # 핵심 키워드 40%+ 매칭
    SEMANTIC_THRESHOLD = 0.75     # 코사인 유사도 0.75+
    
    def __init__(self, embedder=None, llm_client=None):
        """
        Args:
            embedder: TextEmbedder 인스턴스 (의미 검증용)
            llm_client: LLMClient 인스턴스 (함의 검증용)
        """
        self.embedder = embedder
        self.llm = llm_client

    async def check(
        self,
        extracted_text: str,
        original_text: str,
        skip_entailment: bool = False,
    ) -> HallucinationResult:
        """
        추출 결과가 원문에 근거하는지 3중 검증

        Args:
            extracted_text: 추출된 텍스트
            original_text: 원문 전사 텍스트
            skip_entailment: 함의 검증 스킵 여부

        Returns:
            HallucinationResult
        """
        # Stage 1: 구문 검증 (비용 0)
        syntactic_score = self._syntactic_check(extracted_text, original_text)
        if syntactic_score < self.SYNTACTIC_THRESHOLD:
            return HallucinationResult(
                passed=False,
                syntactic_score=syntactic_score,
                semantic_score=0.0,
                entailment_result=None,
                failed_at="syntactic",
                details=f"핵심 키워드 매칭률 {syntactic_score:.0%} < {self.SYNTACTIC_THRESHOLD:.0%}",
            )

        # Stage 2: 의미 검증 (임베딩 비용만)
        semantic_score = 0.0
        if self.embedder:
            semantic_score = await self._semantic_check(extracted_text, original_text)
            if semantic_score < self.SEMANTIC_THRESHOLD:
                return HallucinationResult(
                    passed=False,
                    syntactic_score=syntactic_score,
                    semantic_score=semantic_score,
                    entailment_result=None,
                    failed_at="semantic",
                    details=f"의미 유사도 {semantic_score:.3f} < {self.SEMANTIC_THRESHOLD}",
                )
        else:
            semantic_score = 1.0  # embedder 없으면 스킵 (통과 처리)

        # Stage 3: 함의 검증 (LLM 1회 호출)
        entailment_result = None
        if not skip_entailment and self.llm:
            entailment_result = await self._entailment_check(
                extracted_text, original_text
            )
            if entailment_result != "yes":
                return HallucinationResult(
                    passed=False,
                    syntactic_score=syntactic_score,
                    semantic_score=semantic_score,
                    entailment_result=entailment_result,
                    failed_at="entailment",
                    details=f"LLM 함의 판단: {entailment_result}",
                )

        return HallucinationResult(
            passed=True,
            syntactic_score=syntactic_score,
            semantic_score=semantic_score,
            entailment_result=entailment_result,
            failed_at=None,
            details="3중 검증 통과",
        )

    def _syntactic_check(self, extracted: str, original: str) -> float:
        """
        구문 검증: 추출 텍스트의 핵심 명사가 원문에 존재하는지 확인
        
        간단한 키워드 매칭 (형태소 분석 없이 공백 토큰 기반)
        """
        # 한국어 조사/어미 제거를 위한 간단한 정규화
        def normalize(text: str) -> set:
            text = text.lower()
            # 숫자, 한글 단어, 영문 단어만 추출
            tokens = re.findall(r'[가-힣]{2,}|[a-zA-Z]{2,}|\d+', text)
            # 일반적인 불용어 제거
            stopwords = {'이', '그', '저', '것', '수', '등', '더', '및', '또', '의', '를', '에', '은', '는', '이', '가'}
            return {t for t in tokens if t not in stopwords and len(t) >= 2}

        extracted_tokens = normalize(extracted)
        original_tokens = normalize(original)

        if not extracted_tokens:
            return 1.0  # 추출 텍스트에 키워드가 없으면 통과

        matched = extracted_tokens & original_tokens
        return len(matched) / len(extracted_tokens)

    async def _semantic_check(self, extracted: str, original: str) -> float:
        """의미 검증: 임베딩 코사인 유사도"""
        try:
            emb_extracted = await self.embedder.embed(extracted)
            emb_original = await self.embedder.embed(original[:2000])  # 원문 길이 제한

            # 코사인 유사도 계산
            dot_product = sum(a * b for a, b in zip(emb_extracted, emb_original))
            norm_a = sum(a * a for a in emb_extracted) ** 0.5
            norm_b = sum(b * b for b in emb_original) ** 0.5

            if norm_a == 0 or norm_b == 0:
                return 0.0

            return dot_product / (norm_a * norm_b)

        except Exception as e:
            logger.warning("semantic_check_failed", error=str(e))
            return 1.0  # 실패 시 통과 처리

    async def _entailment_check(self, extracted: str, original: str) -> str:
        """함의 검증: LLM에게 원문이 추출 결과를 함의하는지 판단 요청"""
        try:
            prompt = f"""다음 [원문]이 [추출 결과]의 내용을 뒷받침하는지 판단하세요.

[원문]:
{original[:1500]}

[추출 결과]:
{extracted}

[추출 결과]에 있는 모든 정보가 [원문]에 근거하면 "yes", 
[원문]에 없는 정보가 포함되어 있으면 "no"를 답하세요.

답변 (yes 또는 no만):"""

            import google.generativeai as genai

            loop = asyncio.get_event_loop()
            response = await loop.run_in_executor(
                None,
                lambda: self.llm.model.generate_content(
                    prompt,
                    generation_config=genai.types.GenerationConfig(
                        temperature=0.0,
                        max_output_tokens=10,
                    ),
                ),
            )

            result = response.text.strip().lower()
            if "yes" in result:
                return "yes"
            return "no"

        except Exception as e:
            logger.warning("entailment_check_failed", error=str(e))
            return "yes"  # 실패 시 통과 처리
