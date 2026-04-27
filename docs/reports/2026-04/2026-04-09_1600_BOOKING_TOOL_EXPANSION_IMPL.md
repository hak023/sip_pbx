# Booking Tool 확장 구현 리포트

| 항목 | 내용 |
|---|---|
| 작성일 | 2026-04-09 |
| 상태 | 구현 완료 |
| 관련 경로 | `sip-pbx/src/ai_voicebot/langgraph/tools/booking_tools.py` |
| 참고 리포트 | `2026-04-09_1130_BOOKING_TOOL_EXPANSION_RESEARCH.md` |

---

## 1. 구현 범위 요약

리서치 리포트(A/B/C)의 항목을 다음과 같이 처리했습니다.

| 항목 | Tool | 처리 | 비고 |
|---|---|---|---|
| A-1 | `reschedule_booking_tool` | ✅ 신규 구현 | 원자적 슬롯 카운트 이동 |
| A-2 | `check_multi_date_slots` | ✅ 신규 구현 | 날짜 범위 1회 조회 |
| A-3 | `search_my_bookings` (기존) | ✅ 점검·보완 | 발신번호→예약조회 정상 확인, caller_number 주입 경로 보완 |
| A-4 | `add_booking_memo_tool` | ✅ 신규 구현 | 기존 메모에 줄바꿈 이어붙임 |
| B-2 | 웨이팅 리스트 | ❌ 제외 (사용자 요청) | |
| B-3 | `get_business_hours_tool` | ✅ 신규 구현 | 영업시간 연동 체크박스 UI 포함 |
| B-4 | `send_booking_sms` (기존) | ✅ 점검 | 정상 구현 확인 |
| C-1 | transfer_to_human | ❌ 제외 (이미 존재) | INVITE 방식으로 기구현 |
| C-2 | `search_knowledge_tool` | ✅ 신규 구현 | KB 없으면 graceful fallback |
| C-3 | `get_call_context_tool` | ✅ 신규 구현 + 레이아웃 보완 | 통화이력·시각·발신번호 시스템 프롬프트 주입 |

---

## 2. 변경 파일 목록

### 백엔드

#### `sip-pbx/src/services/booking_service.py`
신규 함수 4개 추가:

```python
reschedule_booking(booking_id, new_slot_date, new_slot_time)  # 원자적 일정 변경
check_multi_date_slots(owner, start_date, end_date, party_size)  # 날짜 범위 슬롯 조회
add_booking_memo(booking_id, memo)  # 메모 추가 (기존 메모 이어붙임)
get_business_hours(owner)  # extra_config.business_hours 조회
```

#### `sip-pbx/src/ai_voicebot/langgraph/tools/booking_tools.py`
신규 Tool 6개 추가, `BOOKING_TOOLS` 리스트 14개로 확장:

| Tool 함수명 | 설명 |
|---|---|
| `reschedule_booking_tool` | 예약 일정 변경 (원자적 처리) |
| `check_multi_date_slots` | 날짜 범위 가용 슬롯 일괄 조회 |
| `add_booking_memo_tool` | 예약 메모/특이사항 추가 |
| `get_business_hours_tool` | 영업시간·휴무일 조회 |
| `get_call_context_tool` | 현재 통화 컨텍스트 반환 |
| `search_knowledge_tool` | 지식베이스 검색 (혼합 질문 처리) |

#### `sip-pbx/src/ai_voicebot/langgraph/nodes/booking_agent.py`
- `_MAX_TOOL_ROUNDS`: 5 → **8** (복잡한 tool 체인 지원)
- `_SMS_TRIGGER_TOOLS`: `reschedule_booking_tool` 추가
- `_OWNER_TOOLS`: 신규 6개 Tool 추가
- **C-3 과거 통화 이력 주입**: 같은 테넌트 과거 통화 최대 3건 요약을 시스템 프롬프트에 추가
- **C-3 발신자 번호 자동 주입**: `create_booking_tool` 호출 시 `customer_phone` 미전달 시 `caller_number` 자동 주입
- **C-3 프롬프트 개선**: 발신자 번호가 있으면 `customer_phone`을 되묻지 않도록 명시
- 시스템 프롬프트에 `reschedule`, `check_multi_date_slots`, `get_business_hours`, `search_knowledge_tool` 절차 추가

#### `sip-pbx/src/ai_voicebot/pipecat/processors/rag_processor.py`
- **A-3 보완**: `process_utterance` 호출 시 `caller_number=caller_number_for_agent` 전달 누락 수정
  - `self._caller_id` → `caller_number` 파라미터로 LangGraph agent에 전달

---

### 프론트엔드

#### `sip-pbx/frontend/app/booking/slots/page.tsx`
- `BulkForm` 인터페이스에 `link_business_hours: boolean` 추가 (default: `true`)
- 일괄 생성 폼에 **"영업시간 AI 연동" 체크박스** 추가
- 체크 시 일괄 생성 전에 `PUT /api/booking/settings/{owner}`를 호출하여 `extra_config.business_hours` 저장:
  ```json
  {
    "open_time": "work_start",
    "close_time": "work_end",
    "break_start": "exclude_windows[0].start",
    "break_end": "exclude_windows[0].end",
    "closed_days": ["요일 미선택 목록"],
    "linked_to_slots": true
  }
  ```
- 연동 안내 메시지 박스 표시 (체크 시 노출)

---

## 3. 주요 구현 상세

### A-1 `reschedule_booking` — 원자적 일정 변경

```
BEGIN IMMEDIATE
  1. 기존 슬롯 booked_count -= 1
  2. 새 슬롯 조회 → booked_count >= capacity 면 rollback + ValueError
  3. 새 슬롯 booked_count += 1
  4. bookings 날짜/시간/slot_id 업데이트
COMMIT
```

기존 `update_booking_tool`과 달리 슬롯 카운트를 **원자적으로** 이동합니다.

### A-2 `check_multi_date_slots` — 날짜 범위 슬롯 조회

```sql
SELECT slot_date,
       COUNT(*) as slot_count,
       SUM(CASE WHEN (capacity - booked_count) >= party_size THEN 1 ELSE 0 END) as available_count
FROM booking_slots
WHERE owner = ? AND slot_date BETWEEN ? AND ? AND is_blocked = 0
GROUP BY slot_date HAVING available_count > 0
ORDER BY slot_date
```

LLM이 "이번 주 언제 가능해요?" 질문에 **1회 tool 호출**로 답할 수 있습니다.

### A-3 점검 결과 — 발신번호 기반 예약 처리

**기존 구현 점검 결과:**
- `search_bookings_by_phone_future(owner, customer_phone)`: 현재 시각 이후 확정 예약 조회 ✅
- `search_my_bookings` Tool: 전화번호로 미래 예약 목록 반환 ✅
- `booking_agent_node`: 발신자 번호로 미래 예약 사전 검색 후 시스템 프롬프트에 주입 ✅

**발견된 문제 (보완):**
- `rag_processor.py`의 `process_utterance` 호출 시 `caller_number`를 전달하지 않아 `_caller_number` state가 항상 빈 문자열이 되는 버그 발견
- **수정**: `caller_number=getattr(self, "_caller_id", None) or ""` 추가 → LangGraph `_caller_number` state에 정상 주입

### B-3 `get_business_hours` — 영업시간 연동

저장 위치: `booking_settings.extra_config.business_hours` (JSON)

```json
{
  "open_time": "09:00",
  "close_time": "18:00",
  "break_start": "12:00",
  "break_end": "13:00",
  "closed_days": ["Saturday", "Sunday"],
  "linked_to_slots": true
}
```

슬롯 일괄 생성 시 "영업시간 AI 연동" 체크박스(default 체크)를 통해 자동 저장됩니다.

AI 봇이 영업시간 문의를 받으면 `get_business_hours_tool` → `get_booking_settings` → `extra_config.business_hours` 순으로 조회합니다.

### B-4 SMS 점검 결과

**구현 경로**: `send_booking_sms` Tool → `POST /api/booking/sms/send` → `send_sip_sms_sync()` → UDP SIP MESSAGE 전송

**점검 결과**: 정상 구현 확인 ✅
- `sip_sms_service.py`: RFC 3428 SIP MESSAGE 템플릿 구현, `sms_log` 테이블에 발송 이력 기록
- `booking.py` 라우터: `SmsSendRequest` 모델, `SIP_SERVER_IP`/`SIP_SERVER_PORT` 환경변수 지원
- `booking_agent_node`: `_SMS_TRIGGER_TOOLS`에 등록된 tool 실행 후 자동 SMS 발송 (to_phone 미전달 시 발신번호 자동 보완)

### C-2 `search_knowledge_tool` — 지식베이스 검색

예약 상담 중 혼합 질문("메뉴도 알려주세요" 등)에 대응합니다.

- Vector DB 사용 가능 시 → `Embedder + VectorDB.search(top_k=3)` 실행
- Vector DB 없거나 오류 시 → graceful fallback 메시지 반환

### C-3 `get_call_context` — 통화 컨텍스트 주입

**시스템 프롬프트 자동 주입 (LLM이 tool 없이도 항상 보유):**

```
오늘 날짜: 2026-04-09 (수요일), 현재 시각: 16:00
발신자 전화번호: 010-1234-5678 ← 이 번호를 customer_phone으로 자동 사용하세요. 되묻지 마세요.
[발신자(010-1234-5678) 미래 예약 목록]
  - 예약번호:bk_abc123 / 2026-04-12 14:00 / 홍길동 2명 / 상태:confirmed
[이전 통화 이력 요약]
  - [2026-04-07 10:32] Q: 내일 예약 가능한가요? A: 네, 오후 2시에 슬롯이 있습니다...
```

**`customer_phone` 자동 주입 (되묻지 않음):**
- `create_booking_tool` 호출 시 `customer_phone` 미전달 → 발신자 번호 자동 주입
- 수집 현황 표시: "발신자 번호 자동 적용"

---

## 4. 검증 포인트

### A-1 reschedule 테스트 시나리오
```
고객: 내일 오후 2시 예약을 모레 3시로 바꿔주세요.
AI: [search_my_bookings → booking_id 확인]
    [reschedule_booking_tool(bk_xxx, 2026-04-10, 15:00)]
    → 슬롯 카운트 원자적 이동 확인
    [send_booking_sms → 변경 확인 SMS]
```

### A-2 다중 날짜 테스트
```
고객: 이번 주 언제 두 명 예약 가능한가요?
AI: [check_multi_date_slots(start=월, end=일, party_size=2)]
    → 1회 호출로 날짜별 슬롯 수 응답
```

### A-3 발신번호 자동 조회 테스트
```
고객: (010-1234-5678 에서 전화)
     제 예약 취소해 주세요.
AI: (시스템 프롬프트에 미래 예약 목록 이미 주입됨)
    [cancel_booking_tool(bk_xxx)]  # search_my_bookings 호출 없이 바로 처리
```

### C-3 customer_phone 자동 적용 테스트
```
고객: (010-1234-5678 에서 전화)
     내일 오후 2시에 홍길동으로 예약해 주세요.
AI: (날짜, 시간, 이름 수집 완료)
    [create_booking_tool(customer_phone="010-1234-5678" 자동 주입)]  # 전화번호 묻지 않음
```

---

## 5. 현재 BOOKING_TOOLS 목록 (14개)

```python
BOOKING_TOOLS = [
    check_available_slots,      # 단일 날짜 슬롯 조회 (기존)
    check_multi_date_slots,     # 날짜 범위 슬롯 조회 (A-2 신규)
    get_booking_info,           # 예약번호로 상세 조회 (기존)
    create_booking_tool,        # 예약 생성 (기존)
    cancel_booking_tool,        # 예약 취소 (기존)
    reschedule_booking_tool,    # 예약 일정 변경 (A-1 신규)
    get_booking_settings,       # 도메인 설정 조회 (기존)
    get_business_hours_tool,    # 영업시간 조회 (B-3 신규)
    update_booking_tool,        # 예약 수정 (기존)
    add_booking_memo_tool,      # 메모 추가 (A-4 신규)
    search_my_bookings,         # 발신번호로 예약 검색 (기존)
    send_booking_sms,           # SIP SMS 발송 (기존)
    get_call_context_tool,      # 통화 컨텍스트 조회 (C-3 신규)
    search_knowledge_tool,      # 지식베이스 검색 (C-2 신규)
]
```

---

## 6. 알려진 제약 및 향후 과제

| 항목 | 내용 |
|---|---|
| `get_business_hours` break_start/end | exclude_windows[0]만 저장. 복수 제외 시간대는 미지원 |
| `search_knowledge_tool` | Vector DB 미구성 시 KB 검색 불가 (graceful fallback 처리됨) |
| 과거 통화 이력 필터링 | 현재는 `callee` 기준으로 필터링. 향후 `caller_id` 기준 정확한 필터 필요 |
| `_MAX_TOOL_ROUNDS = 8` | 복잡한 시나리오에서 8회 초과 시 중간 응답 없이 에러 메시지 반환 |
| SMS 발송 | SIP MESSAGE 방식이므로 softphone이 아닌 일반 PSTN에는 미도달 |
