"""
Google Cloud TTS(ko-KR) 등에서 아라비아 숫자를 영어로 읽는 현상 완화.

숫자 덩어리를 한자어 수사(이천이십육) 또는 자릿수 읽기(일공공사)로 바꿔 TTS 입력에 넣는다.
"""

from __future__ import annotations

import re
from typing import Callable, Match

# 0~9 한자어 수사
_H = ["영", "일", "이", "삼", "사", "오", "육", "칠", "팔", "구"]


def _chunk_under_10000(n: int) -> str:
    """0 < n < 10000 인 정수를 한자어 수사 한 덩어리로 (만 단위 미만)."""
    if n <= 0 or n >= 10000:
        raise ValueError(n)
    d1000, r = divmod(n, 1000)
    d100, r = divmod(r, 100)
    d10, d1 = divmod(r, 10)
    parts: list[str] = []
    if d1000:
        parts.append("천" if d1000 == 1 else _H[d1000] + "천")
    if d100:
        parts.append("백" if d100 == 1 else _H[d100] + "백")
    if d10:
        parts.append("십" if d10 == 1 else _H[d10] + "십")
    if d1:
        parts.append(_H[d1])
    return "".join(parts)


def int_to_korean_sino(n: int) -> str:
    """비음수 정수 → 한자어 기반 한국어 수 읽기 (이천이십육, 일만이천삼백사십오…)."""
    if n < 0:
        return "마이너스" + int_to_korean_sino(-n)
    if n == 0:
        return "영"
    if n < 10000:
        return _chunk_under_10000(n)

    big = ["", "만", "억", "조", "경"]
    chunks: list[int] = []
    x = n
    while x > 0:
        chunks.append(x % 10000)
        x //= 10000
    parts: list[str] = []
    for i in range(len(chunks) - 1, -1, -1):
        ch = chunks[i]
        if ch == 0:
            continue
        suffix = big[i] if i < len(big) else ""
        parts.append(_chunk_under_10000(ch) + suffix)
    return "".join(parts)


def digits_to_korean_serial(s: str) -> str:
    """전화·내선 등: 각 자리를 영일이삼… 로 이어 읽기."""
    return "".join(_H[int(c)] for c in s if c.isdigit())


def _replace_number_match(m: Match[str]) -> str:
    raw = m.group(0)
    if not raw.isdigit():
        return raw
    n = int(raw)
    ln = len(raw)

    # 9자리 이상: 휴대폰·긴 식별자 가능성 → 자릿수 읽기
    if ln >= 9:
        return digits_to_korean_serial(raw)

    # 연도 1900~2099
    if ln == 4 and 1900 <= n <= 2099:
        return int_to_korean_sino(n)

    # 4자리 1000~9999: '천사' 등 오독 방지 → 자릿수 (내선 1004 등)
    if ln == 4 and 1000 <= n <= 9999:
        return digits_to_korean_serial(raw)

    # 3자리: 내선·코드
    if ln == 3:
        return digits_to_korean_serial(raw)

    # 1~2자리: 십·백 단위 자연스러운 읽기
    if ln <= 2:
        return int_to_korean_sino(n)

    # 5~8자리: 만 단위 조합
    return int_to_korean_sino(n)


# 연속 숫자 덩어리 (다른 숫자·문자와 인접 구분)
_DIGIT_RUN = re.compile(r"(?<!\d)\d+(?!\d)")

# IPv4는 그대로 두면 TTS가 영어로 읽을 수 있으나, 잘못 치환 위험이 커서 유지
_IPV4 = re.compile(
    r"\b(?:25[0-5]|2[0-4]\d|[01]?\d{1,2})\.(?:25[0-5]|2[0-4]\d|[01]?\d{1,2})\."
    r"(?:25[0-5]|2[0-4]\d|[01]?\d{1,2})\.(?:25[0-5]|2[0-4]\d|[01]?\d{1,2})\b"
)


def normalize_text_for_korean_tts(text: str) -> str:
    """
    TTS에 넣기 전 텍스트의 숫자 덩어리를 한글 수사로 치환한다.

    - URL/도메인에 포함된 숫자는 별도 분리가 어려워 동일 규칙이 적용될 수 있음.
    - IPv4 주소 문자열은 치환에서 제외한다.
    """
    if not text or not text.strip():
        return text

    spans: list[tuple[int, int, str]] = []
    for m in _IPV4.finditer(text):
        spans.append((m.start(), m.end(), m.group(0)))

    def repl_segment(segment: str) -> str:
        return _DIGIT_RUN.sub(_replace_number_match, segment)

    if not spans:
        return repl_segment(text)

    out: list[str] = []
    pos = 0
    for start, end, literal in spans:
        if start > pos:
            out.append(repl_segment(text[pos:start]))
        out.append(literal)
        pos = end
    if pos < len(text):
        out.append(repl_segment(text[pos:]))
    return "".join(out)
