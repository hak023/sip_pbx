"""
예약 시스템 Pydantic 모델.

Request/Response 모델 + DB Row 매핑 헬퍼.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


def _new_id(prefix: str = "") -> str:
    return f"{prefix}{uuid.uuid4().hex[:12]}"


# ──────────────────────────────────────────
# booking_settings
# ──────────────────────────────────────────

class BookingSettingsBase(BaseModel):
    domain_type: str = Field("general", description="도메인 타입 (restaurant/hospital/general/…)")
    service_name: str = Field("예약 서비스", description="서비스 이름 (TTS·UI 표시용)")
    slot_duration_min: int = Field(60, ge=5, le=1440, description="슬롯 단위(분)")
    max_party_size: int = Field(1, ge=1, le=500, description="최대 인원")
    require_phone: bool = True
    require_name: bool = True
    slot_label: str = Field("예약", description="슬롯 표시 레이블 (예: 테이블, 진료실)")
    confirmation_msg: str = Field(
        "예약이 완료되었습니다. 예약번호는 {booking_id}입니다.",
        description="예약 완료 안내 메시지 템플릿",
    )
    extra_config: Dict[str, Any] = Field(
        default_factory=dict, description="도메인별 추가 설정 JSON"
    )


class BookingSettingsCreate(BookingSettingsBase):
    pass


class BookingSettingsUpdate(BookingSettingsBase):
    pass


class BookingSettingsResponse(BookingSettingsBase):
    owner: str
    updated_at: str

    model_config = {"from_attributes": True}


# ──────────────────────────────────────────
# booking_slots
# ──────────────────────────────────────────

class BookingSlotBase(BaseModel):
    slot_date: str = Field(..., description="날짜 (YYYY-MM-DD)")
    slot_time: str = Field(..., description="시각 (HH:MM)")
    capacity: int = Field(1, ge=1, description="최대 예약 가능 수")
    label: str = Field("", description="슬롯 추가 설명")
    domain_id: Optional[str] = Field(None, description="연결된 예약 도메인 ID")
    is_blocked: bool = Field(False, description="차단(예약 불가) 여부")


class BookingSlotCreate(BookingSlotBase):
    pass


class BookingSlotUpdate(BaseModel):
    capacity: Optional[int] = Field(None, ge=1)
    label: Optional[str] = None
    domain_id: Optional[str] = None
    is_blocked: Optional[bool] = None


class BookingSlotResponse(BookingSlotBase):
    slot_id: str
    owner: str
    booked_count: int
    available: int = Field(0, description="잔여 예약 가능 수")
    created_at: str
    updated_at: str

    model_config = {"from_attributes": True}


# ──────────────────────────────────────────
# bookings
# ──────────────────────────────────────────

class BookingBase(BaseModel):
    slot_date: str = Field(..., description="예약 날짜 (YYYY-MM-DD)")
    slot_time: str = Field(..., description="예약 시각 (HH:MM)")
    customer_name: str = Field("", description="예약자 이름")
    customer_phone: str = Field("", description="예약자 전화번호")
    party_size: int = Field(1, ge=1, description="인원 수")
    service_type: str = Field("", description="서비스 종류 (도메인 의존)")
    extra_data: Dict[str, Any] = Field(
        default_factory=dict, description="도메인별 추가 수집 데이터"
    )
    memo: str = Field("", description="메모")


class BookingCreate(BookingBase):
    slot_id: Optional[str] = Field(None, description="슬롯 ID (없으면 날짜+시각으로 자동 조회)")
    call_id: str = Field("", description="연결된 통화 ID")


class BookingUpdate(BaseModel):
    slot_date: Optional[str] = Field(None, description="변경할 날짜 (YYYY-MM-DD)")
    slot_time: Optional[str] = Field(None, description="변경할 시각 (HH:MM)")
    customer_name: Optional[str] = None
    customer_phone: Optional[str] = None
    party_size: Optional[int] = Field(None, ge=1)
    service_type: Optional[str] = None
    extra_data: Optional[Dict[str, Any]] = None
    memo: Optional[str] = None
    status: Optional[str] = Field(None, description="confirmed / cancelled / no_show / completed")


class BookingResponse(BookingBase):
    booking_id: str
    owner: str
    slot_id: Optional[str]
    status: str
    call_id: str
    created_at: str
    updated_at: str

    model_config = {"from_attributes": True}


# ──────────────────────────────────────────
# booking_schema_fields
# ──────────────────────────────────────────

class SchemaFieldBase(BaseModel):
    field_key: str = Field(..., description="필드 키 (snake_case)")
    field_label: str = Field(..., description="UI 표시 레이블")
    field_type: str = Field("text", description="text / number / select / date / boolean")
    required: bool = False
    default_value: str = ""
    options: List[str] = Field(default_factory=list, description="select 타입 선택지")
    sort_order: int = 0


class SchemaFieldCreate(SchemaFieldBase):
    pass


class SchemaFieldUpdate(BaseModel):
    field_label: Optional[str] = None
    field_type: Optional[str] = None
    required: Optional[bool] = None
    default_value: Optional[str] = None
    options: Optional[List[str]] = None
    sort_order: Optional[int] = None


class SchemaFieldResponse(SchemaFieldBase):
    field_id: str
    owner: str
    created_at: str

    model_config = {"from_attributes": True}


# ──────────────────────────────────────────
# booking_domains  (예약 도메인 설정)
# ──────────────────────────────────────────

class DomainFieldDef(BaseModel):
    """도메인 수집 필드 정의 (도메인 내 인라인)."""
    field_key: str = Field(..., description="식별자 (snake_case)")
    field_label: str = Field(..., description="UI 표시명")
    field_type: str = Field("text", description="text / select / boolean / number / date")
    options: List[str] = Field(default_factory=list, description="select 타입 선택지")


class BookingDomainBase(BaseModel):
    domain_name: str = Field(..., description="도메인 이름 (예: 4인테이블, 홍길동디자이너)")
    description: str = Field("", description="도메인 설명")
    required_fields: List[DomainFieldDef] = Field(
        default_factory=list,
        description="필수 수집 필드 목록",
    )
    optional_fields: List[DomainFieldDef] = Field(
        default_factory=list,
        description="선택 수집 필드 목록",
    )
    sort_order: int = 0
    is_active: bool = True


class BookingDomainCreate(BookingDomainBase):
    pass


class BookingDomainUpdate(BaseModel):
    domain_name: Optional[str] = None
    description: Optional[str] = None
    required_fields: Optional[List[DomainFieldDef]] = None
    optional_fields: Optional[List[DomainFieldDef]] = None
    sort_order: Optional[int] = None
    is_active: Optional[bool] = None


class BookingDomainResponse(BookingDomainBase):
    domain_id: str
    owner: str
    created_at: str
    updated_at: str

    model_config = {"from_attributes": True}


class BookingDomainListResponse(BaseModel):
    total: int
    items: List[BookingDomainResponse]


# ──────────────────────────────────────────
# 슬롯 일괄 자동 생성
# ──────────────────────────────────────────

class ExcludeWindow(BaseModel):
    """제외 시간대 하나 (예: 점심 12:00-13:00)."""
    start: str = Field(..., description="제외 시작 시각 (HH:MM)")
    end: str = Field(..., description="제외 종료 시각 (HH:MM)")
    label: str = Field("", description="제외 사유 표시 (예: 점심시간)")


class BulkSlotCreateRequest(BaseModel):
    """일괄 슬롯 자동 생성 요청 본문."""

    # 기간
    date_from: str = Field(..., description="생성 시작 날짜 (YYYY-MM-DD)")
    date_to: str = Field(..., description="생성 종료 날짜 (YYYY-MM-DD, 포함)")

    # 요일 선택 (0=월 … 6=일), 기본 월~금
    weekdays: List[int] = Field(
        default=[0, 1, 2, 3, 4],
        description="운영 요일 목록 (0=월,1=화,2=수,3=목,4=금,5=토,6=일)",
    )

    # 업무 시간
    work_start: str = Field(..., description="업무 시작 시각 (HH:MM)")
    work_end: str = Field(..., description="업무 종료 시각 (HH:MM)")

    # 슬롯 단위
    slot_duration_min: int = Field(60, ge=5, le=480, description="슬롯 길이(분)")

    # 슬롯 간격 (0이면 duration과 동일 = 붙여서 생성)
    slot_interval_min: int = Field(
        0, ge=0, le=480,
        description="슬롯 시작 간격(분). 0이면 duration과 동일.",
    )

    # 동시 수용 인원
    capacity: int = Field(1, ge=1, le=500, description="슬롯당 최대 인원")

    # 제외 시간대 목록 (점심, 휴식 등)
    exclude_windows: List[ExcludeWindow] = Field(
        default_factory=list,
        description="제외할 시간대 목록 (예: 점심 12:00-13:00)",
    )

    # 중복 슬롯 처리
    skip_existing: bool = Field(
        True,
        description="이미 존재하는 슬롯은 건너뜀(True) / 오류 반환(False)",
    )

    # 공통 레이블 (빈 문자열이면 미사용)
    label: str = Field("", description="모든 생성 슬롯에 붙일 공통 레이블")

    # 도메인 연결 (선택)
    domain_id: Optional[str] = Field(None, description="생성 슬롯에 연결할 예약 도메인 ID")


class BulkSlotCreateResult(BaseModel):
    """일괄 슬롯 생성 결과."""
    created: int = Field(0, description="생성된 슬롯 수")
    skipped: int = Field(0, description="건너뜀(중복) 슬롯 수")
    total_generated: int = Field(0, description="생성 시도 슬롯 수")
    preview: List[str] = Field(
        default_factory=list,
        description="생성된 슬롯 목록 미리보기 (YYYY-MM-DD HH:MM 형식, 최대 50개)",
    )


# ──────────────────────────────────────────
# 공통 응답
# ──────────────────────────────────────────

class BookingListResponse(BaseModel):
    total: int
    items: List[BookingResponse]


class SlotListResponse(BaseModel):
    total: int
    items: List[BookingSlotResponse]
