# AI 예약 로직 User Story 기반 점검 — 구현 리포트

- 작성일: 2026-04-10 14:10
- 상태: 구현 완료
- 참고 점검 리포트: `2026-04-10_1220_BOOKING_USER_STORY_INSPECTION.md`
- 관련 경로:
  - `src/ai_voicebot/langgraph/nodes/booking_agent.py`
  - `src/ai_voicebot/langgraph/tools/booking_tools.py`
  - `src/services/booking_service.py`

---

## 개요

`2026-04-10_1220_BOOKING_USER_STORY_INSPECTION.md`에서 식별된 6개 잔여 과제(BUG 3건, GAP 3건)를 모두 구현했습니다.  
P1(즉시 수정 2건) → P2(단기 수정 3건) → P3(낮음 1건) 순으로 처리했습니다.

---

## 변경 이력 (파일별)

| 파일 경로 | 변경 유형 | 요약 | 비고 |
|---|---|---|---|
| `src/ai_voicebot/langgraph/nodes/booking_agent.py` | 수정 | 시스템 프롬프트 개선 3건 | P1-1, P2-3 |
| `src/ai_voicebot/langgraph/tools/booking_tools.py` | 수정 | `_create_booking` extra_data 추가, `_cancel_booking` owner 추가, `_search_my_bookings` include_past 추가 | P1-2, P2-1, P3-1 |
| `src/services/booking_service.py` | 수정 | `cancel_booking` owner 검증, `update_booking` capacity 체크, `search_bookings_by_phone` 신규 함수 | P2-1, P2-2, P3-1 |

---

## 주요 변경 내용

### [P1-1] 시스템 프롬프트: `update_booking_tool` vs `reschedule_booking_tool` 역할 명확화

**문제:** 시스템 프롬프트 "수정 절차"에 날짜/시간/인원 모두 `update_booking_tool`을 사용하라고 안내되어 있어 LLM이 날짜 변경에도 `update_booking_tool`을 선택할 수 있었음.

**해결:**
- "일정 변경(reschedule) 절차"에 **`update_booking_tool`로 날짜·시간을 변경하면 슬롯 정원 데이터가 깨진다**는 경고 문구 추가.
- "수정 절차 (인원·메모 변경 전용)" 섹션 제목과 설명에 `update_booking_tool`의 적용 범위를 `party_size`, `memo`로 명시.

---

### [P1-2] `_create_booking` Tool에 `extra_data: dict` 파라미터 추가

**문제:** 시스템 프롬프트가 LLM에게 도메인 추가 필드를 `extra_data`로 전달하라 지시하지만 Tool 시그니처에 파라미터가 없어 LLM 호출이 무시됨(GAP-01).

**해결:**
- `_create_booking` 함수에 `extra_data: Optional[dict] = None` 파라미터 추가.
- `BookingCreate(extra_data=extra_data or {})` 로 전달.
- docstring에 `get_booking_settings`의 `domain_extra_fields`/`schema_extra_fields`와의 연동 설명 추가.

---

### [P2-1] `cancel_booking` 서비스에 `owner` 검증 추가

**문제:** `cancel_booking(booking_id)` 가 `owner` 없이 `booking_id`만으로 취소되어 다른 테넌트 예약을 취소할 수 있는 보안 취약점(BUG-03).

**해결:**
- `cancel_booking(booking_id, owner: Optional[str] = None)` 으로 시그니처 변경.
- `owner`가 지정된 경우 DB 조회 결과의 `row["owner"]`와 비교, 불일치 시 `WARNING` 로그 후 `None` 반환.
- `_cancel_booking` Tool도 `owner: str = ""` 파라미터 추가, `cancel_booking(booking_id, owner=owner or None)` 호출.
- Tool 에러 메시지를 "찾을 수 없거나 **접근 권한이 없습니다**"로 변경.

---

### [P2-2] `update_booking` 서비스에 `party_size` 변경 시 capacity 체크 추가

**문제:** `update_booking_tool`로 인원을 변경할 때 슬롯 capacity 검증 없이 DB가 갱신됨(BUG-02).

**해결:**
- `data.party_size is not None`인 경우, 해당 예약의 `slot_id` → `booking_slots.capacity`, `booked_count` 조회.
- 가용 인원 계산: `available_after = capacity - (booked_count - old_party_size)`.
- `data.party_size > available_after`이면 `ValueError` 발생.
- 검증 실패 시 `update_booking_capacity_exceeded` WARNING 로그 기록.

---

### [P2-3] 슬롯 없는 날짜 처리: 인접 날짜 자동 조회 프롬프트 지침 추가

**문제:** 슬롯이 없을 때 LLM이 고객에게 공을 넘기는 단순 안내만 할 가능성이 높았음(GAP-02).

**해결:** 시스템 프롬프트에 "슬롯 없는 날짜 처리" 섹션 신규 추가:
1. `check_multi_date_slots(요청날짜, 요청날짜+7일)` 를 즉시 호출해 인접 1주일 가용 날짜 조회.
2. 가용 날짜가 있으면 구체적인 대안 날짜를 안내.
3. 1주일 내 없으면 "다른 날짜를 말씀해 주시면 확인해 드리겠습니다" 로 안내.

---

### [P3-1] `search_my_bookings` Tool에 `include_past` 지원 (과거 예약 조회)

**문제:** `search_my_bookings`와 `search_bookings_by_phone_future` 모두 미래 예약만 반환해 "지난 예약" 조회 수단이 없었음(GAP-03).

**해결:**
- `booking_service.py`에 `search_bookings_by_phone(owner, customer_phone, include_past=False, limit=10)` 신규 함수 추가.
  - `include_past=True`: 현재 시각 이전 예약을 `slot_date DESC` 정렬로 반환.
  - `include_past=False`: 기존 미래 예약 전용 쿼리와 동일.
- `_search_my_bookings` Tool에 `include_past: bool = False` 파라미터 추가.
- 기존 `search_bookings_by_phone_future`는 하위 호환 유지를 위해 삭제하지 않음.

---

## 주요 결정 사항

1. **`cancel_booking` 하위 호환**: `owner` 파라미터를 `Optional`로 추가해 기존 직접 호출 코드(API 라우터 등)에서 `owner`를 넘기지 않아도 동작하도록 유지. Tool에서만 자동 주입.

2. **`update_booking` capacity 체크 범위**: `slot_id`가 없는 예약(슬롯 미연동)은 capacity 체크를 스킵. 슬롯 연동이 확실한 경우에만 검증.

3. **`search_bookings_by_phone_future` 유지**: 기존 함수를 삭제하지 않고 `search_bookings_by_phone`을 신규 추가해 점진적 이관. LLM 컨텍스트 사전 주입(`booking_agent_node`)은 계속 기존 함수를 사용.

4. **슬롯 없는 날짜 처리**: 1주일 범위로 인접 조회를 지시. 고객이 요청한 날짜 기준 +7일로 제한해 응답 지연을 최소화.

---

## 잔여 과제

| 항목 | 내용 | 우선순위 |
|---|---|---|
| `search_bookings_by_phone_future` 이관 | `booking_agent_node` 컨텍스트 주입을 `search_bookings_by_phone`으로 통합 | 낮음 |
| 동일 슬롯 중복 예약 방지 | `create_booking` 서비스에 동일 고객·동일 슬롯 중복 체크 (US-12 주의 사항) | 낮음 |
