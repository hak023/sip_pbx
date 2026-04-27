# 예약 도메인 설정 기능 구현 리포트

- **작성일**: 2026-04-09 21:00
- **상태**: 구현 완료
- **관련 경로**:
  - `sip-pbx/frontend/app/booking/domains/page.tsx` (신규)
  - `sip-pbx/frontend/app/booking/slots/page.tsx` (수정)
  - `sip-pbx/frontend/app/booking/page.tsx` (수정)
  - `sip-pbx/frontend/types/index.ts` (수정)
  - `sip-pbx/src/booking/database.py` (수정)
  - `sip-pbx/src/booking/models.py` (수정)
  - `sip-pbx/src/services/booking_service.py` (수정)
  - `sip-pbx/src/api/routers/booking.py` (수정)

---

## 1. 요구사항 요약

예약 도메인(예약 유형) 설정을 복수로 관리하고, 각 도메인별로 필수/선택 수집 정보를 정의한다. 슬롯 관리에서 이 도메인을 참조해 연결할 수 있도록 한다.

### 예시
| 도메인 이름       | 필수 수집 정보                          | 선택 수집 정보 |
|-----------------|---------------------------------------|--------------|
| 4인 테이블       | 이름, 전화번호                          | 메모          |
| 홍길동 디자이너   | 이름, 전화번호, 원하는 시술              | 메모          |
| 김개똥 의사      | 이름, 전화번호, 생년월일, 진료여부(초진/재진) | 메모    |

---

## 2. DB 변경

### 신규 테이블: `booking_domains`
```sql
CREATE TABLE IF NOT EXISTS booking_domains (
    domain_id       TEXT    PRIMARY KEY,
    owner           TEXT    NOT NULL,
    domain_name     TEXT    NOT NULL,           -- 예: "4인 테이블"
    description     TEXT    NOT NULL DEFAULT '',
    required_fields TEXT    NOT NULL DEFAULT '[]',  -- JSON: DomainFieldDef[]
    optional_fields TEXT    NOT NULL DEFAULT '[]',  -- JSON: DomainFieldDef[]
    sort_order      INTEGER NOT NULL DEFAULT 0,
    is_active       INTEGER NOT NULL DEFAULT 1,
    created_at      TEXT    NOT NULL DEFAULT (datetime('now','localtime')),
    updated_at      TEXT    NOT NULL DEFAULT (datetime('now','localtime')),
    UNIQUE(owner, domain_name)
);
```

### 신규 테이블: `booking_domain_fields` (확장용, 전역 필드 풀)
```sql
CREATE TABLE IF NOT EXISTS booking_domain_fields (
    field_id    TEXT PRIMARY KEY,
    owner       TEXT NOT NULL,
    field_key   TEXT NOT NULL,
    field_label TEXT NOT NULL,
    field_type  TEXT NOT NULL DEFAULT 'text',
    options     TEXT NOT NULL DEFAULT '[]',
    sort_order  INTEGER NOT NULL DEFAULT 0,
    created_at  TEXT NOT NULL DEFAULT (datetime('now','localtime')),
    UNIQUE(owner, field_key)
);
```

---

## 3. 데이터 구조 (`DomainFieldDef`)

각 필드 하나의 정의:

```typescript
interface DomainFieldDef {
  field_key: string;      // snake_case 식별자 (예: "desired_service")
  field_label: string;    // UI 표시명 (예: "원하는 시술")
  field_type: 'text' | 'select' | 'boolean' | 'number' | 'date';
  options: string[];      // select 타입일 때 선택지 (예: ["초진", "재진"])
}
```

---

## 4. API 엔드포인트

| Method | 경로 | 설명 |
|--------|------|------|
| GET    | `/api/booking/domains?owner=` | 도메인 목록 조회 |
| POST   | `/api/booking/domains?owner=` | 도메인 생성 |
| GET    | `/api/booking/domains/{domain_id}?owner=` | 도메인 상세 |
| PUT    | `/api/booking/domains/{domain_id}?owner=` | 도메인 수정 |
| DELETE | `/api/booking/domains/{domain_id}?owner=` | 도메인 삭제 |

---

## 5. 프론트엔드 UI 설계

### `/booking/domains` 페이지 구조

```
[헤더] 예약 도메인 설정    [슬롯 관리] [예약 목록] [+ 도메인 추가]

[안내 박스] 도메인 예시 및 필수/선택 색상 설명

[도메인 추가/편집 폼 (토글)]
  - 도메인 이름 (텍스트 입력 필수)
  - 설명 (선택)
  - 필수 수집 정보 (FieldEditor - 파란색)
  - 선택 수집 정보 (FieldEditor - 노란색)
  - 활성화 체크박스

[도메인 카드 목록]
  각 카드:
  - 도메인명 / 설명
  - 활성/비활성 토글, 편집, 삭제 버튼
  - 수집 필드 태그 목록 (필수=파란색, 선택=노란색)
```

### `FieldEditor` 컴포넌트 UX

- **프리셋 버튼**: 이름, 전화번호, 생년월일, 인원수, 메모 → 클릭 한 번에 추가
- **직접 입력**: "직접 입력" 버튼으로 빈 필드 추가, 필드명/키/타입 직접 입력
- **선택형(select)**: 옵션 태그 UI, Enter 또는 "추가" 버튼으로 선택지 추가, ×로 제거
- **중복 방지**: 이미 추가된 프리셋 버튼은 비활성화(회색)

### `/booking/slots` 수정사항

- 헤더에 **[도메인 설정]** 링크 추가
- 단일 슬롯 추가 폼에 **예약 도메인 드롭다운** 추가
  - 활성 도메인만 목록에 표시
  - "도메인 미지정" 기본 옵션 포함
  - 도메인이 없을 경우 도메인 설정 페이지 안내 링크 표시

### `/booking` 수정사항

- "도메인 설정" 버튼 링크를 `/booking/settings` → `/booking/domains` 로 변경

---

## 6. 제거/변경 사항

| 항목 | 변경 내용 |
|------|---------|
| `confirmation_msg` (예약 완료 안내 메시지) | 요청에 따라 UI에서 제거 (DB 필드는 유지) |
| "추가 수집 필드" 섹션 | 도메인 설정의 필수/선택 필드로 통합; 별도 페이지 대신 도메인에서 관리 |
| `/booking/settings` 경로 | `/booking/domains`로 대체 |

---

## 7. 향후 연동 계획

- 슬롯 생성 시 선택한 `domain_id`를 `booking_slots` 테이블에 저장 (컬럼 추가 필요)
- AI 보이스봇이 예약 수집 시 해당 슬롯의 도메인을 참조해 필수/선택 필드를 동적으로 수집
- `BookingSlot` 타입에 `domain_id?: string` 추가 필요
