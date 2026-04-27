# AI Bot 예약 기능 구현 점검 및 개선 방향

| 항목 | 내용 |
|---|---|
| 작성일 | 2026-04-09 |
| 버전 | 1.0 |
| 상태 | 점검 완료 |
| 관련 경로 | `src/ai_voicebot/langgraph/nodes/booking_agent.py`, `src/ai_voicebot/langgraph/tools/booking_tools.py` |

---

## 1. 현재 구현 상태 점검

### 1.1 전체 흐름도

```
사용자 발화 (STT)
    │
    ▼
[classify_intent_node]
  ├─ 0차: 예약 키워드 매칭 (~2ms, LLM 스킵)
  │       키워드: "예약", "취소", "예약번호", "가능한 시간" 등 15개
  └─ 4차: LLM 분류 (booking intent 명시 포함)
    │
    ▼ intent == "booking"
[route_utterance_node]  ← RAG/캐시 완전 스킵
    │
    ▼
[booking_agent_node]   ← LLM + Tool Use 루프
    │
    ▼
[update_state_node] → TTS → 사용자
```

### 1.2 구현된 Tool 목록 (5개)

| Tool | 기능 | 구현 상태 |
|---|---|---|
| `check_available_slots` | 날짜·인원 기준 가용 슬롯 조회 | ✅ 완료 |
| `get_booking_info` | 예약번호로 예약 상세 조회 | ✅ 완료 |
| `create_booking_tool` | 예약 생성 + confirmation_msg 치환 | ✅ 완료 |
| `cancel_booking_tool` | 예약 취소 | ✅ 완료 |
| `get_booking_settings` | 도메인 설정 조회 (서비스명·레이블 등) | ✅ 완료 |

### 1.3 기능별 구현 완성도

| 기능 | 완성도 | 비고 |
|---|---|---|
| 예약 가능 시간 안내 | ✅ 완료 | 날짜+인원 기반 슬롯 조회 |
| 예약 생성 (이름·전화·날짜·시간·인원) | ✅ 완료 | Progressive Slot Filling (LLM이 누락 정보 추가 질문) |
| 예약 번호 안내 | ✅ 완료 | confirmation_msg 템플릿 치환 |
| 예약 조회 (예약번호 기반) | ✅ 완료 | |
| 예약 취소 | ✅ 완료 | status = cancelled 처리 |
| 도메인 설정 반영 (서비스명, 레이블 등) | ✅ 완료 | get_booking_settings 자동 참조 |
| 다중 발화 컨텍스트 유지 | ⚠️ 부분 완료 | **[GAP]** 단일 발화 내 tool loop만 유지, 발화 간 컨텍스트 미보존 |
| 예약 수정 | ❌ 미구현 | update_booking API는 있으나 Tool 미등록 |
| 날짜 자연어 파싱 | ⚠️ LLM 의존 | "내일", "다음주 월요일" → LLM이 YYYY-MM-DD 변환 |
| owner 자동 주입 | ✅ 완료 | LLM이 owner 누락 시 state에서 자동 보정 |
| LangChain 미설치 폴백 | ✅ 완료 | 오늘 슬롯 컨텍스트 기반 텍스트 응답 |
| 최대 Tool 호출 제한 | ✅ 완료 | MAX_TOOL_ROUNDS = 5 (무한루프 방지) |

---

## 2. 주요 GAP 분석

### GAP-1: 발화 간 대화 컨텍스트 미보존 (가장 중요)

**현황:**
```python
# booking_agent_node 진입 시마다 메시지 초기화
messages = [
    SystemMessage(content=_BOOKING_SYSTEM_PROMPT),
    HumanMessage(content=user_query),  # ← 현재 발화만 포함
]
```

**문제:** 고객이 "내일 오후 2시에 예약하고 싶어요" → LLM이 이름 질문 → 고객이 "홍길동이에요" 라고 하면,
두 번째 발화(`홍길동이에요`)가 새로운 `booking_agent_node` 호출 시 **이전 맥락 없이 단독으로 전달**됨.

**영향:** LLM이 "홍길동이에요"만 보면 예약 맥락을 이해하지 못해 다시 처음부터 안내할 가능성 높음.

**해결 방향:** `booking_context` 상태 필드(이미 정의됨)를 활용하여 발화 간 수집된 슬롯 정보(날짜, 시간, 이름 등)를 SystemMessage 컨텍스트에 주입.

---

### GAP-2: 예약 수정 Tool 미구현

**현황:** REST API(`PUT /api/booking/{id}`)는 완성되어 있으나 LangChain Tool로 등록되지 않음.

**영향:** 고객이 "예약 시간을 3시로 변경하고 싶어요" 요청 시 처리 불가 → LLM이 "직접 전화 바람" 안내.

---

### GAP-3: 날짜 자연어 파싱 — LLM 단독 의존

**현황:** "내일", "이번 주 금요일", "다음달 첫째주 화요일" 등 자연어 날짜를 LLM이 해석 후 YYYY-MM-DD로 변환.

**문제:**
- LLM이 오늘 날짜를 모르면 오답 가능 (SystemMessage에 오늘 날짜 주입 여부 확인 필요)
- 시간대 애매성: "오후 2시" → LLM이 "14:00"으로 변환하지 않을 수 있음

**해결 방향:** SystemMessage에 `오늘 날짜: {today}` 명시적 주입 (현재 미포함).

---

### GAP-4: 예약 취소 — 예약번호 없이 요청 시 처리 부족

**현황:** `cancel_booking_tool(booking_id)` — 예약번호 필수.

**문제:** 고객이 "내일 2시 예약 취소해줘" (예약번호 모름) → Tool 호출 불가. LLM이 "예약번호를 알려주세요" 안내하나, 예약 번호 조회 Tool이 없음.

**해결 방향:** `search_bookings_by_phone_or_date` Tool 추가 — 전화번호 또는 날짜+시간으로 예약 검색.

---

### GAP-5: 통화 call_id 미연동 (예약 이력 추적)

**현황:** `create_booking_tool`에 `call_id=""` 기본값으로 고정. `state._call_id`에서 가져오지 않음.

**영향:** 예약 생성 시 통화 ID가 DB에 저장되지 않아 "이 통화로 생성된 예약" 역추적 불가.

---

## 3. GitHub 리서치 결과 — 주요 개선 패턴

### 3.1 발화 간 대화 히스토리 유지 (핵심)

**참고:** [ahmad2b/langgraph-voice-call-agent](https://github.com/ahmad2b/langgraph-voice-call-agent), [theaifutureguy/Meeting-Room-Booking-AI-Agent](https://github.com/theaifutureguy/Meeting-Room-Booking-AI-Agent)

**패턴:** `AgentState`에 `messages: Annotated[List[BaseMessage], add_messages]` 필드를 두고, 발화 간에도 booking 관련 메시지 히스토리를 누적.

```python
# 개선 방향: booking_context에 messages 히스토리 보관
booking_context = state.get("booking_context", {})
prev_messages = booking_context.get("messages", [])

messages = [
    SystemMessage(content=_BOOKING_SYSTEM_PROMPT + f"\n오늘 날짜: {today}\n[owner={owner}]"),
    *prev_messages,           # ← 이전 발화 히스토리
    HumanMessage(content=user_query),
]

# 루프 종료 후 히스토리 갱신
booking_context["messages"] = messages  # 다음 발화에 전달
return {
    "response": final_response,
    "booking_context": booking_context,
    ...
}
```

---

### 3.2 오늘 날짜 주입 (날짜 파싱 정확도 향상)

**참고:** [From Chaos to Clinic - DEV Community](https://dev.to/beck_moulton/from-chaos-to-clinic-building-an-autonomous-medical-appointment-agent-with-langgraph-openai-33l7)

```python
from datetime import date
today = date.today().strftime("%Y-%m-%d")
weekday = date.today().strftime("%A")  # "Thursday"

system_content = f"""{_BOOKING_SYSTEM_PROMPT}
오늘 날짜: {today} ({weekday})
owner: {owner}
"""
```

---

### 3.3 SMS 예약 확인 링크 발송

**참고:** [Rajathbharadwaj/voice-agent](https://github.com/Rajathbharadwaj/voice-agent) — 음성으로 예약번호 읽어주는 대신 SMS 발송.

**패턴:** 예약 생성 후 고객 전화번호로 예약 상세 정보 SMS 발송 → 음성으로 긴 예약번호 전달 실수 방지.

```python
# 개선 Tool: send_booking_sms
def _send_booking_sms(booking_id: str, customer_phone: str) -> str:
    """예약 확인 SMS를 발송합니다."""
    # 기존 HITL/알림 인프라 연동
    ...
```

---

### 3.4 예약 검색 Tool 추가 (취소 UX 개선)

**참고:** [ScheduleMe Multi-Agent](https://arxiv.org/html/2509.25693v1) — 전화번호/날짜로 예약 역조회.

```python
def _search_bookings(owner: str, customer_phone: str = "", slot_date: str = "") -> str:
    """전화번호 또는 날짜로 예약을 검색합니다 (취소·조회 시 예약번호 모를 때 활용)."""
    bookings = list_bookings(owner, slot_date=slot_date or None,
                              customer_phone=customer_phone or None, limit=5)
    ...
```

---

### 3.5 예약 수정 Tool 추가

```python
def _update_booking(booking_id: str, slot_date: str = "", slot_time: str = "",
                    party_size: int = 0, memo: str = "") -> str:
    """예약 정보(날짜·시간·인원)를 수정합니다."""
    ...
```

---

## 4. 개선 우선순위

| 우선순위 | 개선 항목 | 예상 효과 | 난이도 |
|---|---|---|---|
| 🔴 P1 | **발화 간 대화 컨텍스트 유지** (booking_context.messages) | 다중 발화 예약 완성률 대폭 향상 | 中 |
| 🔴 P1 | **오늘 날짜를 SystemMessage에 명시 주입** | "내일", "다음주" 등 자연어 날짜 파싱 정확도 향상 | 低 |
| 🟡 P2 | **call_id 연동** (state._call_id → create_booking_tool) | 통화-예약 이력 연결 | 低 |
| 🟡 P2 | **예약 검색 Tool 추가** (전화번호·날짜 기반) | 예약번호 없이 취소·조회 가능 | 中 |
| 🟡 P2 | **예약 수정 Tool 추가** | 시간·인원 변경 지원 | 中 |
| 🟢 P3 | **SMS 예약 확인 발송** | 예약번호 전달 신뢰성 향상 | 高 |
| 🟢 P3 | **LangGraph Checkpointer 도입** | 세션 영속성, 서버 재시작 후 복구 | 高 |

---

## 5. 즉시 적용 가능한 개선 (P1)

### 5.1 booking_agent.py 수정 포인트

```python
# 수정 전
messages = [
    SystemMessage(content=_BOOKING_SYSTEM_PROMPT + f"\n\n[owner={owner}]"),
    HumanMessage(content=user_query),
]

# 수정 후
from datetime import date
today_str = date.today().strftime("%Y-%m-%d (%A)")

booking_context = state.get("booking_context", {})
prev_messages = booking_context.get("messages", [])

messages = [
    SystemMessage(content=f"{_BOOKING_SYSTEM_PROMPT}\n오늘 날짜: {today_str}\n[owner={owner}]"),
    *prev_messages,           # 발화 간 히스토리 유지
    HumanMessage(content=user_query),
]

# ... tool loop 실행 ...

# 루프 종료 후
booking_context["messages"] = [m for m in messages if not isinstance(m, SystemMessage)]
booking_context["messages"] = booking_context["messages"][-20:]  # 최대 20개 유지

return {
    "response": final_response,
    "intent": "booking",
    "business_state": "booking_handled",
    "booking_context": booking_context,  # ← 히스토리 전달
    "confidence": 1.0,
}
```

### 5.2 call_id 연동

```python
# _create_booking Tool 호출 시 call_id 자동 주입
if "owner" in _get_tool_params(tool_name) and "owner" not in tool_args:
    tool_args = {**tool_args, "owner": owner}
if tool_name in {"create_booking_tool", "_create_booking"} and "call_id" not in tool_args:
    tool_args = {**tool_args, "call_id": call_id}  # ← 추가
```

---

## 6. 참고 GitHub 레포지토리

| 레포지토리 | 핵심 패턴 |
|---|---|
| [ahmad2b/langgraph-voice-call-agent](https://github.com/ahmad2b/langgraph-voice-call-agent) | Thread 기반 발화 간 컨텍스트 유지, LiveKit + LangGraph 통합 |
| [theaifutureguy/Meeting-Room-Booking-AI-Agent](https://github.com/theaifutureguy/Meeting-Room-Booking-AI-Agent) | LangGraph 예약 워크플로우, clarification loop |
| [Rajathbharadwaj/voice-agent](https://github.com/Rajathbharadwaj/voice-agent) | 음성 예약 + SMS 발송, 단일 질문 per turn 원칙 |
| [livekit/agents langgraph 예시](https://github.com/livekit/agents/blob/3c20a1ae/examples/voice_agents/langgraph_agent.py) | LangGraph + VAD + STT + TTS 풀파이프라인 |
| [ScheduleMe arxiv](https://arxiv.org/html/2509.25693v1) | 멀티에이전트 캘린더 어시스턴트, supervisor 패턴 |
