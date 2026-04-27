"""
착신 전환 참조 `fwd:<uuid>` → 등록된 내선 1개.

SIP 착신 라우팅(`_call_control_resolve_forward_target`)과
AI 호전환 INVITE(`send_transfer_invite`)에서 동일 알고리즘을 쓰기 위한 공유 모듈.
"""

from __future__ import annotations

import uuid
from typing import Callable, Collection, Optional

import structlog

from src.call_control.forward_pick import pick_group_destination

logger = structlog.get_logger(__name__)


def resolve_fwd_ref_to_registered_extension(
    forward_to: str,
    *,
    rule_owner: str,
    registered_extensions: Collection[str],
    is_extension_busy: Optional[Callable[[str], bool]] = None,
) -> Optional[str]:
    """
    `forward_to`가 `fwd:<uuid>`일 때 DB에서 대상을 읽고 단일/그룹 규칙에 따라
    등록·유휴 우선으로 내선 1개를 반환한다.

    - `fwd:`가 아니면 None.
    - owner 불일치·미등록·DB 오류 시 None.
    """
    if not forward_to or not str(forward_to).strip():
        return None
    s = str(forward_to).strip()
    if not s.lower().startswith("fwd:"):
        return None
    ref_id = s[4:].strip()
    try:
        uuid.UUID(ref_id)
    except Exception:
        logger.warning(
            "forward_resolve_invalid_uuid",
            forward_preview=s[:64],
            rule_owner=rule_owner,
        )
        return None
    try:
        from src.call_control import db as _cc_db

        row = _cc_db.get_forward_target(ref_id)
    except Exception as e:
        logger.warning(
            "forward_resolve_db_error",
            ref_id=ref_id,
            error=str(e),
        )
        return None
    if not row or (row.get("owner") or "") != rule_owner:
        logger.warning(
            "forward_resolve_owner_mismatch",
            ref_id=ref_id,
            rule_owner=rule_owner,
            row_owner=(row or {}).get("owner"),
        )
        return None
    kind = str(row.get("kind") or "single").lower()
    ext: Optional[str] = None
    if kind == "single":
        ext = (row.get("single_extension") or "").strip() or None
    else:
        members = row.get("members") or []
        ring_mode = str(row.get("ring_mode") or "simultaneous")
        ext = pick_group_destination(
            members,
            ring_mode,
            registered_extensions=registered_extensions,
            is_extension_busy=is_extension_busy,
        )
        logger.info(
            "forward_resolve_group_pick",
            ref_id=ref_id,
            ring_mode=ring_mode,
            picked=ext,
            member_count=len(members) if isinstance(members, list) else 0,
        )
    if not ext:
        logger.warning(
            "forward_resolve_empty_target",
            ref_id=ref_id,
            kind=kind,
        )
        return None
    reg = {str(x).strip() for x in registered_extensions if str(x).strip()}
    if ext not in reg:
        logger.warning(
            "forward_resolve_extension_not_registered",
            ref_id=ref_id,
            extension=ext,
        )
        return None
    return ext
