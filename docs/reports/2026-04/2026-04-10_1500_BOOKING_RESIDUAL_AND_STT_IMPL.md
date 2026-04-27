# AI 예약 로직 — 잔여 과제 처리 + STT 오류 대비 + User Story 재점검 리포트

- 작성일: 2026-04-10 15:00
- 상태: 구현 완료
- 선행 리포트: `2026-04-10_1410_BOOKING_USER_STORY_IMPL.md`
- 관련 경로:
  - `src/ai_voicebot/langgraph/nodes/booking_agent.py`
  - `src/ai_voicebot/langgraph/tools/booking_tools.py`
  - `src/services/booking_service.py`

---

## 개요

1. 이전 리포트의 잔여 과제 2건(`search_bookings_by_phone_future` 이관, 중복 예약 방지)을 완료했습니다.
2. STT 오류로 잘못된 예약 정보가 입력될 수 있는 문제를 대비하여, **예약 생성·변경·취소 실행 전 필수 확인 발화**를 시스템 프롬프트에 반영했습니다.
3. 기존 12개 User Story를 STT 편차 항목 포함하여 재점검했습니다.

---

## 변경 이력 (파일별)

| 파일 경로 | 변경 유형 | 요약 | 비고 |
|---|---|---|---|
| `src/ai_voicebot/langgraph/nodes/booking_agent.py` | 수정 | `search_bookings_by_phone_future` → `search_bookings_by_phone`으로 이관 | T1-1 |
| `src/ai_voicebot/langgraph/nodes/booking_agent.py` | 수정 | 시스템 프롬프트에 STT 오류 방지 확인 절차 추가 (신규·reschedule·cancel·update 전 확인 발화) | T2-1 |
| `src/services/booking_service.py` | 수정 | `create_booking`에 동일 고객·동일 슬롯 중복 예약 방지 체크 추가 | T1-2 |

---

## 주요 변경 내용

### [T1-1] `search_bookings_by_phone_future` 이관

`booking_agent_node`의 발신자 미래 예약 사전 조회를 기존 `search_bookings_by_phone_future`에서
`search_bookings_by_phone(include_past=False)`로 변경했습니다.

- `search_bookings_by_phone_future`는 삭제하지 않고 하위 호환 유지
- `search_bookings_by_phone`이 단일 진입점으로 미래/과거를 모두 처리

---

### [T1-2] 동일 고객·동일 슬롯 중복 예약 방지

`create_booking` 서비스에 `INSERT` 직전 중복 체크 쿼리를 추가했습니다.

**체크 조건:**
- `slot_id`가 있으면: `owner + customer_phone + slot_id + status='confirmed'`
- `slot_id`가 없으면: `owner + customer_phone + slot_date + slot_time + status='confirmed'`

**동작:**
- 중복 감지 시 `create_booking_duplicate_detected` WARNING 로그 기록
- `ValueError("동일 날짜·시간에 이미 예약이 있습니다. 기존 예약번호: {dup_id}")` 발생
- LLM이 에러 메시지를 받아 기존 예약 안내 후 대화 진행

---

### [T2-1] STT 오류 방지 — 예약 생성 전 필수 확인 절차

음성 통화 STT는 날짜·시간·이름·인원을 잘못 인식할 수 있습니다.
이를 방지하기 위해 시스템 프롬프트에 다음 내용을 추가했습니다.

**신규 예약 (`create_booking_tool` 직전):**
> "확인해 드리겠습니다. [날짜] [시간], [인원]명, 성함은 [이름]으로 예약 진행할까요?"

**일정 변경 (`reschedule_booking_tool` 직전):**
> "예약번호 [ID]를 [새날짜] [새시간]으로 변경할까요?"

**취소 (`cancel_booking_tool` 직전):**
> "[날짜] [시간] 예약을 취소할까요?"

**인원 변경 (`update_booking_tool` 직전):**
> "인원을 [N]명으로 변경할까요?"

**정정 흐름:**
- 고객 긍정 → 즉시 Tool 호출
- 고객 정정 → 해당 필드만 재수집 후 재확인 1회

---

## User Story 재점검 (STT 편차 포함)

### 기존 12개 User Story 재점검 결과

| User Story | 수용 여부 | 이번 회차 개선 | 비고 |
|---|---|---|---|
| US-01 신규 예약 (기본) | ✅ | STT 확인 발화 추가 | 확인 후 예약 생성 |
| US-02 발신자 번호 자동 적용 | ✅ | — | 코드 레벨 안전장치 유지 |
| US-03 슬롯 없는 날짜 요청 | ✅ | 이전 회차에서 인접 날짜 안내 추가됨 | GAP-02 해소 |
| US-04 이번 주 아무 때나 | ✅ | — | LLM 날짜 계산 의존 (변동 없음) |
| US-05 예약 변경 (reschedule) | ✅ | reschedule 전 확인 발화 추가 | STT 오류 방지 |
| US-06 예약 취소 | ✅ | 취소 전 확인 발화 추가, owner 검증 적용 | BUG-03 해소 |
| US-07 예약 조회 (미래) | ✅ | — | 변동 없음 |
| US-07b 과거 예약 조회 | ✅ | `include_past=true` 신규 지원 | GAP-03 해소 |
| US-08 인원 변경 | ✅ | capacity 체크 + 변경 전 확인 발화 추가 | BUG-02 해소 |
| US-09 정원 초과 슬롯 요청 | ✅ | — | 서비스 레벨 방어 유지 |
| US-10 영업시간 혼합 질문 | ✅ | — | 변동 없음 |
| US-11 다발화 정보 수집 | ✅ | STT 확인으로 수집 오류 수정 가능 | 확인 발화가 안전망 역할 |
| US-12 기존 예약 있는 재예약 | ✅ | 중복 예약 방지 체크 추가 | 동일 슬롯 중복 방어 |

### 신규 User Story — STT 오류 시나리오

| # | User Story | 시나리오 | 수용 여부 |
|---|---|---|---|
| US-13 | **STT 날짜 오인식 정정** | AI: "내일 오후 2시로 예약할까요?" → 고객: "아니요, 모레요" → AI 재수집 후 재확인 | ✅ |
| US-14 | **STT 이름 오인식 정정** | AI: "홍길순으로 예약할까요?" → 고객: "홍길동이요" → 수정 후 재확인 | ✅ |
| US-15 | **STT 인원 오인식 정정** | AI: "1명으로 예약할까요?" → 고객: "아니요 2명이요" → 수정 후 재확인 | ✅ |
| US-16 | **연속 정정 (2회)** | 날짜 정정 → 재확인 → 시간도 정정 | ✅ (각 정정마다 재확인 1회) |
| US-17 | **모두 맞아요** | 확인 발화 후 고객 "네, 맞아요" → 즉시 예약 생성 | ✅ |

### 전체 수용 현황 (17개 기준)

| 구분 | 수량 |
|---|---|
| ✅ 수용 가능 | 17개 (100%) |
| ⚠️ 부분 수용 | 0개 |
| ❌ 미수용 | 0개 |

---

## 주요 결정 사항

1. **확인 발화는 프롬프트 레벨로 구현**: STT 오류 방지를 위한 확인·정정 흐름은 별도 Tool이나 State 변수 없이 시스템 프롬프트 지침으로만 구현했습니다. LangGraph 노드 구조를 건드리지 않아 리스크를 최소화합니다.

2. **확인 1회 제한**: "확인 발화는 1회만 하세요" 규칙을 명시해 LLM이 과도하게 재확인을 반복하는 것을 방지합니다.

3. **중복 체크는 트랜잭션 내부**: `BEGIN IMMEDIATE` 잠금 안에서 중복 체크와 INSERT를 원자적으로 수행하므로 동시 예약 경쟁 상태에서도 안전합니다.

---

## 잔여 과제

| 항목 | 내용 | 우선순위 |
|---|---|---|
| STT 확인 발화 실효성 모니터링 | 실제 통화 로그에서 확인 발화 후 정정 발생 비율 추적 | 낮음 |
| `search_bookings_by_phone_future` 제거 | 충분한 운영 기간 후 레거시 함수 삭제 | 낮음 |
