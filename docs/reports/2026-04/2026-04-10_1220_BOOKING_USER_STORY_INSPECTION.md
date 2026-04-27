# AI 예약 로직 User Story 기반 점검 리포트

- 작성일: 2026-04-10
- 상태: 점검 완료 (결함 6건 식별)
- 관련 경로:
  - `src/ai_voicebot/langgraph/nodes/booking_agent.py`
  - `src/ai_voicebot/langgraph/tools/booking_tools.py`
  - `src/services/booking_service.py`
  - `src/ai_voicebot/langgraph/nodes/classify_intent.py`

---

## 1. 대표 User Story 목록

| # | User Story | 시나리오 |
|---|-----------|---------|
| US-01 | **신규 예약 (기본)** | 고객이 날짜·시간·인원·이름을 순서대로 답하고 예약 완료 |
| US-02 | **발신자 번호 자동 적용** | 발신자 번호가 있을 때 전화번호를 묻지 않고 예약 생성 |
| US-03 | **슬롯 없는 날짜 요청** | 고객이 원하는 날짜에 빈 슬롯이 없을 때 다른 날짜 안내 |
| US-04 | **이번 주 아무 때나** | "이번 주 언제 가능해요?" → 복수 날짜 가용 슬롯 안내 |
| US-05 | **예약 변경 (reschedule)** | 기존 예약을 다른 날짜/시간으로 이동 |
| US-06 | **예약 취소** | 고객이 예약을 취소 요청 |
| US-07 | **예약 조회** | "제 예약 언제예요?" |
| US-08 | **인원 변경 (update)** | 예약된 인원 수를 변경 |
| US-09 | **정원 초과 슬롯 요청** | 고객이 원하는 시간이 이미 만석일 때 |
| US-10 | **예약 중 영업시간 질문** | "몇 시까지 해요?" 혼합 발화 |
| US-11 | **여러 발화에 걸친 정보 수집** | 정보를 조금씩 나누어 제공하는 고객 |
| US-12 | **이미 예약이 있는 고객 재예약** | 기존 예약 안내 후 추가 예약 진행 |

---

## 2. User Story별 현재 로직 수용 여부

---

### US-01: 신규 예약 (기본)
> 고객: "내일 오후 2시 2명으로 예약하고 싶어요" → "성함이 어떻게 되세요?" → "홍길동이요" → 예약 완료

**흐름:**
1. `classify_intent` → `intent=booking`
2. `route_utterance` → `utterance_lane=booking` → `booking_agent`
3. `get_booking_settings` (1회) → `check_available_slots(내일, 2명)`
4. 슬롯 있으면 이름 질문 → `create_booking_tool` → `send_booking_sms`

**판정: ✅ 수용 가능**

**주의:** 현재 시스템 프롬프트에서 `get_booking_settings`를 **첫 번째 발화에서 즉시 호출**하도록 지시하는데, LLM이 때로 settings를 먼저 조회하지 않고 슬롯 조회로 바로 넘어갈 수 있음. `settings_cache`가 없으면 `_format_settings_hint`는 빈 문자열이므로 두 번째 발화부터 수집 정책 주입됨.

---

### US-02: 발신자 번호 자동 적용
> 발신자 번호 010-1234-5678 → 전화번호 없이 예약 완료

**흐름:**
- `caller_number`가 `booking_agent_node`로 전달됨
- SystemMessage에 `발신자 전화번호: 010-1234-5678 ← 되묻지 마세요` 명시
- `create_booking_tool` 호출 시 `tool_args["customer_phone"]` 자동 주입 (코드 레벨 보장)

**판정: ✅ 수용 가능 (코드 레벨 안전장치 있음)**

---

### US-03: 슬롯 없는 날짜 요청
> "4월 15일 예약 가능해요?" → 해당 날짜 슬롯 없음 → 다른 날짜 제안

**흐름:**
- `check_available_slots(2026-04-15)` → `{"available": false, "slots": []}`
- 시스템 프롬프트: "슬롯이 없으면 다른 날짜/시간을 제안하세요"

**판정: ⚠️ 부분 수용**

**문제:** LLM에게 "다른 날짜 제안"을 지시하지만 **구체적인 가용 날짜를 능동적으로 알려주는 Tool 호출 지침이 없음**. LLM이 "죄송합니다, 해당 날짜는 예약이 어렵습니다. 다른 날짜를 말씀해 주시겠어요?"로 공을 고객에게 넘길 가능성이 높음. `check_multi_date_slots`를 자동으로 호출해 가까운 가용 날짜를 안내하는 절차가 없음.

---

### US-04: "이번 주 아무 때나"
> "이번 주 언제 가능해요?" → 가용 날짜/시간 안내

**흐름:**
- 프롬프트: "이번 주 언제 가능해요?" → `check_multi_date_slots(start_date, end_date)` 1회 호출
- `check_multi_date_slots` 서비스 함수 정상 구현됨

**판정: ✅ 수용 가능**

**주의:** 오늘 날짜는 SystemMessage에 주입되지만 "이번 주"의 start/end를 LLM이 계산해야 함. 오늘이 금·토·일인 경우 LLM이 "이번 주"를 다음 주로 해석할 수 있음.

---

### US-05: 예약 변경 (reschedule)
> "제 예약을 이번 주 목요일 오전 10시로 바꾸고 싶어요"

**흐름:**
1. `[발신자 미래 예약 목록]`에서 `booking_id` 확인 (사전 주입됨)
2. 새 날짜/시간 수집 → `check_available_slots` 확인
3. `reschedule_booking_tool` 호출 → 원자적 처리
4. `send_booking_sms` 발송

**서비스 레벨:** `reschedule_booking`은 트랜잭션 안에서 구 슬롯 감소 + 신 슬롯 증가 + bookings 업데이트를 원자적으로 처리. 정원 초과 시 rollback.

**판정: ✅ 수용 가능**

**문제점:**
- 새 슬롯이 DB에 존재하지 않을 경우 (슬롯 미생성 상태) `new_slot_id = None`으로 처리되어 `slot_id`가 `NULL`로 저장됨. 날짜/시간은 업데이트되지만 슬롯 카운트 반영이 안 됨. 프롬프트에 "변경 전 `check_available_slots`로 확인하라"는 지침은 있으나, **확인 후 reschedule 시 새 슬롯이 없으면 어떻게 처리하라는 안내 없음**.

---

### US-06: 예약 취소
> "예약 취소해 주세요"

**흐름:**
1. `[발신자 미래 예약 목록]`에서 `booking_id` 확인
2. 목록 없으면 `search_my_bookings` 호출
3. `cancel_booking_tool` 호출
4. `send_booking_sms` 발송

**판정: ✅ 수용 가능**

**문제점:**
- `cancel_booking_tool`의 `_cancel_booking` 함수는 `booking_id`만 받음. `owner` 검증 없이 booking_id만으로 취소 가능 → **다른 테넌트의 예약을 취소할 수 없지만, 동일 발신자가 다른 테넌트 예약번호를 알면 취소 가능** (서비스 레벨에 owner 검증 없음).
- 복수 예약 중 하나만 취소할 때 LLM이 어느 것을 취소할지 특정하는 대화 지침이 명시적으로 없음.

---

### US-07: 예약 조회
> "제 예약 언제예요?"

**흐름:**
- `[발신자 미래 예약 목록]`이 이미 SystemMessage에 주입됨
- 프롬프트: "Tool 호출 없이 바로 안내 가능"

**판정: ✅ 수용 가능**

**주의:** 미래 예약만 사전 주입됨(`search_bookings_by_phone_future`). "지난 달 예약이 어떻게 됐나요?" 같은 **과거 예약 조회는 Tool 호출 필요**하나, `search_my_bookings`도 미래 예약만 반환. 과거 예약 조회 수단이 없음.

---

### US-08: 인원 변경
> "예약 인원을 3명으로 바꿔주세요"

**흐름:**
1. `[발신자 미래 예약 목록]`에서 `booking_id` 확인
2. `update_booking_tool(booking_id, party_size=3)`

**판정: ⚠️ 부분 수용**

**문제점:**
- `update_booking_tool`은 내부적으로 `update_booking(booking_id, BookingUpdate(...))` 호출.
- `update_booking`은 `slot_date`/`slot_time`/`party_size`/`memo`만 수정하며 **슬롯 용량 체크를 하지 않음**.
- 즉, 슬롯 capacity=2인데 `party_size=5`로 변경해도 서비스 레벨에서 막지 않음.
- 또한 `update_booking`은 **slotbooked_count를 재계산하지 않음** (reschedule과 달리 booked_count 미반영).

---

### US-09: 정원 초과 슬롯 요청
> "오후 3시로 해 주세요" → 해당 슬롯이 만석

**흐름:**
- `check_available_slots(날짜, party_size)` → `(capacity - booked_count) >= party_size` 필터 → 결과 없음
- LLM이 "해당 시간대는 예약이 마감되었습니다"로 안내

**판정: ✅ 수용 가능**

**참고:** `create_booking_tool` 내부에서도 `booked_count >= capacity`이면 `ValueError` → 에러 메시지 반환. LLM이 재확인 없이 create를 시도해도 서비스 레벨에서 차단됨.

---

### US-10: 예약 중 영업시간 혼합 질문
> "예약 가능한 날짜가 어떻게 되나요? 아 참, 몇 시까지 해요?"

**흐름:**
- 프롬프트: 혼합 질문 → `search_knowledge_tool` 또는 `get_business_hours_tool` 호출
- `get_business_hours_tool` → `found: true`이면 안내, `false`이면 KB 검색

**판정: ✅ 수용 가능**

---

### US-11: 여러 발화에 걸친 정보 수집
> 발화1: "예약하고 싶어요" → 발화2: "내일이요" → 발화3: "오후 2시요" → 발화4: "2명이요" → 발화5: "홍길동이요"

**흐름:**
- `booking_context.messages`로 발화 간 히스토리 유지 (최대 20개)
- `_format_collected_slots`가 매 발화마다 수집 현황 SystemMessage 주입
- `classify_intent`에서 `_booking_active=True`이면 `booking` 분류 우선

**판정: ✅ 수용 가능**

**주의:**
- `_BOOKING_KEYWORDS = frozenset()`으로 비활성화되어 있어 첫 발화의 `booking` 분류는 전적으로 LLM에 의존.
- "예약하고 싶어요" 같은 짧은 발화를 LLM이 `question`으로 분류하면 `booking_agent`에 도달하지 못함.

---

### US-12: 기존 예약 있는 고객 재예약
> 발신자에게 이미 4/15 예약이 있을 때 "이번 주 금요일에도 하나 더 예약할게요"

**흐름:**
- `[발신자 미래 예약 목록]`이 SystemMessage에 이미 표시됨
- LLM이 기존 예약을 인지한 채 신규 예약 절차 진행

**판정: ✅ 수용 가능**

**주의:**
- 동일 고객의 동일 슬롯 중복 예약 방지 로직이 없음. `create_booking` 서비스에 중복 체크 없어 동일 슬롯에 여러 건 생성 가능(capacity 내에서).

---

## 3. 발견된 결함/미구현 항목

| # | 분류 | 심각도 | 설명 | 관련 파일 |
|---|------|--------|------|-----------|
| BUG-01 | 데이터 정합성 | 🔴 높음 | `update_booking_tool`이 날짜/시간 변경 시 슬롯 `booked_count`를 갱신하지 않음 (`reschedule_booking`과 달리 단순 UPDATE). 날짜 변경 시 구 슬롯 감소·신 슬롯 증가 없음. | `booking_service.py:update_booking` |
| BUG-02 | 데이터 정합성 | 🟡 중간 | `update_booking_tool`의 인원 변경 시 슬롯 용량(capacity) 검증 없음. 슬롯 capacity 초과 인원으로 설정 가능. | `booking_service.py:update_booking` |
| BUG-03 | 보안 | 🟡 중간 | `cancel_booking_tool`의 `_cancel_booking`이 `owner` 검증 없이 `booking_id`만으로 취소 처리. 서비스 레벨 owner 확인 없음. | `booking_tools.py:_cancel_booking`, `booking_service.py:cancel_booking` |
| GAP-01 | 기능 누락 | 🟡 중간 | `_create_booking` tool 시그니처에 `extra_data` 파라미터 없음. 시스템 프롬프트는 `extra_data`를 전달하라고 지시하지만 LLM이 호출해도 스키마에 없어 무시됨. | `booking_tools.py:_create_booking` |
| GAP-02 | UX | 🟡 중간 | 슬롯 없는 날짜 요청 시 인접 가용 날짜를 능동적으로 안내하는 프롬프트 지침 없음. LLM이 고객에게 날짜를 다시 묻는 방향으로 응답할 가능성 높음. | `booking_agent.py:_BOOKING_SYSTEM_PROMPT` |
| GAP-03 | 기능 누락 | 🟠 낮음 | 과거 예약 조회 수단 없음. `search_my_bookings`/`search_bookings_by_phone_future` 모두 미래 예약만 반환. | `booking_tools.py`, `booking_service.py` |
| GAP-04 | UX | 🟠 낮음 | 첫 발화 시 `settings_cache`가 없어 `_format_settings_hint`가 빈 문자열. LLM이 settings 조회 전에 이미 기본 5필드 수집을 시작할 수 있음. | `booking_agent.py` |

---

## 4. 심각도별 요약

### 🔴 즉시 수정 권장

**BUG-01**: `update_booking_tool`로 날짜·시간 변경 시 슬롯 카운트가 맞지 않음.

현재 `update_booking_tool` docstring에도 "날짜·시간 변경은 reschedule_booking_tool 사용 권장"이라는 지침이 없어 LLM이 두 Tool을 혼용할 수 있음. 시스템 프롬프트의 "수정 절차"에 `update_booking_tool`이 명시되어 있어 날짜 변경에도 사용될 수 있는 구조.

**권장:** 프롬프트에서 날짜·시간 변경은 반드시 `reschedule_booking_tool`을 사용하도록 명시. `update_booking_tool`은 메모·인원 변경 전용으로 명시.

---

### 🟡 단기 수정 권장

**BUG-02**: 인원 변경 시 capacity 검증 추가 (`update_booking` 서비스에 슬롯 용량 체크).

**BUG-03**: `cancel_booking` 서비스에 owner 파라미터 추가 및 검증.

**GAP-01**: `_create_booking` Tool 시그니처에 `extra_data: dict = None` 파라미터 추가.

**GAP-02**: 슬롯 없을 때 `check_multi_date_slots`로 인접 날짜를 자동 조회하는 프롬프트 지침 추가.

---

## 5. 현재 구현 수용 여부 표

| User Story | 수용 | 비고 |
|-----------|------|------|
| US-01 신규 예약 기본 | ✅ | 정상 |
| US-02 발신자 번호 자동 | ✅ | 코드 레벨 안전 |
| US-03 슬롯 없는 날짜 | ⚠️ | 인접 날짜 능동 안내 없음 (GAP-02) |
| US-04 이번 주 아무 때나 | ✅ | LLM 날짜 계산 의존 |
| US-05 예약 변경 | ✅ | 단, 새 슬롯 미존재 시 카운트 누락 |
| US-06 예약 취소 | ⚠️ | owner 검증 없음 (BUG-03) |
| US-07 예약 조회 | ✅ | 미래 예약만 가능 |
| US-08 인원 변경 | ⚠️ | capacity 검증 없음 (BUG-02) |
| US-09 정원 초과 | ✅ | 서비스 레벨 방어 있음 |
| US-10 영업시간 혼합 | ✅ | 정상 |
| US-11 다발화 수집 | ✅ | 첫 발화 분류 LLM 의존 |
| US-12 기존 예약 재예약 | ✅ | 중복 방지 없음 (인지 필요) |

**12개 중 수용 가능 9개(75%), 부분 수용 3개(25%)**

---

## 6. 잔여 과제 (우선순위 순)

1. **[P1]** 시스템 프롬프트에 `update_booking_tool`은 인원·메모 전용, 날짜·시간 변경은 `reschedule_booking_tool` 사용 명시
2. **[P1]** `_create_booking` Tool에 `extra_data: dict` 파라미터 추가 (도메인 추가 필드 연동 완성)
3. **[P2]** `cancel_booking` 서비스에 owner 검증 추가
4. **[P2]** `update_booking` 서비스에 party_size 변경 시 capacity 체크 추가
5. **[P2]** 슬롯 없을 때 인접 날짜 자동 조회 프롬프트 지침 추가
6. **[P3]** 과거 예약 조회 Tool 또는 기간 파라미터 지원 추가
