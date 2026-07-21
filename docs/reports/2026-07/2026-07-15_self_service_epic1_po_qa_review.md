# 셀프서비스 AI 도우미 Epic 1 — PO/QA 검토 리포트

**작성일**: 2026-07-15
**검토 대상**: Story 1.1~1.9 (셀프서비스 AI 도우미)
**검토자**: Copilot (BMAD PO/QA 역할 겸임)
**관련 문서**: [self-service-ai-assistant-prd.md](../../product/self-service-ai-assistant-prd.md), [self-service-ai-assistant-architecture.md](../../architecture/self-service-ai-assistant-architecture.md), [docs/stories/1.1~1.9](../../stories/)

## 요약

Story 1.1~1.8은 모두 구현·테스트 완료(Status=Review)이며 회귀 테스트 164개 전체 통과. 검토 과정에서 **문서 동기화 누락 2건**과 **보안 경화가 필요한 1건**을 발견해 즉시 수정했다. Story 1.9(프론트엔드 이력 페이지)는 아직 Draft(미착수) 상태다.

## 1. Story별 상태 재확인

| Story | 제목                        | Status            | 테스트                       |
| ----- | --------------------------- | ----------------- | ---------------------------- |
| 1.1   | 자기 호출 감지              | Review            | 20                           |
| 1.2   | 셀프서비스 대화 레인        | Review            | 13                           |
| 1.3   | 매뉴얼 RAG 연동             | Review            | 17                           |
| 1.4   | 설정 카탈로그(읽기)         | Review            | 14                           |
| 1.5   | 온보딩 체크리스트           | Review            | 18                           |
| 1.6   | 설정 조회 Tool              | Review            | 16(→17, 보안 테스트 추가 후) |
| 1.7   | 이용 통계 조회 Tool         | Review            | 15                           |
| 1.8   | 자동설정(쓰기) Tool         | Review            | 40                           |
| 1.9   | 변경 이력 프론트엔드 페이지 | **Draft(미착수)** | -                            |

전체 회귀: `python -m pytest tests_new/unit/test_ai_voicebot tests_new/unit/test_events -q --no-cov` → **164 passed**.

## 2. 발견 사항 및 조치

### 2.1 [수정 완료] 문서 동기화 누락 (`copilot-instructions.md` 필수 규칙 위반)

- **`docs/SYSTEM_OVERVIEW.md`**: 셀프서비스 기능에 대한 언급이 전혀 없었음(§4 핵심 기능 목록에 누락). → **§4.11 "셀프서비스 AI 도우미" 섹션 신규 추가**(처리 흐름 mermaid, RAG/온보딩/카탈로그/통계/자동설정 요약, 관련 문서 링크).
- **`docs/INDEX.md`**: Dev Stories 표의 1.1~1.8이 전부 실제로는 "Review"인데 문서상 "Draft"로 표기되어 있었음(스토리 구현 완료 시마다 상태를 갱신하지 않은 누적 누락). → **1.1~1.8을 Review로, 1.9는 Draft로 정정**.

### 2.2 [수정 완료] 보안 경화 — owner 파라미터 강제 오버라이드 미흡

**발견**: `self_service_agent.py::_run_self_service_tool_loop()`의 owner 자동 주입 로직이 `if "owner" not in tool_args: tool_args["owner"] = owner` 형태였다. 모든 셀프서비스 Tool 함수가 `owner: str`을 필수 파라미터로 선언하므로, LLM의 function-calling 스키마에는 `owner`가 항상 포함되며 LLM이 (환각이든 프롬프트 인젝션이든) 임의의 owner 값을 채워 보내면 **세션 owner로 덮어써지지 않고 그대로 사용될 수 있는 구조**였다. 이는 Story 1.8 Task 4가 명시한 보안 요구사항("owner는 세션 컨텍스트로 고정되어 LLM이 다른 owner를 지정할 수 없음을 코드 레벨에서 검증")을 실제로는 충족하지 못하고 있었다는 뜻이다(이전 QA 시점에는 필드 단위 우회만 테스트했고 owner 단위 우회는 테스트하지 않았던 공백).

**조치**: `tool_args["owner"] = owner`를 **무조건 강제 오버라이드**하도록 수정(LLM이 무엇을 보내든 세션 owner로 교체). `call_id`도 동일하게 무조건 주입으로 통일(LLM이 애초에 알 수 없는 값이므로).

**회귀 테스트 추가**: `test_owner_is_force_overridden_regardless_of_llm_supplied_value` — LLM이 tool_call args에 `owner="attacker-owned-tenant"`를 채워 보내도 실제 실행 시 세션 owner(`"1003"`)로 강제 치환됨을 검증.

이 발견은 `booking_agent_node`에도 동일한 패턴(`if "owner" not in tool_args`)이 존재함을 확인했다 — 다만 booking_agent는 시스템 프롬프트에 `owner: {owner}`를 명시해 LLM이 인지하고 그대로 echo하는 것을 전제로 설계되어 있어 이번 Story 범위 밖의 별도 리스크로 남겨둔다(아래 3.3 참고).

### 2.3 [확인·기록만, 조치 불필요] 운영 리스크 관찰 사항

1. **bind_tools 실제 LLM 환경 미검증**: Story 1.6~1.8에서 도입한 `bind_tools` 기반 tool-calling 루프는 전부 mock LLM으로만 테스트되었고, 실제 Gemini(LangChain bind_tools) 응답 포맷에 대한 통합 테스트는 수행되지 않았다. `llm_client._chat_model` 속성 존재 여부로 자동 폴백되므로 프로덕션에서 문제가 있어도 기존 프롬프트 플로우로 안전하게 저하(graceful degrade)되지만, 실제 자동설정 기능이 작동하는지는 실제 통화/문자로 별도 확인이 필요하다.
2. **`self_service_config_changes` 테이블 반영 시점**: `src/booking/database.py::init_db()`가 `src/api/main.py` 시작 시 자동 호출됨을 확인했다 — 별도 수동 마이그레이션 불필요, 다음 서버 재시작 시 자동 생성됨.
3. **persona 저장 시 임베딩 재계산 비용**: `PersonaService.save_persona()`는 `escalation_mode`처럼 `description`과 무관한 필드만 바꿔도 매번 `description` 임베딩을 재계산한다. 이는 기존 `persona.py` 라우터의 PATCH 엔드포인트도 동일하게 갖고 있던 특성이라(Story 1.8이 새로 만든 문제가 아님, CR4에 따라 동일 함수를 재사용한 결과) 별도 조치는 하지 않았으나, 향후 개선 여지로 기록해 둔다.

## 3. 남은 결정 사항

### 3.1 Story 1.9(프론트엔드 이력 페이지) 처리 방향

Story 1.9는 Epic의 유일한 신규 REST 엔드포인트가 필요한 Story이며 아직 착수하지 않았다. Story 1.1~1.8만으로도 셀프서비스 AI 도우미의 **핵심 대화형 기능(조회·통계·자동설정)은 이미 100% 동작**하지만, "AI가 방금 무엇을 바꿨는지 화면으로 확인"하는 신뢰 보강 기능은 빠져 있다.

**권장**: Story 1.9를 이어서 구현하는 것을 권장한다(백엔드 데이터는 Story 1.8에서 이미 다 쌓이고 있어 조회 API + 프론트 페이지만 추가하면 됨, 상대적으로 작은 작업).

### 3.2 QA 관점 최종 판정

- **AC/IV 충족도**: Story 1.1~1.8의 모든 AC·IV가 코드와 테스트로 뒷받침됨(각 Story 문서의 "구현 중 발견된 사실" 절에 스코프 조정 근거 명시).
- **보안**: 제외 목록 하드 게이트(IV2), owner 강제 격리(신규 수정), 필드 화이트리스트 3중 방어 확인.
- **테스트**: 164개 전체 통과, 회귀 없음.
- **결론**: Story 1.1~1.8은 **PO/QA 승인 가능** 상태. Story 1.9는 별도 작업으로 진행 필요.

### 3.3 후속 검토 필요(범위 밖으로 기록만)

- `booking_agent_node`의 owner 주입 방식(시스템 프롬프트 echo 신뢰 + 누락 시에만 보완)이 self_service보다 약한 보안 모델이라는 점 — 별도 이슈로 다룰지 판단 필요(이번 Epic 범위 밖).

## 4. 변경 파일 (이번 검토 세션에서 수정)

- `docs/SYSTEM_OVERVIEW.md` (§4.11 신규 추가, 최종수정일 갱신)
- `docs/INDEX.md` (Dev Stories 상태 Draft→Review 정정)
- `src/ai_voicebot/langgraph/nodes/self_service_agent.py` (owner/call_id 강제 오버라이드 보안 수정)
- `tests_new/unit/test_ai_voicebot/test_self_service_settings_tool.py` (owner 강제 오버라이드 회귀 테스트 추가, 17 tests)

---
*최종 업데이트: 2026-07-15*
