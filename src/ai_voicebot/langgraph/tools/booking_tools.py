"""
예약 시스템 LangChain Tool 정의.

LLM이 function calling을 통해 직접 호출하는 도구들.
BookingService를 Python 함수로 래핑하여 HTTP 오버헤드 없이 DB에 직접 접근한다.

도구 목록:
  - check_available_slots   : 예약 가능 시간대 조회 (단일 날짜)
  - check_multi_date_slots  : 날짜 범위 가용 슬롯 일괄 조회 (A-2)
  - get_booking_info        : 예약 상세 조회
  - create_booking_tool     : 예약 생성
  - cancel_booking_tool     : 예약 취소
  - reschedule_booking_tool : 예약 일정 변경 — 원자적 처리 (A-1)
  - get_booking_settings    : 도메인 설정 조회
  - get_business_hours_tool : 영업시간·휴무일 조회 (B-3)
  - update_booking_tool     : 예약 수정 (날짜/시간/인원/메모)
  - add_booking_memo_tool   : 예약 메모/특이사항 추가 (A-4)
  - search_my_bookings      : 발신자 전화번호로 미래 예약 검색
  - send_booking_sms        : SIP MESSAGE(SMS) 예약 확인 발송 (B-4)
  - get_call_context_tool   : 현재 통화 컨텍스트 조회 (C-3)
  - search_knowledge_tool   : 지식베이스 검색 (C-2)
"""

from __future__ import annotations

import json
from contextvars import ContextVar
from typing import Any, Optional

import structlog

from src.common.call_data_record_logger import log_call_data

logger = structlog.get_logger(__name__)

# ── RAG 엔진 컨텍스트 (ContextVar) ──────────────────────────────────────────
# booking_agent_node가 LLM tool call 루프 진입 전 set().
# _search_knowledge 내부에서 get()하여 파이프라인 인스턴스를 재사용한다.
# 스레드/코루틴 안전: ContextVar는 asyncio Task 단위로 격리됨.
_RAG_ENGINE_CONTEXT: ContextVar[Optional[Any]] = ContextVar("_rag_engine_ctx", default=None)

try:
    from langchain_core.tools import tool as langchain_tool
    _LANGCHAIN_AVAILABLE = True
except ImportError:
    _LANGCHAIN_AVAILABLE = False
    logger.warning("langchain_core not installed — booking tools disabled")
    langchain_tool = None  # type: ignore


def _make_tool(fn):
    """langchain_core가 없으면 원본 함수를 그대로 반환 (import 안전)."""
    if _LANGCHAIN_AVAILABLE and langchain_tool is not None:
        return langchain_tool(fn)
    return fn


# ──────────────────────────────────────────────────────────────────────────
# Tool 1: 예약 가능 슬롯 조회
# ──────────────────────────────────────────────────────────────────────────

def _check_available_slots(owner: str, slot_date: str, party_size: int = 1) -> str:
    """
    예약 가능한 시간대를 조회합니다.

    Args:
        owner: 테넌트 ID (착신 SIP 내선번호)
        slot_date: 조회할 날짜 (YYYY-MM-DD 형식)
        party_size: 예약 인원 수 (기본값 1)

    Returns:
        JSON 문자열: 가용 슬롯 목록 또는 오류 메시지
    """
    try:
        from src.services.booking_service import get_available_slots_for_llm
        slots = get_available_slots_for_llm(owner, slot_date, party_size)
        logger.info(
            "booking_tool_check_slots",
            owner=owner, date=slot_date, party_size=party_size,
            slot_count=len(slots),
        )
        if not slots:
            return json.dumps({
                "available": False,
                "message": f"{slot_date}에 예약 가능한 시간대가 없습니다.",
                "slots": [],
            }, ensure_ascii=False)
        return json.dumps({
            "available": True,
            "date": slot_date,
            "slots": [
                {
                    "slot_id": s["slot_id"],
                    "time": s["slot_time"],
                    "available_count": s["available"],
                    "label": s.get("label", ""),
                }
                for s in slots
            ],
        }, ensure_ascii=False)
    except Exception as e:
        logger.error("booking_tool_check_slots_error", error=str(e))
        return json.dumps({"error": f"슬롯 조회 중 오류가 발생했습니다: {e}"}, ensure_ascii=False)


check_available_slots = _make_tool(_check_available_slots)
check_available_slots.__doc__ = _check_available_slots.__doc__


# ──────────────────────────────────────────────────────────────────────────
# Tool 2: 예약 상세 조회
# ──────────────────────────────────────────────────────────────────────────

def _get_booking_info(booking_id: str) -> str:
    """
    예약 상세 정보를 조회합니다.

    Args:
        booking_id: 예약 ID

    Returns:
        JSON 문자열: 예약 상세 정보 또는 오류 메시지
    """
    try:
        from src.services.booking_service import get_booking
        booking = get_booking(booking_id)
        logger.info("booking_tool_get_info", booking_id=booking_id, found=booking is not None)
        if not booking:
            return json.dumps({"error": f"예약 번호 {booking_id}를 찾을 수 없습니다."}, ensure_ascii=False)
        return json.dumps({
            "booking_id": booking["booking_id"],
            "date": booking["slot_date"],
            "time": booking["slot_time"],
            "customer_name": booking["customer_name"],
            "customer_phone": booking["customer_phone"],
            "party_size": booking["party_size"],
            "service_type": booking["service_type"],
            "status": booking["status"],
            "memo": booking["memo"],
        }, ensure_ascii=False)
    except Exception as e:
        logger.error("booking_tool_get_info_error", booking_id=booking_id, error=str(e))
        return json.dumps({"error": f"예약 조회 중 오류가 발생했습니다: {e}"}, ensure_ascii=False)


get_booking_info = _make_tool(_get_booking_info)
get_booking_info.__doc__ = _get_booking_info.__doc__


# ──────────────────────────────────────────────────────────────────────────
# Tool 3: 예약 생성
# ──────────────────────────────────────────────────────────────────────────

def _create_booking(
    owner: str,
    slot_date: str,
    slot_time: str,
    customer_name: str,
    customer_phone: str,
    party_size: int = 1,
    service_type: str = "",
    slot_id: Optional[str] = None,
    call_id: str = "",
    memo: str = "",
    extra_data: Optional[dict] = None,
) -> str:
    """
    예약을 생성하고 예약번호를 반환합니다.

    Args:
        owner: 테넌트 ID
        slot_date: 예약 날짜 (YYYY-MM-DD)
        slot_time: 예약 시각 (HH:MM)
        customer_name: 예약자 이름
        customer_phone: 예약자 전화번호
        party_size: 예약 인원 수 (기본값 1)
        service_type: 서비스 종류 (선택)
        slot_id: 슬롯 ID (없으면 날짜+시각으로 자동 조회)
        call_id: 통화 ID — booking_agent_node가 자동 주입합니다.
        memo: 메모 (선택)
        extra_data: 도메인/테넌트 추가 수집 필드 값 {"field_key": 값} 형태. get_booking_settings의
                    domain_extra_fields/schema_extra_fields에서 required=true인 항목을 수집한 경우 전달.

    Returns:
        JSON 문자열: 생성된 예약 정보 또는 오류 메시지
    """
    try:
        from src.services.booking_service import create_booking
        from src.booking.models import BookingCreate

        data = BookingCreate(
            slot_date=slot_date,
            slot_time=slot_time,
            customer_name=customer_name,
            customer_phone=customer_phone,
            party_size=party_size,
            service_type=service_type,
            slot_id=slot_id,
            call_id=call_id,
            memo=memo,
            extra_data=extra_data or {},
        )
        booking = create_booking(owner, data)
        logger.info(
            "booking_tool_created",
            booking_id=booking["booking_id"], owner=owner,
            date=slot_date, time=slot_time,
        )
        if call_id:
            if booking.get("idempotent_repeat"):
                log_call_data(
                    call_id,
                    "booking",
                    "booking_idempotent_return",
                    booking_id=booking["booking_id"],
                    slot_date=booking.get("slot_date", slot_date),
                    slot_time=booking.get("slot_time", slot_time),
                    party_size=booking.get("party_size", party_size),
                    owner=owner,
                    note="동일 confirmed 예약 존재 — INSERT 생략·기존 예약 반환",
                )
            else:
                log_call_data(
                    call_id,
                    "booking",
                    "booking_committed",
                    booking_id=booking["booking_id"],
                    slot_date=booking.get("slot_date", slot_date),
                    slot_time=booking.get("slot_time", slot_time),
                    party_size=booking.get("party_size", party_size),
                    owner=owner,
                    confirmation_sms_sent=bool(booking.get("confirmation_sms_sent")),
                )

        # 음성(TTS)과 SIP 확인 문자 동일 문구 (booking_confirmation_text + create 시 notify)
        from src.services.booking_confirmation_text import build_booking_confirmation_text

        msg = build_booking_confirmation_text(owner, booking)

        return json.dumps({
            "success": True,
            "booking_id": booking["booking_id"],
            "date": booking["slot_date"],
            "time": booking["slot_time"],
            "customer_name": booking["customer_name"],
            "party_size": booking["party_size"],
            "status": booking["status"],
            "confirmation_message": msg,
            "confirmation_sms_sent": bool(booking.get("confirmation_sms_sent")),
            "confirmation_sms_error": booking.get("confirmation_sms_error"),
        }, ensure_ascii=False)
    except ValueError as e:
        logger.warning("booking_tool_create_conflict", error=str(e))
        if call_id:
            log_call_data(
                call_id,
                "booking",
                "booking_rejected",
                reason_code="value_error",
                detail=(str(e) or "")[:200],
            )
        return json.dumps({"error": str(e), "success": False}, ensure_ascii=False)
    except Exception as e:
        logger.error("booking_tool_create_error", error=str(e))
        if call_id:
            log_call_data(
                call_id,
                "booking",
                "booking_rejected",
                reason_code="create_exception",
                detail=(str(e) or "")[:200],
            )
        return json.dumps({"error": f"예약 생성 중 오류가 발생했습니다: {e}", "success": False}, ensure_ascii=False)


create_booking_tool = _make_tool(_create_booking)
create_booking_tool.__doc__ = _create_booking.__doc__


# ──────────────────────────────────────────────────────────────────────────
# Tool 4: 예약 취소
# ──────────────────────────────────────────────────────────────────────────

def _cancel_booking(booking_id: str, owner: str = "") -> str:
    """
    예약을 취소합니다.

    Args:
        booking_id: 취소할 예약 ID
        owner: 테넌트 ID — booking_agent_node가 자동 주입합니다. owner 불일치 시 취소 거부.

    Returns:
        JSON 문자열: 취소 결과 메시지
    """
    try:
        from src.services.booking_service import cancel_booking
        result = cancel_booking(booking_id, owner=owner or None)
        logger.info("booking_tool_cancelled", booking_id=booking_id, owner=owner, found=result is not None)
        if not result:
            return json.dumps({
                "error": f"예약 번호 {booking_id}를 찾을 수 없거나 접근 권한이 없습니다.",
                "success": False,
            }, ensure_ascii=False)
        return json.dumps({
            "success": True,
            "booking_id": booking_id,
            "status": result.get("status"),
            "message": f"예약번호 {booking_id}가 취소되었습니다.",
        }, ensure_ascii=False)
    except Exception as e:
        logger.error("booking_tool_cancel_error", booking_id=booking_id, error=str(e))
        return json.dumps({"error": f"예약 취소 중 오류가 발생했습니다: {e}", "success": False}, ensure_ascii=False)


cancel_booking_tool = _make_tool(_cancel_booking)
cancel_booking_tool.__doc__ = _cancel_booking.__doc__


# ──────────────────────────────────────────────────────────────────────────
# Tool 5: 도메인 설정 조회 (LLM 안내 메시지 구성용)
# ──────────────────────────────────────────────────────────────────────────

def _get_booking_settings(owner: str) -> str:
    """
    예약 서비스의 도메인 설정을 조회합니다 (LLM 안내 메시지 구성 시 참고용).

    반환 데이터에는 AI가 고객에게 수집해야 할 필드 정책이 포함됩니다:
    - require_phone: False이면 customer_phone을 묻지 마세요.
    - require_name: False이면 customer_name을 묻지 마세요.
    - domain_extra_fields: 도메인별 추가 수집 필드 목록 (required_fields + optional_fields).
      각 항목: {field_key, field_label, field_type, required, options[]}
      required=true인 필드는 create_booking_tool 호출 전 반드시 수집해야 합니다.
      수집한 값은 create_booking_tool의 extra_data에 {field_key: 값} 형태로 전달하세요.

    Args:
        owner: 테넌트 ID

    Returns:
        JSON 문자열: 도메인 설정 + AI 수집 정책
    """
    try:
        from src.services.booking_service import get_settings, list_domains, list_schema_fields

        settings = get_settings(owner)
        logger.info("booking_tool_get_settings", owner=owner, found=settings is not None)

        base: dict = {
            "domain_type": "general",
            "service_name": "예약 서비스",
            "slot_label": "예약",
            "max_party_size": 1,
            "slot_duration_min": 60,
            "require_phone": True,
            "require_name": True,
            "domain_extra_fields": [],
            "schema_extra_fields": [],
        }

        if settings:
            base.update({
                "domain_type": settings.get("domain_type", "general"),
                "service_name": settings.get("service_name", "예약 서비스"),
                "slot_label": settings.get("slot_label", "예약"),
                "max_party_size": settings.get("max_party_size", 1),
                "slot_duration_min": settings.get("slot_duration_min", 60),
                "require_phone": bool(settings.get("require_phone", True)),
                "require_name": bool(settings.get("require_name", True)),
            })

        # booking_domains의 활성 도메인별 추가 필드 수집
        try:
            domains = list_domains(owner)
            domain_extra: list = []
            for dom in domains:
                if not dom.get("is_active", True):
                    continue
                dom_name = dom.get("domain_name", "")
                dom_id = dom.get("domain_id", "")
                required_raw = dom.get("required_fields") or "[]"
                optional_raw = dom.get("optional_fields") or "[]"
                if isinstance(required_raw, str):
                    import json as _json
                    req_fields = _json.loads(required_raw)
                    opt_fields = _json.loads(optional_raw)
                else:
                    req_fields = required_raw
                    opt_fields = optional_raw
                for f in req_fields:
                    domain_extra.append({
                        "domain_id": dom_id,
                        "domain_name": dom_name,
                        "field_key": f.get("field_key"),
                        "field_label": f.get("field_label"),
                        "field_type": f.get("field_type", "text"),
                        "required": True,
                        "options": f.get("options", []),
                    })
                for f in opt_fields:
                    domain_extra.append({
                        "domain_id": dom_id,
                        "domain_name": dom_name,
                        "field_key": f.get("field_key"),
                        "field_label": f.get("field_label"),
                        "field_type": f.get("field_type", "text"),
                        "required": False,
                        "options": f.get("options", []),
                    })
            base["domain_extra_fields"] = domain_extra
        except Exception as e:
            logger.warning("booking_tool_get_settings_domain_fields_failed", error=str(e))

        # booking_schema_fields의 추가 수집 필드
        try:
            schema_fields = list_schema_fields(owner)
            base["schema_extra_fields"] = [
                {
                    "field_key": f.get("field_key"),
                    "field_label": f.get("field_label"),
                    "field_type": f.get("field_type", "text"),
                    "required": bool(f.get("required", False)),
                    "options": json.loads(f.get("options", "[]")) if isinstance(f.get("options"), str) else (f.get("options") or []),
                    "default_value": f.get("default_value", ""),
                }
                for f in schema_fields
            ]
        except Exception as e:
            logger.warning("booking_tool_get_settings_schema_fields_failed", error=str(e))

        logger.info(
            "booking_tool_get_settings_complete",
            owner=owner,
            require_phone=base["require_phone"],
            require_name=base["require_name"],
            domain_extra_count=len(base["domain_extra_fields"]),
            schema_extra_count=len(base["schema_extra_fields"]),
        )
        return json.dumps(base, ensure_ascii=False)
    except Exception as e:
        logger.error("booking_tool_get_settings_error", owner=owner, error=str(e))
        return json.dumps({"error": f"설정 조회 중 오류가 발생했습니다: {e}"}, ensure_ascii=False)


get_booking_settings = _make_tool(_get_booking_settings)
get_booking_settings.__doc__ = _get_booking_settings.__doc__


# ──────────────────────────────────────────────────────────────────────────
# Tool 6: 예약 수정
# ──────────────────────────────────────────────────────────────────────────

def _update_booking(
    booking_id: str,
    slot_date: str = "",
    slot_time: str = "",
    party_size: int = 0,
    memo: str = "",
) -> str:
    """
    예약 정보(날짜·시간·인원·메모)를 수정합니다.

    Args:
        booking_id: 수정할 예약 ID
        slot_date: 변경할 날짜 (YYYY-MM-DD, 생략 가능)
        slot_time: 변경할 시각 (HH:MM, 생략 가능)
        party_size: 변경할 인원 (0이면 유지)
        memo: 메모 (생략 가능)

    Returns:
        JSON 문자열: 수정 결과
    """
    try:
        from src.services.booking_service import update_booking, get_booking
        from src.booking.models import BookingUpdate

        existing = get_booking(booking_id)
        if not existing:
            return json.dumps({"error": f"예약 번호 {booking_id}를 찾을 수 없습니다.", "success": False}, ensure_ascii=False)

        update_data = BookingUpdate(
            slot_date=slot_date if slot_date else None,
            slot_time=slot_time if slot_time else None,
            party_size=party_size if party_size > 0 else None,
            memo=memo if memo else None,
        )
        result = update_booking(booking_id, update_data)
        logger.info("booking_tool_updated", booking_id=booking_id)
        return json.dumps({
            "success": True,
            "booking_id": booking_id,
            "date": result.get("slot_date"),
            "time": result.get("slot_time"),
            "party_size": result.get("party_size"),
            "message": f"예약번호 {booking_id}가 수정되었습니다.",
        }, ensure_ascii=False)
    except Exception as e:
        logger.error("booking_tool_update_error", booking_id=booking_id, error=str(e))
        return json.dumps({"error": f"예약 수정 중 오류: {e}", "success": False}, ensure_ascii=False)


update_booking_tool = _make_tool(_update_booking)
update_booking_tool.__doc__ = _update_booking.__doc__


# ──────────────────────────────────────────────────────────────────────────
# Tool 7: 발신자 전화번호로 미래 예약 검색
# ──────────────────────────────────────────────────────────────────────────

def _search_my_bookings(
    owner: str,
    customer_phone: str,
    include_past: bool = False,
) -> str:
    """
    발신자 전화번호로 예약을 검색합니다.
    예약번호를 모를 때 취소·조회·수정에 활용합니다.

    Args:
        owner: 테넌트 ID
        customer_phone: 발신자 전화번호
        include_past: True이면 과거(이미 지난) 예약도 조회합니다.
                      "지난 예약", "이전 예약", "지난달 예약" 같은 과거 조회 요청에 true로 설정하세요.
                      기본값은 False (미래 예약만).

    Returns:
        JSON 문자열: 예약 목록 (include_past=False: 미래 예약, True: 과거 예약)
    """
    try:
        from src.services.booking_service import search_bookings_by_phone
        bookings = search_bookings_by_phone(owner, customer_phone, include_past=include_past)
        logger.info(
            "booking_tool_search_my",
            owner=owner,
            phone=customer_phone,
            include_past=include_past,
            count=len(bookings),
        )
        period_label = "과거" if include_past else "미래"
        if not bookings:
            return json.dumps({
                "found": False,
                "include_past": include_past,
                "message": f"{customer_phone}로 조회된 {period_label} 예약이 없습니다.",
                "bookings": [],
            }, ensure_ascii=False)
        return json.dumps({
            "found": True,
            "include_past": include_past,
            "count": len(bookings),
            "bookings": [
                {
                    "booking_id": b["booking_id"],
                    "date": b["slot_date"],
                    "time": b["slot_time"],
                    "customer_name": b["customer_name"],
                    "party_size": b["party_size"],
                    "status": b["status"],
                    "memo": b.get("memo", ""),
                }
                for b in bookings
            ],
        }, ensure_ascii=False)
    except Exception as e:
        logger.error("booking_tool_search_my_error", error=str(e))
        return json.dumps({"error": f"예약 검색 중 오류: {e}"}, ensure_ascii=False)


search_my_bookings = _make_tool(_search_my_bookings)
search_my_bookings.__doc__ = _search_my_bookings.__doc__


# ──────────────────────────────────────────────────────────────────────────
# Tool 8: SIP SMS 발송
# ──────────────────────────────────────────────────────────────────────────

def _send_booking_sms(
    to_phone: str,
    message: str,
    owner: str = "",
) -> str:
    """
    고객 전화번호로 예약 관련 SMS를 발송합니다.
    예약 생성·수정·취소 시 확인 메시지 전송에 활용합니다.

    Args:
        to_phone: 수신 전화번호 (발신자 번호)
        message: 발송할 문자 내용
        owner: 테넌트 ID (발신 번호 결정용)

    Returns:
        JSON 문자열: 발송 결과
    """
    try:
        import httpx
        resp = httpx.post(
            "http://127.0.0.1:8000/api/booking/sms/send",
            json={"to_phone": to_phone, "message": message, "owner": owner},
            timeout=5.0,
        )
        if resp.status_code == 200:
            data = resp.json()
            logger.info("booking_tool_sms_sent", to=to_phone, owner=owner)
            return json.dumps({"success": True, "message": "SMS가 발송되었습니다.", **data}, ensure_ascii=False)
        else:
            logger.warning("booking_tool_sms_failed", status=resp.status_code, to=to_phone)
            return json.dumps({"success": False, "error": f"SMS 발송 실패 (HTTP {resp.status_code})"}, ensure_ascii=False)
    except Exception as e:
        logger.error("booking_tool_sms_error", error=str(e))
        return json.dumps({"success": False, "error": f"SMS 발송 오류: {e}"}, ensure_ascii=False)


send_booking_sms = _make_tool(_send_booking_sms)
send_booking_sms.__doc__ = _send_booking_sms.__doc__


# ──────────────────────────────────────────────────────────────────────────
# Tool 9: 예약 일정 변경 (reschedule)
# ──────────────────────────────────────────────────────────────────────────

def _reschedule_booking(
    booking_id: str,
    new_slot_date: str,
    new_slot_time: str,
) -> str:
    """
    예약 날짜와 시각을 변경합니다 (원자적 처리).
    기존 슬롯 카운트 감소 → 새 슬롯 카운트 증가 → 예약 날짜/시간 업데이트가 단일 트랜잭션으로 처리됩니다.

    Args:
        booking_id: 변경할 예약 ID
        new_slot_date: 새 날짜 (YYYY-MM-DD)
        new_slot_time: 새 시각 (HH:MM)

    Returns:
        JSON 문자열: 변경 결과
    """
    try:
        from src.services.booking_service import reschedule_booking
        result = reschedule_booking(booking_id, new_slot_date, new_slot_time)
        logger.info(
            "booking_tool_rescheduled",
            booking_id=booking_id,
            new_date=new_slot_date,
            new_time=new_slot_time,
        )
        return json.dumps({
            "success": True,
            "booking_id": result["booking_id"],
            "date": result["slot_date"],
            "time": result["slot_time"],
            "status": result["status"],
            "message": f"예약번호 {booking_id}의 일정이 {new_slot_date} {new_slot_time}으로 변경되었습니다.",
        }, ensure_ascii=False)
    except ValueError as e:
        logger.warning("booking_tool_reschedule_conflict", booking_id=booking_id, error=str(e))
        return json.dumps({"error": str(e), "success": False}, ensure_ascii=False)
    except Exception as e:
        logger.error("booking_tool_reschedule_error", booking_id=booking_id, error=str(e))
        return json.dumps({"error": f"예약 변경 중 오류: {e}", "success": False}, ensure_ascii=False)


reschedule_booking_tool = _make_tool(_reschedule_booking)
reschedule_booking_tool.__doc__ = _reschedule_booking.__doc__


# ──────────────────────────────────────────────────────────────────────────
# Tool 10: 복수 날짜 슬롯 일괄 조회
# ──────────────────────────────────────────────────────────────────────────

def _check_multi_date_slots(
    owner: str,
    start_date: str,
    end_date: str,
    party_size: int = 1,
) -> str:
    """
    날짜 범위에서 예약 가능한 날짜와 슬롯 수를 일괄 조회합니다.
    "이번 주 언제 예약 가능해요?" 같은 질문에 한 번의 호출로 답합니다.

    Args:
        owner: 테넌트 ID
        start_date: 조회 시작일 (YYYY-MM-DD)
        end_date: 조회 종료일 (YYYY-MM-DD)
        party_size: 예약 인원 수 (기본값 1)

    Returns:
        JSON 문자열: 날짜별 가용 슬롯 요약
    """
    try:
        from src.services.booking_service import check_multi_date_slots
        results = check_multi_date_slots(owner, start_date, end_date, party_size)
        logger.info(
            "booking_tool_multi_date_slots",
            owner=owner,
            start=start_date,
            end=end_date,
            available_days=len(results),
        )
        if not results:
            return json.dumps({
                "available": False,
                "message": f"{start_date}~{end_date} 기간에 {party_size}명 예약 가능한 날이 없습니다.",
                "dates": [],
            }, ensure_ascii=False)
        return json.dumps({
            "available": True,
            "start_date": start_date,
            "end_date": end_date,
            "dates": [
                {
                    "date": r["slot_date"],
                    "available_slots": r["available_count"],
                    "total_slots": r["slot_count"],
                }
                for r in results
            ],
        }, ensure_ascii=False)
    except Exception as e:
        logger.error("booking_tool_multi_date_slots_error", error=str(e))
        return json.dumps({"error": f"다중 날짜 조회 중 오류: {e}"}, ensure_ascii=False)


check_multi_date_slots = _make_tool(_check_multi_date_slots)
check_multi_date_slots.__doc__ = _check_multi_date_slots.__doc__


# ──────────────────────────────────────────────────────────────────────────
# Tool 11: 예약 메모 추가
# ──────────────────────────────────────────────────────────────────────────

def _add_booking_memo(booking_id: str, memo: str) -> str:
    """
    기존 예약에 메모나 특이사항을 추가합니다.
    예약 후 추가 요청사항(알레르기, 좌석 선호, 특이사항 등)을 기록할 때 사용합니다.

    Args:
        booking_id: 예약 ID
        memo: 추가할 메모 내용

    Returns:
        JSON 문자열: 업데이트 결과
    """
    try:
        from src.services.booking_service import add_booking_memo
        result = add_booking_memo(booking_id, memo)
        logger.info("booking_tool_memo_added", booking_id=booking_id)
        if not result:
            return json.dumps({"error": f"예약 번호 {booking_id}를 찾을 수 없습니다.", "success": False}, ensure_ascii=False)
        return json.dumps({
            "success": True,
            "booking_id": booking_id,
            "memo": result.get("memo", ""),
            "message": "메모가 추가되었습니다.",
        }, ensure_ascii=False)
    except Exception as e:
        logger.error("booking_tool_memo_error", booking_id=booking_id, error=str(e))
        return json.dumps({"error": f"메모 추가 중 오류: {e}", "success": False}, ensure_ascii=False)


add_booking_memo_tool = _make_tool(_add_booking_memo)
add_booking_memo_tool.__doc__ = _add_booking_memo.__doc__


# ──────────────────────────────────────────────────────────────────────────
# Tool 12: 영업시간 조회 (슬롯 영업시간 연동 설정 포함)
# ──────────────────────────────────────────────────────────────────────────

def _get_business_hours(owner: str) -> str:
    """
    영업시간 및 휴무일 정보를 조회합니다.
    고객이 영업시간을 명시적으로 물어볼 때만 호출하세요.

    linked_to_slots 해석:
      - true : 슬롯이 이 영업시간 기준으로 생성됨 → 안내 기준으로 사용 가능
      - false: 영업시간은 참고용, 실제 예약 가능 여부는 check_available_slots로 확인 필요

    found=false 이면 "정확한 영업시간은 매장에 직접 문의 부탁드립니다"라고 안내하세요.

    Args:
        owner: 테넌트 ID

    Returns:
        JSON 문자열: 영업시간 정보
    """
    try:
        from src.services.booking_service import get_business_hours
        bh = get_business_hours(owner)
        logger.info("booking_tool_business_hours", owner=owner, found=bh is not None)
        if not bh:
            return json.dumps({
                "found": False,
                "message": "영업시간 정보가 설정되지 않았습니다. 정확한 영업시간은 매장에 직접 문의 부탁드립니다.",
            }, ensure_ascii=False)
        linked = bh.get("linked_to_slots", False)
        return json.dumps({
            "found": True,
            "open_time": bh.get("open_time", ""),
            "close_time": bh.get("close_time", ""),
            "break_start": bh.get("break_start", ""),
            "break_end": bh.get("break_end", ""),
            "closed_days": bh.get("closed_days", []),
            "linked_to_slots": linked,
            "note": (
                "이 영업시간 기준으로 슬롯이 생성되어 있습니다. 예약 가능 시간 안내 시 활용하세요."
                if linked else
                "참고용 영업시간입니다. 실제 예약 가능 여부는 슬롯 조회(check_available_slots)로 확인하세요."
            ),
        }, ensure_ascii=False)
    except Exception as e:
        logger.error("booking_tool_business_hours_error", owner=owner, error=str(e))
        return json.dumps({"error": f"영업시간 조회 중 오류: {e}"}, ensure_ascii=False)


get_business_hours_tool = _make_tool(_get_business_hours)
get_business_hours_tool.__doc__ = _get_business_hours.__doc__


# ──────────────────────────────────────────────────────────────────────────
# Tool 13: 현재 통화 컨텍스트 조회 (발신번호 + 현재시각 + 과거 통화 요약)
# ──────────────────────────────────────────────────────────────────────────

def _get_call_context(owner: str, call_id: str = "") -> str:
    """
    현재 통화의 컨텍스트(발신번호, 현재 시각, 과거 통화 이력 요약)를 반환합니다.
    booking_agent_node가 _call_context 키로 이 정보를 state에서 직접 주입하므로
    일반적으로 직접 호출할 필요는 없습니다.

    Args:
        owner: 테넌트 ID
        call_id: 통화 ID (선택)

    Returns:
        JSON 문자열: 통화 컨텍스트
    """
    try:
        from datetime import datetime
        now = datetime.now()
        return json.dumps({
            "current_time": now.strftime("%Y-%m-%d %H:%M"),
            "owner": owner,
            "call_id": call_id,
            "note": "발신자 전화번호와 과거 통화 이력은 시스템 메시지에 이미 제공되어 있습니다.",
        }, ensure_ascii=False)
    except Exception as e:
        logger.error("booking_tool_call_context_error", error=str(e))
        return json.dumps({"error": f"통화 컨텍스트 조회 오류: {e}"}, ensure_ascii=False)


get_call_context_tool = _make_tool(_get_call_context)
get_call_context_tool.__doc__ = _get_call_context.__doc__


# ──────────────────────────────────────────────────────────────────────────
# Tool 14: 지식베이스 검색 (booking agent 내 혼합 질문 처리)
# ──────────────────────────────────────────────────────────────────────────

def _search_knowledge(owner: str, query: str, category: str = "") -> str:
    """
    예약 상담 중 혼합 질문(메뉴, 서비스 안내, 주차, 위치, 영업시간 등)에 답하기 위해
    지식베이스(KB)를 검색합니다.

    "예약도 하고 메뉴도 알고 싶어요" 같은 복합 요청에 활용합니다.
    영업시간 tool에서 found=false가 반환된 경우에도 이 tool로 KB를 검색하세요.

    Args:
        owner: 테넌트 ID
        query: 검색할 질문 (자연어)
        category: 검색 범위 카테고리 (선택). 예: "FAQ", "menu", "parking", "business_hours".
                  비워두면 전체 KB를 검색합니다.

    Returns:
        JSON 문자열:
          found=true  → snippets: 관련 문서 발췌 목록 (최대 3개)
          found=false → message: 정보를 찾지 못했다는 안내
    """
    try:
        from src.services.booking_service import get_settings
        settings = get_settings(owner)
        service_name = settings.get("service_name", "서비스") if settings else "서비스"

        # ── 1순위: 파이프라인 RAG 엔진 재사용 (ContextVar 통해 주입) ──────────
        rag_engine = _RAG_ENGINE_CONTEXT.get()
        if rag_engine is not None:
            try:
                search_kwargs: dict = {"owner_filter": owner or None}
                if category:
                    search_kwargs["category_filter"] = category
                results = rag_engine.search(query, **search_kwargs)
                if results:
                    snippets = []
                    for r in results[:3]:
                        text = r.get("content") or r.get("text") or r.get("document", "")
                        if isinstance(text, str) and text.strip():
                            snippets.append(text.strip()[:250])
                    if snippets:
                        logger.info(
                            "booking_tool_search_knowledge_rag_engine_hit",
                            owner=owner,
                            query_preview=query[:40],
                            category=category or "all",
                            hit_count=len(snippets),
                        )
                        return json.dumps({
                            "found": True,
                            "query": query,
                            "category": category or "all",
                            "source": "rag_engine",
                            "snippets": snippets,
                        }, ensure_ascii=False)
            except Exception as rag_err:
                logger.warning("booking_tool_search_knowledge_rag_engine_failed",
                               error=str(rag_err))

        # ── 2순위: VectorDB 직접 접근 (fallback) ─────────────────────────────
        try:
            from src.ai_voicebot.knowledge.embedder import Embedder
            from src.ai_voicebot.knowledge.vector_db import VectorDB
            embedder = Embedder()
            vector_db = VectorDB(owner=owner)
            query_vec = embedder.embed(query)

            search_filter: dict = {}
            if category:
                search_filter["category"] = category

            results = vector_db.search(query_vec, top_k=3, where=search_filter or None)
            if results:
                snippets = []
                for r in results[:3]:
                    text = r.get("content") or r.get("text") or r.get("document", "")
                    if isinstance(text, str) and text.strip():
                        snippets.append(text.strip()[:250])
                if snippets:
                    logger.info(
                        "booking_tool_search_knowledge_vectordb_hit",
                        owner=owner,
                        query_preview=query[:40],
                        category=category or "all",
                        hit_count=len(snippets),
                    )
                    return json.dumps({
                        "found": True,
                        "query": query,
                        "category": category or "all",
                        "source": "vector_db",
                        "snippets": snippets,
                    }, ensure_ascii=False)
        except Exception as kb_err:
            logger.warning("booking_tool_search_knowledge_vectordb_fallback", error=str(kb_err))

        logger.info(
            "booking_tool_search_knowledge_not_found",
            owner=owner,
            query_preview=query[:40],
            category=category or "all",
        )
        return json.dumps({
            "found": False,
            "query": query,
            "category": category or "all",
            "message": f"{service_name}에서 '{query}'에 대한 상세 정보를 찾지 못했습니다. 직접 문의해 주세요.",
        }, ensure_ascii=False)
    except Exception as e:
        logger.error("booking_tool_search_knowledge_error", owner=owner, error=str(e))
        return json.dumps({"error": f"지식베이스 검색 오류: {e}"}, ensure_ascii=False)


search_knowledge_tool = _make_tool(_search_knowledge)
search_knowledge_tool.__doc__ = _search_knowledge.__doc__


# ──────────────────────────────────────────────────────────────────────────
# 모든 예약 Tool 목록 (ToolNode에 전달)
# ──────────────────────────────────────────────────────────────────────────

BOOKING_TOOLS = [
    check_available_slots,
    check_multi_date_slots,
    get_booking_info,
    create_booking_tool,
    cancel_booking_tool,
    reschedule_booking_tool,
    get_booking_settings,
    get_business_hours_tool,
    update_booking_tool,
    add_booking_memo_tool,
    search_my_bookings,
    # send_booking_sms 제거 — 통화 종료 후 _send_end_call_sms()에서 일괄 발송
    get_call_context_tool,
    search_knowledge_tool,
]
