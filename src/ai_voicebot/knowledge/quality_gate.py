"""
Quality Gate

추출물 최종 품질 필터.
규칙 기반으로 저품질 추출물을 폐기합니다.
"""

import re
import structlog
from typing import Dict, List, Tuple
from dataclasses import dataclass

logger = structlog.get_logger(__name__)

# 인사말 패턴 (정보 가치 없음)
GREETING_PATTERNS = [
    r'^안녕하?세요[.!?]?$',
    r'^네[,.]?\s*(안녕하세요|감사합니다)[.!?]?$',
    r'^감사합니다[.!?]?$',
    r'^알겠습니다[.!?]?$',
    r'^네[.!?]?$',
    r'^아[,.]?\s*네[.!?]?$',
    r'^여보세요[.!?]?$',
]


@dataclass
class QualityResult:
    """품질 검사 결과"""
    passed: bool
    failed_rules: List[str]
    warnings: List[str]


class QualityGate:
    """추출물 품질 필터"""

    def __init__(
        self,
        min_confidence: float = 0.7,
        min_text_length: int = 10,
        max_text_length: int = 2000,
    ):
        self.min_confidence = min_confidence
        self.min_text_length = min_text_length
        self.max_text_length = max_text_length

    def check(self, item: Dict) -> QualityResult:
        """
        단일 추출물 품질 검사

        Args:
            item: 추출물 dict
                - text: str
                - confidence: float
                - category: str (optional)
                - hallucination_passed: bool (optional)

        Returns:
            QualityResult
        """
        failed = []
        warnings = []

        text = item.get("text", "")
        confidence = item.get("confidence", 0.0)
        category = item.get("category", "")
        halluc_passed = item.get("hallucination_passed", True)

        # Rule 1: 최소 신뢰도
        if confidence < self.min_confidence:
            failed.append(f"min_confidence: {confidence:.2f} < {self.min_confidence}")

        # Rule 2: 최소 텍스트 길이
        if len(text) < self.min_text_length:
            failed.append(f"min_text_length: {len(text)} < {self.min_text_length}")

        # Rule 3: 최대 텍스트 길이
        if len(text) > self.max_text_length:
            warnings.append(f"max_text_length: {len(text)} > {self.max_text_length} (잘림 가능)")

        # Rule 4: 인사말만 있는 경우
        if self._is_greeting_only(text):
            failed.append("greeting_only: 인사말만 포함된 텍스트")

        # Rule 5: 환각 검증 실패
        if not halluc_passed:
            failed.append("hallucination_check: 환각 검증 미통과")

        # Rule 6: "기타" 카테고리는 더 높은 신뢰도 요구
        if category == "기타" and confidence < 0.85:
            failed.append(f"ambiguous_category: '기타' 카테고리 + 신뢰도 {confidence:.2f} < 0.85")

        # Rule 7: 텍스트에 실질 정보 포함 여부 (숫자, 고유명사 등)
        if not self._has_substantive_info(text):
            warnings.append("low_info: 숫자/고유명사 등 실질 정보 부족")

        return QualityResult(
            passed=len(failed) == 0,
            failed_rules=failed,
            warnings=warnings,
        )

    def check_batch(self, items: List[Dict]) -> List[Tuple[Dict, QualityResult]]:
        """배치 품질 검사"""
        return [(item, self.check(item)) for item in items]

    @staticmethod
    def _is_greeting_only(text: str) -> bool:
        """인사말만 있는 텍스트인지 확인"""
        text_clean = text.strip()
        for pattern in GREETING_PATTERNS:
            if re.match(pattern, text_clean):
                return True
        return False

    @staticmethod
    def _has_substantive_info(text: str) -> bool:
        """실질적 정보(숫자, 시간, 장소 등)가 포함되어 있는지"""
        # 숫자 포함
        if re.search(r'\d', text):
            return True
        # 시간 관련 키워드
        if re.search(r'시|분|월|일|요일|내일|오늘|어제|주말', text):
            return True
        # 장소 관련
        if re.search(r'역|로|길|동|구|시|층|호', text):
            return True
        # 20자 이상이면 정보 가치가 있을 가능성
        if len(text.strip()) >= 20:
            return True
        return False
