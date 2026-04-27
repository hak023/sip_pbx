## 메타

- 작성일: 2026-04-20
- 관련: `2026-04-20_2000_CALL_lJOx6QvFnO_BOOKING_LOGIC_AUDIT.md` (bind_tools 미노출 → 예약 미커밋)

## 개요

`LLMClient`는 LangChain `BaseChatModel`을 노출하지 않아 `booking_agent`가 `bind_tools` 경로를 타지 못하고 텍스트 폴백만 하던 문제를 해소했다. **`google.generativeai.GenerativeModel`에 동일 예약 도구 목록을 `glm.Tool`로 선언**한 뒤, **`function_call` → 로컬 `_execute_tool` → `function_response` → 재호출** 루프로 LangChain 경로와 동일한 대화·히스토리(`AIMessage`/`ToolMessage`)를 유지한다.

## 변경 이력 (파일별)

| 파일 경로 | 변경 유형 | 요약 | 비고 |
|-----------|-----------|------|------|
| `sip-pbx/src/ai_voicebot/langgraph/booking_gemini_fc.py` | 추가 | JSON Schema→`glm.Schema`, LC 메시지↔Gemini contents, FC 파싱·호출 헬퍼 | 신규 |
| `sip-pbx/src/ai_voicebot/langgraph/nodes/booking_agent.py` | 수정 | `bind_tools` 실패 또는 `_chat_model` 없을 때 Gemini FC 모델로 도구 루프; `ToolMessage`에 `name` 설정 | 설계대로 |

## 주요 결정 사항

- **LangChain 우선**: `_chat_model` + `bind_tools`가 있으면 기존 `ainvoke` 경로 유지.
- **차선: Gemini 네이티브 FC**: 동일 API 키·모델명으로 `GenerativeModel(..., tools=[...])` 생성. `langchain-google-genai` 버전 이슈와 무관하게 동작.
- **출력 토큰**: 예약 루프는 `max_output_tokens=2048` 상한으로 `_effective_generation_config` 사용.
- **프롬프트 차단**: `prompt_feedback.block_reason` 시 안전한 한 줄 응답으로 종료.

## 잔여 과제 (선택)

- 운영 환경에서 실 통화로 `booking_tool_start` / `booking_committed` 로그·DB 반복 검증.
- `pyproject.toml`에 `langchain-core` / `langgraph` 명시 여부(현재는 런타임 설치 전제).
