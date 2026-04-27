"""발신자 식별 문자열에서 DB 매칭용 needle(숫자 조각) 추출.

call_records.caller_id LIKE '%needle%' 및 caller_contacts.canonical_phone 키에 공통 사용.
"""

from __future__ import annotations


def sip_uri_user_local_part(raw: str) -> str:
    """``sip:user@host`` / ``<sip:user@host>`` 에서 user 부분만 추출. 실패 시 빈 문자열."""
    s = (raw or "").strip()
    if s.startswith("<") and s.endswith(">"):
        s = s[1:-1].strip()
    low = s.lower()
    if not low.startswith("sip:"):
        return ""
    try:
        rest = s.split(":", 1)[1]
    except IndexError:
        return ""
    if "@" not in rest:
        return ""
    return rest.split("@", 1)[0].strip("<>\"' ")


def caller_match_needle(raw: str, max_len: int = 8, min_len: int = 4) -> tuple[str, str]:
    """DB ``caller_id LIKE '%needle%'`` 용 조각과 출처.

    Returns:
        (needle, source) — ``sip_user`` | ``tail_digits`` | ``empty``.
    """
    s = (raw or "").strip()
    user = sip_uri_user_local_part(s)
    if user:
        user_digits = "".join(c for c in user if c.isdigit())
        if len(user_digits) >= min_len:
            if len(user_digits) >= max_len:
                return user_digits[-max_len:], "sip_user"
            return user_digits, "sip_user"

    d = "".join(c for c in s if c.isdigit())
    if not d:
        return "", "empty"
    if len(d) >= max_len:
        return d[-max_len:], "tail_digits"
    if len(d) >= min_len:
        return d[-min_len:], "tail_digits"
    return d, "tail_digits"


def digits_tail_for_caller_match(raw: str, max_len: int = 8, min_len: int = 4) -> str:
    needle, _src = caller_match_needle(raw, max_len=max_len, min_len=min_len)
    return needle


def last_digit_suffix(raw: str, n: int = 4) -> str:
    """표시용 접미사: 문자열에서 숫자만 모아 끝 n자리 (부족하면 있는 만큼)."""
    d = "".join(c for c in (raw or "") if c.isdigit())
    if not d:
        return ""
    return d[-n:] if len(d) >= n else d
