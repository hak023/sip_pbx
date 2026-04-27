# AI Bot 예약 기능 개선 구현 리포트

| 항목 | 내용 |
|---|---|
| 작성일 | 2026-04-09 |
| 버전 | 1.0 |
| 상태 | 구현 완료 |
| 기반 분석 | `2026-04-09_1113_BOOKING_AI_BOT_REVIEW_AND_IMPROVEMENT.md` |

---

## 1. 구현 개요

점검 리포트(P1/P2/P3) 기반으로 AI Bot 예약 기능을 전면 개선했다.
주요 변경: 발화 간 대화 히스토리 유지, 발신자 번호 기반 예약 사전 조회, SIP SMS 발송, LangGraph Checkpointer 도입.

---

## 2. 변경 파일 목록

| 파일 | 변경 유형 | 설명 |
|---|---|---|
| `src/ai_voicebot/langgraph/nodes/booking_agent.py` | 전면 재작성 | P1+P2 개선 일체 적용 |
| `src/ai_voicebot/langgraph/tools/booking_tools.py` | 수정 + 추가 | Tool 3개 추가, call_id 연동 |
| `src/ai_voicebot/langgraph/state.py` | 수정 | `_caller_number` 필드 추가 |
| `src/ai_voicebot/langgraph/agent.py` | 수정 | caller_number 주입, booking_context 보존, Checkpointer 적용 |
| `src/ai_voicebot/langgraph/checkpointer.py` | **신규** | LangGraph Checkpointer 모듈 |
| `src/services/booking_service.py` | 수정 | `search_bookings_by_phone_future`, `update_booking` 날짜/시간 지원 |
| `src/services/sip_sms_service.py` | **신규** | SIP MESSAGE(SMS) 발송 서비스 |
| `src/api/routers/booking.py` | 수정 | `POST /api/booking/sms/send` 엔드포인트 추가 |
| `src/booking/models.py` | 수정 | `BookingUpdate`에 `slot_date`, `slot_time` 필드 추가 |

---

## 3. P1 — 핵심 개선

### 3.1 발화 간 대화 히스토리 유지 (P1-1)

**변경 전**: `booking_agent_node` 진입 시마다 메시지 배열이 현재 발화 1개로 초기화되어 다중 발화 대화 불가.

**변경 후**:

```python
# booking_context.messages에서 이전 히스토리 복원
booking_context = dict(state.get("booking_context") or {})
prev_messages = booking_context.get("messages", [])   # ← 이전 발화들

messages = [
    SystemMessage(content=system_content),
    *trimmed_prev,          # ← 발화 간 전달
    HumanMessage(content=user_query),
]

# 루프 종료 후 히스토리 갱신 (최대 20개 유지)
history_to_save = [m for m in messages if not isinstance(m, SystemMessage)]
booking_context["messages"] = history_to_save[-20:]
```

- `ConversationAgent._state["booking_context"]`에 매 발화 후 저장 → 다음 발화에 자동 전달
- 최대 20개 메시지 윈도우 슬라이딩 유지

**대화 흐름 예시**:
```
[발화 1] 고객: 내일 오후 2시에 예약하고 싶어요.
  → LLM: 이름과 연락처를 알려주세요.
  → booking_context.messages = [HumanMessage, AIMessage, ToolMessage...]

[발화 2] 고객: 홍길동이에요.
  → messages = [System, prev[HumanMessage+AIMessage], HumanMessage("홍길동")]
  → LLM: 이전 맥락 인지 → 연락처 추가 질문 또는 예약 진행
```

---

### 3.2 오늘 날짜를 SystemMessage에 명시 주입 (P1-2)

```python
now_dt = datetime.now()
today_str = now_dt.strftime("%Y-%m-%d")
weekday_kr = ["월", "화", "수", "목", "금", "토", "일"][now_dt.weekday()]
now_time_str = now_dt.strftime("%H:%M")

system_content = (
    f"{_BOOKING_SYSTEM_PROMPT}"
    f"\n오늘 날짜: {today_str} ({weekday_kr}요일), 현재 시각: {now_time_str}"
    ...
)
```

- "내일", "다음 주 금요일", "오후 2시" 등 자연어 날짜/시간 파싱 정확도 향상

---

## 4. P2 — 기능 확장

### 4.1 call_id 자동 주입 (P2-1)

```python
# Tool 실행 루프에서 create_booking_tool 호출 시
if tool_name in {"create_booking_tool", "_create_booking"}:
    tool_args["_inject_call_id"] = call_id   # state._call_id 자동 주입
```

- 예약 생성 시 `bookings.call_id` 컬럼에 통화 ID 저장 → 통화-예약 역추적 가능

---

### 4.2 발신자 전화번호 기반 미래 예약 사전 조회 (P2-2)

**신규 함수**: `booking_service.search_bookings_by_phone_future(owner, customer_phone)`

```sql
SELECT * FROM bookings
WHERE owner = ?
  AND customer_phone = ?
  AND status = 'confirmed'
  AND (
    slot_date > ?                          -- 오늘 이후
    OR (slot_date = ? AND slot_time >= ?) -- 오늘 현재 시각 이후
  )
ORDER BY slot_date ASC, slot_time ASC
LIMIT 10
```

**booking_agent_node에서 LLM 호출 전 사전 조회**:
```python
if caller_number:
    future_bookings = search_bookings_by_phone_future(owner, caller_number, limit=5)
    if future_bookings:
        caller_bookings_context = "\n[발신자 미래 예약 목록]\n" + ...
    # SystemMessage에 컨텍스트로 주입
```

- LLM은 "예약 확인해줘" 요청에 Tool 호출 없이 이미 로드된 예약 정보로 즉시 응답 가능
- 취소·수정 요청 시 예약번호 자동 제공 → LLM이 바로 cancel/update_booking 호출 가능

---

### 4.3 예약 검색 Tool 추가 (P2-2, Tool 7)

**신규 Tool**: `search_my_bookings(owner, customer_phone)`

- 발신자 번호로 미래 확정 예약 검색
- 예약번호 모르고 "취소해줘" 시 LLM이 자동 호출

---

### 4.4 예약 수정 Tool 추가 (P2-3, Tool 6)

**신규 Tool**: `update_booking_tool(booking_id, slot_date, slot_time, party_size, memo)`

```python
# booking_service.update_booking에 slot_date, slot_time 필드 추가
# BookingUpdate 모델도 동일하게 확장
```

- "예약 시간을 3시로 변경해줘" → LLM이 search_my_bookings → update_booking_tool 순서로 처리

---

## 5. P3 — 고급 기능

### 5.1 SIP MESSAGE(SMS) 발송 (P3-1)

#### 5.1.1 신규 서비스: `src/services/sip_sms_service.py`

RFC 3428 (SIP Instant Messaging) 기반 UDP 소켓 직접 전송.

```
MESSAGE sip:{to_user}@{sip_server}:5060 SIP/2.0
Via: SIP/2.0/UDP {local_ip}:5090;branch=...
From: <sip:{from_user}@{local_ip}>;tag=...
To: <sip:{to_user}@{sip_server}>
CSeq: 1 MESSAGE
Content-Type: text/plain; charset=UTF-8

[메시지 본문]
```

- 발송 이력: `booking.db` `sms_log` 테이블에 자동 기록
- SIP 서버 주소: 환경변수 `SIP_SERVER_IP` / `SIP_SERVER_PORT` (기본: 127.0.0.1:5060)

#### 5.1.2 신규 API: `POST /api/booking/sms/send`

```json
// Request
{ "to_phone": "01012345678", "message": "예약 확인 ...", "owner": "1003" }

// Response
{ "success": true, "message": "SMS 발송 완료", "to": "01012345678", "from": "1003" }
```

#### 5.1.3 신규 Tool: `send_booking_sms(to_phone, message, owner)` (Tool 8)

LLM 시스템 프롬프트에 명시:
> "예약 생성·수정·취소 완료 후에는 반드시 send_booking_sms로 고객에게 확인 SMS를 발송하세요."

Tool 실행 시 `to_phone`이 비어 있으면 `_caller_number`에서 자동 보완.

---

### 5.2 LangGraph Checkpointer (P3-2)

#### 5.2.1 신규 모듈: `src/ai_voicebot/langgraph/checkpointer.py`

| 우선순위 | Checkpointer | 특징 |
|---|---|---|
| 1순위 | `SqliteSaver` (langgraph-checkpoint-sqlite) | DB 영속화, 서버 재시작 후 복구 |
| 2순위 | `MemorySaver` (langgraph 기본) | 인메모리, 재시작 시 초기화 |
| Fallback | None | 체크포인터 없이 실행 |

```bash
# 영속 체크포인터 활성화
pip install langgraph-checkpoint-sqlite
```

#### 5.2.2 thread_id = call_id 매핑

```python
config = get_thread_config(call_id)   # {"configurable": {"thread_id": call_id}}
result = await graph.ainvoke(state, config=config)
```

- 통화별로 독립적인 체크포인트 → 동시 통화 간 상태 격리
- 통화 종료 후 `clear_checkpoint(call_id)`로 정리 가능

#### 5.2.3 그래프 컴파일 변경

```python
# 변경 전
compiled = graph.compile()

# 변경 후
compiled = graph.compile(checkpointer=checkpointer) if checkpointer else graph.compile()
```

---

## 6. 전체 데이터 흐름 (개선 후)

```
전화 수신
  │
  ▼ caller_number = 발신자 번호
[ConversationAgent.process_utterance]
  │ kwargs["caller_number"] 주입
  ▼
[classify_intent_node] ← 예약 키워드 매칭 (~2ms)
  │ intent = "booking"
  ▼
[route_utterance_node] ← RAG 스킵
  │
  ▼
[booking_agent_node]
  ├─ booking_context.messages 복원 (이전 발화 히스토리)
  ├─ 오늘 날짜·시각 SystemMessage 주입
  ├─ 발신자 전화번호로 미래 예약 사전 조회 → SystemMessage에 포함
  │
  ├─ LLM + 8개 Tool 루프 (최대 5회)
  │   ├─ check_available_slots
  │   ├─ get_booking_info
  │   ├─ create_booking_tool  ← call_id 자동 주입
  │   ├─ cancel_booking_tool
  │   ├─ get_booking_settings
  │   ├─ update_booking_tool  ← [신규]
  │   ├─ search_my_bookings   ← [신규]
  │   └─ send_booking_sms     ← [신규] 예약 변동 시 자동 호출
  │
  ├─ booking_context.messages 업데이트 (최대 20개 윈도우)
  └─ booking_context 반환 → ConversationAgent._state에 보존
  │
  ▼ Checkpointer (SqliteSaver / MemorySaver)
  │ thread_id = call_id → SQLite 영속화
  ▼
[update_state_node] → TTS → 고객

고객 다음 발화:
  booking_context.messages = 이전 대화 내용 → LLM이 맥락 인지
```

---

## 7. 환경변수 설정

| 변수 | 기본값 | 설명 |
|---|---|---|
| `SIP_SERVER_IP` | `127.0.0.1` | SIP MESSAGE 전송 대상 서버 IP |
| `SIP_SERVER_PORT` | `5060` | SIP 서버 포트 |
| `BOOKING_DB_PATH` | `./data/booking.db` | SQLite DB 경로 (Checkpointer 공유) |

---

## 8. 추가 설치 권장

```bash
# LangGraph 영속 체크포인터
pip install langgraph-checkpoint-sqlite

# SMS Tool에서 내부 API 호출 시
pip install httpx   # 이미 설치된 경우 생략
```

---

## 9. 향후 과제

| 항목 | 설명 |
|---|---|
| 통화 종료 시 `clear_checkpoint` 호출 | `run_ai_call.py` 또는 BYE 핸들러에서 호출 |
| SMS 발송 실패 재시도 큐 | 발송 실패 시 비동기 재시도 로직 |
| SMS 수신 핸들러 | SIP MESSAGE 수신 시 예약 시스템 연동 |
| caller_number 자동 추출 | `sip_endpoint.py`에서 INVITE From 헤더 파싱 후 `process_utterance`에 자동 전달 |
