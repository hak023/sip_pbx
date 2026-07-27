# Gemini SDK 마이그레이션(`google-generativeai` → `google-genai`) — Brownfield PRD

**작성일**: 2026-07-24
**버전**: 0.1 (초안)
**상태**: 초안 — Epic/Story 확정 전
**관련 문서**:
- [gemini-genai-migration-brief.md](gemini-genai-migration-brief.md) — 본 PRD의 상위 Project Brief
- [prd.md](prd.md) — 마스터 PRD (승인 후 Cross-cutting/Phase로 편입 예정)
- [voice-latency-turn-taking-prd.md](voice-latency-turn-taking-prd.md) — 음성 지연 개선 Epic(본 마이그레이션의 상위 동기, Epic 3~5)
- [../architecture/coding-standards.md](../architecture/coding-standards.md) §4~§6 — Tool-calling 3단계 폴백 구조, 검증 방법론(반드시 보존해야 하는 계약)
- [../reports/2026-07/2026-07-24_root_cause_gemini_thinking_not_actually_disabled.md](../reports/2026-07/2026-07-24_root_cause_gemini_thinking_not_actually_disabled.md)
- [../reports/2026-07/2026-07-24_google_genai_thinking_off_spike_validation.md](../reports/2026-07/2026-07-24_google_genai_thinking_off_spike_validation.md) — 스파이크 검증(TTFT 3.81s→0.77s), 코드 인벤토리

> **범위/생성 방식 안내**: 사용자 요청("스파이크 검증 후 BMAD 절차로 진행")에 따라 코드베이스 직접
> 조사(grep/read) + 실제 API 호출 스파이크 결과를 근거로 작성한 완성 초안(YOLO 모드)이다.

---

## Intro: Project Analysis and Context

### Analysis Source

IDE 기반 코드베이스 분석(grep 인벤토리) + [gemini-genai-migration-brief.md](gemini-genai-migration-brief.md) 리서치·스파이크 결과 재사용.

### Current Project State

`LLMClient`(`src/ai_voicebot/ai_pipeline/llm_client.py`)는 `google-generativeai==0.8.6`(공식
deprecated) SDK로 Gemini를 호출하며, thinking 비활성화 코드(`_thinking_off()`)가 이 SDK 버전에
없는 `ThinkingConfig` 타입을 참조하다 조용히 실패해 **thinking이 실제로는 한 번도 꺼진 적이
없다**. 이로 인해 통화 응대·의도 분류·Tool-calling 등 `LLMClient`를 쓰는 모든 경로에서 불필요한
3~6초대 TTFT 지연이 발생하고 있다(스파이크로 실증: thinking on 3.81s → off 0.77s).

### Available Documentation Analysis

| 문서                                  | 상태                                                                     |
| ------------------------------------- | ------------------------------------------------------------------------ |
| Tech Stack                            | ✅ (`pyproject.toml`, `requirements-ai.txt`에 `google-genai` 이미 설치됨) |
| LLM Tool-calling 아키텍처             | ✅ ([coding-standards.md](../architecture/coding-standards.md) §4~§6)     |
| 근본 원인 분석                        | ✅ (2026-07-24 root-cause 리포트)                                         |
| SDK 영향 범위 인벤토리                | ✅ (2026-07-24 스파이크 리포트 §4)                                        |
| google-genai 공식 마이그레이션 가이드 | ⚠️ 본 Story 작성 시 팀이 Google 공식 문서를 직접 재확인 필요              |

### Enhancement Type

☑ Technology Stack Upgrade / Refactor (기능 변경 없음, 내부 SDK 계층 치환)

### Enhancement Description

`google-generativeai` SDK에 대한 모든 직접 의존을 `google-genai`(이미 venv v1.75.0 설치됨)로
치환하여 `thinking_budget=0`이 실제로 적용되도록 한다. 공개 메서드 시그니처·응답 포맷·
Tool-calling 3단계 폴백 구조·멀티턴 상태 관리 등 기존 계약은 모두 보존한다.

### Impact Assessment

☑ Significant Impact — `LLMClient`(핵심 8개 공개 메서드), Gemini 네이티브 Tool-calling 헬퍼
(`booking_gemini_fc.py`, booking/self_service 등 여러 LangGraph 노드가 공유), knowledge/ 4개
모듈, 라우터/서비스 2개 파일까지 영향받는다. 다만 **호출부(booking_agent.py,
self_service_agent.py 등)의 시그니처는 변경하지 않는 어댑터 패턴**을 채택해 실제 변경은
"SDK 계층 내부 치환"으로 국한한다(CR1).

---

## Goals and Background Context

### Goals

- 모든 LLM 호출에서 thinking이 실제로 비활성화되어(`thinking_budget=0`), 내부 추론이 필요 없는
  응답의 TTFT가 수 초 단축된다.
- 기존 통화 응대·예약(booking)·셀프서비스 Tool-calling 동작은 회귀 없이 그대로 유지된다.
- Gemini 네이티브 Function-calling의 스키마 변환(특히 `Any` 타입 파라미터 처리, 2026-07-21
  버그 이력)이 신규 SDK에서도 동일하게 안전하게 동작한다.

### Background Context

[Project Brief](gemini-genai-migration-brief.md)에서 확정한 대로, 모델 교체로는 문제를
회피·검증할 수 없고 SDK 마이그레이션만이 유일한 해결 경로다. 이 저장소는 이미 `google-genai`가
venv에 설치되어 있어 추가 설치 없이 착수 가능하다.

### Change Log

| Change    | Date       | Version | Description                                                      | Author                 |
| --------- | ---------- | ------- | ---------------------------------------------------------------- | ---------------------- |
| 초안 생성 | 2026-07-24 | 0.1     | Project Brief + 스파이크 검증 결과 기반 브라운필드 PRD 최초 작성 | Copilot (BMAD PM 역할) |

---

## Requirements

### Functional

- **FR1**: `LLMClient`는 `google-genai` 클라이언트를 사용해야 하며, 모든 생성 호출에
  `thinking_config=types.ThinkingConfig(thinking_budget=0)`을 실제로 적용해야 한다(현재처럼
  조용히 무시되지 않아야 함 — 적용 실패 시 반드시 로그로 드러나야 한다).
- **FR2**: `LLMClient`의 8개 공개 메서드(`generate_simple`, `generate_help_items_json`,
  `generate_response`, `generate_response_streaming`, `format_for_customer`,
  `format_hitl_reply_for_customer`, `judge_barge_in`, `judge_usefulness`)는 시그니처·반환 타입을
  변경하지 않아야 한다(호출부 무변경 원칙).
- **FR3**: `booking_gemini_fc.py`의 공개 함수(`_langchain_tools_to_glm_tool`,
  `build_booking_generative_model`, `invoke_booking_model_with_gemini_fc`,
  `_candidate_function_calls`, `_candidate_text`)는 `google-genai`의 `types.Tool`/
  `types.FunctionDeclaration`/`types.Schema`/`Client.models.generate_content` 체계로
  재구현하되, 함수 시그니처와 반환 구조(tool_calls 리스트, 텍스트)는 유지해야 한다.
- **FR4**: JSON Schema → Gemini Schema 변환 로직은 2026-07-21에 발견된 `Any` 타입 파라미터
  오분류 버그(`st in ("object", "")` → 빈 OBJECT로 오변환)와 동일한 클래스의 문제가 재발하지
  않도록, 기존 회귀 테스트(`test_booking_gemini_fc_schema.py`)를 신규 SDK 기준으로 이식하고
  통과해야 한다.
- **FR5**: knowledge/ 4개 모듈(`entity_extractor.py`, `hallucination_checker.py`,
  `qa_extractor.py`, `summarizer.py`)의 지역 `import google.generativeai as genai` 호출부는
  `google-genai` 기반으로 전환하되, 각 모듈의 기존 출력 포맷(JSON 파싱 등)을 유지해야 한다.
- **FR6**: `api/routers/call_history.py`, `services/ringback_service.py`의 `google.generativeai`
  직접 사용 지점도 동일 기준으로 전환해야 한다.
- **FR7**: 마이그레이션 완료 후 `google-generativeai` 패키지에 대한 신규 직접 import가
  저장소 어디에도 남아있지 않아야 한다(grep으로 검증 가능해야 함).

### Non Functional

- **NFR1**: 마이그레이션 후 `finish_reason`/안전 필터(`safety_ratings`) 등 신규 SDK의 응답
  필드 표현이 기존 파싱 코드(정수 매핑 등)와 다르면, 어댑터 계층에서 기존 코드가 기대하는
  형태로 정규화해야 한다(호출부 수정 없이 흡수).
- **NFR2**: 신규 SDK 전환 후에도 셀프서비스/예약 세션의 첫 응답 지연이 기존 대비 **악화되지
  않아야 하며**, thinking 비활성화 효과로 인해 개선되어야 한다(스파이크 실측 수준 참고).
- **NFR3**: 마이그레이션은 `.env`/`config.yaml`에 신규 필수 설정을 추가하지 않아야 한다
  (기존 `GEMINI_API_KEY`/`GOOGLE_API_KEY` 환경변수 그대로 사용).

### Compatibility Requirements

- **CR1**: `LLMClient`를 사용하는 모든 호출부(`booking_agent.py`, `self_service_agent.py`,
  `classify_intent_node`, ringback 등)는 코드 변경이 필요 없어야 한다(어댑터 계층에서 흡수).
- **CR2**: `coding-standards.md` §4의 Tool-calling 3단계 폴백 구조(`bind_tools()` → Gemini
  네이티브 FC → 프롬프트 전용 폴백)와 §5의 멀티턴 `tool_messages` 상태 관리 방식은 마이그레이션
  전후 동일하게 유지되어야 한다.
- **CR3**: 기존 단위/통합 테스트(전체 회귀 스위트, 339개+)는 마이그레이션 후에도 모두 통과해야
  하며, mock 기반 테스트가 실제 SDK 차이를 놓치지 않도록 최소 1개 이상의 실 API 호출 통합
  테스트(스파이크 스크립트 패턴)를 유지해야 한다.

---

## Technical Constraints and Integration Requirements

### Existing Technology Stack

```
Languages:    Python 3.11+
LLM SDK(현재): google-generativeai==0.8.6 (deprecated)
LLM SDK(목표): google-genai==1.75.0 (이미 venv 설치됨)
Tool-calling:  google.ai.generativelanguage(glm) 네이티브 FC → google-genai types.Tool로 전환
```

### Integration Approach

- **어댑터 우선 전략**: `LLMClient` 내부에 `google-genai` 클라이언트를 캡슐화하고, 기존
  `self.model.generate_content(...)` 호출부를 `client.models.generate_content(...)`/
  `generate_content_stream(...)`로 치환하되 공개 메서드 시그니처는 그대로 둔다.
- **Tool-calling 재구현**: `booking_gemini_fc.py`는 `glm.Tool`/`glm.Schema` 구성 로직을
  `types.Tool`/`types.FunctionDeclaration`/`types.Schema`로 재작성하되 공개 함수 계약을 유지한다.
- **단계적 롤아웃**: (1) `LLMClient` 비-Tool 경로(생성/판단 메서드) 우선 전환 → (2)
  `booking_gemini_fc.py` Tool-calling 경로 전환 → (3) knowledge/ 4개 모듈 → (4) 라우터/서비스
  2개 파일. 각 단계마다 회귀 테스트 + 실서버 통합 검증(coding-standards.md §6 cross-check).

### Code Organization and Standards

- **File Structure Approach**: 기존 파일 구조 그대로 유지(`llm_client.py`,
  `booking_gemini_fc.py` 등 파일명·위치 불변). 신규 어댑터 헬퍼가 필요하면 같은 파일 내부
  private 함수로 추가(신규 모듈 분리는 Tool-calling 스키마 변환 로직처럼 복잡도가 높을 때만
  고려).
- **Naming Conventions**: 기존 `_thinking_off`, `_effective_generation_config` 등 헬퍼명 유지.
- **Coding Standards**: `.github/copilot-instructions.md`(문제 은폐 금지, 재시도로 증상만
  가리기 금지)와 `coding-standards.md` §4~§6 그대로 적용.
- **Testing Integration Strategy**: `tests_new/unit/`에 신규 SDK 기준 어댑터 단위 테스트 추가,
  `test_booking_gemini_fc_schema.py`는 신규 SDK의 Schema 타입 기준으로 이식. 실서버 통합 검증은
  `docs/architecture/coding-standards.md` §6 방법론(call_data_record 로그 cross-check)을 따른다.
- **Documentation Standards**: 완료 시 `docs/reports/YYYY-MM/`에 완료 보고서,
  `SYSTEM_OVERVIEW.md`/`INDEX.md` 업데이트(copilot-instructions.md 체크리스트 준수).

---

## Epic 6: Gemini SDK 마이그레이션 (Story 분할)

기존 저장소 Epic 넘버링(1~5)에 이어 **Epic 6**으로 등록한다. Story는 아래 순서로 착수한다
(각 Story 완료 시 회귀 테스트 + 필요한 경우 실서버 cross-check을 거친다).

1. **Story 6.1 — `LLMClient` 전환**: 어댑터 도입, thinking 비활성화 실제 적용, 8개 공개
   메서드 회귀 테스트. ([story 파일](../stories/6.1.llm-client-genai-adapter.story.md))
2. **Story 6.2 — Tool-calling 재구현**: `booking_gemini_fc.py`를 `google-genai` Tool 체계로
   재작성, 스키마 변환 회귀 테스트 이식, booking/self_service 실서버 cross-check.
3. **Story 6.3 — 주변 모듈 전환**: knowledge/ 4개 모듈, call_history.py, ringback_service.py 전환.
4. **Story 6.4 — 전체 통합 검증 및 정리**: `google-generativeai` 완전 제거 확인(grep), 전체 회귀
   + 실서버 TTFT 실측 비교, 완료 리포트.

*최종 업데이트: 2026-07-24*
