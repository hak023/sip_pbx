# 예약 시도 미커밋 점검 — `call_id=xUfFVrFw8R`

- **작성일(로컬)**: 2026-04-20 16:41
- **상태**: 로그 원인 분석 + 진단 로그 보강
- **근거**: `call_data_record_20260420.log` L65–88, `app.log` 동일 통화 구간

## 개요

`call_data_record`에는 **`booking_intent_routed`**로 `intent=booking` 승격과 **`booking_agent` 노드 소요 시간**이 찍혀 있으나, **`booking_committed` / `booking_tool_start` / `booking_rejected`** 같은 **도구·DB 계열 이벤트가 전혀 없다.** `app.log`에는 해당 구간에 **`booking_agent_fallback_complete`**만 있고 **`booking_agent_tool_calls`는 없다.** 코드상 이 조합은 **`booking_agent_node`가 LangChain `bind_tools` 루프에 들어가지 못하고 `_fallback_text_booking`만 탄 경우**와 일치한다. 폴백은 **`llm_client.generate_response`**로 자연어 안내만 생성하며 **`create_booking_tool`을 호출하지 않으므로 SQLite 예약 행이 생기지 않는다**가 정상 동작이다.

## 로그 근거 (요약)

| 출처 | 관찰 |
|------|------|
| `call_data_record` L77–78, L84–85 | `booking_intent_routed` + `booking_agent` ~2.6s — **의도 라우팅·노드 진입은 됨** |
| `call_data_record` L79, L86 | `llm_exchange` 응답이 **"2026년 4월"(8자)** 또는 **일반 오류 문구** — 도구 성공 JSON 형태 아님 |
| `call_data_record` | **`booking_committed` 없음** → DB 커밋 없음 |
| `app.log` | `booking_agent_node_enter` … **`caller_number` 빈 문자열** |
| `app.log` | **`booking_agent_fallback_complete`** ×2 — **폴백 경로 종료** |
| `app.log` | 동 통화에 **`booking_agent_tool_calls` 없음** |

## 기술적 원인

`booking_agent.py`는 내부 LangChain 모델을 다음처럼 꺼낸 뒤 `bind_tools`를 쓴다.

```python
raw_llm = getattr(llm_client, "_chat_model", None) or getattr(llm_client, "chat_model", None)
if raw_llm is None:
    return await _fallback_text_booking(...)
```

Pipecat·음성 경로에서 주입되는 **`llm_client`는 보통 위 속성이 없는 래퍼**라 `raw_llm`이 `None`이 되기 쉽다. 그 결과 **예약 도구 루프 없이** 폴백만 실행되고, 사용자가 “예약하려고요”라고 해도 **실제 `bookings` INSERT는 발생하지 않는다.**

보조 이슈: `booking_agent_node_enter`에 **`caller_number`가 비어 있음** — 설령 도구 경로였어도 `customer_phone` 자동 주입이 약해져 추가 확인이 필요했을 수 있다(이번 호의 1차 원인은 폴백).

## 코드 보강 (재발 시 로그로 즉시 구분)

- `raw_llm is None` 직전 **`booking_agent_no_bind_tools_model`** 경고 로그 추가 (`llm_client_type`, `call_id`).

## 잔여 과제 (설계)

- Pipecat용 LLM과 동일 설정으로 **`langchain_core` BaseChatModel 인스턴스**를 `booking_agent`에 넘기거나, 폴백이 아닌 **`create_booking` 직접 호출 경로**(슬롯 파싱 후 서비스 레이어)를 별도 설계.
- LangGraph 상태에 **SIP 발신 표시(내선 1004 등)**를 `_caller_number`로 일관 주입해 도구 인자 보강.

## 변경 이력 (파일별)

| 파일 경로 | 변경 유형 | 요약 |
|-----------|------------|------|
| `sip-pbx/src/ai_voicebot/langgraph/nodes/booking_agent.py` | 수정 | `raw_llm is None` 시 `booking_agent_no_bind_tools_model` 경고 |
| 본 문서 | 추가 | `xUfFVrFw8R` 미커밋 원인 정리 |
