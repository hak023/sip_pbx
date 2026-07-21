# 셀프서비스 AI 도우미 — Tool-calling 미동작 버그 수정 (Gemini 네이티브 FC 폴백 추가)

- **작성일**: 2026-07-15
- **버전**: 1.0
- **상태**: 완료 (코드 수정 및 단위 테스트 완료, 실서버 재검증 대기)
- **관련 문서**:
  - [../../qa/self-service-ai-assistant-bmad-qa-test-plan.md](../../qa/self-service-ai-assistant-bmad-qa-test-plan.md)
  - [./2026-07-15_self_service_epic1_po_qa_review.md](./2026-07-15_self_service_epic1_po_qa_review.md)
  - [./2026-07-15_self_service_bmad_qa_step1_test_entrypoint.md](./2026-07-15_self_service_bmad_qa_step1_test_entrypoint.md)
  - [../../stories/1.6.settings-query-tool.story.md](../../stories/1.6.settings-query-tool.story.md)

## 1. 문제 요약

BMAD QA 자동 테스트(Step 3, `/api/self-service/test/converse` 엔드포인트로 실제 서버에 17개
테스트 케이스를 실행)에서, **셀프서비스 Tool(온보딩 조회·설정 조회·통계 조회·자동 설정 변경)이
단 한 번도 실제로 호출되지 않는 것**이 확인되었다. 모든 요청이 Tool 없이 프롬프트 전용 응답
경로로만 처리되었다.

## 2. 근본 원인

`self_service_agent.py`의 `_try_bind_self_service_tools()`는 LLM 인스턴스에서
`_chat_model`/`chat_model` 속성을 찾아 LangChain `bind_tools()`를 시도한다. 그러나 실제
프로덕션에서 쓰이는 `LLMClient`(`src/ai_voicebot/ai_pipeline/llm_client.py`)는 LangChain
`BaseChatModel`을 전혀 노출하지 않고, `self.model = genai.GenerativeModel(...)`처럼 순수
`google.generativeai` SDK 객체만 보유한다. 따라서 `getattr(llm_client, "_chat_model", None)`은
프로덕션에서 **항상 `None`**이 되어 `bind_tools()`가 결코 실행되지 않고, 노드는 항상
"Tool 없는 프롬프트 전용" 폴백 경로로 빠졌다.

이 문제는 191개의 기존 단위 테스트로는 전혀 잡히지 않았는데, 모든 테스트가 Mock LLM 클라이언트를
사용했고 Mock이 자연스럽게 `_chat_model=None`을 반환해 "폴백 경로가 의도대로 잘 동작한다"는
착각을 주었기 때문이다. 사용자가 요청한 실제 서버 대상 자동 통합 테스트(STT 이후~TTS 이전 진입점)
가 이 문제를 처음으로 드러냈다.

동일한 아키텍처 제약이 `booking_agent.py`에도 있으나, 그쪽은 Gemini 네이티브 function calling
폴백(`booking_gemini_fc.py`)이 이미 구현되어 있어 실제로 Tool-calling이 동작한다.
`self_service_agent.py`는 Story 1.6 구현 당시 이 폴백 계층 없이 `bind_tools()` 단일 경로만
설계된 것이 이번에 확인된 설계 공백이다.

## 3. 수정 내용

`sip-pbx/src/ai_voicebot/langgraph/nodes/self_service_agent.py`에 3단계 Tool-calling 폴백
구조를 추가했다(`booking_agent.py`/`booking_gemini_fc.py`의 기존 검증된 패턴 재사용):

1. `_try_bind_self_service_tools()` — LangChain `bind_tools()` 시도(향후 LLMClient 변경 시 대비,
   현재는 항상 실패).
2. **(신규)** `_try_build_self_service_gemini_fc()` — `booking_gemini_fc.py`의
   `_langchain_tools_to_glm_tool(SELF_SERVICE_TOOLS)` + `build_booking_generative_model()`을
   재사용해 Gemini 네이티브 FC 모델을 생성. **이것이 실제로 동작하는 경로.**
3. 둘 다 실패하면 기존 프롬프트 전용 폴백(Story 1.2/1.3/1.5) 유지.

`_run_self_service_tool_loop()`를 `llm_with_tools`(LangChain) 또는 `gen_model`(Gemini 네이티브)
중 하나를 받아 라운드마다 분기하도록 재작성했다(`booking_agent.py`의 dual-path 루프와 동일
구조). Gemini 네이티브 경로에서는 `invoke_booking_model_with_gemini_fc()` → 
`_candidate_function_calls()`/`_candidate_text()`로 응답을 파싱해 `AIMessage(tool_calls=...)`로
정규화한다. `owner`/`call_id` 강제 주입 등 기존 보안 로직(Story 1.8 AC)은 그대로 유지된다.

## 4. 검증 결과

- 기존 191개 단위 테스트 시그니처 변경분(`_run_self_service_tool_loop` 호출부 4곳) 수정 후 전부
  통과.
- 신규 테스트 5건 추가(`test_self_service_settings_tool.py`):
  - `_try_build_self_service_gemini_fc` 성공/실패 케이스 2건
  - `_run_self_service_tool_loop`의 Gemini 네이티브 FC 경로 Tool 실행 검증 1건
  - `self_service_agent_node`가 bind_tools 불가 시 Gemini 네이티브 FC 경로로 분기하는지 검증하는
    노드 레벨 통합 테스트 1건(+ 관련 회귀 확인 1건)
- 전체 회귀 스위트: `python -m pytest tests_new/unit/test_ai_voicebot tests_new/unit/test_events -q --no-cov`
  → **196 passed** (기존 191 + 신규 5), 회귀 없음.

## 5. 남은 작업

- [ ] 사용자 서버 재시작 후 `scripts/self_service_qa_step3.ps1`(또는 Tool-calling 관련 케이스만)
      재실행하여 `tool_trace`에 `self_service_tool_start`/`self_service_tool_done`/
      `self_service_auto_config_applied` 등 실제 이벤트가 기록되는지 최종 확인.
- [ ] Stories 1.6/1.7/1.8 story 문서의 QA Results "✅ 승인(PASS)" 문구를, 이번에 발견된 버그와 수정
      내용을 반영해 갱신.
- [ ] BMAD QA Step 4 최종 리포트 작성(발견된 버그, 수정 내용, 수정 전/후 테스트 근거 포함).

---
*최종 업데이트: 2026-07-15*
