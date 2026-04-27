"""프로세스 내 단일 SIPEndpoint 참조 (에스컬레이션 등 비-SIP 모듈에서 등록/조회용)."""

from __future__ import annotations

from typing import Any, Optional

_sip_endpoint: Optional[Any] = None


def set_sip_endpoint_global(endpoint: Optional[Any]) -> None:
    global _sip_endpoint
    _sip_endpoint = endpoint


def get_sip_endpoint_global() -> Optional[Any]:
    return _sip_endpoint
