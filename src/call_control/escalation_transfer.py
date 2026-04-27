"""AI 에스컬레이션 호전환 대상 내선 — 착신 규칙(call-control)과 SIP와 동일한 우선순위로 해석."""

from __future__ import annotations

import uuid
from typing import Any, Callable, Collection, Optional, Set, Tuple

import structlog

from src.call_control import db as cc_db
from src.call_control.forward_pick import parse_forward_extension, pick_group_destination
from src.call_control import routing_engine

logger = structlog.get_logger(__name__)


def _default_busy(_ext: str) -> bool:
    return False


def resolve_forward_to_extension(
    forward_to: Optional[str],
    rule_owner: str,
    registered_extensions: Optional[Collection[str]],
    is_extension_busy: Optional[Callable[[str], bool]] = None,
) -> Optional[str]:
    """forward_to(SIP URI·내선·fwd:uuid)를 전환용 내선 문자열로 해석. 등록 집합이 있으면 등록된 내선만."""
    if not forward_to or not str(forward_to).strip():
        return None
    s = str(forward_to).strip()
    reg: Optional[Set[str]] = None
    if registered_extensions is not None:
        reg = {str(x).strip() for x in registered_extensions if str(x).strip()}
    busy_fn = is_extension_busy or _default_busy

    if s.lower().startswith("fwd:"):
        ref_id = s[4:].strip()
        try:
            uuid.UUID(ref_id)
        except Exception:
            logger.warning("escalation_fwd_invalid_uuid", forward_preview=s[:80], rule_owner=rule_owner)
            return None
        try:
            row = cc_db.get_forward_target(ref_id)
        except Exception as e:
            logger.warning("escalation_fwd_db_error", ref_id=ref_id, error=str(e))
            return None
        if not row or (row.get("owner") or "") != rule_owner:
            logger.warning(
                "escalation_fwd_owner_mismatch",
                ref_id=ref_id,
                rule_owner=rule_owner,
                row_owner=(row or {}).get("owner"),
            )
            return None
        kind = str(row.get("kind") or "single").lower()
        if kind == "single":
            ext = (row.get("single_extension") or "").strip() or None
        else:
            members = row.get("members") or []
            ring_mode = str(row.get("ring_mode") or "simultaneous")
            ext = pick_group_destination(members, ring_mode, reg, busy_fn)
        if not ext:
            return None
        if reg is not None and ext not in reg:
            logger.warning("escalation_fwd_extension_not_registered", extension=ext, ref_id=ref_id)
            return None
        return ext

    ext = parse_forward_extension(forward_to)
    if not ext:
        return None
    if reg is not None and ext not in reg:
        logger.warning("escalation_forward_extension_not_registered", extension=ext, rule_owner=rule_owner)
        return None
    return ext


def _target_from_routing_dict(
    rule: dict,
    callee_owner: str,
    caller_username: Optional[str],
    registered_extensions: Optional[Collection[str]],
    is_extension_busy: Optional[Callable[[str], bool]],
) -> Tuple[Optional[str], str]:
    """단일 규칙 dict(일반 규칙 또는 발신자 필터)에서 에스컬레이션 SIP 내선 1개."""
    callee = (callee_owner or "").strip()
    if not callee:
        return None, "empty_callee_owner"

    action = str(rule.get("action") or "direct").lower()
    forward_to = rule.get("forward_to")
    busy_fn = is_extension_busy or _default_busy
    owner_busy = bool(busy_fn(callee)) if callee else False

    if action == "block":
        is_cf = bool(rule.get("pattern"))
        return None, "caller_filter_block" if is_cf else "routing_block"

    if action in ("immediate_ai",):
        return None, "immediate_ai_no_human_target"

    if action in ("no_answer_ai", "direct"):
        if registered_extensions is None or callee in registered_extensions:
            return callee, "ok_owner_line"
        return callee, "ok_owner_line_unverified_registration"

    if action == "busy_ai":
        # 통화중 AI 규칙이어도 사람 에스컬레이션은 착신 owner 내선으로 통일 (요구사항)
        if registered_extensions is None or callee in registered_extensions:
            return callee, "ok_busy_ai_owner"
        return callee, "ok_busy_ai_owner_unverified"

    if action in ("forward_always", "forward"):
        ext = resolve_forward_to_extension(
            forward_to, callee, registered_extensions, is_extension_busy
        )
        if ext:
            return ext, "ok_forward_always"
        return None, "forward_unresolved"

    if action == "forward_when_busy":
        if not owner_busy:
            return None, "forward_when_busy_not_busy"
        ext = resolve_forward_to_extension(
            forward_to, callee, registered_extensions, is_extension_busy
        )
        if ext:
            return ext, "ok_forward_when_busy"
        return None, "forward_when_busy_unresolved"

    if action == "ring_group":
        if registered_extensions is None or callee in registered_extensions:
            return callee, "ring_group_fallback_owner"
        return callee, "ring_group_fallback_owner_unverified"

    return None, f"unknown_action_{action}"


def resolve_escalation_transfer_extension(
    callee_owner: str,
    caller_username: Optional[str] = None,
    *,
    registered_extensions: Optional[Collection[str]] = None,
    is_extension_busy: Optional[Callable[[str], bool]] = None,
) -> Tuple[Optional[str], str]:
    """
    Returns:
        (extension_or_none, reason_code) — reason는 로그·디버깅용.
    """
    callee = (callee_owner or "").strip()
    caller = (caller_username or "").strip() or None

    if callee and caller:
        cf = routing_engine.resolve_caller_filter(callee, caller)
        if cf:
            return _target_from_routing_dict(cf, callee, caller, registered_extensions, is_extension_busy)

    res = routing_engine.resolve_rule(callee)
    if not res:
        if registered_extensions is None or callee in registered_extensions:
            return callee, "no_rule_fallback_owner"
        return callee, "no_rule_fallback_owner_unverified"

    rule = res["rule"]
    return _target_from_routing_dict(rule, callee, caller, registered_extensions, is_extension_busy)


def build_escalation_sip_context() -> tuple[Optional[Collection[str]], Optional[Callable[[str], bool]]]:
    """전역 SIPEndpoint가 있으면 등록 내선 집합·busy 콜백을 반환."""
    try:
        from src.sip_core.sip_runtime import get_sip_endpoint_global

        ep = get_sip_endpoint_global()
        if not ep:
            return None, None
        reg = getattr(ep, "_registered_users", None) or {}
        keys = frozenset(str(k).strip() for k in reg.keys() if str(k).strip())

        def _busy(ext: str) -> bool:
            try:
                return bool(ep._extension_has_active_call(ext))  # type: ignore[attr-defined]
            except Exception:
                return False

        return keys, _busy
    except Exception as e:
        logger.debug("escalation_sip_context_unavailable", error=str(e))
        return None, None
