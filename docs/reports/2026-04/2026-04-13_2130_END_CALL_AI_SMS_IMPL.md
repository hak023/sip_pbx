## 개요

AI Bot 통화 종료 시 분산되어 있던 SMS 발송 로직(통화 중 `send_booking_sms` tool + 종료 후 단순 요약)을 제거하고,
`_send_end_call_sms()` 하나로 통합했다. KB 인사말 조회 → LLM 본문 생성 → SIP MESSAGE 발신 → DB 저장 순으로 동작한다.

---

## 변경 이력 (파일별)

| 파일 경로 | 변경 유형 | 요약 | 비고 |
|---|---|---|---|
| `sip-pbx/src/ai_voicebot/langgraph/tools/booking_tools.py` | 수정 | `BOOKING_TOOLS` 목록에서 `send_booking_sms` 제거 | 함수/툴 객체는 보존 |
| `sip-pbx/src/ai_voicebot/langgraph/nodes/booking_agent.py` | 수정 | 시스템 프롬프트에서 `send_booking_sms` 호출 지시 제거, `_SMS_TRIGGER_TOOLS` / `_OWNER_TOOLS` 내 SMS 항목 제거, tool 결과에서 `last_action` / `last_booking` 저장 추가 | — |
| `sip-pbx/src/ai_voicebot/orchestrator/ai_orchestrator.py` | 수정 | `_send_call_summary_sms()` → `_send_end_call_sms()` 교체, `end_call()`의 `create_task` 호출 대상 변경 | — |

---

## 주요 결정 사항

### 1. 예약 액션 추적 — `booking_context["last_action"]` / `["last_booking"]`

기존에는 `booking_context`에 예약 액션 종류가 별도 필드로 저장되지 않았다.
`booking_agent.py`에서 tool 실행 직후 성공(`success: true`) 응답을 파싱해
`last_action` (`"create"` | `"cancel"` | `"update"`)과 `last_booking`(예약 결과 JSON)을 booking_context에 기록하도록 변경했다.

### 2. LLM 호출 — `self.llm.generate_response()`

`_send_end_call_sms()`는 `asyncio.create_task()`로 별도 Task에서 실행되어 ContextVar에 접근할 수 없다.
따라서 `ai_orchestrator`가 보유한 `self.llm` 인스턴스를 직접 사용한다.
`self.llm`이 `None`이면 단순 텍스트 조합으로 폴백한다.

### 3. SMS 구성 순서

1. KB `greeting_phase1` 인사말 (HTTP GET, 없으면 기본값)
2. LLM이 conversation.messages(AI 응답 최대 5개)와 예약 정보를 받아 300자 이하 SMS 생성
3. 예약 액션이 있을 때만 예약 섹션 포함
4. 마지막 줄에 "추가 문의사항은 전화 또는 문자로 남겨주시면 감사하겠습니다." 고정

### 4. DB 저장

SIP MESSAGE 발신 후 `chat_messages` 테이블에 `direction=outbound`로 기록해 채팅 관리 페이지에서 이력을 확인할 수 있다.

---

## 잔여 과제

- `_langgraph_state`가 `ai_orchestrator` 인스턴스에 실제로 설정되지 않으면 예약 컨텍스트를 읽을 수 없다. LangGraph 실행 완료 시 결과를 `self._langgraph_state`에 저장하는 코드 추가 필요.
- 통화 중 예약 외 `send_booking_sms` tool을 명시적으로 호출하는 외부 코드가 있다면 추가 제거 필요.
