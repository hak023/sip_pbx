"""
예약 시스템 서비스 레이어.

비즈니스 로직 처리:
- 슬롯 CRUD
- 예약 생성/조회/수정/취소 (낙관적 잠금 via SQLite 트랜잭션)
- 도메인 설정 관리
- 스키마 필드 관리
"""

from __future__ import annotations

import json
import uuid
from datetime import date, datetime, timedelta
from typing import Any, Dict, List, Optional, Tuple

import structlog

from src.booking.database import get_db, row_to_dict
from src.booking.models import (
    BookingCreate,
    BookingDomainCreate,
    BookingDomainUpdate,
    BookingSettingsCreate,
    BookingSettingsUpdate,
    BookingSlotCreate,
    BookingSlotUpdate,
    BookingUpdate,
    BulkSlotCreateRequest,
    BulkSlotCreateResult,
    SchemaFieldCreate,
    SchemaFieldUpdate,
)

logger = structlog.get_logger(__name__)


def _now_str() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _new_id(prefix: str = "") -> str:
    return f"{prefix}{uuid.uuid4().hex[:12]}"


# ──────────────────────────────────────────
# booking_settings
# ──────────────────────────────────────────

def get_settings(owner: str) -> Optional[Dict[str, Any]]:
    with get_db() as conn:
        row = conn.execute(
            "SELECT * FROM booking_settings WHERE owner = ?", (owner,)
        ).fetchone()
    return row_to_dict(row)


def upsert_settings(owner: str, data: BookingSettingsCreate | BookingSettingsUpdate) -> Dict[str, Any]:
    now = _now_str()
    extra = json.dumps(data.extra_config, ensure_ascii=False)
    with get_db() as conn:
        conn.execute(
            """
            INSERT INTO booking_settings
                (owner, domain_type, service_name, slot_duration_min, max_party_size,
                 require_phone, require_name, slot_label, confirmation_msg, extra_config, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(owner) DO UPDATE SET
                domain_type       = excluded.domain_type,
                service_name      = excluded.service_name,
                slot_duration_min = excluded.slot_duration_min,
                max_party_size    = excluded.max_party_size,
                require_phone     = excluded.require_phone,
                require_name      = excluded.require_name,
                slot_label        = excluded.slot_label,
                confirmation_msg  = excluded.confirmation_msg,
                extra_config      = excluded.extra_config,
                updated_at        = excluded.updated_at
            """,
            (
                owner,
                data.domain_type,
                data.service_name,
                data.slot_duration_min,
                data.max_party_size,
                int(data.require_phone),
                int(data.require_name),
                data.slot_label,
                data.confirmation_msg,
                extra,
                now,
            ),
        )
        row = conn.execute(
            "SELECT * FROM booking_settings WHERE owner = ?", (owner,)
        ).fetchone()
    return row_to_dict(row)


# ──────────────────────────────────────────
# booking_slots
# ──────────────────────────────────────────

def list_slots(
    owner: str,
    slot_date: Optional[str] = None,
    slot_month: Optional[str] = None,
    include_full: bool = True,
    include_blocked: bool = False,
) -> List[Dict[str, Any]]:
    sql = "SELECT * FROM booking_slots WHERE owner = ?"
    params: list = [owner]
    if slot_date:
        sql += " AND slot_date = ?"
        params.append(slot_date)
    elif slot_month:
        sql += " AND slot_date LIKE ?"
        params.append(f"{slot_month}-%")
    if not include_blocked:
        sql += " AND is_blocked = 0"
    if not include_full:
        sql += " AND booked_count < capacity"
    sql += " ORDER BY slot_date ASC, slot_time ASC"
    with get_db() as conn:
        rows = conn.execute(sql, params).fetchall()
    items = [row_to_dict(r) for r in rows]
    for item in items:
        item["available"] = max(0, item["capacity"] - item["booked_count"])
    return items


def _parse_hhmm(hhmm: str) -> Tuple[int, int]:
    """'HH:MM' 문자열 → (hour, minute) 튜플."""
    parts = hhmm.split(":")
    return int(parts[0]), int(parts[1])


def _minutes_from_midnight(hhmm: str) -> int:
    h, m = _parse_hhmm(hhmm)
    return h * 60 + m


def _minutes_to_hhmm(total_minutes: int) -> str:
    h = total_minutes // 60
    m = total_minutes % 60
    return f"{h:02d}:{m:02d}"


def _is_in_exclude_window(slot_start_min: int, slot_end_min: int, windows: list) -> bool:
    """슬롯이 제외 시간대와 겹치는지 확인 (반열린 구간 비교)."""
    for w in windows:
        ex_start = _minutes_from_midnight(w.start)
        ex_end = _minutes_from_midnight(w.end)
        # 겹침 조건: slot_start < ex_end AND slot_end > ex_start
        if slot_start_min < ex_end and slot_end_min > ex_start:
            return True
    return False


def bulk_create_slots(owner: str, req: BulkSlotCreateRequest) -> BulkSlotCreateResult:
    """
    기간·요일·업무시간·제외시간대를 기반으로 슬롯을 일괄 생성한다.

    알고리즘:
      1. date_from ~ date_to 날짜를 순회하며 weekdays 필터 적용
      2. 각 날짜에서 work_start ~ work_end 범위를 slot_interval_min 간격으로 분할
      3. 각 슬롯이 exclude_windows 와 겹치면 건너뜀
      4. 중복(UNIQUE 위반) 슬롯은 skip_existing 설정에 따라 처리
    """
    from_date = date.fromisoformat(req.date_from)
    to_date = date.fromisoformat(req.date_to)

    work_start_min = _minutes_from_midnight(req.work_start)
    work_end_min = _minutes_from_midnight(req.work_end)
    interval_min = req.slot_interval_min if req.slot_interval_min > 0 else req.slot_duration_min

    created = 0
    skipped = 0
    preview: List[str] = []

    now = _now_str()
    current = from_date

    with get_db() as conn:
        while current <= to_date:
            # weekday(): 0=월, 6=일
            if current.weekday() in req.weekdays:
                cursor_min = work_start_min
                while cursor_min + req.slot_duration_min <= work_end_min:
                    slot_end_min = cursor_min + req.slot_duration_min

                    if not _is_in_exclude_window(cursor_min, slot_end_min, req.exclude_windows):
                        slot_date_str = current.isoformat()
                        slot_time_str = _minutes_to_hhmm(cursor_min)
                        slot_id = _new_id("sl_")
                        try:
                            conn.execute(
                                """
                                INSERT INTO booking_slots
                                    (slot_id, owner, slot_date, slot_time, capacity,
                                     label, domain_id, is_blocked, created_at, updated_at)
                                VALUES (?, ?, ?, ?, ?, ?, ?, 0, ?, ?)
                                """,
                                (
                                    slot_id, owner, slot_date_str, slot_time_str,
                                    req.capacity, req.label, req.domain_id, now, now,
                                ),
                            )
                            created += 1
                            if len(preview) < 50:
                                preview.append(f"{slot_date_str} {slot_time_str}")
                        except Exception as e:
                            if "UNIQUE" in str(e):
                                if req.skip_existing:
                                    skipped += 1
                                else:
                                    raise
                            else:
                                raise
                    cursor_min += interval_min
            current += timedelta(days=1)

    total_generated = created + skipped
    logger.info(
        "bulk_slots_created",
        owner=owner,
        created=created,
        skipped=skipped,
        date_from=req.date_from,
        date_to=req.date_to,
    )
    return BulkSlotCreateResult(
        created=created,
        skipped=skipped,
        total_generated=total_generated,
        preview=preview,
    )


def get_slot(slot_id: str) -> Optional[Dict[str, Any]]:
    with get_db() as conn:
        row = conn.execute(
            "SELECT * FROM booking_slots WHERE slot_id = ?", (slot_id,)
        ).fetchone()
    if not row:
        return None
    item = row_to_dict(row)
    item["available"] = max(0, item["capacity"] - item["booked_count"])
    return item


def create_slot(owner: str, data: BookingSlotCreate) -> Dict[str, Any]:
    slot_id = _new_id("sl_")
    now = _now_str()
    with get_db() as conn:
        conn.execute(
            """
            INSERT INTO booking_slots
                (slot_id, owner, slot_date, slot_time, capacity, label, domain_id, is_blocked, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                slot_id, owner, data.slot_date, data.slot_time,
                data.capacity, data.label, data.domain_id, int(data.is_blocked), now, now,
            ),
        )
        row = conn.execute(
            "SELECT * FROM booking_slots WHERE slot_id = ?", (slot_id,)
        ).fetchone()
    item = row_to_dict(row)
    item["available"] = max(0, item["capacity"] - item["booked_count"])
    logger.info("booking_slot_created", slot_id=slot_id, owner=owner,
                date=data.slot_date, time=data.slot_time)
    return item


def update_slot(slot_id: str, data: BookingSlotUpdate) -> Optional[Dict[str, Any]]:
    sets, params = [], []
    if data.capacity is not None:
        sets.append("capacity = ?"); params.append(data.capacity)
    if data.label is not None:
        sets.append("label = ?"); params.append(data.label)
    if data.domain_id is not None:
        sets.append("domain_id = ?"); params.append(data.domain_id)
    if data.is_blocked is not None:
        sets.append("is_blocked = ?"); params.append(int(data.is_blocked))
    if not sets:
        return get_slot(slot_id)
    sets.append("updated_at = ?"); params.append(_now_str())
    params.append(slot_id)
    with get_db() as conn:
        conn.execute(
            f"UPDATE booking_slots SET {', '.join(sets)} WHERE slot_id = ?", params
        )
        row = conn.execute(
            "SELECT * FROM booking_slots WHERE slot_id = ?", (slot_id,)
        ).fetchone()
    if not row:
        return None
    item = row_to_dict(row)
    item["available"] = max(0, item["capacity"] - item["booked_count"])
    return item


def delete_slot(slot_id: str) -> bool:
    with get_db() as conn:
        cur = conn.execute(
            "DELETE FROM booking_slots WHERE slot_id = ?", (slot_id,)
        )
    return cur.rowcount > 0


# ──────────────────────────────────────────
# bookings
# ──────────────────────────────────────────

def list_bookings(
    owner: str,
    slot_date: Optional[str] = None,
    slot_month: Optional[str] = None,
    status: Optional[str] = None,
    customer_phone: Optional[str] = None,
    limit: int = 100,
    offset: int = 0,
) -> Dict[str, Any]:
    sql = "SELECT * FROM bookings WHERE owner = ?"
    count_sql = "SELECT COUNT(*) as cnt FROM bookings WHERE owner = ?"
    params: list = [owner]
    filters = ""
    if slot_date:
        filters += " AND slot_date = ?"
        params.append(slot_date)
    elif slot_month:
        # YYYY-MM 형식 → 해당 월 전체 조회 (slot_date LIKE 'YYYY-MM-%')
        filters += " AND slot_date LIKE ?"
        params.append(f"{slot_month}-%")
    if status:
        filters += " AND status = ?"
        params.append(status)
    if customer_phone:
        filters += " AND customer_phone = ?"
        params.append(customer_phone)
    sql += filters + " ORDER BY slot_date ASC, slot_time ASC LIMIT ? OFFSET ?"
    count_sql += filters
    with get_db() as conn:
        total = conn.execute(count_sql, params).fetchone()["cnt"]
        rows = conn.execute(sql, params + [limit, offset]).fetchall()
    items = [row_to_dict(r) for r in rows]
    return {"total": total, "items": items}


def get_booking(booking_id: str) -> Optional[Dict[str, Any]]:
    with get_db() as conn:
        row = conn.execute(
            "SELECT * FROM bookings WHERE booking_id = ?", (booking_id,)
        ).fetchone()
    return row_to_dict(row)


def create_booking(owner: str, data: BookingCreate) -> Dict[str, Any]:
    """
    예약 생성 (낙관적 잠금):
    1. slot_id 확정: 주어졌으면 직접 사용, 없으면 date+time으로 조회
    2. 동일 전화·동일 슬롯(또는 동일 일시) confirmed 예약이 이미 있으면 INSERT 없이 기존 row 반환(멱등)
    3. booked_count < capacity 확인 후 UPDATE booking_slots.booked_count + INSERT bookings
    모두 같은 트랜잭션 내 처리 → SQLite 단일 파일 잠금으로 동시성 보장
    """
    booking_id = _new_id("bk_")
    now = _now_str()
    extra = json.dumps(data.extra_data, ensure_ascii=False)

    conn = None
    try:
        import sqlite3
        from src.booking.database import get_connection
        conn = get_connection()
        conn.execute("BEGIN IMMEDIATE")

        slot_id = data.slot_id
        slot_row = None
        if slot_id:
            slot_row = conn.execute(
                "SELECT * FROM booking_slots WHERE slot_id = ? AND owner = ?",
                (slot_id, owner),
            ).fetchone()
        if not slot_row:
            slot_row = conn.execute(
                """SELECT * FROM booking_slots
                   WHERE owner = ? AND slot_date = ? AND slot_time = ? AND is_blocked = 0""",
                (owner, data.slot_date, data.slot_time),
            ).fetchone()

        if slot_row:
            slot_id = slot_row["slot_id"]
        else:
            slot_id = None

        # 동일 고객·동일 슬롯(또는 동일 일시) 중복은 **슬롯 증가 전**에 검사 — LLM 재호출 시 슬롯 이중 증가 방지
        if data.customer_phone:
            dup_check_params: tuple
            dup_sql: str
            if slot_id:
                dup_sql = (
                    "SELECT booking_id FROM bookings "
                    "WHERE owner = ? AND customer_phone = ? AND slot_id = ? "
                    "AND status = 'confirmed'"
                )
                dup_check_params = (owner, data.customer_phone, slot_id)
            else:
                dup_sql = (
                    "SELECT booking_id FROM bookings "
                    "WHERE owner = ? AND customer_phone = ? "
                    "AND slot_date = ? AND slot_time = ? AND status = 'confirmed'"
                )
                dup_check_params = (owner, data.customer_phone, data.slot_date, data.slot_time)
            dup_row = conn.execute(dup_sql, dup_check_params).fetchone()
            if dup_row:
                dup_id = dup_row["booking_id"]
                logger.warning(
                    "create_booking_idempotent_hit",
                    owner=owner,
                    customer_phone=data.customer_phone,
                    slot_date=data.slot_date,
                    slot_time=data.slot_time,
                    existing_booking_id=dup_id,
                    note="동일 전화·슬롯(또는 일시) confirmed 예약 존재 — INSERT 생략·기존 row 반환",
                )
                conn.rollback()
                conn.close()
                conn = None
                existing = get_booking(dup_id)
                if not existing:
                    raise ValueError(
                        f"동일 날짜·시간({data.slot_date} {data.slot_time})에 이미 예약이 있으나 "
                        f"조회에 실패했습니다. 기존 예약번호: {dup_id}"
                    )
                out = dict(existing)
                out.setdefault("confirmation_sms_sent", False)
                out["idempotent_repeat"] = True
                return out

        if slot_row:
            if slot_row["booked_count"] >= slot_row["capacity"]:
                raise ValueError(f"슬롯 정원 초과 (slot_id={slot_id})")
            conn.execute(
                "UPDATE booking_slots SET booked_count = booked_count + 1, updated_at = ? WHERE slot_id = ?",
                (now, slot_id),
            )

        conn.execute(
            """
            INSERT INTO bookings
                (booking_id, owner, slot_id, slot_date, slot_time,
                 customer_name, customer_phone, party_size, service_type,
                 status, extra_data, call_id, memo, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'confirmed', ?, ?, ?, ?, ?)
            """,
            (
                booking_id, owner, slot_id, data.slot_date, data.slot_time,
                data.customer_name, data.customer_phone, data.party_size,
                data.service_type, extra, data.call_id, data.memo, now, now,
            ),
        )
        conn.commit()
        row = conn.execute(
            "SELECT * FROM bookings WHERE booking_id = ?", (booking_id,)
        ).fetchone()
        result = row_to_dict(row)
        logger.info("booking_created", booking_id=booking_id, owner=owner,
                    slot_id=slot_id, date=data.slot_date, time=data.slot_time)
        # ── Google Calendar 동기화 훅 (실패해도 예약 생성에 영향 없음) ──
        try:
            from src.services import gcal_service
            gcal_event_id = gcal_service.create_event(owner, result)
            if gcal_event_id:
                gcal_service.save_gcal_map(booking_id, gcal_event_id, owner)
        except Exception as _gcal_err:
            logger.warning("gcal_create_event_hook_failed", booking_id=booking_id, error=str(_gcal_err))
        # SIP MESSAGE(RCS) 예약 확인 문자 — 실패해도 예약 응답은 유지
        try:
            from src.services.booking_notify import notify_booking_created_sms

            sms_meta = notify_booking_created_sms(owner, result, call_id=data.call_id or "")
            result = {**result, **sms_meta}
        except Exception as _sms_err:
            logger.warning(
                "booking_create_confirmation_sms_hook_failed",
                booking_id=booking_id,
                error=str(_sms_err),
            )
            result = {
                **result,
                "confirmation_sms_sent": False,
                "confirmation_sms_error": "notify_exception",
            }
        return result
    except Exception:
        if conn:
            conn.rollback()
        raise
    finally:
        if conn:
            conn.close()


def update_booking(booking_id: str, data: BookingUpdate) -> Optional[Dict[str, Any]]:
    """예약 정보 수정 (인원·메모·이름·전화번호 등). 날짜·시간 변경은 reschedule_booking 사용 권장.

    party_size 변경 시 슬롯 capacity 검증을 수행합니다.
    capacity를 초과하는 인원으로 변경하면 ValueError를 발생시킵니다.
    """
    sets, params = [], []
    if data.slot_date is not None:
        sets.append("slot_date = ?"); params.append(data.slot_date)
    if data.slot_time is not None:
        sets.append("slot_time = ?"); params.append(data.slot_time)
    if data.customer_name is not None:
        sets.append("customer_name = ?"); params.append(data.customer_name)
    if data.customer_phone is not None:
        sets.append("customer_phone = ?"); params.append(data.customer_phone)
    if data.party_size is not None:
        sets.append("party_size = ?"); params.append(data.party_size)
    if data.service_type is not None:
        sets.append("service_type = ?"); params.append(data.service_type)
    if data.extra_data is not None:
        sets.append("extra_data = ?"); params.append(json.dumps(data.extra_data, ensure_ascii=False))
    if data.memo is not None:
        sets.append("memo = ?"); params.append(data.memo)
    if data.status is not None:
        sets.append("status = ?"); params.append(data.status)
    if not sets:
        return get_booking(booking_id)
    sets.append("updated_at = ?"); params.append(_now_str())
    params.append(booking_id)

    with get_db() as conn:
        # party_size 변경 시 슬롯 용량 검증
        if data.party_size is not None:
            booking_row = conn.execute(
                "SELECT slot_id, party_size FROM bookings WHERE booking_id = ?", (booking_id,)
            ).fetchone()
            if booking_row and booking_row["slot_id"]:
                slot_row = conn.execute(
                    "SELECT capacity, booked_count FROM booking_slots WHERE slot_id = ?",
                    (booking_row["slot_id"],),
                ).fetchone()
                if slot_row:
                    old_party = booking_row["party_size"] or 1
                    capacity = slot_row["capacity"] or 1
                    booked = slot_row["booked_count"] or 0
                    # 현재 예약의 기존 인원을 제외한 나머지 사용량 + 새 인원
                    available_after = capacity - (booked - old_party)
                    if data.party_size > available_after:
                        logger.warning(
                            "update_booking_capacity_exceeded",
                            booking_id=booking_id,
                            slot_id=booking_row["slot_id"],
                            requested=data.party_size,
                            available=available_after,
                        )
                        raise ValueError(
                            f"슬롯 정원 초과: 요청 인원 {data.party_size}명, "
                            f"현재 가용 인원 {available_after}명입니다."
                        )

        conn.execute(
            f"UPDATE bookings SET {', '.join(sets)} WHERE booking_id = ?", params
        )
        row = conn.execute(
            "SELECT * FROM bookings WHERE booking_id = ?", (booking_id,)
        ).fetchone()
    result = row_to_dict(row)
    # ── Google Calendar 동기화 훅 ──
    try:
        from src.services import gcal_service
        if result:
            _owner = result.get("owner", "")
            gcal_service.update_event(_owner, booking_id, result)
    except Exception as _gcal_err:
        logger.warning("gcal_update_event_hook_failed", booking_id=booking_id, error=str(_gcal_err))
    try:
        from src.services.booking_notify import notify_booking_lifecycle_sms

        if result and result.get("owner"):
            notify_booking_lifecycle_sms(
                str(result["owner"]),
                result,
                "update",
                call_id=str(result.get("call_id") or ""),
            )
    except Exception as _sms_err:
        logger.warning("booking_update_notify_sms_failed", booking_id=booking_id, error=str(_sms_err))
    return result


def cancel_booking(booking_id: str, owner: Optional[str] = None) -> Optional[Dict[str, Any]]:
    """예약 취소: status=cancelled + 슬롯 booked_count 감소.

    Args:
        booking_id: 취소할 예약 ID
        owner: 테넌트 ID. 지정 시 예약의 owner가 일치하는지 검증합니다.
               불일치하면 None을 반환합니다.
    """
    now = _now_str()
    from src.booking.database import get_connection
    conn = get_connection()
    try:
        conn.execute("BEGIN IMMEDIATE")
        row = conn.execute(
            "SELECT * FROM bookings WHERE booking_id = ?", (booking_id,)
        ).fetchone()
        if not row:
            conn.rollback()
            return None
        if owner is not None and row["owner"] != owner:
            logger.warning(
                "cancel_booking_owner_mismatch",
                booking_id=booking_id,
                expected_owner=owner,
                actual_owner=row["owner"],
            )
            conn.rollback()
            return None
        if row["status"] == "cancelled":
            conn.rollback()
            return row_to_dict(row)

        conn.execute(
            "UPDATE bookings SET status = 'cancelled', updated_at = ? WHERE booking_id = ?",
            (now, booking_id),
        )
        if row["slot_id"]:
            conn.execute(
                """UPDATE booking_slots
                   SET booked_count = MAX(0, booked_count - 1), updated_at = ?
                   WHERE slot_id = ?""",
                (now, row["slot_id"]),
            )
        conn.commit()
        updated = conn.execute(
            "SELECT * FROM bookings WHERE booking_id = ?", (booking_id,)
        ).fetchone()
        logger.info("booking_cancelled", booking_id=booking_id)
        cancelled_result = row_to_dict(updated)
        # ── Google Calendar 동기화 훅 ──
        try:
            from src.services import gcal_service
            _owner = (owner or "") if owner else (cancelled_result or {}).get("owner", "")
            gcal_service.cancel_event(_owner, booking_id)
        except Exception as _gcal_err:
            logger.warning("gcal_cancel_event_hook_failed", booking_id=booking_id, error=str(_gcal_err))
        try:
            from src.services.booking_notify import notify_booking_lifecycle_sms

            own = (owner or "") or (cancelled_result or {}).get("owner") or ""
            if cancelled_result and own:
                notify_booking_lifecycle_sms(
                    str(own),
                    cancelled_result,
                    "cancel",
                    call_id=str(cancelled_result.get("call_id") or ""),
                )
        except Exception as _sms_err:
            logger.warning("booking_cancel_notify_sms_failed", booking_id=booking_id, error=str(_sms_err))
        return cancelled_result
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


# ──────────────────────────────────────────
# booking_schema_fields
# ──────────────────────────────────────────

def list_schema_fields(owner: str) -> List[Dict[str, Any]]:
    with get_db() as conn:
        rows = conn.execute(
            "SELECT * FROM booking_schema_fields WHERE owner = ? ORDER BY sort_order, field_key",
            (owner,),
        ).fetchall()
    return [row_to_dict(r) for r in rows]


def create_schema_field(owner: str, data: SchemaFieldCreate) -> Dict[str, Any]:
    field_id = _new_id("sf_")
    now = _now_str()
    opts = json.dumps(data.options, ensure_ascii=False)
    with get_db() as conn:
        conn.execute(
            """
            INSERT INTO booking_schema_fields
                (field_id, owner, field_key, field_label, field_type, required,
                 default_value, options, sort_order, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                field_id, owner, data.field_key, data.field_label, data.field_type,
                int(data.required), data.default_value, opts, data.sort_order, now,
            ),
        )
        row = conn.execute(
            "SELECT * FROM booking_schema_fields WHERE field_id = ?", (field_id,)
        ).fetchone()
    return row_to_dict(row)


def update_schema_field(field_id: str, data: SchemaFieldUpdate) -> Optional[Dict[str, Any]]:
    sets, params = [], []
    if data.field_label is not None:
        sets.append("field_label = ?"); params.append(data.field_label)
    if data.field_type is not None:
        sets.append("field_type = ?"); params.append(data.field_type)
    if data.required is not None:
        sets.append("required = ?"); params.append(int(data.required))
    if data.default_value is not None:
        sets.append("default_value = ?"); params.append(data.default_value)
    if data.options is not None:
        sets.append("options = ?"); params.append(json.dumps(data.options, ensure_ascii=False))
    if data.sort_order is not None:
        sets.append("sort_order = ?"); params.append(data.sort_order)
    if not sets:
        with get_db() as conn:
            row = conn.execute(
                "SELECT * FROM booking_schema_fields WHERE field_id = ?", (field_id,)
            ).fetchone()
        return row_to_dict(row)
    params.append(field_id)
    with get_db() as conn:
        conn.execute(
            f"UPDATE booking_schema_fields SET {', '.join(sets)} WHERE field_id = ?", params
        )
        row = conn.execute(
            "SELECT * FROM booking_schema_fields WHERE field_id = ?", (field_id,)
        ).fetchone()
    return row_to_dict(row)


def delete_schema_field(field_id: str) -> bool:
    with get_db() as conn:
        cur = conn.execute(
            "DELETE FROM booking_schema_fields WHERE field_id = ?", (field_id,)
        )
    return cur.rowcount > 0


# ──────────────────────────────────────────
# LLM Tool 전용 헬퍼 (booking_tools.py에서 사용)
# ──────────────────────────────────────────

def reschedule_booking(
    booking_id: str,
    new_slot_date: str,
    new_slot_time: str,
) -> Dict[str, Any]:
    """
    예약 날짜/시각 변경 (원자적 처리).

    1. 기존 슬롯 booked_count 감소
    2. 새 슬롯 booked_count 증가 (정원 초과 시 rollback)
    3. bookings 날짜/시간 업데이트

    모두 같은 트랜잭션 내 처리.
    """
    now = _now_str()
    from src.booking.database import get_connection
    conn = get_connection()
    try:
        conn.execute("BEGIN IMMEDIATE")

        # 기존 예약 확인
        row = conn.execute(
            "SELECT * FROM bookings WHERE booking_id = ?", (booking_id,)
        ).fetchone()
        if not row:
            raise ValueError(f"예약 번호 {booking_id}를 찾을 수 없습니다.")
        if row["status"] == "cancelled":
            raise ValueError(f"취소된 예약은 변경할 수 없습니다. (booking_id={booking_id})")

        owner = row["owner"]
        old_slot_id = row["slot_id"]
        old_slot_date = str(row["slot_date"] or "")
        old_slot_time = str(row["slot_time"] or "")

        # 기존 슬롯 booked_count 감소
        if old_slot_id:
            conn.execute(
                "UPDATE booking_slots SET booked_count = MAX(0, booked_count - 1), updated_at = ? WHERE slot_id = ?",
                (now, old_slot_id),
            )

        # 새 슬롯 조회
        new_slot_row = conn.execute(
            "SELECT * FROM booking_slots WHERE owner = ? AND slot_date = ? AND slot_time = ? AND is_blocked = 0",
            (owner, new_slot_date, new_slot_time),
        ).fetchone()

        new_slot_id = None
        if new_slot_row:
            new_slot_id = new_slot_row["slot_id"]
            if new_slot_row["booked_count"] >= new_slot_row["capacity"]:
                raise ValueError(f"{new_slot_date} {new_slot_time} 슬롯은 정원이 초과되었습니다.")
            conn.execute(
                "UPDATE booking_slots SET booked_count = booked_count + 1, updated_at = ? WHERE slot_id = ?",
                (now, new_slot_id),
            )

        # 예약 날짜/시간 업데이트
        conn.execute(
            """UPDATE bookings SET slot_date = ?, slot_time = ?, slot_id = ?, updated_at = ?
               WHERE booking_id = ?""",
            (new_slot_date, new_slot_time, new_slot_id, now, booking_id),
        )
        conn.commit()

        updated = conn.execute(
            "SELECT * FROM bookings WHERE booking_id = ?", (booking_id,)
        ).fetchone()
        logger.info(
            "booking_rescheduled",
            booking_id=booking_id,
            old_slot_id=old_slot_id,
            new_slot_id=new_slot_id,
            new_date=new_slot_date,
            new_time=new_slot_time,
        )
        reschedule_result = row_to_dict(updated)
        # ── Google Calendar 동기화 훅 ──
        try:
            from src.services import gcal_service
            gcal_service.update_event(owner, booking_id, reschedule_result)
        except Exception as _gcal_err:
            logger.warning("gcal_reschedule_event_hook_failed", booking_id=booking_id, error=str(_gcal_err))
        try:
            from src.services.booking_notify import notify_booking_lifecycle_sms

            if reschedule_result:
                notify_booking_lifecycle_sms(
                    str(owner),
                    reschedule_result,
                    "reschedule",
                    call_id=str(reschedule_result.get("call_id") or ""),
                    old_slot_date=old_slot_date,
                    old_slot_time=old_slot_time,
                )
        except Exception as _sms_err:
            logger.warning("booking_reschedule_notify_sms_failed", booking_id=booking_id, error=str(_sms_err))
        return reschedule_result
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def check_multi_date_slots(
    owner: str,
    start_date: str,
    end_date: str,
    party_size: int = 1,
) -> List[Dict[str, Any]]:
    """
    날짜 범위로 가용 슬롯 일괄 조회 (LLM Tool용).

    Args:
        owner: 테넌트 ID
        start_date: 시작일 (YYYY-MM-DD)
        end_date: 종료일 (YYYY-MM-DD)
        party_size: 예약 인원

    Returns:
        날짜별 가용 슬롯 요약 목록
    """
    with get_db() as conn:
        rows = conn.execute(
            """
            SELECT slot_date, COUNT(*) as slot_count,
                   SUM(CASE WHEN (capacity - booked_count) >= ? THEN 1 ELSE 0 END) as available_count
            FROM booking_slots
            WHERE owner = ?
              AND slot_date >= ?
              AND slot_date <= ?
              AND is_blocked = 0
            GROUP BY slot_date
            HAVING available_count > 0
            ORDER BY slot_date ASC
            """,
            (party_size, owner, start_date, end_date),
        ).fetchall()
    return [dict(r) for r in rows]


def add_booking_memo(booking_id: str, memo: str) -> Optional[Dict[str, Any]]:
    """
    기존 예약에 메모/특이사항 추가 또는 업데이트.

    Args:
        booking_id: 예약 ID
        memo: 추가할 메모 내용

    Returns:
        업데이트된 예약 정보
    """
    now = _now_str()
    with get_db() as conn:
        row = conn.execute(
            "SELECT * FROM bookings WHERE booking_id = ?", (booking_id,)
        ).fetchone()
        if not row:
            return None
        # 기존 메모가 있으면 줄바꿈으로 이어붙임
        existing_memo = (row_to_dict(row) or {}).get("memo") or ""
        new_memo = (existing_memo + "\n" + memo).strip() if existing_memo else memo
        conn.execute(
            "UPDATE bookings SET memo = ?, updated_at = ? WHERE booking_id = ?",
            (new_memo, now, booking_id),
        )
        updated = conn.execute(
            "SELECT * FROM bookings WHERE booking_id = ?", (booking_id,)
        ).fetchone()
    logger.info("booking_memo_added", booking_id=booking_id, memo_len=len(new_memo))
    return row_to_dict(updated)


def get_business_hours(owner: str) -> Optional[Dict[str, Any]]:
    """
    테넌트의 영업시간 설정을 조회 (booking_settings.extra_config에서 business_hours 추출).

    Returns:
        {
            "open_time": "09:00",
            "close_time": "18:00",
            "break_start": "12:00",
            "break_end": "13:00",
            "closed_days": ["Saturday", "Sunday"],
            "linked_to_slots": True/False
        }
        없으면 None
    """
    settings = get_settings(owner)
    if not settings:
        return None
    extra = settings.get("extra_config") or {}
    if isinstance(extra, str):
        try:
            extra = json.loads(extra)
        except Exception:
            extra = {}
    bh = extra.get("business_hours")
    return bh if isinstance(bh, dict) else None


_DEFAULT_WAITING_PHRASES = [
    "잠시만 기다려 주세요.",
    "정보를 확인하고 있습니다.",
    "조금 더 기다려 주세요.",
]


def get_waiting_phrases(owner: str) -> List[str]:
    """KB(booking_settings.extra_config.waiting_phrases)에서 대기 안내 멘트 목록을 반환.

    KB에 설정이 없으면 기본 멘트(_DEFAULT_WAITING_PHRASES)를 반환한다.

    Returns:
        List[str] — 멘트 목록 (최소 1개 보장)
    """
    settings = get_settings(owner)
    if settings:
        extra = settings.get("extra_config") or {}
        if isinstance(extra, str):
            try:
                extra = json.loads(extra)
            except Exception:
                extra = {}
        phrases = extra.get("waiting_phrases")
        if isinstance(phrases, list) and any(isinstance(p, str) and p.strip() for p in phrases):
            return [p for p in phrases if isinstance(p, str) and p.strip()]
    return list(_DEFAULT_WAITING_PHRASES)


def search_bookings_by_phone_future(
    owner: str,
    customer_phone: str,
    limit: int = 10,
) -> List[Dict[str, Any]]:
    """
    발신자 전화번호로 현재 시각 이후 미래 예약만 검색 (LLM 컨텍스트 사전 주입용).

    Args:
        owner: 테넌트 ID
        customer_phone: 발신자 전화번호
        limit: 최대 결과 수

    Returns:
        현재 시각 이후 확정(confirmed) 예약 목록, slot_date·slot_time 오름차순
    """
    from datetime import datetime
    now = datetime.now()
    today_str = now.strftime("%Y-%m-%d")
    now_time_str = now.strftime("%H:%M")

    with get_db() as conn:
        rows = conn.execute(
            """
            SELECT * FROM bookings
            WHERE owner = ?
              AND customer_phone = ?
              AND status = 'confirmed'
              AND (
                slot_date > ?
                OR (slot_date = ? AND slot_time >= ?)
              )
            ORDER BY slot_date ASC, slot_time ASC
            LIMIT ?
            """,
            (owner, customer_phone, today_str, today_str, now_time_str, limit),
        ).fetchall()
    return [row_to_dict(r) for r in rows]


def search_bookings_by_phone(
    owner: str,
    customer_phone: str,
    include_past: bool = False,
    limit: int = 10,
) -> List[Dict[str, Any]]:
    """
    발신자 전화번호로 예약을 검색합니다.

    Args:
        owner: 테넌트 ID
        customer_phone: 발신자 전화번호
        include_past: True이면 현재 시각 이전(과거) 예약도 포함. False이면 미래 예약만.
        limit: 최대 결과 수

    Returns:
        확정(confirmed) 및 취소(cancelled) 예약 목록.
        include_past=False 시 slot_date·slot_time 오름차순,
        include_past=True 시 slot_date·slot_time 내림차순 (최근 과거 먼저).
    """
    from datetime import datetime
    now = datetime.now()
    today_str = now.strftime("%Y-%m-%d")
    now_time_str = now.strftime("%H:%M")

    with get_db() as conn:
        if include_past:
            rows = conn.execute(
                """
                SELECT * FROM bookings
                WHERE owner = ?
                  AND customer_phone = ?
                  AND (
                    slot_date < ?
                    OR (slot_date = ? AND slot_time < ?)
                  )
                ORDER BY slot_date DESC, slot_time DESC
                LIMIT ?
                """,
                (owner, customer_phone, today_str, today_str, now_time_str, limit),
            ).fetchall()
        else:
            rows = conn.execute(
                """
                SELECT * FROM bookings
                WHERE owner = ?
                  AND customer_phone = ?
                  AND status = 'confirmed'
                  AND (
                    slot_date > ?
                    OR (slot_date = ? AND slot_time >= ?)
                  )
                ORDER BY slot_date ASC, slot_time ASC
                LIMIT ?
                """,
                (owner, customer_phone, today_str, today_str, now_time_str, limit),
            ).fetchall()
    return [row_to_dict(r) for r in rows]


# ──────────────────────────────────────────
# booking_domains  (예약 도메인 설정)
# ──────────────────────────────────────────

def list_domains(owner: str) -> List[Dict[str, Any]]:
    with get_db() as conn:
        rows = conn.execute(
            "SELECT * FROM booking_domains WHERE owner = ? ORDER BY sort_order, created_at",
            (owner,),
        ).fetchall()
    return [row_to_dict(r) for r in rows]


def get_domain(owner: str, domain_id: str) -> Optional[Dict[str, Any]]:
    with get_db() as conn:
        row = conn.execute(
            "SELECT * FROM booking_domains WHERE owner = ? AND domain_id = ?",
            (owner, domain_id),
        ).fetchone()
    return row_to_dict(row)


def create_domain(owner: str, body: BookingDomainCreate) -> Dict[str, Any]:
    domain_id = _new_id("dom_")
    now = _now_str()
    with get_db() as conn:
        conn.execute(
            """INSERT INTO booking_domains
               (domain_id, owner, domain_name, description, required_fields, optional_fields,
                sort_order, is_active, created_at, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                domain_id,
                owner,
                body.domain_name,
                body.description,
                json.dumps([f.model_dump() for f in body.required_fields], ensure_ascii=False),
                json.dumps([f.model_dump() for f in body.optional_fields], ensure_ascii=False),
                body.sort_order,
                1 if body.is_active else 0,
                now,
                now,
            ),
        )
    return get_domain(owner, domain_id)  # type: ignore[return-value]


def update_domain(owner: str, domain_id: str, body: BookingDomainUpdate) -> Optional[Dict[str, Any]]:
    existing = get_domain(owner, domain_id)
    if not existing:
        return None
    sets: list[str] = []
    params: list[Any] = []

    if body.domain_name is not None:
        sets.append("domain_name = ?"); params.append(body.domain_name)
    if body.description is not None:
        sets.append("description = ?"); params.append(body.description)
    if body.required_fields is not None:
        sets.append("required_fields = ?")
        params.append(json.dumps([f.model_dump() for f in body.required_fields], ensure_ascii=False))
    if body.optional_fields is not None:
        sets.append("optional_fields = ?")
        params.append(json.dumps([f.model_dump() for f in body.optional_fields], ensure_ascii=False))
    if body.sort_order is not None:
        sets.append("sort_order = ?"); params.append(body.sort_order)
    if body.is_active is not None:
        sets.append("is_active = ?"); params.append(1 if body.is_active else 0)

    sets.append("updated_at = ?"); params.append(_now_str())
    params.extend([owner, domain_id])

    with get_db() as conn:
        conn.execute(
            f"UPDATE booking_domains SET {', '.join(sets)} WHERE owner = ? AND domain_id = ?",
            params,
        )
    return get_domain(owner, domain_id)


def delete_domain(owner: str, domain_id: str) -> bool:
    with get_db() as conn:
        cur = conn.execute(
            "DELETE FROM booking_domains WHERE owner = ? AND domain_id = ?",
            (owner, domain_id),
        )
    return cur.rowcount > 0


def get_available_slots_for_llm(
    owner: str, slot_date: str, party_size: int = 1
) -> List[Dict[str, Any]]:
    """LLM 도구에서 사용. 인원 수용 가능한 가용 슬롯만 반환."""
    with get_db() as conn:
        rows = conn.execute(
            """SELECT * FROM booking_slots
               WHERE owner = ? AND slot_date = ?
                 AND is_blocked = 0
                 AND (capacity - booked_count) >= ?
               ORDER BY slot_time""",
            (owner, slot_date, party_size),
        ).fetchall()
    items = [row_to_dict(r) for r in rows]
    for item in items:
        item["available"] = max(0, item["capacity"] - item["booked_count"])
    return items
