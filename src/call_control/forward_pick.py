"""착신 전환 그룹에서 내선 1개 선택 (SIP 엔드포인트와 동일 알고리즘, 순수 함수)."""

from __future__ import annotations

from typing import Any, Callable, Collection, Optional, Set


def parse_forward_extension(forward_to: Optional[str]) -> Optional[str]:
    """call-control `forward_to` 값을 등록 조회용 내선/사용자명으로 파싱."""
    if not forward_to or not str(forward_to).strip():
        return None
    s = str(forward_to).strip()
    if s.lower().startswith("sip:"):
        rest = s[4:]
        user_part = rest.split("@", 1)[0]
        if ";" in user_part:
            user_part = user_part.split(";", 1)[0]
        user_part = user_part.strip().strip("<>")
        return user_part.split(":")[-1] if user_part else None
    return s.split("@", 1)[0].strip() or None


def pick_group_destination(
    members: Any,
    ring_mode: str,
    registered_extensions: Optional[Collection[str]] = None,
    is_extension_busy: Optional[Callable[[str], bool]] = None,
) -> Optional[str]:
    """그룹 멤버 중 1명 선택. 등록 집합이 있으면 «유휴·등록 우선 → 등록»."""
    exts = [str(m).strip() for m in (members or []) if str(m).strip()]
    if not exts:
        return None
    _ = (ring_mode or "simultaneous").lower()
    reg: Optional[Set[str]] = None
    if registered_extensions is not None:
        reg = {str(x).strip() for x in registered_extensions if str(x).strip()}

    def _busy(ext: str) -> bool:
        if is_extension_busy is None:
            return False
        try:
            return bool(is_extension_busy(ext))
        except Exception:
            return False

    if reg is not None:
        for ext in exts:
            if ext in reg and not _busy(ext):
                return ext
        for ext in exts:
            if ext in reg:
                return ext
        return None
    for ext in exts:
        if not _busy(ext):
            return ext
    return exts[0] if exts else None
