"""
예약 시스템 REST API 라우터.

엔드포인트 목록:
  GET    /api/booking/slots              — 슬롯 목록 조회
  POST   /api/booking/slots              — 슬롯 생성
  PUT    /api/booking/slots/{slot_id}    — 슬롯 수정
  DELETE /api/booking/slots/{slot_id}    — 슬롯 삭제

  GET    /api/booking                    — 예약 목록 조회
  POST   /api/booking                    — 예약 생성
  GET    /api/booking/{booking_id}       — 예약 상세
  PUT    /api/booking/{booking_id}       — 예약 수정
  DELETE /api/booking/{booking_id}       — 예약 취소

  GET    /api/booking/settings/{owner}   — 도메인 설정 조회
  PUT    /api/booking/settings/{owner}   — 도메인 설정 저장

  GET    /api/booking/fields/{owner}     — 스키마 필드 목록
  POST   /api/booking/fields/{owner}     — 스키마 필드 추가
  PUT    /api/booking/fields/{owner}/{field_id}  — 스키마 필드 수정
  DELETE /api/booking/fields/{owner}/{field_id}  — 스키마 필드 삭제
"""

from __future__ import annotations

import logging
from typing import List, Optional

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

from src.booking.models import (
    BookingCreate,
    BookingDomainCreate,
    BookingDomainListResponse,
    BookingDomainResponse,
    BookingDomainUpdate,
    BookingListResponse,
    BookingResponse,
    BookingSettingsCreate,
    BookingSettingsResponse,
    BookingSettingsUpdate,
    BookingSlotCreate,
    BookingSlotResponse,
    BookingSlotUpdate,
    BookingUpdate,
    BulkSlotCreateRequest,
    BulkSlotCreateResult,
    SchemaFieldCreate,
    SchemaFieldResponse,
    SchemaFieldUpdate,
    SlotListResponse,
)
from src.services import booking_service as svc

logger = logging.getLogger(__name__)


class SmsSendRequest(BaseModel):
    to_phone: str
    message: str
    owner: str = ""
    from_phone: str = ""

router = APIRouter(prefix="/booking", tags=["booking"])


# ──────────────────────────────────────────
# 슬롯 관리
# ──────────────────────────────────────────

@router.get("/slots", response_model=SlotListResponse)
def api_list_slots(
    owner: str = Query(..., description="테넌트 owner"),
    slot_date: Optional[str] = Query(None, description="날짜 필터 (YYYY-MM-DD)"),
    slot_month: Optional[str] = Query(None, description="월 전체 필터 (YYYY-MM)"),
    include_full: bool = Query(True, description="만석 슬롯 포함 여부"),
    include_blocked: bool = Query(True, description="차단 슬롯 포함 여부"),
):
    items = svc.list_slots(owner, slot_date, slot_month, include_full, include_blocked)
    return {"total": len(items), "items": items}


@router.post("/slots/bulk", response_model=BulkSlotCreateResult, status_code=201)
def api_bulk_create_slots(
    owner: str = Query(..., description="테넌트 owner"),
    body: BulkSlotCreateRequest = ...,
):
    """업무시간·제외시간·기간을 설정해 슬롯을 일괄 자동 생성한다."""
    try:
        return svc.bulk_create_slots(owner, body)
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
    except Exception as e:
        logger.exception("bulk_slot_create_error")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/slots", response_model=BookingSlotResponse, status_code=201)
def api_create_slot(
    owner: str = Query(..., description="테넌트 owner"),
    body: BookingSlotCreate = ...,
):
    try:
        return svc.create_slot(owner, body)
    except Exception as e:
        if "UNIQUE" in str(e):
            raise HTTPException(status_code=409, detail="이미 동일 일시의 슬롯이 존재합니다.")
        logger.exception("slot_create_error")
        raise HTTPException(status_code=500, detail=str(e))


@router.put("/slots/{slot_id}", response_model=BookingSlotResponse)
def api_update_slot(slot_id: str, body: BookingSlotUpdate):
    result = svc.update_slot(slot_id, body)
    if not result:
        raise HTTPException(status_code=404, detail="슬롯을 찾을 수 없습니다.")
    return result


@router.delete("/slots/{slot_id}", status_code=204)
def api_delete_slot(slot_id: str):
    if not svc.delete_slot(slot_id):
        raise HTTPException(status_code=404, detail="슬롯을 찾을 수 없습니다.")


# ──────────────────────────────────────────
# 예약 관리 — 고정 경로 (반드시 /{booking_id} 보다 먼저 등록)
# ──────────────────────────────────────────

@router.get("", response_model=BookingListResponse)
def api_list_bookings(
    owner: str = Query(..., description="테넌트 owner"),
    slot_date: Optional[str] = Query(None, description="특정 날짜 필터 (YYYY-MM-DD)"),
    slot_month: Optional[str] = Query(None, description="월 전체 필터 (YYYY-MM)"),
    status: Optional[str] = Query(None),
    customer_phone: Optional[str] = Query(None),
    limit: int = Query(500, ge=1, le=1000),
    offset: int = Query(0, ge=0),
):
    return svc.list_bookings(owner, slot_date, slot_month, status, customer_phone, limit, offset)


@router.post("", response_model=BookingResponse, status_code=201)
def api_create_booking(
    owner: str = Query(..., description="테넌트 owner"),
    body: BookingCreate = ...,
):
    try:
        raw = svc.create_booking(owner, body)
        payload = {k: raw[k] for k in BookingResponse.model_fields if k in raw}
        return BookingResponse.model_validate(payload)
    except ValueError as e:
        raise HTTPException(status_code=409, detail=str(e))
    except Exception as e:
        logger.exception("booking_create_error")
        raise HTTPException(status_code=500, detail=str(e))


# ──────────────────────────────────────────
# 도메인 설정 — 고정 경로
# ──────────────────────────────────────────

@router.get("/settings/{owner}", response_model=Optional[BookingSettingsResponse])
def api_get_settings(owner: str):
    return svc.get_settings(owner)


@router.put("/settings/{owner}", response_model=BookingSettingsResponse)
def api_upsert_settings(owner: str, body: BookingSettingsUpdate):
    return svc.upsert_settings(owner, body)


@router.get("/settings/{owner}/business-hours")
def api_get_business_hours(owner: str):
    """영업시간 설정 조회 (extra_config.business_hours)."""
    bh = svc.get_business_hours(owner)
    return {"found": bh is not None, "business_hours": bh}


@router.put("/settings/{owner}/business-hours")
def api_update_business_hours(owner: str, body: dict):
    """영업시간 설정을 extra_config.business_hours에 저장."""
    import json as _json
    settings = svc.get_settings(owner)
    existing_extra: dict = {}
    if settings:
        raw = settings.get("extra_config", {})
        existing_extra = raw if isinstance(raw, dict) else {}

    # 기존 설정 베이스 생성
    from src.booking.models import BookingSettingsUpdate as BsUpdate
    base = settings or {}
    update = BsUpdate(
        domain_type=base.get("domain_type", "general"),
        service_name=base.get("service_name", "예약 서비스"),
        slot_duration_min=base.get("slot_duration_min", 60),
        max_party_size=base.get("max_party_size", 10),
        require_phone=base.get("require_phone", True),
        require_name=base.get("require_name", True),
        slot_label=base.get("slot_label", "예약"),
        confirmation_msg=base.get("confirmation_msg", ""),
        extra_config={**existing_extra, "business_hours": body},
    )
    return svc.upsert_settings(owner, update)


# ──────────────────────────────────────────
# 스키마 필드 — 고정 경로
# ──────────────────────────────────────────

@router.get("/fields/{owner}", response_model=List[SchemaFieldResponse])
def api_list_fields(owner: str):
    return svc.list_schema_fields(owner)


@router.post("/fields/{owner}", response_model=SchemaFieldResponse, status_code=201)
def api_create_field(owner: str, body: SchemaFieldCreate):
    try:
        return svc.create_schema_field(owner, body)
    except Exception as e:
        if "UNIQUE" in str(e):
            raise HTTPException(status_code=409, detail="동일한 field_key가 이미 존재합니다.")
        raise HTTPException(status_code=500, detail=str(e))


@router.put("/fields/{owner}/{field_id}", response_model=SchemaFieldResponse)
def api_update_field(owner: str, field_id: str, body: SchemaFieldUpdate):
    result = svc.update_schema_field(field_id, body)
    if not result:
        raise HTTPException(status_code=404, detail="필드를 찾을 수 없습니다.")
    return result


@router.delete("/fields/{owner}/{field_id}", status_code=204)
def api_delete_field(owner: str, field_id: str):
    if not svc.delete_schema_field(field_id):
        raise HTTPException(status_code=404, detail="필드를 찾을 수 없습니다.")


# ──────────────────────────────────────────
# 예약 도메인 설정 (booking_domains)
# ──────────────────────────────────────────

@router.get("/domains", response_model=BookingDomainListResponse)
def api_list_domains(owner: str = Query(..., description="테넌트 owner")):
    items = svc.list_domains(owner)
    return {"total": len(items), "items": items}


@router.post("/domains", response_model=BookingDomainResponse, status_code=201)
def api_create_domain(
    owner: str = Query(..., description="테넌트 owner"),
    body: BookingDomainCreate = ...,
):
    try:
        return svc.create_domain(owner, body)
    except Exception as e:
        if "UNIQUE" in str(e):
            raise HTTPException(status_code=409, detail="동일한 도메인 이름이 이미 존재합니다.")
        logger.exception("domain_create_error")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/domains/{domain_id}", response_model=BookingDomainResponse)
def api_get_domain(domain_id: str, owner: str = Query(...)):
    result = svc.get_domain(owner, domain_id)
    if not result:
        raise HTTPException(status_code=404, detail="도메인을 찾을 수 없습니다.")
    return result


@router.put("/domains/{domain_id}", response_model=BookingDomainResponse)
def api_update_domain(domain_id: str, owner: str = Query(...), body: BookingDomainUpdate = ...):
    result = svc.update_domain(owner, domain_id, body)
    if not result:
        raise HTTPException(status_code=404, detail="도메인을 찾을 수 없습니다.")
    return result


@router.delete("/domains/{domain_id}", status_code=204)
def api_delete_domain(domain_id: str, owner: str = Query(...)):
    if not svc.delete_domain(owner, domain_id):
        raise HTTPException(status_code=404, detail="도메인을 찾을 수 없습니다.")


# ──────────────────────────────────────────
# 예약 관리 — 동적 경로 /{booking_id}  ← 반드시 맨 마지막에 등록
# ──────────────────────────────────────────

@router.get("/{booking_id}", response_model=BookingResponse)
def api_get_booking(booking_id: str):
    result = svc.get_booking(booking_id)
    if not result:
        raise HTTPException(status_code=404, detail="예약을 찾을 수 없습니다.")
    return result


@router.put("/{booking_id}", response_model=BookingResponse)
def api_update_booking(booking_id: str, body: BookingUpdate):
    result = svc.update_booking(booking_id, body)
    if not result:
        raise HTTPException(status_code=404, detail="예약을 찾을 수 없습니다.")
    return result


@router.delete("/{booking_id}", response_model=BookingResponse)
def api_cancel_booking(booking_id: str):
    result = svc.cancel_booking(booking_id)
    if not result:
        raise HTTPException(status_code=404, detail="예약을 찾을 수 없습니다.")
    return result


# ──────────────────────────────────────────
# SIP SMS 발송
# ──────────────────────────────────────────

@router.post("/sms/send")
def api_send_sms(body: SmsSendRequest):
    """
    SIP MESSAGE(SMS)를 발송한다.

    발신자(owner) 번호로 수신자(to_phone)에게 SIP MESSAGE를 전송.
    LLM Tool(send_booking_sms)에서 http://127.0.0.1:8000/api/booking/sms/send 로 호출.
    """
    try:
        from src.services.sip_sms_service import send_sip_sms_sync
        from src.config.models import Config
        import os

        # SIP 서버 주소는 환경변수 또는 기본값 127.0.0.1:5060
        sip_ip = os.environ.get("SIP_SERVER_IP", "127.0.0.1")
        sip_port = int(os.environ.get("SIP_SERVER_PORT", "5060"))
        from_phone = body.from_phone or body.owner or "ai-booking"

        result = send_sip_sms_sync(
            to_phone=body.to_phone,
            message=body.message,
            from_phone=from_phone,
            sip_server_ip=sip_ip,
            sip_server_port=sip_port,
        )
        if not result["success"]:
            raise HTTPException(status_code=502, detail=result["message"])
        return result
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("api_send_sms_error")
        raise HTTPException(status_code=500, detail=str(e))
