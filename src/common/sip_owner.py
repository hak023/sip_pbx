"""
SIP URI / 테넌트 식별자 → Chroma·RAG용 owner (username만).

규칙: '@' 앞부분만 사용하고, 앞에 `sip:`(대소문자 무관)가 있으면 제거.
예: sip:1004@192.168.0.1 → 1004, 1004 → 1004
"""

from __future__ import annotations

from typing import Optional


def normalize_owner_username(value: Optional[str]) -> str:
    """
    SIP URI 또는 내선 문자열을 테넌트 owner 키로 정규화.

    Args:
        value: To-URI, sip:user@host, 또는 순수 내선(예: 1004)

    Returns:
        user 부분만 (예: 1004). 빈 입력이면 "".
    """
    if value is None or not isinstance(value, str):
        return ""
    s = value.strip()
    if not s:
        return ""

    if "@" in s:
        local = s.split("@", 1)[0].strip()
    else:
        local = s

    lower = local.lower()
    if lower.startswith("sip:"):
        local = local[4:].strip()

    if ";" in local:
        local = local.split(";", 1)[0].strip()

    return local if local else s
