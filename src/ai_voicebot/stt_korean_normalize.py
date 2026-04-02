"""짧은 한국어 STT 결과에 대한 보수적 정규화 (인바운드·아웃바운드 공통)."""

from __future__ import annotations

import re
from typing import Optional

_LEADING_YO_SPILL = re.compile(r"^요\s+")
_COMPACT = re.compile(r"\s+")


def normalize_stt_short_korean(text: str) -> str:
    """앞 턴 잔여 '요 ' 제거, 짧은 만족도형 '…점이' → '…점이요' 보정."""
    t = (text or "").strip()
    if not t:
        return t
    if _LEADING_YO_SPILL.match(t) and "점" in t:
        t2 = _LEADING_YO_SPILL.sub("", t).strip()
        if t2:
            t = t2
    compact = _COMPACT.sub("", t)
    if len(t) <= 14 and compact.endswith("점이") and not compact.endswith("점이요"):
        if re.search(r"(?:[1-5]|일|이|삼|사|오)점이$", compact):
            t = t.rstrip("。．.!?") + "요"
    return t


def looks_like_satisfaction_question(question: str) -> bool:
    """만족도·점수 질문으로 보이면 휴리스틱 답변 매칭 허용."""
    q = (question or "").strip()
    if not q:
        return False
    if re.search(r"[1-5]\s*점", q):
        return True
    if re.search(r"(?:일|이|삼|사|오)\s*점", q):
        return True
    if "평가" in q and ("점" in q or "만족" in q):
        return True
    if "만족도" in q:
        return True
    return False


def extract_satisfaction_answer_canonical(user_text: str) -> Optional[str]:
    """발화에서 1~5점 표현을 추출하면 'N점' 형태로 반환, 없으면 None."""
    raw = (user_text or "").strip()
    if not raw:
        return None
    t = _COMPACT.sub("", raw)
    t = re.sub(r"^[요욧]+", "", t)
    t = t.rstrip("。．.?!？…")

    m = re.search(r"([1-5])\s*점", t)
    if m:
        return f"{m.group(1)}점"

    kr_map = {"일": "1", "이": "2", "삼": "3", "사": "4", "오": "5"}
    for word, digit in kr_map.items():
        if re.search(rf"{word}점", t):
            return f"{digit}점"
    if "오점" in t:
        return "5점"

    return None
