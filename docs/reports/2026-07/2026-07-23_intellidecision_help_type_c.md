# IntelliDecision 유형 C(포괄적 도움 요청) 신설 — 완료 리포트

**작성일**: 2026-07-23
**작업 유형**: 신규 기능 반영(리뷰 요청 기반) — 셀프서비스 AI 도우미 Story 1.15
**관련 문서**: [1.15.intellidecision-help-type-capability-overview.story.md](../../stories/1.15.intellidecision-help-type-capability-overview.story.md),
[self-service-ai-assistant-prd.md](../../product/self-service-ai-assistant-prd.md)(FR25),
[self-service-ai-assistant-architecture.md](../../architecture/self-service-ai-assistant-architecture.md),
[self-service-ai-assistant-introduction.md](../../presentation/self-service-ai-assistant-introduction.md)

---

## 1. 요청 배경

사용자 요청: "셀프서비스 AI 시스템에는 help 관련한 분류가 필요하다. 사용자가 AI에게 '어떤 일을
할 수 있어?'와 같이 도움을 요청할 때 AI가 수행할 수 있는 내용을 예시와 함께 설명해야 하고,
IntelliDecision 로직에 포함하는 게 좋겠다. 내용을 검토해서 리포트해달라."

## 2. 리뷰 결과 — 실제 공백 확인

기존 IntelliDecision(PRD FR12, Story 1.10)은 설정 변경 관련 발화를 **유형 A(탐색성)**·
**유형 B(실행성)** 두 가지로만 구분한다. 코드(`self_service_agent.py::_TOOL_USAGE_INSTRUCTION`
항목 11)를 직접 확인한 결과, 두 유형 모두 "이미 특정 기능·설정 하나를 전제로 한 발화"만
다루며, "AI가 뭘 할 수 있어?"처럼 **대상이 특정되지 않은 포괄적 질문**에는 명시적으로
대응하는 로직이 전혀 없었다.

이런 포괄적 질문은 매뉴얼 RAG 검색에 전적으로 위임되는데, RAG 소스
(`docs/product/self-service-manual-content.md` §9)를 직접 읽어본 결과 관련 Q&A
("셀프서비스 AI 도우미에게 무엇을 물어볼 수 있나요?")가 존재하긴 했으나, 답변이 다음처럼
**미래형(stale) 서술**이었다:

> "이 매뉴얼에 담긴 모든 내용을 물어볼 수 있습니다. 또한 **향후 지원되는 기능이 추가되면**
> '지금 내 알림 설정이 어떻게 되어 있어?'처럼 현재 설정값을 조회하거나..."

실제로는 Epic 1(Story 1.1~1.14)·Epic 2(Story 2.1~2.8)가 이미 완료되어 설정 조회(7개 도메인)·
자동설정(3개 도메인 쓰기)·통계 조회·통화 이력 자연어 질의(3종)·온보딩 체크리스트·화면 안내가
전부 구현되어 있음에도, 이 Q&A는 "향후 지원되면"이라는 문구로 이미 존재하는 기능을 안내하지
못하고 있었다. 게다가 RAG가 이 Q&A를 임베딩 유사도로 못 찾는 표현("너 뭐 할 수 있어?" 등)의
경우에는 일반 폴백 문구("제가 알지 못하는 내용입니다")만 나가는 완전한 공백도 있었다.

**결론**: 사용자의 지적이 정확했다 — help 성격의 포괄적 질문에 대한 전용 분류·응대 로직이
실제로 누락되어 있었다. 이를 IntelliDecision의 세 번째 유형(유형 C)으로 반영했다.

## 3. 반영 내용

### 3.1 시스템 프롬프트 로직 (`src/ai_voicebot/langgraph/nodes/self_service_agent.py`)

- `_SELF_SERVICE_SYSTEM_PROMPT_TEMPLATE`(기본 시스템 프롬프트)에 신규 규칙(항목 7)을 추가해
  **유형 C(포괄적 도움 요청)** 를 정의했다. 트리거 예시: "뭘 할 수 있어?", "어떤 도움을 줄 수
  있어?", "무슨 일을 해줄 수 있어?", "사용법 알려줘".
  - 응답 시 최소 3개 카테고리(설정 조회/자동설정/통계/통화 이력 NLQ/온보딩/매뉴얼 Q&A)를
    **구체적 예시 발화**와 함께 3~4문장으로 요약하고, 마지막에 후속 질문을 유도하도록 지시.
  - 존재하지 않는 기능을 지어내지 않도록 명시(환각 방지).
- **설계 결정**: 유형 C는 Tool 호출이 필요 없는 순수 안내이므로, Tool 바인딩 성공 여부에 따라
  조립이 갈리는 `_TOOL_USAGE_INSTRUCTION`이 아니라 **항상 적용되는 기본 프롬프트**에 추가했다.
  이렇게 해야 프로덕션에서 실제로 쓰이는 Gemini 네이티브 FC 경로뿐 아니라, `bind_tools()`가
  항상 실패하는 이 코드베이스의 구조(repo 메모 §LLM 클라이언트 아키텍처 참고)나 향후 두 경로
  모두 실패했을 때의 프롬프트 전용 폴백에서도 동일하게 유형 C가 적용된다.
- `_TOOL_USAGE_INSTRUCTION`의 유형 A/B 판단 항목(구 11번 → 12번)에 "포괄적 질문은 이 항목이
  아니라 유형 C 규칙을 따르라"는 경계 문장을 추가해, LLM이 포괄적 질문을 유형 A로 오분류해
  매뉴얼 텍스트 단편만 반환하지 않도록 방지했다.
- 이어지는 Tool 사용 지시 항목 번호(구 8~14)를 9~15로 재조정 — 기본 프롬프트에 항목이 하나
  늘어나 번호가 겹치는 문제를 방지(기본 프롬프트 1~8, 부가 지시 9~15로 순차 연결).
- 모듈 docstring에 Story 1.15 변경 근거를 기록.

### 3.2 매뉴얼 RAG 콘텐츠 (`docs/product/self-service-manual-content.md`)

- §9 "무엇을 물어볼 수 있나요?" Q&A를 미래형 서술에서 **실제 구현된 6개 능력 카테고리**
  (설정 조회/자동설정/통계 조회/통화 이력 NLQ/온보딩 안내/매뉴얼 Q&A) 기준으로 재작성했다.
  프롬프트 규칙(3.1)이 주 경로이고, 이 변경은 RAG가 해당 Q&A를 검색 결과로 반환하는 경우에도
  정확한 답이 나가도록 하는 **이중 방어**다.
- 문서 버전 1.1 → 1.2, 개정 이력 갱신.
- **주의(미완료 항목)**: 이 매뉴얼은 owner별로 ChromaDB에 색인되며(`doc_type=self_service_manual`),
  `manual_indexer.py::index_self_service_manual()`은 이미 색인된 owner에는 `force=True` 없이는
  재색인하지 않는 멱등 구조다. 따라서 **원본 `.md` 파일 수정만으로는 이미 색인된 실제 테넌트의
  RAG 검색 결과에 자동 반영되지 않는다** — 재색인은 실제 테넌트 데이터에 영향을 주는 작업이므로
  이번 세션에서 직접 실행하지 않았고, 다음 유지보수 시점에 사용자 승인 후 진행할 것을 권장한다
  (Story 1.15 IV3).

### 3.3 설계 문서 반영

- **PRD** (`docs/product/self-service-ai-assistant-prd.md`): FR25(IntelliDecision 유형 C)
  신설, 버전 0.5 → 0.6, Change Log 갱신.
- **Architecture** (`docs/architecture/self-service-ai-assistant-architecture.md`): "IntelliDecision
  변경 (Story 2.6)" 섹션 아래에 "IntelliDecision 유형 C 추가 (Story 1.15)" 섹션 신설 — 설계
  결정 근거(기본 프롬프트에 추가한 이유, 이중 방어 근거) 기록. 버전 0.4 → 0.5, Change Log 갱신.
- **이해관계자 발표자료** (`docs/presentation/self-service-ai-assistant-introduction.md`):
  §4 IntelliDecision 섹션에 유형 C를 표·판단 플로우(mermaid)·응대 예시·설계 결정 이력 표
  전체에 반영.
- **Story 파일**: `docs/stories/1.15.intellidecision-help-type-capability-overview.story.md`
  신규 작성(Status: Done, Task 7 실서버 검증만 다음 세션으로 이월).
- **SYSTEM_OVERVIEW.md**/**INDEX.md**: §4.11 셀프서비스 섹션에 유형 C 한 줄 요약 추가, Story
  인덱스 표에 1.15 행 추가.

## 4. 검증 결과

### 4.1 단위 회귀 테스트

```
python -m pytest tests_new/unit/test_ai_voicebot/ -k self_service -q --no-cov
```

전체 self_service 관련 단위 테스트(약 229건) **전부 통과**(실패/오류 0건). 프롬프트 상수
문자열 변경 및 번호 재조정이 임포트·포맷팅(`str.format()`)·기존 로직에 영향을 주지 않음을
확인했다.

### 4.2 실서버 검증 (미실시 — 다음 세션 예정)

- **IV1(유형 C 실응답)**: "AI야 너 뭘 할 수 있어?" 계열 발화를 셀프서비스 세션으로 반복
  실행해 실제 응답이 최소 3개 카테고리 + 구체 예시를 포함하는지 확인 필요 — 서버 재시작 필요.
- **IV2(유형 A/B 회귀)**: 기존 Story 1.10/2.6 QA 16건 재실행 — 신규 규칙은 추가된 항목이라
  회귀 리스크는 낮다고 판단하나 실서버로 확정 필요.
- **IV3(매뉴얼 재색인)**: §9 콘텐츠 변경을 실제 owner의 ChromaDB에 반영하려면
  `index_self_service_manual(..., force=True)` 실행 필요(실제 테넌트 데이터 영향 — 사용자
  승인 후 진행 권장).

이 세 항목은 실행 중인 서버가 필요하고 포트/서버 재시작은 사용자 승인이 필요한 작업이므로
(`.github/copilot-instructions.md` 규칙), 이번 세션에서는 코드·문서 반영과 단위 테스트
검증까지 완료하고 실서버 검증은 다음 세션으로 명확히 이월한다.

## 5. 결론

사용자가 지적한 "help 분류 공백"은 실제 코드·매뉴얼 콘텐츠 확인 결과 사실로 확인되었다.
IntelliDecision에 유형 C(포괄적 도움 요청)를 신설해 기존 유형 A/B와 동일한 설계 원칙
(LLM 판단 우선, Tool 호출 최소화, 실제 기능만 안내)을 유지하면서 공백을 해소했다. 프롬프트
로직·매뉴얼 콘텐츠·PRD/architecture/발표자료 문서를 모두 갱신했고 단위 회귀는 전부 통과했다.
남은 실서버 검증(IV1~IV3)은 서버 재시작이 필요해 다음 세션으로 이월한다.

---
*최종 업데이트: 2026-07-23*
