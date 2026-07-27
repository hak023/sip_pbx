# Project Brief: Gemini SDK 마이그레이션 (`google-generativeai` → `google-genai`)

**작성일**: 2026-07-24
**버전**: 0.1 (초안)
**상태**: 초안 (Draft) — PRD 작성 전 단계
**관련 문서**:
- [voice-latency-turn-taking-brief.md](voice-latency-turn-taking-brief.md), [voice-latency-turn-taking-prd.md](voice-latency-turn-taking-prd.md) — 음성 지연 개선 Epic(본 마이그레이션의 상위 동기)
- [../architecture/voice-latency-turn-taking-architecture.md](../architecture/voice-latency-turn-taking-architecture.md)
- [../architecture/coding-standards.md](../architecture/coding-standards.md) §4 — LLM Tool-calling 3단계 폴백 구조(마이그레이션 시 반드시 보존해야 하는 계약)
- [../reports/2026-07/2026-07-24_root_cause_gemini_thinking_not_actually_disabled.md](../reports/2026-07/2026-07-24_root_cause_gemini_thinking_not_actually_disabled.md) — 근본 원인 확정 리포트
- [../reports/2026-07/2026-07-24_google_genai_thinking_off_spike_validation.md](../reports/2026-07/2026-07-24_google_genai_thinking_off_spike_validation.md) — 스파이크 검증 리포트(TTFT 3.81s→0.77s 실증, 영향 범위 인벤토리)

> **생성 방식 안내**: 사용자 요청("문서 확인해서 작업 시작" → 스파이크 검증 → BMAD 절차 진행)에 따라
> 코드베이스 직접 조사(grep/read) + 실제 API 호출 스파이크 결과를 근거로 작성한 초안이다.

---

## Executive Summary

**핵심 문제**: 설치된 `google-generativeai==0.8.6`(Google 공식 deprecated) SDK에는 `ThinkingConfig`
타입 자체가 없어, `LLMClient._thinking_off()`의 thinking 비활성화 코드가 `except (AttributeError,
TypeError): pass`로 조용히 실패해왔다. 즉 **Gemini 2.5 Flash의 thinking(내부 추론)이 단 한 번도
꺼진 적이 없었고**, 이것이 통화 응대·의도 분류·Tool-calling 등 `LLMClient`를 쓰는 모든 경로에서
수 초(6~9초, 최악 16초) 지연의 핵심 원인이다. 모델 교체(`gemini-2.0-flash` 폐지 404,
`gemini-2.5-flash-lite` 계정 제한 404)로는 회피 불가 — 유일한 해결 경로는 신규 `google-genai`
SDK(이미 venv에 v1.75.0 설치됨)로 마이그레이션하는 것이다.

**검증 완료**: 독립 스파이크 스크립트로 `thinking_budget=0`을 실제 적용해 TTFT가 3.81초 → 0.77초
(약 80% 감소)로 줄어드는 것을 확인했다(재현 가능, 실 프로덕션 코드 미반영 상태).

**목표**: `google-generativeai` 의존 코드 전체(`LLMClient` 8개 공개 메서드 + Gemini 네이티브
Tool-calling 헬퍼 `booking_gemini_fc.py` + knowledge/ 4개 모듈 + 2개 라우터/서비스 파일)를
`google-genai`로 전환해 thinking을 실제로 비활성화하고, 기존 Tool-calling 3단계 폴백 구조·
멀티턴 상태·로깅 컨벤션을 그대로 보존한다.

**핵심 가치 제안**: "SDK를 바꿔도 기존 통화 응대·예약·셀프서비스 동작은 그대로 유지된 채, 내부
추론이 필요 없는 모든 응답의 TTFT가 수 초 단축된다."

---

## Problem Statement

### 1) Thinking이 한 번도 꺼진 적이 없었음 (근본 원인 확정)

- `LLMClient.__init__`/`_thinking_off()`(`llm_client.py`)는 `genai.types.ThinkingConfig(thinking_budget=0)`을
  생성해 모든 호출에 적용하도록 설계돼 있으나, `google-generativeai==0.8.6`에는 이 타입이 없어
  `AttributeError`가 발생하고 넓은 `except`가 이를 삼킨다. 로그 레벨이 debug라 운영 로그에서도
  드러나지 않았다.
- 영향 범위: `generate_simple`, `generate_help_items_json`, `generate_response`,
  `generate_response_streaming`, `format_for_customer`, `format_hitl_reply_for_customer`,
  `judge_barge_in`, `judge_usefulness` — `LLMClient`의 사실상 전체 공개 API.
- 2026-03-30 리포트의 "평균 8.69초, 최악 16초" 지연도 동일 원인일 가능성이 매우 높다(별도 확정
  검증은 이번 Epic 범위 밖).

### 2) 모델 교체로는 우회·검증 모두 불가능

- `gemini-2.0-flash`: 폐지(404). `gemini-2.5-flash-lite`: 이 계정에서 신규 사용 제한(404).
  thinking이 없는 대안 모델 자체가 이 계정에 없다 — SDK 마이그레이션이 유일한 경로.

### 3) 마이그레이션 표면이 넓고, Tool-calling 계약을 깨뜨릴 위험이 크다

- `google.generativeai` 직접 사용: `llm_client.py`(핵심), `knowledge/entity_extractor.py`,
  `knowledge/hallucination_checker.py`, `knowledge/qa_extractor.py`, `knowledge/summarizer.py`,
  `api/routers/call_history.py`, `services/ringback_service.py`.
- Gemini 네이티브 Function-calling(`google.ai.generativelanguage` = `glm`, 별도 SDK 네임스페이스):
  `langgraph/booking_gemini_fc.py` — booking/self_service 등 여러 LangGraph 노드가 공유하는
  범용 헬퍼(`_langchain_tools_to_glm_tool`, `build_booking_generative_model`,
  `invoke_booking_model_with_gemini_fc`, `_candidate_function_calls`/`_candidate_text`).
  `google-genai`는 `types.Tool`/`types.FunctionDeclaration`/`Client.models.generate_content`로
  API 형태가 다르므로 **단순 import 치환이 아니라 이 헬퍼 전체의 재구현이 필요**하다.
- `coding-standards.md` §4의 "3단계 폴백 구조"(`bind_tools()` → Gemini 네이티브 FC → 프롬프트
  전용 폴백)와 §5의 "멀티턴 tool_messages 상태"는 마이그레이션 후에도 동일하게 동작해야 하는
  회귀 방지 계약이다.

---

## Proposed Solution (개략)

1. `google-genai` 클라이언트를 감싸는 어댑터를 `LLMClient` 내부에 도입(공개 메서드 시그니처는
   변경하지 않아 호출부 영향 최소화) — `generate_content` → `client.models.generate_content`/
   `generate_content_stream`, `GenerationConfig` → `types.GenerateContentConfig`,
   `ThinkingConfig(thinking_budget=0)`는 신규 SDK에서 정식 지원되므로 그대로 적용.
2. `booking_gemini_fc.py`의 `glm.Tool`/`glm.Schema` 구성 로직을 `google-genai`의
   `types.Tool`/`types.FunctionDeclaration`/`types.Schema` 체계로 재작성하되, 공개 함수 시그니처
   (`build_booking_generative_model`, `invoke_booking_model_with_gemini_fc`,
   `_candidate_function_calls`, `_candidate_text`)는 유지해 호출부(`booking_agent.py`,
   `self_service_agent.py` 등)를 건드리지 않는다.
3. knowledge/ 4개 모듈의 지역 `import google.generativeai as genai` 호출부도 동일 어댑터 또는
   직접 `google-genai` 호출로 전환.
4. 단계적 롤아웃: 스파이크(완료) → 어댑터 구현 + 단위 테스트 → 회귀 스위트 전체 실행 → 실서버
   통합 검증(Tool-calling 로그 cross-check, `coding-standards.md` §6 방법론) → 완료 리포트.

## Non-Goals

- Gemini 이외 벤더(OpenAI 등) 추상화 레이어 도입은 범위 밖.
- 프롬프트 내용·시스템 프롬프트 로직 변경은 범위 밖(순수 SDK 계층 치환).
- `intent_tier.py` 등 이미 제거된 기능의 부활은 범위 밖.

## Success Metrics

- 실서버에서 chitchat/out_of_scope 등 안전 서브셋 응답의 TTFT가 스파이크 실측 수준(≤1초대)으로
  개선됨을 QA 하네스(`ai_pipeline_test.py`)로 확인.
- 기존 Tool-calling 회귀(booking/self_service) 전체 PASS, tool_trace 및
  `call_data_record_*.log` cross-check 이상 없음.
- `judge_usefulness`/`judge_barge_in` 등 판단성 호출의 출력 포맷(JSON 등)이 마이그레이션 후에도
  동일하게 파싱됨.

## Risks

- `google-genai`의 안전 필터/finish_reason 표현이 `google-generativeai`와 달라 기존 파싱 코드
  (`finish_reason` 정수 매핑 등)가 깨질 수 있음 — 어댑터 계층에서 정규화 필요.
- Gemini 네이티브 FC 스키마 변환 버그 재발 위험(2026-07-21 `Any` 타입 → OBJECT 오분류 버그 사례)
  — 재작성 시 동일 회귀 테스트(`test_booking_gemini_fc_schema.py`)를 반드시 유지·확장할 것.

*최종 업데이트: 2026-07-24*
