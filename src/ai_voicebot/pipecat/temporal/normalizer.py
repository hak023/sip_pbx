"""
시간 표현 정규화: 상대 표현(오늘/내일/어제 등)을 절대 날짜 문자열로 변환.
"""

import re
from datetime import datetime, timedelta
from typing import Optional


class TemporalExpressionNormalizer:
    """
    사용자 질의 내 시간 표현을 절대 날짜로 치환.
    예: "오늘 날씨" -> "2026년 3월 13일 날씨"
    """

    def __init__(self, base_date: Optional[datetime] = None):
        self._base = base_date or datetime.now()

    def rewrite_query(self, text: str) -> str:
        if not text or not text.strip():
            return text
        out = text
        # 오늘
        out = re.sub(
            r"\b오늘\b",
            self._format_date(self._base),
            out,
            flags=re.IGNORECASE,
        )
        # 내일
        out = re.sub(
            r"\b내일\b",
            self._format_date(self._base + timedelta(days=1)),
            out,
            flags=re.IGNORECASE,
        )
        # 어제
        out = re.sub(
            r"\b어제\b",
            self._format_date(self._base - timedelta(days=1)),
            out,
            flags=re.IGNORECASE,
        )
        # 모레
        out = re.sub(
            r"\b모레\b",
            self._format_date(self._base + timedelta(days=2)),
            out,
            flags=re.IGNORECASE,
        )
        # 그저께
        out = re.sub(
            r"\b그저께\b",
            self._format_date(self._base - timedelta(days=2)),
            out,
            flags=re.IGNORECASE,
        )
        return out

    @staticmethod
    def _format_date(d: datetime) -> str:
        return f"{d.year}년 {d.month}월 {d.day}일"
