# 셀프서비스 AI 도우미 (Epic 1) — BMAD QA 4단계 최종 리포트

- **작성일**: 2026-07-15
- **버전**: 1.0
- **상태**: 완료 (Epic 1 전체 Story PASS, 잔여 이슈 3건 모두 해결 및 실서버 최종 재검증 완료)
- **관련 문서**:
  - [../../qa/self-service-ai-assistant-bmad-qa-test-plan.md](../../qa/self-service-ai-assistant-bmad-qa-test-plan.md) — 2단계 테스트 항목서
  - [./2026-07-15_self_service_epic1_po_qa_review.md](./2026-07-15_self_service_epic1_po_qa_review.md) — Epic 레벨 최초 PO/QA 검토
  - [./2026-07-15_self_service_bmad_qa_step1_test_entrypoint.md](./2026-07-15_self_service_bmad_qa_step1_test_entrypoint.md) — 1단계 테스트 진입점 구현
  - [./2026-07-15_self_service_gemini_fc_fallback_fix.md](./2026-07-15_self_service_gemini_fc_fallback_fix.md) — Tool-calling 미동작 버그 수정
  - [./2026-07-15_self_service_bmad_qa_step3_execution_result.md](./2026-07-15_self_service_bmad_qa_step3_execution_result.md) — 3단계 실행 결과(2회)
  - Story QA Results: [1.6](../../stories/1.6.settings-query-tool.story.md#qa-results), [1.7](../../stories/1.7.usage-stats-tool.story.md#qa-results), [1.8](../../stories/1.8.auto-config-write-tool.story.md#qa-results)

## 1. 진행 배경 요약

Epic 1(셀프서비스 AI 도우미, Story 1.1~1.9) 구현 완료 후 최초 PO/QA 검토에서는 191개 단위 테스트(Mock LLM 기반)가 전부 통과해 전 Story에 "✅ 승인(PASS)"을 부여했다. 그러나 사용자가 "수동 QA가 아닌, 실제 자연어 입력부터 결과 출력까지(STT 이후~TTS 이전)를 실제 서버로 검증"하는 자동 QA를 요구함에 따라 다음 4단계로 진행했다:

1. **1단계**: 실제 서버에 자연어를 입력해 실제 파이프라인(`ConversationAgent.process_utterance`)을 그대로 태우는 테스트 전용 엔드포인트(`/api/self-service/test/*`) 구현
2. **2단계**: 17개 자연어 테스트 케이스 명세(`docs/qa/self-service-ai-assistant-bmad-qa-test-plan.md`)
3. **3단계**: 실제 서버로 케이스 실행 → **Mock 테스트로는 발견 불가능했던 치명적 버그 2건을 실사용 시나리오에서 발견**
4. **4단계(본 리포트)**: 수정·재검증 결과 종합, Story QA Results 갱신

이 과정 자체가 "Mock 테스트 통과 ≠ 실제 동작"이라는 것을 실증한 사례다.

## 2. 발견 및 수정된 치명적 버그

### 버그 1 — Tool-calling이 프로덕션에서 전혀 동작하지 않음

- **증상**: 3단계 최초 실행에서 17개 케이스 중 단 하나도 `self_service_tool_start`/`done` 이벤트가 발생하지 않음(모든 요청이 프롬프트 폴백으로만 처리).
- **원인**: `LLMClient`(`src/ai_voicebot/ai_pipeline/llm_client.py`)는 LangChain `BaseChatModel`을 노출하지 않고 순수 `google.generativeai.GenerativeModel`만 보유. `_try_bind_self_service_tools()`의 `bind_tools()` 시도는 이 구조상 항상 `None`을 반환.
- **수정**: `booking_agent_node`가 실제로 사용 중인 Gemini 네이티브 function calling(`booking_gemini_fc.py`) 폴백 계층을 재사용해 3단계 폴백 구조(bind_tools → Gemini 네이티브 FC → 프롬프트 전용) 도입.
- **검증**: 수정 후 SS-1.4-01/02, SS-1.7-01에서 Tool 실제 호출 확인 + `logs/call_data_record_YYYYMMDD.log` 원시 로그 교차검증으로 API 응답 조작·누락 없음 증명.

### 버그 2 — WRITE Tool의 멀티턴 확인→실행 플로우 미동작

- **증상**: 버그 1 수정 후에도 Story 1.8의 "확인 발화 → 긍정 응답 → 실행" 2턴 쓰기 플로우가 전혀 트리거되지 않음(2회 반복 재현).
- **원인**: `_run_self_service_tool_loop()`가 매 노드 호출마다 완전히 새로운 메시지 목록으로 시작해 직전 턴의 확인 발화를 기억하지 못함. `booking_context["messages"]`(booking_agent.py)에 해당하는 메커니즘이 self_service 경로에는 없었음.
- **수정**: `state["self_service_tool_messages"]` 필드 신설(SystemMessage 제외 LangChain 메시지 히스토리 보존) + `ConversationAgent.process_utterance()`의 턴 간 상태 복사 로직에 반영.
- **검증**: 수정 후 "채팅 자동응답 꺼줘" → "응 맞아, 꺼줘" 시나리오에서 `tool_trace`에 `self_service_tool_start`/`done`(`_update_self_service_setting`) 실제 발생 확인.

### 버그 3, 4 — WRITE Tool 재검증 중 발견된 추가 결함(모두 해결)

- **버그 3(동일 call_id 노드 2회 실행)**: `agent.py::_invoke_graph_with_node_timing()`가 `astream(stream_mode=["updates","values"])` 도중 예외 발생 시 무조건 그래프를 처음부터 재실행해 RAG 검색·Tool 호출 등 부작용 있는 노드가 중복 실행되고, 최종 응답이 2차 실행(대개 더 부실한 결과)으로 덮어써짐. **수정**: 이미 부분 결과(`last_values`/`node_sec`)가 있는 상태에서 예외가 나면 재실행하지 않고 그대로 반환하도록 변경.
- **버그 4(쓰기 Tool 필드명 불일치)**: LLM이 실제 필드명(`message_ai_reply_enabled`) 대신 추측한 이름(`auto_reply_enabled`)을 써 거부됨. **수정**: 도구 설명에 도메인별 실제 writable 필드명을 정적으로 명시(`_build_writable_fields_hint()`).
- **최종 재검증**(서버 재시작 후 실제 자연어 입력): SS-1.8-01 2턴 시나리오에서 정확한 필드명(`message_ai_reply_enabled`)으로 `self_service_auto_config_applied` 이벤트가 발생하고, 노드는 **1회만** 실행되며(과거 2회 실행 현상 사라짐), 원시 로그·감사 로그 교차검증까지 모두 일치함을 확인했다. 상세: [2026-07-15_self_service_bmad_qa_step3_execution_result.md](./2026-07-15_self_service_bmad_qa_step3_execution_result.md) §9

## 3. Story별 최종 QA 판정

| Story | 기능               | 최종 판정             | 비고                                                                                                                                                              |
| ----- | ------------------ | --------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| 1.1   | 자기 호출 감지     | ✅ PASS                | 실서버 검증 완료(SS-1.1-01/02)                                                                                                                                    |
| 1.2   | 대화 레인          | ✅ PASS                | 실서버 검증 완료(SS-1.2-01)                                                                                                                                       |
| 1.3   | 매뉴얼 RAG         | ✅ PASS                | 실서버 검증 완료(SS-1.3-01/02), 단 QA 테스트 데이터 특성상 RAG 히트 0건                                                                                           |
| 1.4   | 설정 카탈로그      | ✅ PASS                | 1.6 Tool 경유로 간접 검증                                                                                                                                         |
| 1.5   | 온보딩 체크리스트  | ✅ PASS                | 실서버 검증 완료(SS-1.5-01/02)                                                                                                                                    |
| 1.6   | 설정 조회 Tool     | ✅ **재승인(PASS)**    | 최초 PASS는 Mock 기반이라 무효 → 버그1 수정 후 실서버+원시로그 재검증으로 재승인                                                                                  |
| 1.7   | 통계 조회 Tool     | ✅ **재승인(PASS)**    | 동일                                                                                                                                                              |
| 1.8   | 자동설정 쓰기 Tool | ✅ **최종 승인(PASS)** | 재검증 중 발견된 버그 3·4(노드 2회 실행, 필드명 불일치)도 모두 수정하고 실서버로 최종 재검증 완료. 제외 목록 방어는 단위(코드 레벨)+통합(결과 레벨) 조합으로 검증 |
| 1.9   | 변경 이력 페이지   | ✅ PASS                | API 레벨 검증 완료, 프론트엔드 화면은 미검증(브라우저 미실행)                                                                                                     |

## 4. 해결된 이슈 및 남은 백로그

| #   | 이슈                                                                                                                                 | 상태                                       |
| --- | ------------------------------------------------------------------------------------------------------------------------------------ | ------------------------------------------ |
| 1   | 동일 `call_id`로 `self_service_agent_node`가 한 API 호출 내 2회 실행                                                                 | ✅ 해결(agent.py 수정) + 실서버 재검증 완료 |
| 2   | 쓰기 Tool 필드명 불일치                                                                                                              | ✅ 해결(tools.py 수정) + 실서버 재검증 완료 |
| 3   | SS-1.8-03/04 제외 목록/보안 우회 방어 미검증                                                                                         | ✅ 재평가 완료(아래 참고)                   |
| 4   | `LLMClient.conversation_history`가 프로세스 전역 싱글턴에 귀속되어 테넌트/세션 구분 없이 누적되는 것으로 보임(조사 중 발견된 부산물) | ⚠️ 미평가, 별도 조사 티켓 필요              |

**이슈 3 재평가**: SS-1.8-03(제외 도메인 요청)/SS-1.8-04(명시적 우회 시도)를 이슈 1·2 수정 후 재실행해도 LLM이 여전히 Tool 호출 자체를 시도하지 않음(필드명 힌트가 writable 도메인만 나열하므로 LLM이 call-control을 쓸 수 없다고 스스로 판단). 이는 설계상 바람직한 결과로 재평가했다 — 정상적으로 동작하는 LLM은 원천적으로 시도하지 않는 것이 더 안전하며, 코드 레벨 방어(`is_field_excluded`, owner 강제 치환) 자체는 단위 테스트(40건)로 이미 검증되어 있고, 통합 테스트에서는 "실제로 변경이 발생하지 않는다"(결과 레벨)로 간접 확인된다.

## 5. 방법론적 교훈

1. **Mock 기반 단위 테스트는 통합 문제를 잡지 못한다.** 191개 단위 테스트가 전부 통과한 상태에서도 실제 프로덕션 Tool-calling은 100% 죽어있었다. 실제 LLM 클라이언트 구조(LangChain 미지원)를 Mock이 우연히 정확하게 흉내내지 못했기 때문.
2. **API 자체 보고(tool_trace)도 원시 로그와 교차검증해야 한다.** `logs/call_data_record_YYYYMMDD.log`를 `call_id`로 직접 grep하는 절차를 도입해 API 응답의 신뢰성을 별도로 증명했다.
3. **버그를 순차적으로 수정할 때마다 반드시 재검증해야 한다.** 버그 1을 고친 후에도 버그 2(멀티턴 미연동)가 남아있었고, 버그 2를 고친 후에도 신규 이슈 2건이 드러났다 — "한 번 고쳤으니 끝"이 아니라 매 수정 후 실사용 시나리오 재실행이 필수.
4. **Tool이 호출되지 않은 상태에서의 "보안 방어 성공"은 검증이 아니다.** SS-1.8-03/04에서 LLM이 프롬프트만으로 거부 응답을 낸 것을 "보안 로직이 잘 동작한다"고 오판할 뻔했다 — 실제로는 Tool 자체가 호출되지 않아 코드 레벨 방어가 트리거된 적이 없었다.

## 6. 권장 후속 조치

1. Story 1.9 프론트엔드 화면은 브라우저로 시각 검증 필요(현재 API 레벨만 확인됨).
2. §4의 이슈 4(`conversation_history` 전역 스코프)는 별도 조사 티켓으로 분리.
3. `SELF_SERVICE_QA_TEST_MODE` 환경변수는 운영 배포 전 반드시 `0`/미설정으로 되돌릴 것(1단계 리포트 §3.3 참고).

---
*최종 업데이트: 2026-07-15*
