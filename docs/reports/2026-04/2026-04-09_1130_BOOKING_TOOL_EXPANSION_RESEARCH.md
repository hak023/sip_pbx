# AI Voicebot Tool 확장 리서치 — Booking 이후 구현 후보

| 항목 | 내용 |
|---|---|
| 작성일 | 2026-04-09 |
| 상태 | 리서치 완료 |
| 관련 경로 | `sip-pbx/src/ai_voicebot/langgraph/tools/booking_tools.py` |
| 참고 | GitHub: cris-m/langgraph_examples, ROCKYBH7/langgraph-customer-support, Maple, XYNTRA, Vocally, Vapi, Lacy.ai |

---

## 1. 현재 구현된 Tool 현황 (기준선)

| Tool 이름 | 설명 |
|---|---|
| `check_available_slots` | 날짜·인원으로 가용 슬롯 조회 |
| `get_booking_info` | 예약번호로 예약 상세 조회 |
| `create_booking_tool` | 예약 생성 (confirmation_msg 치환) |
| `cancel_booking_tool` | 예약 취소 |
| `get_booking_settings` | 도메인 설정 조회 (LLM 안내 메시지 구성용) |

---

## 2. 리서치 결과 — 추가 구현 후보 Tool 목록

리서치 소스: Maple/XYNTRA/Vocally(음식점·병원 보이스봇), Vapi/Lacy.ai(콜센터 플랫폼), GitHub 오픈소스(cris-m/langgraph_examples, ROCKYBH7/langgraph-customer-support)

---

### 우선순위 A — 즉시 효과, 현재 인프라 활용 가능

#### A-1. `reschedule_booking` — 예약 변경
```
현재: create + cancel 두 번 호출해야 변경 가능
문제: LLM이 두 단계를 순서대로 실행해야 해서 오류 가능성 높음
개선: 날짜/시간 변경을 원자적으로 처리
```
- 입력: `booking_id`, `new_slot_date`, `new_slot_time`
- 동작: 기존 슬롯 `booked_count--` → 새 슬롯 `booked_count++` → `bookings` 업데이트 (단일 트랜잭션)
- 난이도: ★★☆☆☆ (BookingService에 메서드 1개 추가)

**보이스봇 대화 예시:**
```
고객: 내일 두 시 예약을 모레 세 시로 바꾸고 싶어요.
AI: [reschedule_booking] 변경 완료했습니다. 기존 bk_abc → 2026-04-11 15:00으로 변경되었습니다.
```

---

#### A-2. `check_multi_date_slots` — 복수 날짜 슬롯 일괄 조회
```
현재: check_available_slots는 하루치만 조회
문제: "이번 주 언제 비어요?" 같은 질문에 LLM이 여러 번 tool을 호출해야 함 (~수 초)
개선: 날짜 범위 지정으로 1회 호출에 결과 반환
```
- 입력: `owner`, `start_date`, `end_date`, `party_size`
- 출력: 날짜별 가용 슬롯 요약 (날짜 + 가능한 시간대 개수)
- 난이도: ★★☆☆☆ (DB 쿼리 조건 수정)

**보이스봇 대화 예시:**
```
고객: 이번 주 중에 두 명 예약 가능한 날이 언제예요?
AI: [check_multi_date_slots(start=월, end=금)] 화요일 2개, 목요일 3개 슬롯이 있어요.
```

---

#### A-3. `lookup_booking_by_phone` — 전화번호로 예약 조회
```
현재: get_booking_info는 예약번호(bk_xxx)가 있어야 작동
문제: 고객 대부분은 예약번호를 모름
개선: 전화번호 → 최근 예약 자동 조회
```
- 입력: `owner`, `customer_phone`, `status_filter` (optional: `confirmed`)
- 출력: 해당 번호의 최근 예약 목록 (최대 3건)
- 난이도: ★★☆☆☆

**보이스봇 대화 예시:**
```
고객: 제 예약 확인하고 싶어요. 010-1234-5678이에요.
AI: [lookup_booking_by_phone] 내일 오후 2시 예약 1건이 확인됩니다.
```

---

### 우선순위 B — 고가치, 중간 난이도

#### B-1. `add_booking_memo` — 예약 메모/특이사항 추가
```
현재: create_booking 시에만 memo 입력 가능
문제: 이미 예약된 건에 특이사항(알레르기, 요청사항 등)을 나중에 추가하지 못함
개선: 통화 중 추가 요청사항을 예약에 실시간 기록
```
- 입력: `booking_id`, `memo`
- 동작: `bookings.memo` 필드 업데이트
- 난이도: ★★☆☆☆

**도메인별 활용:**
- 레스토랑: "창가 자리로 부탁드려요", "땅콩 알레르기 있어요"
- 병원: "주차권 필요해요", "초진이에요"

---

#### B-2. `get_waitlist` / `join_waitlist` — 웨이팅 리스트 관리
```
현재: 슬롯이 가득 차면 "예약 불가"만 안내
문제: 취소 발생 시 대기자에게 연결 불가 → 매출 기회 손실
개선: 대기 등록 후 취소 발생 시 자동 알림 가능 구조
```
- Maple, XYNTRA, Vocally 모두 웨이팅 리스트를 핵심 기능으로 제공
- `join_waitlist`: `owner`, `slot_date`, `slot_time_pref`, `customer_name`, `customer_phone` 입력 → `booking_waitlist` 테이블에 저장
- `get_waitlist_position`: 대기 순번 조회
- 난이도: ★★★☆☆ (새 테이블 추가, 취소 시 알림 훅 추가)

**보이스봇 대화 예시:**
```
고객: 내일 두 시 예약 가능한가요?
AI: [check_available_slots] → 마감됨
AI: 해당 시간은 모두 예약되었습니다. 취소 시 연락드릴 웨이팅 리스트에 등록해 드릴까요?
고객: 네, 부탁해요.
AI: [join_waitlist] 등록되었습니다. 현재 2번째 대기입니다.
```

---

#### B-3. `get_business_hours` — 영업시간·휴무일 조회
```
현재: 영업시간 정보가 지식베이스(RAG)에만 있어 RAG 경로를 타야 함
문제: 예약 가능 시간대 안내 시 영업시간을 함께 안내해야 하는데 별도 경로가 필요
개선: booking_agent 컨텍스트 내에서 즉시 조회 가능
```
- `booking_settings` 또는 별도 `business_hours` 테이블 활용
- 입력: `owner`, `date` (optional)
- 출력: 해당 날짜 영업 여부, 영업시간, 브레이크타임
- 난이도: ★★★☆☆

---

#### B-4. `send_confirmation_sms` — 예약 확인 SMS 발송 (Tool stub)
```
현재: TTS로만 예약번호 안내 → 고객이 놓치면 재확인 불가
개선: 예약 완료 즉시 SMS로 예약번호·시간 발송
```
- Maple, XYNTRA, Vocally 모두 SMS 확인 기능 보유
- 실제 발송은 외부 SMS API(Coolsms, NHN Cloud 등)와 연동
- Tool 자체는 stub으로 구현하고 실제 발송 모듈을 뒤에 붙이는 구조
- 입력: `customer_phone`, `customer_name`, `booking_id`, `slot_date`, `slot_time`
- 난이도: ★★★☆☆ (외부 API 연동 포함)

---

### 우선순위 C — 고급 기능, 더 큰 범위

#### C-1. `transfer_to_human` — 인간 상담원 연결 (SIP Transfer)
```
현재: HITL(Human-in-the-Loop)은 웹 대시보드 알림으로만 구현
개선: 고객 요청 시 LLM이 직접 SIP 호전환을 트리거
```
- cris-m/langgraph_examples의 Customer Support Call Agent가 이 패턴을 구현
- ROCKYBH7/langgraph-customer-support도 escalation 노드 존재
- 입력: `reason`, `target_extension` (또는 큐 이름)
- 동작: SIP B2BUA에 REFER 메시지 전송 → 실제 호전환
- 현재 HITL 시스템의 `needs_human` 플래그와 연계 가능
- 난이도: ★★★★☆ (SIP 레이어 연동 필요)

**보이스봇 대화 예시:**
```
고객: 상담원 연결해주세요.
AI: [transfer_to_human(reason="고객 요청")] → SIP REFER → 상담원 내선 연결
```

---

#### C-2. `search_knowledge` — 지식베이스 직접 검색 (Tool화)
```
현재: RAG는 별도 노드(adaptive_rag)를 타는 고정 경로
개선: booking_agent와 동일한 Tool Use 방식으로 LLM이 필요할 때만 지식 검색
```
- 예약 상담 중 "이 식당 메뉴가 뭐예요?" 같은 혼합 질문에 대응
- 입력: `owner`, `query`, `category` (optional)
- 출력: 지식베이스 검색 결과 요약 (최대 2~3개 문서)
- 현재 `adaptive_rag_node` 내부 로직을 Tool로 wrapping
- 난이도: ★★★★☆

---

#### C-3. `get_call_context` — 현재 통화 컨텍스트 조회
```
현재: LLM이 현재 통화의 call_id, 발신번호, 통화 시간을 알 수 없음
개선: LLM이 Tool로 현재 통화 정보를 가져와 예약에 자동 연계
```
- 입력: 없음 (state에서 자동 추출)
- 출력: `call_id`, `caller_number`, `callee`, `call_start_time`, `elapsed_seconds`
- `caller_number`를 예약자 전화번호로 자동 제안 가능 ("발신번호로 등록할까요?")
- 난이도: ★★★☆☆

**보이스봇 대화 예시:**
```
고객: 예약하고 싶어요.
AI: [get_call_context] → caller=010-1234-5678
AI: 전화하신 번호 010-1234-5678로 예약자 연락처를 등록할까요?
```

---

## 3. 구현 우선순위 요약

| 순위 | Tool | 난이도 | 기대 효과 | 구현 소요 |
|---|---|---|---|---|
| 1 | `lookup_booking_by_phone` | ★★☆ | 고객 UX 즉시 개선 | 1~2시간 |
| 2 | `reschedule_booking` | ★★☆ | 예약 변경 오류 제거 | 2~3시간 |
| 3 | `check_multi_date_slots` | ★★☆ | 복수 날짜 질문 1회 처리 | 2~3시간 |
| 4 | `add_booking_memo` | ★★☆ | 도메인별 요청사항 처리 | 1~2시간 |
| 5 | `join_waitlist` | ★★★☆ | 마감 슬롯 대기 등록 | 4~6시간 |
| 6 | `get_business_hours` | ★★★☆ | 영업시간 통합 안내 | 3~4시간 |
| 7 | `send_confirmation_sms` | ★★★☆ | 예약 확인 문자 발송 | 4~8시간 |
| 8 | `transfer_to_human` | ★★★★☆ | SIP 직접 호전환 | 8~12시간 |
| 9 | `search_knowledge` | ★★★★☆ | 혼합 질문 처리 | 6~10시간 |
| 10 | `get_call_context` | ★★★☆ | 발신번호 자동 연계 | 3~5시간 |

---

## 4. 리서치에서 발견한 보이스봇 Tool 패턴

### 패턴 1: 고객 식별 → 예약 조회 체인
```
전화번호 자동 수집 → lookup_booking_by_phone → 상황에 맞는 안내
```
Maple, XYNTRA, Vocally 모두 이 패턴 사용. 고객이 예약번호를 몰라도 전화번호만 있으면 조회 가능.

### 패턴 2: 슬롯 부족 → 웨이팅 전환
```
check_available_slots → 마감 감지 → join_waitlist 자동 제안
```
레스토랑·병원 보이스봇에서 매출 손실 방지를 위한 필수 패턴.

### 패턴 3: 예약 완료 후 다중 채널 확인
```
create_booking → TTS 안내 + send_confirmation_sms 동시 실행
```
XYNTRA의 SMS confirmation 기능과 동일. 고객이 예약번호를 기억하지 못해도 문자로 보관.

### 패턴 4: 혼합 intent 처리
```
booking_agent 내에서 search_knowledge를 sub-tool로 호출
→ "예약 가능한 시간 + 메뉴도 알려주세요" 한 번에 처리
```
현재는 두 intent가 별도 경로를 타야 함. Tool화 시 booking_agent 단일 경로에서 처리 가능.

---

## 5. 현재 시스템과의 통합 포인트

```
[현재 booking_agent 흐름]
classify_intent → (booking keyword) → booking_agent_node → BOOKING_TOOLS → update_state

[확장 후]
classify_intent → (booking keyword) → booking_agent_node
                                            ↓
                                    BOOKING_TOOLS (확장)
                                    ├── check_available_slots     ← 기존
                                    ├── check_multi_date_slots    ← 신규 A-2
                                    ├── get_booking_info          ← 기존
                                    ├── lookup_booking_by_phone   ← 신규 A-3
                                    ├── create_booking_tool       ← 기존
                                    ├── reschedule_booking        ← 신규 A-1
                                    ├── cancel_booking_tool       ← 기존
                                    ├── add_booking_memo          ← 신규 B-1
                                    ├── join_waitlist             ← 신규 B-2
                                    ├── get_business_hours        ← 신규 B-3
                                    ├── send_confirmation_sms     ← 신규 B-4
                                    ├── transfer_to_human         ← 신규 C-1
                                    ├── search_knowledge          ← 신규 C-2
                                    ├── get_call_context          ← 신규 C-3
                                    └── get_booking_settings      ← 기존
```

모든 신규 Tool은 `booking_tools.py`에 추가 후 `BOOKING_TOOLS` 리스트에 append하면 됨.
`booking_agent_node`의 `MAX_TOOL_ROUNDS`를 현재 5에서 7~8로 늘리면 복잡한 tool 체인도 처리 가능.

---

## 6. 단기 구현 권장안 (3개 Tool, 1일 작업)

현재 시스템에서 즉시 효과가 큰 3개를 먼저 구현:

1. **`lookup_booking_by_phone`** — 고객이 예약번호 없이도 조회 가능 (UX 필수)
2. **`reschedule_booking`** — 예약 변경 원자적 처리 (신뢰성 필수)
3. **`add_booking_memo`** — 요청사항 기록 (도메인 활용도 향상)

세 Tool 모두:
- 기존 `BookingService` + `SQLite` 인프라 그대로 활용
- `booking_tools.py`에 함수 추가 + `BOOKING_TOOLS` 리스트 append만으로 완성
- `booking_agent_node` 수정 불필요
