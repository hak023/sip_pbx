"""
음성(TTS)으로 나가기 전 고객 멘트 정화.

LLM이 MAX_TOKENS 등으로 JSON·도구 조각만 반환한 경우 그대로 읽히는 것을 막는다.
"""

from __future__ import annotations

import re
from typing import Optional, Tuple

# 한글 음절 (가-힣)
_RE_HANGUL = re.compile(r"[\uac00-\ud7a3]")

_FALLBACK_DEFAULT = (
    "응답이 잘려서 안내가 어렵습니다. 잠시 후 다시 한 번 말씀해 주시겠어요?"
)
_FALLBACK_BOOKING = (
    "예약 안내 응답이 잘렸습니다. 원하시는 날짜와 시간을 다시 말씀해 주시겠어요?"
)


def _has_hangul(s: str) -> bool:
    return _RE_HANGUL.search(s) is not None


def _looks_like_tool_or_json_fragment(s: str) -> Tuple[bool, Optional[str]]:
    """
    TTS에 부적합한 LLM 구조화 출력 조각 여부.

    Returns:
        (is_bad, reason_code)
    """
    if not s:
        return False, None
    t = s.strip()
    low_head = t[:80].lower()

    if t.startswith("```"):
        return True, "markdown_fence_leading"
    if "```json" in low_head or (t.startswith("`") and "json" in low_head[:20]):
        return True, "markdown_json_fence"
    # 도구 호출 JSON 시뮬레이션 조각 (Nyki4RQxfk 유형)
    if "tool_" in t[:200] and (t.startswith("{") or t.startswith("```")):
        return True, "tool_field_fragment"
    if t.startswith("{") and ("tool_calls" in t[:300] or '"tool_calls"' in t[:300]):
        return True, "tool_calls_json"
    # 순수 JSON 형태이나 한글이 거의 없고 짧음 → 고객 멘트가 아님
    if t.startswith("{") and len(t) <= 800 and not _has_hangul(t):
        return True, "json_no_customer_language"
    return False, None


def sanitize_voice_assistant_text(
    text: str,
    *,
    intent: str = "",
) -> Tuple[str, Optional[str]]:
    """
    TTS·고객 음성 출력용 문자열을 검사한다.

    구조화 출력 조각이면 안내 멘트로 바꾼다.

    Returns:
        (safe_text, reason) — reason 이 None 이면 원문 유지(정화 없음).
    """
    raw = text or ""
    stripped = raw.strip()
    if not stripped:
        return raw, None

    bad, reason = _looks_like_tool_or_json_fragment(stripped)
    if not bad:
        return raw, None

    fb = _FALLBACK_BOOKING if (intent or "").strip().lower() == "booking" else _FALLBACK_DEFAULT
    return fb, reason
