## 메타

- **작성일(로컬)**: 2026-04-21 14:48
- **상태**: 구현 완료
- **선행 리포트**: `sip-pbx/docs/reports/2026-04/2026-04-21_1349_TTS_PREFIX_BOOKING_TOOLS_RTP_LOG_IMPL.md` §잔여 과제

## 개요

`2026-04-21_1349` 리포트의 잔여 과제인 (1) **Gemini FC `Struct`/`MapComposite` 직렬화 오류** 완화, (2) **`stt_transcript_watchdog_alert`와 RTP·릴레이 상태 상관 로그**를 구현했다.

## 변경 이력 (파일별)

| 파일 경로 | 변경 유형 | 요약 | 비고 |
|-----------|------------|------|------|
| `sip-pbx/src/ai_voicebot/langgraph/booking_gemini_fc.py` | 수정 | `_sanitize_for_gemini_struct` + `ParseDict` 실패 시 fallback Struct | ToolMessage·function_call args 공통 |
| `sip-pbx/src/ai_voicebot/pipecat/processors/rag_processor.py` | 수정 | `rtp_worker` weakref + `_rtp_snapshot_for_stt_watchdog` + 알림에 `rtp_snapshot` | 착신/바이패스 상관 분석용 |
| `sip-pbx/src/ai_voicebot/pipecat/pipeline_builder.py` | 수정 | `RAGLLMProcessor(..., rtp_worker=rtp_worker)` | 단일 조립 지점 |
| `sip-pbx/src/ai_voicebot/langgraph/nodes/booking_agent.py` | 수정 | `booking_agent_llm_invoke_error`에 `error_type`·`recent_message_types`·`call_id` | TCP와 무관한 직렬화 추적 |

## 주요 결정 사항

1. **Struct**: protobuf가 허용하지 않는 값(NaN/Inf, 비표준 타입, 과도한 중첩 등)을 사전에 JSON 친화 값으로 정규화하고, `ParseDict` 예외 시 짧은 fallback payload로 재시도해 **라운드2 LLM 호출이 완전히 죽지 않게** 했다.
2. **워치독**: STT 알림은 여전히 **동일 Pipecat 파이프라인** 기준이며, 동일 시각의 **`rtp_snapshot`**(relay_mode, pipecat_mode, STT/TTS 큐 깊이, bypass·caller/callee 패킷 카운터)으로 **미디어 경로 가설을 로그에서 교차 검증**할 수 있다.

## Struct fallback 의미(보강)

- **의미**: LLM이 돌려준 **한국어 문장이 parse하기 어렵다**는 뜻이 **아님**. `ToolMessage`/function_call 인자를 **Gemini `Content`용 `protobuf Struct`로 넣는 `ParseDict` 단계**가 실패한 경우다.
- **디버깅 로그(보강)**: `booking_gemini_struct_parse_failed_fallback`에 `debug_context`(예: `function_call.args:create_booking_tool`, `function_response.body:…`), `incoming_json_preview`(sanitize **전** dict JSON), `sanitized_json_preview`(sanitize **후**), 키 목록을 **원문에 가깝게(길이 상한 내)** 남긴다.

## 잔여 과제

- 동일 로그가 **반복**되면 도구 반환 JSON에서 비표준 타입·과도한 중첩을 **생성 단계에서 제거**할지 검토(로그만으로 원인 확정 후).
