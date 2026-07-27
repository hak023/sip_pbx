# `ringback_service.py`/`call_history.py` Gemini 모델 404 결함 수정 리포트

**작성일**: 2026-07-27
**관련 문서**: [6.3.peripheral-modules-genai-migration.story.md](../../stories/6.3.peripheral-modules-genai-migration.story.md) §"Story 범위 밖에서 발견한 기존 결함"

## 1. 문제 요약

Story 6.3에서 `ringback_service.py`의 `_call_llm`/`_call_llm_style_line`가 사용하는 모델
`"gemini-2.0-flash"`가 이 Google 계정에서 이미 폐지(404 NOT_FOUND)되어 있음을 발견했다.
추가 확인 결과 `call_history.py::generate_unhandled_draft`의 `"gemini-2.0-flash-lite"`도
동일하게 404임을 확인했다 — 즉 링백 가사/스타일 자동 생성, 미처리 문의 답변 초안 생성
3개 기능이 **모두 항상 실패**하고 있었다.

## 2. 수정 내용

사용자 지시("다른 로직과 동일한 LLM 모델을 사용하도록")에 따라, 별도 모델명을 하드코딩하지
않고 시스템 전역에서 이미 사용 중인 `LLMClient` 싱글턴(`src/ai_voicebot/factory.py::
get_llm_client()`)의 `_client`(google-genai Client)/`model_name`을 재사용하도록 수정했다.

- `ringback_service.py`: `_resolve_ringback_llm_client_and_model()` 헬퍼 신설. 싱글턴이
  있으면 그 client/model_name을 그대로 쓰고, 없는 예외적 컨텍스트(독립 스크립트 등)에서만
  `_RINGBACK_LLM_MODEL_FALLBACK = "gemini-2.5-flash"`(config.yaml `gemini.model` 기본값과
  동일)로 새 클라이언트를 생성한다.
- `call_history.py::generate_unhandled_draft`: 동일한 패턴으로 `get_llm_client()`을 우선
  사용하도록 수정.

## 3. 검증 결과

- 실 API 호출로 `_call_llm`/`_call_llm_style_line` 둘 다 `err=None`, 정상 텍스트 생성 확인
  (독립 스크립트 컨텍스트라 싱글턴이 없어 폴백 모델 `gemini-2.5-flash` 경로로 검증됨 —
  다른 로직과 완전히 동일한 모델).
- `tests_new/unit` 전체 회귀(사전 무관 결함 3건 제외) 재실행 — 0 FAILED, 종료 코드 0.

## 4. 참고

실서버(사용자가 재시작한 프로세스)에서는 `get_llm_client()` 싱글턴이 실제로 채워져 있으므로,
링백/미처리 답변 생성 기능이 다음 실행 시 `config.yaml`의 `gemini.model`(현재
`gemini-2.5-flash`)과 정확히 동일한 모델·클라이언트를 재사용하게 된다(리소스 절약 부수 효과도
있음 — 매 호출마다 새 `genai.Client` 생성하지 않음).

*최종 업데이트: 2026-07-27*
