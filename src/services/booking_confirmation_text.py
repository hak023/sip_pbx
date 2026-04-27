"""예약 확정 문구 — 음성(TTS)·SIP MESSAGE(RCS) 동일 소스."""

from __future__ import annotations

import logging
from typing import Any, Mapping

logger = logging.getLogger(__name__)


def build_booking_confirmation_text(owner: str, booking: Mapping[str, Any]) -> str:
    """booking_settings.confirmation_msg 템플릿으로 확정 멘트 생성.

    Args:
        owner: 테넌트 ID
        booking: bookings 행 dict (booking_id, slot_date, slot_time, party_size 등)

    템플릿에 없는 플레이스홀더는 무시하고, 실패 시 기본 문장으로 폴백한다.
    """
    from src.services.booking_service import get_settings

    bid = str(booking.get("booking_id") or "").strip()
    if not bid:
        return "예약이 완료되었습니다."

    settings = get_settings(owner) or {}
    template = (settings.get("confirmation_msg") or "").strip() or (
        "예약이 완료되었습니다. 예약번호는 {booking_id}입니다."
    )

    slot_date = str(booking.get("slot_date") or "")
    slot_time = str(booking.get("slot_time") or "")
    try:
        party_size = int(booking.get("party_size") or 1)
    except (TypeError, ValueError):
        party_size = 1
    customer_name = str(booking.get("customer_name") or "")

    safe = {
        "booking_id": bid,
        "slot_date": slot_date,
        "slot_time": slot_time,
        "party_size": party_size,
        "customer_name": customer_name,
    }
    try:
        return template.format(**safe)
    except (KeyError, ValueError) as e:
        logger.warning(
            "booking_confirmation_template_format_failed",
            owner=owner,
            booking_id=bid,
            error=str(e),
        )
        return f"예약이 완료되었습니다. 예약번호는 {bid}입니다."
