"""예약 관련 SIP MESSAGE(문서상 RCS) — 생성·취소·변경·일정변경 알림."""

from __future__ import annotations

import json
import logging
import os
import sqlite3
from datetime import datetime
from typing import Any, Dict, Literal, Mapping, Optional

logger = logging.getLogger(__name__)

NotifyEvent = Literal["create", "cancel", "reschedule", "update"]


def _settings_extra_dict(settings: Optional[Mapping[str, Any]]) -> dict:
    if not settings:
        return {}
    raw = settings.get("extra_config")
    if isinstance(raw, str):
        try:
            return json.loads(raw) if raw.strip() else {}
        except (json.JSONDecodeError, TypeError):
            return {}
    if isinstance(raw, dict):
        return raw
    return {}


def _notify_channel(extra: dict) -> str:
    """``extra_config.notify_channel``: ``sip_message``(기본) | ``chat_api``."""
    raw = (extra.get("notify_channel") or "sip_message").strip().lower()
    if raw in ("chat", "chat_api", "sip_message", "sip"):
        if raw in ("chat", "chat_api"):
            return "chat_api"
        return "sip_message"
    return "sip_message"


def _deliver_booking_text(
    owner: str,
    to_phone: str,
    body: str,
    *,
    channel: str,
) -> Dict[str, Any]:
    """SIP 직접 또는 채팅 릴레이(SIP MESSAGE)로 본문 전송."""
    to_phone = (to_phone or "").strip()
    owner = (owner or "").strip()
    if not to_phone or not body.strip():
        return {"success": False, "message": "missing_to_or_body"}

    if channel == "chat_api":
        try:
            from src.services.chat_relay_service import resolve_sip_from_for_outbound
            from src.services.chat_sip_delivery import deliver_chat_sip_message

            sip_from = resolve_sip_from_for_outbound(owner) or owner or "pbx"
            return deliver_chat_sip_message(sip_from, to_phone, body, suppress_ai_loop=True)
        except Exception as e:
            logger.warning("booking_notify_chat_api_failed", error=str(e))
            return {"success": False, "message": str(e)}

    from_phone = owner or "ai-booking"
    sip_ip = os.environ.get("SIP_SERVER_IP", "127.0.0.1")
    sip_port = int(os.environ.get("SIP_SERVER_PORT", "5060"))
    from src.services.sip_sms_service import send_sip_sms_sync

    return send_sip_sms_sync(
        to_phone=to_phone,
        message=body,
        from_phone=from_phone,
        sip_server_ip=sip_ip,
        sip_server_port=sip_port,
    )


def _ensure_confirmation_table(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS booking_confirmation_sms (
            booking_id TEXT PRIMARY KEY,
            sent_at TEXT NOT NULL,
            status TEXT NOT NULL,
            error TEXT NOT NULL DEFAULT ''
        )
        """
    )


def _confirmation_sent_success(conn: sqlite3.Connection, booking_id: str) -> bool:
    _ensure_confirmation_table(conn)
    row = conn.execute(
        "SELECT status FROM booking_confirmation_sms WHERE booking_id = ?",
        (booking_id,),
    ).fetchone()
    return bool(row and (row["status"] or "").lower() == "sent")


def _clear_confirmation_if_not_sent(conn: sqlite3.Connection, booking_id: str) -> None:
    """성공이 아닌 행만 제거해 동일 예약에 대한 재시도 허용."""
    _ensure_confirmation_table(conn)
    conn.execute(
        "DELETE FROM booking_confirmation_sms WHERE booking_id = ? AND lower(status) != 'sent'",
        (booking_id,),
    )


def _record_confirmation(conn: sqlite3.Connection, booking_id: str, ok: bool, err: str) -> None:
    _ensure_confirmation_table(conn)
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    conn.execute(
        """
        INSERT OR REPLACE INTO booking_confirmation_sms (booking_id, sent_at, status, error)
        VALUES (?, ?, ?, ?)
        """,
        (booking_id, now, "sent" if ok else "failed", "" if ok else (err or "")[:200]),
    )


def _lifecycle_enabled(extra: dict, event: NotifyEvent) -> bool:
    if event == "create" and extra.get("notify_on_create_sms") is False:
        return False
    if event == "cancel" and extra.get("notify_on_cancel_sms") is False:
        return False
    if event == "reschedule" and extra.get("notify_on_reschedule_sms") is False:
        return False
    # 인원/메모 등 수정 문자는 기본 끔 — ``notify_on_update_sms``: true 일 때만 발송
    if event == "update" and extra.get("notify_on_update_sms") is not True:
        return False
    return True


def _build_lifecycle_body(
    event: NotifyEvent,
    booking: Mapping[str, Any],
    *,
    old_slot_date: str = "",
    old_slot_time: str = "",
) -> str:
    bid = str(booking.get("booking_id") or "").strip()
    d = str(booking.get("slot_date") or "")
    t = str(booking.get("slot_time") or "")
    name = str(booking.get("customer_name") or "").strip()
    party = booking.get("party_size", "")
    if event == "cancel":
        return (
            f"예약이 취소되었습니다. 예약번호 {bid}, 일시 {d} {t}."
            + (f" 예약자 {name}님." if name else "")
        ).strip()
    if event == "reschedule":
        old = f"{old_slot_date} {old_slot_time}".strip()
        if old:
            return f"예약 일정이 변경되었습니다. 예약번호 {bid}. {old} → {d} {t}."
        return f"예약 일정이 변경되었습니다. 예약번호 {bid}. 새 일시: {d} {t}."
    if event == "update":
        return (
            f"예약 정보가 갱신되었습니다. 예약번호 {bid}, 일시 {d} {t}"
            f"{', 인원 ' + str(party) + '명' if party != '' else ''}."
        ).strip()
    return ""


def notify_booking_lifecycle_sms(
    owner: str,
    booking: Mapping[str, Any],
    event: NotifyEvent,
    *,
    call_id: str = "",
    old_slot_date: str = "",
    old_slot_time: str = "",
) -> None:
    """취소·일정변경·(인원/메모 등) 수정 시 알림. 실패해도 DB 트랜잭션은 이미 커밋된 상태."""
    if event == "create":
        return
    try:
        from src.services.booking_service import get_settings

        settings = get_settings(owner) or {}
        extra = _settings_extra_dict(settings)
        if not _lifecycle_enabled(extra, event):
            logger.debug("booking_lifecycle_sms_skipped_disabled", event=event, owner=owner)
            return

        to_phone = str(booking.get("customer_phone") or "").strip()
        if not to_phone:
            logger.debug("booking_lifecycle_sms_skip_no_phone", event=event)
            return

        body = _build_lifecycle_body(
            event, booking, old_slot_date=old_slot_date, old_slot_time=old_slot_time
        )
        if len(body) > 500:
            body = body[:497] + "..."

        channel = _notify_channel(extra)
        result = _deliver_booking_text(owner, to_phone, body, channel=channel)
        ok = bool(result.get("success"))

        logger.info(
            "booking_lifecycle_sms_done",
            event=event,
            owner=owner,
            booking_id=booking.get("booking_id"),
            sent=ok,
            channel=channel,
            call_id=(call_id or "")[:24],
        )

        try:
            from src.services.chat_service import save_chat_message
            from src.services.chat_relay_service import resolve_sip_from_for_outbound

            from_ph = resolve_sip_from_for_outbound(owner) if channel == "chat_api" else (owner or "ai-booking")
            save_chat_message(
                thread_id=to_phone,
                owner=owner or "pbx",
                direction="outbound",
                from_phone=from_ph,
                to_phone=to_phone,
                body=body,
                call_id=call_id or str(booking.get("call_id") or ""),
                status="sent" if ok else "failed",
                error_code="" if ok else f"booking_{event}_sms",
            )
        except Exception as chat_err:
            logger.debug("booking_lifecycle_chat_log_skipped", error=str(chat_err))
    except Exception as e:
        logger.warning(
            "booking_lifecycle_sms_exception",
            event=event,
            owner=owner,
            error=str(e),
        )


def notify_booking_created_sms(
    owner: str,
    booking: Mapping[str, Any],
    *,
    call_id: str = "",
) -> Dict[str, Any]:
    """예약 생성 직후 확인 문자 발송. **성공(sent)인 경우만** 동일 booking_id 재발송 차단."""
    out: Dict[str, Any] = {"confirmation_sms_sent": False, "confirmation_sms_error": None}

    booking_id = str(booking.get("booking_id") or "").strip()
    to_phone = str(booking.get("customer_phone") or "").strip()
    if not booking_id:
        out["confirmation_sms_error"] = "no_booking_id"
        return out
    if not to_phone:
        out["confirmation_sms_error"] = "no_customer_phone"
        return out

    try:
        from src.services.booking_service import get_settings
        from src.services.booking_confirmation_text import build_booking_confirmation_text
        from src.booking.database import get_connection

        settings = get_settings(owner) or {}
        extra = _settings_extra_dict(settings)
        if not _lifecycle_enabled(extra, "create"):
            out["confirmation_sms_error"] = "disabled_by_settings"
            return out

        conn = get_connection()
        try:
            if _confirmation_sent_success(conn, booking_id):
                out["confirmation_sms_error"] = "already_sent"
                return out
            _clear_confirmation_if_not_sent(conn, booking_id)
            conn.commit()
        finally:
            conn.close()

        body = build_booking_confirmation_text(owner, booking)
        if len(body) > 500:
            body = body[:497] + "..."

        channel = _notify_channel(extra)
        result = _deliver_booking_text(owner, to_phone, body, channel=channel)
        ok = bool(result.get("success"))

        conn2 = get_connection()
        try:
            _record_confirmation(conn2, booking_id, ok, str(result.get("message") or ""))
            conn2.commit()
        finally:
            conn2.close()

        out["confirmation_sms_sent"] = ok
        if not ok:
            out["confirmation_sms_error"] = str(result.get("message") or "send_failed")[:200]

        logger.info(
            "booking_confirmation_sms_done",
            booking_id=booking_id,
            owner=owner,
            sent=ok,
            channel=channel,
            call_id=(call_id or "")[:24],
            body_len=len(body),
        )
        try:
            from src.services.chat_service import save_chat_message
            from src.services.chat_relay_service import resolve_sip_from_for_outbound

            from_ph = resolve_sip_from_for_outbound(owner) if channel == "chat_api" else (owner or "ai-booking")
            save_chat_message(
                thread_id=to_phone,
                owner=owner or "pbx",
                direction="outbound",
                from_phone=from_ph,
                to_phone=to_phone,
                body=body,
                call_id=call_id or "",
                status="sent" if ok else "failed",
                error_code="" if ok else "booking_confirmation_sms",
            )
        except Exception as chat_err:
            logger.debug("booking_confirmation_chat_log_skipped", error=str(chat_err))

    except Exception as e:
        out["confirmation_sms_error"] = str(e)[:200]
        logger.warning(
            "booking_confirmation_sms_exception",
            booking_id=booking_id,
            owner=owner,
            error=str(e),
        )
    return out
