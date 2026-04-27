"""SIP MESSAGE 수신 본문: charset·CPIM 처리 및 채팅 DB/WS 제외할 시그널링 판별."""

from __future__ import annotations

import re
from typing import Tuple

# 채팅 UI에 넣지 않는 Content-Type (RFC 3994 isComposing, IMDN, sipfrag 등)
_SIGNAL_CT_SUBSTR = (
    "im-iscomposing",
    "imdn+xml",
    "application/imdn",
    "message/imdn+xml",
    "message/sipfrag",
    "application/pidf+xml",  # presence
    "application/pidf-diff+xml",
    "application/vnd.3gpp",
)


def split_sip_headers_and_body(data: bytes) -> tuple[str, bytes]:
    """SIP datagram → 헤더 블록(ISO-8859-1)·본문 바이트."""
    sep = b"\r\n\r\n"
    i = data.find(sep)
    if i < 0:
        sep = b"\n\n"
        i = data.find(sep)
    if i < 0:
        return data.decode("iso-8859-1", errors="replace"), b""
    return data[:i].decode("iso-8859-1", errors="replace"), data[i + len(sep) :]


def charset_from_content_type(ct: str) -> str:
    if not ct:
        return "utf-8"
    m = re.search(r"charset\s*=\s*([^;\s]+)", ct, re.I)
    if m:
        return m.group(1).strip().strip('"').strip("'")
    return "utf-8"


def _normalize_codec(name: str) -> str:
    n = (name or "utf-8").strip().lower()
    if n in ("utf8",):
        return "utf-8"
    return n


def decode_bytes_payload(raw: bytes, charset: str) -> str:
    enc = _normalize_codec(charset)
    if not raw:
        return ""
    try:
        return raw.decode(enc)
    except (LookupError, UnicodeDecodeError):
        return raw.decode("utf-8", errors="replace")


def _main_mime(ct: str) -> str:
    return (ct or "").split(";", 1)[0].strip().lower()


def is_signaling_message_content(content_type_header: str, body_bytes: bytes) -> bool:
    """채팅 말풍선·스레드 미리보기에 넣지 않을 SIP MESSAGE 인지."""
    ct_l = (content_type_header or "").lower()
    for sub in _SIGNAL_CT_SUBSTR:
        if sub in ct_l:
            return True
    head = body_bytes.lstrip()[:512]
    try:
        probe = head.decode("utf-8", errors="ignore").lower()
    except Exception:
        probe = ""
    if probe.startswith("<?xml") and ("iscomposing" in probe or "im-iscomposing" in probe):
        return True
    if "<iscomposing" in probe or "im-iscomposing" in probe:
        return True
    return False


def parse_cpim_inner(body_bytes: bytes) -> tuple[str, str]:
    """message/CPIM: 내부 MIME 헤더 뒤 페이로드를 charset 에 맞게 디코드. (inner_text, inner_content_type)"""
    sep = b"\r\n\r\n"
    i = body_bytes.find(sep)
    if i < 0:
        sep = b"\n\n"
        i = body_bytes.find(sep)
    if i < 0:
        return body_bytes.decode("utf-8", errors="replace"), "text/plain; charset=utf-8"
    head_b, inner_b = body_bytes[:i], body_bytes[i + len(sep) :]
    head = head_b.decode("ascii", errors="replace")
    inner_ct = "text/plain; charset=utf-8"
    for line in head.splitlines():
        ls = line.strip()
        if ls.lower().startswith("content-type:"):
            inner_ct = ls.split(":", 1)[1].strip()
            break
    ich = charset_from_content_type(inner_ct)
    inner_text = decode_bytes_payload(inner_b, ich)
    return inner_text, inner_ct


def normalize_inbound_message_for_chat(
    body_bytes: bytes, content_type_header: str
) -> Tuple[str, str, bool]:
    """채팅 저장·표시용 본문과, 채팅 DB/WS 에 넣을지 여부.

    Returns:
        (chat_text, effective_content_type_for_log, persist_to_chat)
    """
    ct_raw = (content_type_header or "").strip()
    ct_l = ct_raw.lower()
    main = _main_mime(ct_raw)

    if is_signaling_message_content(ct_raw, body_bytes):
        return "", ct_raw, False

    if "message/cpim" in main or main.endswith("/cpim"):
        inner_text, inner_ct = parse_cpim_inner(body_bytes)
        if is_signaling_message_content(inner_ct, inner_text.encode("utf-8", errors="replace")):
            return "", ct_raw, False
        t = inner_text.strip()
        if not t:
            return "", inner_ct, False
        return t, inner_ct, True

    ch = charset_from_content_type(ct_raw)
    text = decode_bytes_payload(body_bytes, ch).strip()
    if not text:
        return "", ct_raw, False
    return text, ct_raw, True
