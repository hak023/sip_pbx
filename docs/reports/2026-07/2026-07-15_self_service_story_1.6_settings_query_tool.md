# Story 1.6 (설정 조회 Tool) 구현 완료 보고서

**작성일**: 2026-07-15
**관련 문서**: [1.6.settings-query-tool.story.md](../../stories/1.6.settings-query-tool.story.md), [1.4.settings-catalog-readonly.story.md](../../stories/1.4.settings-catalog-readonly.story.md)
**상태**: 완료 (Story Status → Review)

## 1. 문제 요약

테넌트 관리자가 "지금 알림 설정 어떻게 돼있어?"처럼 물으면 대시보드 접속 없이 현재 값을 답변받아야 한다. Story 1.4의 카탈로그 조회 함수를 LangGraph Tool로 노출하고, LLM이 실제로 그 Tool을 호출해 값을 확인하도록 해야 한다(환각 방지, FR10).

## 2. 중요 발견 — Story 1.2/1.5에 실제 Tool-calling 루프가 없었음

Story 1.6의 Dev Notes와 Task 2는 "Story 1.2/1.5에서 이미 구성된 LLM+Tool 루프"를 전제로 작성되었으나, 실제 코드를 확인한 결과 `self_service_agent_node`는 `bind_tools()` 없이 순수 프롬프트 텍스트만으로 LLM을 호출하는 구조였다(RAG 참고 정보·온보딩 체크리스트도 모두 시스템 프롬프트 삽입 방식). 이 Story에서 **처음으로 실제 Tool-calling 루프를 도입**해야 했다.

## 3. 구현 내용

### 3.1 `get_self_service_settings_tool` (Task 1, `src/ai_voicebot/self_service/tools.py` 수정)

- `settings_catalog.get_domain_value(domain, owner)`만 호출하는 얇은 래퍼(IV1 — 도메인 유효성 검증 로직을 재구현하지 않음)
- `get_domain_value()`가 반환한 `unregistered_domain` 에러만 감지해 사용자 친화적 문구 + `available_domains` 목록으로 재라벨링(그 외 에러는 그대로 통과)
- `SELF_SERVICE_TOOLS = [get_onboarding_checklist_tool, get_self_service_settings_tool]` 목록 정의

### 3.2 `self_service_agent_node`에 첫 실제 Tool-calling 루프 도입 (Task 2)

`booking_agent_node`와 유사하지만 대폭 단순화된 구조:

- `_try_bind_self_service_tools(llm_client, call_id)`: `llm_client._chat_model`(또는 `.chat_model`)에 `bind_tools(SELF_SERVICE_TOOLS)` 시도. langchain_core 미설치·속성 없음·bind_tools 실패 시 `None` 반환
- `llm_with_tools`가 `None`이면 **Story 1.2/1.3/1.5의 기존 프롬프트 플로우로 그대로 폴백** — 회귀 없음을 기존 테스트 전체 통과로 확인
- `llm_with_tools`가 있으면 `_run_self_service_tool_loop()`(최대 4라운드, `AIMessage`/`ToolMessage` 교환)로 실제 function-calling 수행
- `booking_agent_node`와의 의도적 차이: Gemini 네이티브 function-calling 폴백을 두지 않음 — 설정 조회는 읽기 전용이라 위험도가 낮고, bind_tools 미지원 시 기존 프롬프트 폴백으로 충분하다고 판단(스코프 축소, Dev 판단)
- Tool 사용 지시(`_TOOL_USAGE_INSTRUCTION`)는 bind_tools 경로에서만 시스템 프롬프트에 추가 — 도구가 바인딩되지 않은 폴백 경로에 "Tool을 호출하라"는 지시가 노출되면 LLM이 텍스트로 흉내내 혼동할 수 있어 분리

### 3.3 테스트 (`tests_new/unit/test_ai_voicebot/test_self_service_settings_tool.py`, 신규)

16개 테스트:
- Tool 함수: 등록된 도메인 값 반환, 미등록 도메인 친화적 메시지, 기타 에러 그대로 통과, 예외 흡수
- 데이터 일치성 계약 테스트(Task 3): Tool 반환값이 `get_domain_value()` 결과와 완전히 동일함을 검증(변환/가공 없음 — IV1 회귀 방지)
- `_try_bind_self_service_tools`: `_chat_model` 없음/bind_tools 성공/실패 3가지 분기
- `_execute_self_service_tool`: 알 수 없는 도구 오류, 등록된 도구 정상 실행
- `_run_self_service_tool_loop`: 툴 호출 후 최종 텍스트 반환, 최대 라운드 초과, invoke 예외 처리
- 노드 통합: bind_tools 가능 시 Tool 루프 사용, bind_tools 불가 시 기존 프롬프트 폴백 사용(회귀 계약)

## 4. 검증 결과

```
python -m pytest tests_new/unit/test_ai_voicebot/test_self_service_settings_tool.py -v --no-cov
→ 16 passed

python -m pytest tests_new/unit/test_ai_voicebot tests_new/unit/test_events -q --no-cov
→ 108 passed (Story 1.1~1.6 누적 92 + 신규 16), 회귀 없음
```

기존 Story 1.2/1.3/1.5 테스트가 사용하는 `_FakeLLM` 목 객체들은 `_chat_model` 속성이 없어 자동으로 폴백 경로를 타므로, 코드 변경 없이 전체 통과했다.

## 5. 변경 파일

- `src/ai_voicebot/self_service/tools.py` (수정 — `get_self_service_settings_tool`, `SELF_SERVICE_TOOLS` 추가)
- `src/ai_voicebot/langgraph/nodes/self_service_agent.py` (수정 — `_try_bind_self_service_tools`/`_execute_self_service_tool`/`_run_self_service_tool_loop` 추가, 노드 본문에 통합)
- `tests_new/unit/test_ai_voicebot/test_self_service_settings_tool.py` (신규, 16 tests)
- `docs/stories/1.6.settings-query-tool.story.md` (Task 1~3 체크, "구현 중 발견된 사실" 섹션 추가, Dev Agent Record/Change Log 갱신, Status → Review)

## 6. 후속 작업

- Story 1.7(통계 조회)·Story 1.8(자동설정 실행)에서 이번에 도입한 `SELF_SERVICE_TOOLS` 목록과 Tool-calling 루프 구조를 그대로 확장해 재사용 예정. Story 1.8은 쓰기 작업이므로 `destructive` 플래그(Story 1.4) 집행 로직이 이 루프에 추가로 필요하다.

---
*최종 업데이트: 2026-07-15*
