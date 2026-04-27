# 슬롯-도메인 연결 구현 보고서

- **작성일**: 2026-04-09 22:00
- **상태**: 완료
- **관련 경로**: `sip-pbx/frontend/app/booking/slots/`, `sip-pbx/src/booking/`, `sip-pbx/src/services/`

---

## 개요

슬롯 생성 시 예약 도메인을 선택할 수 있도록 연결 기능을 구현했다.  
일괄 자동 생성과 단일 슬롯 추가 양쪽 모두 도메인 드롭다운을 제공하며,  
레이블 입력창(도메인 개념으로 대체)과 일별 뷰 날짜 이동 버그도 함께 수정했다.

---

## 변경 이력 (파일별)

| 파일 경로 | 변경 유형 | 요약 | 비고 |
|-----------|-----------|------|------|
| `frontend/app/booking/slots/page.tsx` | 수정 | 도메인 선택 드롭다운 추가, 레이블 제거, 날짜 버그 수정 | 상세 아래 |
| `frontend/types/index.ts` | 수정 | `BookingSlot`에 `domain_id?: string` 추가 | 설계대로 |
| `sip-pbx/src/booking/database.py` | 수정 | `booking_slots`에 `domain_id` 컬럼 추가 + 마이그레이션 | 설계대로 |
| `sip-pbx/src/booking/models.py` | 수정 | `BookingSlotBase`, `BookingSlotUpdate`, `BulkSlotCreateRequest`에 `domain_id` 추가 | 설계대로 |
| `sip-pbx/src/services/booking_service.py` | 수정 | `create_slot`, `bulk_create_slots`, `update_slot`에 `domain_id` 반영 | 설계대로 |
| `c:\work\workspace_sippbx\.cursor\rules\implementation-report-changelog.mdc` | 수정 | `alwaysApply: true`로 변경, 트리거 조건 명확화 | 룰 강화 |

---

## 파일별 변경 상세

### `frontend/app/booking/slots/page.tsx`

**1. 일괄 자동 생성 폼**
- **변경**: `BulkForm.label` 제거 → `BulkForm.domain_id` 추가
- **UI**: "공통 레이블" 입력창 제거 → "예약 도메인" `<select>` 드롭다운으로 대체
- **기존 동작 제거**: 있음 — `label` 필드 및 관련 UI 제거
- **설계 대비**: 설계대로 (도메인 개념이 레이블을 대체)

**2. 단일 슬롯 추가 폼**
- **변경**: `NewSlotForm.label` 제거, 레이블 입력창 제거
- **도메인 미지정 안내**: 도메인이 없을 경우 도메인 설정 페이지 링크 표시
- **기존 동작 제거**: 있음 — 레이블 입력 제거
- **설계 대비**: 설계대로

**3. 일별 뷰 날짜 이동 버그 수정**
- **원인**: `toDateStr(d)` / `toMonthStr(d)` 함수가 `.toISOString()`(UTC 기준)을 사용해 한국(UTC+9) 환경에서 자정 전후로 날짜가 하루씩 어긋남
- **수정**: `getFullYear()`, `getMonth()`, `getDate()` 등 **로컬 시간 기준** 메서드로 교체
- **설계 대비**: 버그 수정 (설계 이탈 아님)

**4. 슬롯 목록 행**
- 도메인 ID가 있는 경우 도메인명을 인디고 배지로 표시
- `domainMap` (도메인 ID → 이름 맵) 추가

### `sip-pbx/src/booking/database.py`

- `booking_slots` DDL에 `domain_id TEXT DEFAULT NULL` 컬럼 추가
- `_MIGRATIONS` 리스트 추가: 기존 DB에 컬럼이 없을 경우 `ALTER TABLE`로 안전하게 추가 (예외 무시)

### `sip-pbx/src/booking/models.py`

- `BookingSlotBase`: `domain_id: Optional[str] = Field(None, ...)` 추가
- `BookingSlotUpdate`: `domain_id: Optional[str] = None` 추가
- `BulkSlotCreateRequest`: `domain_id: Optional[str] = Field(None, ...)` 추가

### `sip-pbx/src/services/booking_service.py`

- `create_slot`: INSERT 쿼리에 `domain_id` 컬럼·값 추가
- `bulk_create_slots`: INSERT 쿼리에 `domain_id` 컬럼·값 추가 (`req.domain_id`)
- `update_slot`: `data.domain_id is not None` 조건으로 SET 절에 `domain_id = ?` 추가

---

## 주요 결정 사항

- **레이블 완전 제거**: 도메인 개념이 레이블을 대체하므로 입력 필드를 제거해 UI를 단순화했다. 기존 슬롯의 `label` 컬럼·데이터는 삭제하지 않고 유지(하위 호환).
- **마이그레이션 방식**: 별도 마이그레이션 파일 없이 `init_db()` 내 `_MIGRATIONS` 리스트에서 `ALTER TABLE`을 시도하고 이미 있으면 예외를 무시하는 간단한 방식을 채택했다.
- **날짜 버그**: UTC/로컬 시간 불일치 문제는 `toISOString()` 대신 로컬 date getter 메서드로 교체하는 것이 가장 안전하고 명확한 해결책이다.

---

## 잔여 과제

- 도메인이 삭제된 경우 기존 슬롯의 `domain_id`가 고아(orphan)로 남을 수 있음 → 슬롯 목록 표시 시 `domainMap`에 없는 ID는 배지 미표시로 graceful 처리 완료, 별도 정리 로직은 추후 고려.
