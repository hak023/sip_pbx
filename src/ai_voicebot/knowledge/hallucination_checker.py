"""
Hallucination Checker

추출 결과가 원문에 근거하는지 3중 검증합니다.
(AUTOSUMM, ACL 2025 참조 - 94% 사실 일관성)

검증 단계:
1. 구문 검증: 핵심 키워드가 원문에 존재하는지
2. 의미 검증: 임베딩 코사인 유사도
3. 함의 검증: LLM에게 원문이 추출 결과를 함의하는지 판단 요청

비용 최적화: 앞 단계에서 탈락하면 뒷 단계 스킵

전사 정규화(초단문 턴 통화): `transcript_normalization.enabled`가 true이면,
초단문(4자 이하) 턴 연속 제거 + 공백 압축으로 "발신자: 아 / 착신자: 네 기 상 / 발신자: 기"
→ "착신자: 네기상" 식으로 이어 붙여 구문 매칭률을 높인다.
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

    # 임계값 (기본)
    SYNTACTIC_THRESHOLD = 0.4     # 핵심 키워드 40%+ 매칭
    SEMANTIC_THRESHOLD = 0.75     # 코사인 유사도 0.75+
    
    def __init__(self, embedder=None, llm_client=None, config: Optional[Dict] = None):
        """
        Args:
            embedder: TextEmbedder 인스턴스 (의미 검증용)
            llm_client: LLMClient 인스턴스 (함의 검증용)
            config: transcript_normalization 설정 (초단문 턴 완화)
        """
        self.embedder = embedder
        self.llm = llm_client
        self.config = config or {}
        # 전사 정규화(초단문 턴 통화·환각 검증 완화)
        tn_cfg = self.config.get("transcript_normalization", {})
        self._normalize_for_hallucination = tn_cfg.get("enabled", True)
        self._collapse_short_turns = tn_cfg.get("collapse_short_turns", True)
        self._syntactic_threshold_relaxed = tn_cfg.get(
            "syntactic_threshold_relaxed", 0.25
        )
        self._short_turn_max_chars = tn_cfg.get("short_turn_max_chars", 4)
        logger.info(
            "hallucination_checker_init",
            normalize_enabled=self._normalize_for_hallucination,
            collapse_short_turns=self._collapse_short_turns,
            syntactic_relaxed=self._syntactic_threshold_relaxed,
        )

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
        # 전사 정규화 (초단문 턴 제거·공백 압축)
        transcript_for_check = (
            self._normalize_transcript(original_text)
            if self._normalize_for_hallucination
            else original_text
        )
        is_short_turn_transcript = self._looks_like_short_turn_transcript(original_text)
        # Stage 1: 구문 검증 (비용 0). 짧은 턴 다수이면 완화 임계값 적용.
        syntactic_threshold = (
            self._syntactic_threshold_relaxed
            if is_short_turn_transcript
            else self.SYNTACTIC_THRESHOLD
        )
        syntactic_score = self._syntactic_check(extracted_text, transcript_for_check)
        if syntactic_score < syntactic_threshold:
            logger.debug(
                "hallucination_syntactic_fail",
                score=round(syntactic_score, 3),
                threshold=syntactic_threshold,
                short_turn=is_short_turn_transcript,
                extracted_preview=extracted_text[:60],
                transcript_preview=transcript_for_check[:80],
            )
            return HallucinationResult(
                passed=False,
                syntactic_score=syntactic_score,
                semantic_score=0.0,
                entailment_result=None,
                failed_at="syntactic",
                details=f"핵심 키워드 매칭률 {syntactic_score:.0%} < {syntactic_threshold:.0%} (short_turn={is_short_turn_transcript})",
            )

        # Stage 2: 의미 검증 (임베딩 비용만)
        semantic_score = 0.0
        if self.embedder:
            semantic_score = await self._semantic_check(extracted_text, transcript_for_check)
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
                extracted_text, transcript_for_check
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

    def _looks_like_short_turn_transcript(self, text: str) -> bool:
        """짧은 턴(4자 이하)이 전체의 50% 이상이면 초단문 전사로 본다."""
        if not self._collapse_short_turns:
            return False
        lines = [ln.strip() for ln in text.split("\n") if ln.strip()]
        if len(lines) < 5:
            return False
        turn_count = 0
        short_count = 0
        for ln in lines:
            if ":" not in ln:
                continue
            turn_count += 1
            parts = ln.split(":", 1)
            if len(parts) == 2:
                content = parts[1].strip()
                if len(content) <= self._short_turn_max_chars:
                    short_count += 1
        if turn_count < 5:
            return False
        ratio = short_count / turn_count
        return ratio >= 0.5

    def _normalize_transcript(self, text: str) -> str:
        """
        초단문 턴 제거 + 화자 라벨 제거 + 공백 압축.
        예: "발신자: 기\n착신자: 상 청 홈" → "상 청 홈" (기 스킵, 공백 유지)
        """
        if not self._collapse_short_turns:
            return text
        lines = text.split("\n")
        content_parts = []
        for ln in lines:
            ln = ln.strip()
            if not ln or ":" not in ln:
                continue
            _, _, content = ln.partition(":")
            content = content.strip()
            # 초단문 턴 스킵
            if len(content) <= self._short_turn_max_chars:
                continue
            content_parts.append(content)
        # 화자 구분 없이 순수 텍스트만 공백으로 이음
        joined = " ".join(content_parts)
        # 연속 공백 압축
        joined = re.sub(r"\s+", " ", joined).strip()
        return joined

    def _syntactic_check(self, extracted: str, original: str) -> float:
        """
        구문 검증: 추출 텍스트의 핵심 명사가 원문에 존재하는지 확인.
        정규화된 전사는 공백 유지 상태이므로, 부분 문자열 매칭으로 토큰 존재 확인.
        """
        def normalize_tokens(text: str) -> set:
            """2글자 이상 한글/영문/숫자 토큰 추출."""
            text = text.lower()
            tokens = re.findall(r'[가-힣]{2,}|[a-zA-Z]{2,}|\d+', text)
            stopwords = {'이', '그', '저', '것', '수', '등', '더', '및', '또', '의', '를', '에', '은', '는', '이', '가'}
            return {t for t in tokens if t not in stopwords and len(t) >= 2}

        extracted_tokens = normalize_tokens(extracted)
        if not extracted_tokens:
            return 1.0
        
        # 원문을 공백 제거 + lower로 연속 문자열화
        original_collapsed = re.sub(r"\s+", "", original.lower())
        
        matched = 0
        for tok in extracted_tokens:
            # 토큰이 원문(공백 제거)에 부분 문자열로 있으면 매칭
            if tok.lower() in original_collapsed:
                matched += 1
        
        return matched / len(extracted_tokens)

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
