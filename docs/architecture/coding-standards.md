# 코딩 표준 (BMAD Dev 에이전트 상시 로드 문서)

**작성일**: 2026-07-16
**상태**: 진행 중 — 실제로 디버깅·QA 중 검증된 사실만 기록한다(추측 금지)
**용도**: `bmad/.bmad-core/core-config.yaml`의 `devLoadAlwaysFiles`에 등록되어, BMAD Dev 에이전트(James)가
스토리 작업 시작 전 항상 읽는다. 새로운 함정/컨벤션을 발견하면 여기에 즉시 추가한다(리포트에만
적고 여기 반영하지 않으면 다음 Dev 세션이 같은 문제를 반복한다).

---

## 1. 로깅 컨벤션 — 두 종류의 로거가 공존한다

- `src/common/*_db.py` 계열(`call_record_db.py`, `self_service_config_change_db.py` 등)은
  **stdlib** `logging.getLogger(__name__)` 사용 → **%-포맷 위치 인자만 허용**.
  `logger.warning("msg", key=val)`처럼 키워드 인자를 넘기면 `TypeError` 발생.
- `src/ai_voicebot/**` (self_service 포함)은 **structlog** `structlog.get_logger(__name__)` 사용 →
  키워드 인자 로깅 가능.
- **새 모듈 작성 전 같은 디렉터리의 기존 파일이 어떤 로거를 쓰는지 먼저 확인할 것.**

## 2. DB 스키마의 실제 소스는 `migrations/`가 아니다

- `migrations/*.sql`은 Postgres 문법(UUID, plpgsql)이며 어떤 Python 코드에서도 참조되지 않는
  **미사용/레거시 경로**다.
- 실제 런타임(SQLite) 스키마는 `src/booking/database.py`의 `_DDL`(CREATE TABLE) +
  `_MIGRATIONS`(ALTER TABLE 리스트)이며 `init_db()`가 서버 기동 시 실행한다.
- **새 테이블/컬럼 추가 시 `migrations/`가 아니라 `booking/database.py`의 `_DDL`/`_MIGRATIONS`에
  추가해야 실제로 반영된다.**

## 3. self_service 모듈 레이어 분리 원칙

- `settings_catalog.py`: 순수 조회/디스패치 레지스트리(get_fn/update_fn 등록)만 담당. 판단
  로직·감사 로깅 등 부작용은 절대 넣지 않는다.
- `onboarding.py` / `stats.py` / `auto_config.py`: 카탈로그를 소비하는 판단/집계/쓰기
  오케스트레이션 레이어. 카탈로그와 분리 유지.
- `tools.py`: LangChain Tool 얇은 wrapper 모음(`SELF_SERVICE_TOOLS`). `booking_tools.py`의
  `_make_tool` 패턴(langchain_core 미설치 시 원본 함수 반환)을 복제해서 쓴다(private 심볼 직접
  import 금지).

## 4. LLM Tool-calling — `bind_tools()`는 이 코드베이스에서 항상 실패한다

- `LLMClient`(`src/ai_voicebot/ai_pipeline/llm_client.py`)는 LangChain `BaseChatModel`을 노출하지
  않는다(`self.model = genai.GenerativeModel(...)` — 순수 `google.generativeai` SDK 래퍼).
  `_chat_model`/`chat_model` 속성 자체가 없다.
  → `getattr(llm_client, "_chat_model", None)`으로 raw LLM을 얻어 `bind_tools()`하는 코드는
  **프로덕션에서 항상 `None`**을 반환한다(mock 테스트에서만 동작하는 것처럼 보인다).
- 실제로 동작하는 유일한 Tool-calling 경로는 **Gemini 네이티브 function calling**
  (`google.ai.generativelanguage` = `glm`)이며, `src/ai_voicebot/langgraph/booking_gemini_fc.py`에
  범용 헬퍼가 있다(이름은 booking이지만 재사용 가능):
  - `_langchain_tools_to_glm_tool(tools)` — LangChain tool 리스트 → `glm.Tool`
  - `build_booking_generative_model(llm_client, glm_tool)` — tools가 붙은 새 `GenerativeModel` 생성
  - `invoke_booking_model_with_gemini_fc(gen_model=, lc_messages=, generation_config=)` — LangChain
    메시지 → Gemini contents 변환 후 `generate_content` 호출
  - `_candidate_function_calls(resp)` / `_candidate_text(resp)` — 응답 파싱
- **신규 LangGraph 노드에 Tool-calling을 붙일 때 반드시 3단계 폴백 구조를 쓸 것**:
  1. `bind_tools()` 시도(현재는 항상 실패하지만 향후 대비 유지)
  2. Gemini 네이티브 FC(`booking_gemini_fc.py` 헬퍼 재사용) — **실제로 동작하는 경로**
  3. 프롬프트 전용 폴백(둘 다 실패 시)
  - `booking_agent.py`가 원조 구현체. 2번을 생략하면 Tool이 전혀 호출되지 않는 조용한 버그가
    생긴다(2026-07-15 self_service_agent.py에서 실제 발견·수정됨).

## 5. Tool-calling 루프의 멀티턴 상태 — 새 state 키는 반드시 `agent.py`에 복사해야 유지된다

- Tool-calling 루프(`_run_self_service_tool_loop()`, `booking_agent.py` 동일 구조)는 매 노드
  호출마다 새 `messages` 리스트로 시작하지 않고, `state["<name>_tool_messages"]`
  (SystemMessage 제외 LangChain 메시지 리스트)로 이전 턴 기록을 유지하는 패턴을 쓴다
  (`booking_context["messages"]`가 원조 패턴).
- **주의**: `ConversationAgent.process_utterance()`가 턴 종료 시
  `self._state["<key>"] = result["<key>"]`처럼 **명시적으로 복사**하는 줄이 있어야 다음 턴에
  실제로 유지된다. 새 state 키를 추가할 때마다 이 복사 라인도 함께 추가할 것(안 하면 노드가
  값을 반환해도 다음 턴 호출 시 사라진다).

## 6. Tool-calling 검증 방법론 — API 응답만 믿지 말 것

- API 응답(`tool_trace` 등)만으로 "Tool이 호출됐다"고 판정하지 말고,
  `logs/call_data_record_YYYYMMDD.log`(JSON Lines)를 `call_id`로 직접 grep해서 원본 로그와
  대조해야 한다(API 자체 버그로 응답이 조작/누락될 가능성을 배제하기 위함).
  `scripts/self_service_qa_step3.ps1`의 `Test-RawLogCrossCheck` 함수가 이 패턴의 예시.
- mocked LLM 클라이언트 단위 테스트는 이런 통합 문제를 못 잡는다(mock이 `_chat_model=None`을
  자연스럽게 반환해 "폴백이 잘 동작한다"는 착각을 준다). 새 Tool-calling 기능은 반드시 실제
  서버 기동 후 통합 테스트로 로그에 실제 함수 호출 이벤트가 찍히는지 확인한다.

## 7. Config 접근 — 중첩 속성은 항상 `getattr` 체인으로

```python
# Good
enable_stt = getattr(
    getattr(getattr(config, 'ai_voicebot', None), 'recording', None),
    'post_processing_stt', None,
)

# Bad — 중간 단계가 None이면 AttributeError
enable_stt = config.ai_voicebot.recording.post_processing_stt
```

## 8. 에러 처리·예외 삼키기 금지

- 예외를 조용히 삼키지 않는다(`except: pass` 금지). 반드시 `logger.error(..., exc_info=True)`로
  기록한다. 예외를 삼키면 `agent.py::_invoke_graph_with_node_timing()`처럼 "예외 발생 시 전체
  재실행" 같은 숨은 버그가 재현 불가능해진다(2026-07-15 사례, §9 참고).

## 9. 알려진 함정 — LangGraph 노드 예외 시 전체 재실행

- `agent.py::_invoke_graph_with_node_timing()`는 `astream(stream_mode=["updates","values"])`
  도중 예외가 나면 과거에는 **무조건** `stream_mode="values"`로 그래프를 처음부터 재실행했다
  (부작용이 이미 발생했어도 재실행 → 동일 call_id로 노드가 2회 실행되고 마지막 실행의 응답이
  최종 응답을 덮어쓰는 버그로 이어졌다). 이미 `last_values`/`node_sec`이 채워진 상태라면
  재실행하지 않고 부분 결과를 반환하도록 수정 완료(2026-07-15). 유사한 "예외 시 전체 재시도"
  패턴을 새로 작성하지 말 것 — 대신 부분 상태를 보존하고 로그 레벨을 `warning` 이상으로 남긴다.

## 10. LangChain `@tool` docstring은 등록 시점에 캡처된다

- `@tool` 데코레이터는 데코레이션 시점의 `__doc__`을 그대로 캡처한다. 필드 힌트 등을 동적으로
  docstring에 삽입하려면(`.format()` 등) 반드시 `_make_tool()`/`@tool` 호출 **이전**에 처리해야
  한다. 사후에 `.__doc__`을 바꿔도 이미 생성된 `StructuredTool.description`에는 반영되지 않는다
  (`tools.py::_build_writable_fields_hint()` 참고).

---

*최종 업데이트: 2026-07-16*
