"""SIP From / P-Asserted-Identity 등 헤더 값에서 발신 식별자(번호·내선) 추출."""

from __future__ import annotations

import re


def parse_sip_identity_from_header_value(header_value: str) -> str:
    """헤더 한 줄(또는 여러 URI 중 첫 부분)에서 사용자 식별 문자열 추출.

    지원:
    - ``sip:`` / ``sips:`` user@host (대소문자 무시)
    - ``tel:`` E.164 등 (공백·하이픈 제거는 호출부 선택; 여기서는 앞뒤 공백만 trim)
    """
    if not header_value or not str(header_value).strip():
        return ""
    s = str(header_value).strip()

    # 첫 꺾쇠 URI 우선 (P-Asserted-Identity: "<sip:...>" 형태)
    angle = re.search(r"<([^>]+)>", s)
    if angle:
        s = angle.group(1).strip()

    # tel:+82101234... (세미콜론·쉼표·공백 전까지)
    m = re.search(r"(?i)\btel:\s*([^;>,\s]+)", s)
    if m:
        return m.group(1).strip()

    # sip(s):user@host
    m = re.search(r"(?i)\bsips?:\s*([^@;>\s]+)\s*@", s)
    if m:
        return m.group(1).strip()

    return ""
