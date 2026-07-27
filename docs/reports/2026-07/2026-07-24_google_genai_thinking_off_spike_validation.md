# 스파이크 검증 리포트 — google-genai SDK `thinking_budget=0`이 TTFT 지연을 실제로 해소하는가

**작성일**: 2026-07-24
**관련 문서**: [2026-07-24_session_handover_voice_latency_and_gemini_thinking_root_cause.md](2026-07-24_session_handover_voice_latency_and_gemini_thinking_root_cause.md),
[2026-07-24_root_cause_gemini_thinking_not_actually_disabled.md](2026-07-24_root_cause_gemini_thinking_not_actually_disabled.md)
**상태**: 스파이크 완료, 가설 확정. 정식 마이그레이션은 미착수(BMAD 절차 필요).

## 1. 목적

인계 리포트가 제시한 옵션 2(SDK 마이그레이션 착수 전 빠른 검증)를 수행. `google-generativeai`
(deprecated, `ThinkingConfig` 미지원)를 `google-genai`(이미 venv에 v1.75.0 설치됨)로 교체하면
`thinking_budget=0`이 실제로 TTFT를 줄이는지 프로덕션 코드 변경 없이 독립 스크립트로 확인.

## 2. 방법

`sip-pbx/scripts/spike_google_genai_thinking_off.py` 신규 작성(프로덕션 미반영, 독립 실행
스크립트). `google.genai.Client`로 동일 chitchat 프롬프트("안녕하세요! 오늘 날씨가 참
좋네요.")를 모델 `gemini-2.5-flash`에 두 번 스트리밍 호출:
1. `thinking_config` 미지정(기존 `google-generativeai`와 동일 상황 = auto thinking)
2. `thinking_config=ThinkingConfig(thinking_budget=0)`

API 키는 `C:\work\gemini-api-key.json`(start-all.ps1이 사용하는 동일 키 파일)에서 로드해
터미널 세션에 `$env:GEMINI_API_KEY`로 설정 후 실행.

## 3. 결과

| 케이스                | TTFT   | 전체 소요 |
| --------------------- | ------ | --------- |
| thinking 미지정(auto) | 3.810s | 3.812s    |
| `thinking_budget=0`   | 0.773s | 1.190s    |

**TTFT가 3.81초 → 0.77초로 약 80% 감소.** 인계 리포트의 가설(현재 SDK에서 thinking이 단 한
번도 꺼진 적이 없어 6~9초대 지연이 발생했다)이 실증적으로 확정됨.

## 4. 마이그레이션 영향 범위 확인(코드 인벤토리)

`google.generativeai` 직접 사용 지점:
- `src/ai_voicebot/ai_pipeline/llm_client.py` — `LLMClient` 전체(핵심, 공개 메서드 7개:
  `generate_simple`, `generate_help_items_json`, `generate_response`,
  `generate_response_streaming`, `format_for_customer`, `format_hitl_reply_for_customer`,
  `judge_barge_in`, `judge_usefulness`)
- `src/ai_voicebot/knowledge/entity_extractor.py`, `hallucination_checker.py`,
  `qa_extractor.py`, `summarizer.py` — 각각 지역 `import google.generativeai as genai`
- `src/api/routers/call_history.py`, `src/services/ringback_service.py`

Gemini 네이티브 Function-calling(별도 SDK 경로, `google.ai.generativelanguage` = `glm`):
- `src/ai_voicebot/langgraph/booking_gemini_fc.py` — `LLMClient.model`(`genai.GenerativeModel`)에
  `glm.Tool`을 붙이는 범용 헬퍼. booking/self_service 등 여러 Tool-calling 경로가 공유.
  **단순 SDK 치환이 아니라 `google.genai`의 `types.Tool`/`types.FunctionDeclaration` 체계로
  재설계 필요**(coding-standards.md의 LLM Tool-calling 3단계 폴백 구조 문서화 원칙 참고).

## 5. 결론 및 다음 단계

- 가설 확정: `google-genai` 마이그레이션으로 thinking을 실제로 끌 수 있으며, chitchat류 응답의
  TTFT를 수 초 단위로 줄일 수 있다.
- 영향 범위가 `LLMClient`(8개 공개 메서드) + Tool-calling 헬퍼(`booking_gemini_fc.py`, 여러
  Story가 의존) + 4개 knowledge 모듈까지 광범위하여, **바로 코드 치환에 들어가지 않고
  `sip-pbx-bmad-harness.instructions.md` 절차대로 Brief/PRD → architecture 갱신 → Story 분할
  후 착수해야 한다.**
- 다음 세션 착수 지점: `docs/product/`에 신규 Brief/PRD(가칭 "Gemini SDK 마이그레이션") 작성부터
  시작.

*최종 업데이트: 2026-07-24*
