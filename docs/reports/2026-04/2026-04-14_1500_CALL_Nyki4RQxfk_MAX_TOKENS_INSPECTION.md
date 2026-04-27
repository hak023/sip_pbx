# call_id Nyki4RQxfk — MAX_TOKENS 점검

- **작성일(로컬)**: 2026-04-14
- **상태**: 로그 기준 원인 확정
- **관련 로그**: `sip-pbx/logs/app.log` (2026-04-20T17:20:18~23), `sip-pbx/logs/call_data_record_20260420.log`

## 개요

`Nyki4RQxfk` 통화에서 예약 발화 처리 중 **Gemini(또는 동일 LLM 클라이언트)의 `finish_reason: MAX_TOKENS`** 로 응답이 중간에 잘렸고, 그 결과 **의도 분류 JSON 파싱 실패** 및 **booking 폴백 응답이 JSON 조각만 생성**되어 TTS까지 동일 문자열이 전달되었다.

## 관측 요약 (시간순)

1. **17:20:18** `classify_intent_merged` LLM 요청 (`prompt_len` 1601).
2. **17:20:20** `llm_generate_response_finish_reason`: `finish_reason=MAX_TOKENS`, `max_output_tokens=128`, `response_len=9`.
3. **17:20:20** `llm_response_truncated_max_tokens` 경고(동일 상한 128).
4. **17:20:20** `classify_intent_json_parse_failed` — `raw_preview`: `` ```json\n{` `` 수준으로 **마크다운 코드펜스로 시작**해 파서가 실패.
5. **17:20:20** `classify_intent_nlu_fallback_to_question` 후 `route_utterance_booking_direct`로 **booking** 경로는 유지.
6. **17:20:20** `booking_agent_no_bind_tools_model` — 도구 바인딩 불가로 **텍스트 폴백**만 수행.
7. **17:20:23** 다시 `finish_reason=MAX_TOKENS`, **`max_output_tokens=300`**, `response_len=18` — 응답 본문이 `` ```json\n{\n  \"tool_` `` 에서 끊김.
8. **17:20:23** `langgraph_agent_result` / `llm_exchange_full` / TTS 입력 모두 동일 18자 조각.

## 코드와의 대응

| 구간 | 코드 위치 | 설정값 |
|------|-----------|--------|
| 의도 분류(merged) | `sip-pbx/src/ai_voicebot/langgraph/nodes/classify_intent.py` | `max_output_tokens=128` |
| booking 에이전트 폴백 | `sip-pbx/src/ai_voicebot/langgraph/nodes/booking_agent.py` | `max_output_tokens=300` |

로그의 `max_output_tokens` 값(128, 300)은 위 코드와 일치한다.

## 결론

- **“max token 관련 에러”**에 해당하는 것은 API 예외가 아니라 **`finish_reason: MAX_TOKENS`(출력 상한 도달)** 이다.
- **직접 원인**: 해당 호출에서 `max_output_tokens`가 **의도 분류·폴백 응답에 비해 낮고**, 모델이 **순수 JSON 대신 마크다운 JSON** 형태로 쓰기 시작해 **짧은 예산 안에 유효 JSON을 완성하지 못함**.
- **부수 현상**: `booking_agent_no_bind_tools_model`로 **도구 없이** 긴 구조화 출력을 텍스트로 시도 → 상한에 더 쉽게 걸림.
- **관측 개선 여지**: `llm_generate_response_finish_reason` 등 일부 LLM 로그에 `call_id`가 빈 문자열로 남아, 동일 시각 다중 통화 시 상관이 어려울 수 있음(본 케이스는 앞뒤 `Nyki4RQxfk` 이벤트로 특정 가능).

## 권장 후속 (구현 시)

1. ~~`classify_intent` merged …~~ **반영됨** — `2026-04-14_1610_MAX_TOKENS_TTS_SANITIZE_IMPL.md`.
2. `booking_agent`: **`bind_tools` 가능 모델** 정리(선택).
3. LLM 완료 로그에 `call_id` 전달 일원화(선택).

## 변경 이력 (파일별)

| 파일 경로 | 변경 유형 | 요약 | 비고 |
|-----------|-----------|------|------|
| (본 문서) | 추가 | `Nyki4RQxfk` MAX_TOKENS 점검 결과 기록 | 로그·코드 대조 |
