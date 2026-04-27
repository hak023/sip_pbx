# MAX_TOKENS 후속 + TTS JSON 차단 구현

- **작성일(로컬)**: 2026-04-14
- **상태**: 구현 완료
- **선행 점검**: `2026-04-14_1500_CALL_Nyki4RQxfk_MAX_TOKENS_INSPECTION.md`

## 개요

`Nyki4RQxfk` 점검에서 제안한 대로 **의도 분류·예약 폴백 LLM의 `max_output_tokens` 상향**, **순수 JSON 출력 유도 프롬프트 보강**, **예약 텍스트 폴백 전용 시스템 프롬프트**를 적용했다. 추가로 **TTS로 JSON·도구 조각이 나가지 않도록** 파이프라인에서 정화한다.

## 변경 이력 (파일별)

| 파일 경로 | 변경 유형 | 요약 | 비고 |
|-----------|-----------|------|------|
| `sip-pbx/src/ai_voicebot/langgraph/nodes/classify_intent.py` | 수정 | merged 분류 `max_output_tokens` 128→512, 코드펜스 금지·JSON만 출력 문구 추가 | 설계대로 |
| `sip-pbx/src/ai_voicebot/langgraph/nodes/booking_agent.py` | 수정 | `_BOOKING_TEXT_FALLBACK_SYSTEM` 추가, 폴백 호출 시 해당 프롬프트·`max_output_tokens` 1024 | 도구 경로 `_BOOKING_SYSTEM_PROMPT` 유지 |
| `sip-pbx/src/common/tts_output_sanitize.py` | 추가 | `sanitize_voice_assistant_text` — 마크다운 펜스·tool 조각·한글 없는 JSON 등 TTS 차단 | intent=booking 시 전용 멘트 |
| `sip-pbx/src/ai_voicebot/pipecat/processors/rag_processor.py` | 수정 | LangGraph 응답 TTS 직전·레거시 LLM 경로에 정화 적용, 조각 시 `chunks` 비움 | `tts_output_sanitized_llm_fragment` 로그 |
| `sip-pbx/docs/reports/2026-04/2026-04-14_1610_MAX_TOKENS_TTS_SANITIZE_IMPL.md` | 추가 | 본 리포트 | — |

## 주요 결정 사항

- **TTS 정화 위치**: `RAGLLMProcessor`에서 HITL·follow_up 저장 **이후**, `log_call_data` / `TextFrame` **이전**에 적용해 고객에게 나가는 문자열만 바꾼다. `langgraph_agent_result` 등 앞선 로그는 원문 유지로 디버깅 가능.
- **스트리밍 청크**: 정화가 발생하면 `chunks`를 비워 단일 `TextFrame`으로 안내 멘트만 전달한다.
- **레거시 RAG+LLM 경로**: 동일 정화를 적용해 분기 간 동작을 맞춘다.

## 잔여 과제 (선택)

- LLM 완료 로그에 `call_id`가 비는 문제는 별도 클라이언트 수정이 필요할 수 있음(저장소 외 패키지).
- `bind_tools` 가능 모델로 통일 시 텍스트 폴백 빈도 감소 기대.
