## 메타

- **작성일(로컬)**: 2026-04-16
- **상태**: 구현 완료
- **트리거**: `app.log` — `conversation_agent_invoke_error` / SqliteSaver async 미지원

## 개요

LangGraph 그래프가 `ainvoke`·`astream` 비동기 API를 사용하는데, 동기 `SqliteSaver`는 async 체크포인트 API를 지원하지 않아 런타임 예외가 발생했다. `AsyncSqliteSaver` + `aiosqlite` 싱글턴으로 영속 체크포인트를 유지하고, 그래프 컴파일은 이벤트 루프에서 `get_or_build_compiled_graph_async()` 로 수행한다.

## 변경 이력 (파일별)

| 파일 경로 | 변경 유형 | 요약 | 비고 |
|-----------|-----------|------|------|
| `sip-pbx/src/ai_voicebot/langgraph/checkpointer.py` | 수정 | 동기 SqliteSaver 제거, `get_async_sqlite_checkpointer`, `clear_checkpoint`를 동기 sqlite3로 정리 | |
| `sip-pbx/src/ai_voicebot/langgraph/agent.py` | 수정 | `_build_state_graph` 분리, `get_or_build_compiled_graph_async`, ConversationAgent 지연 로드 | |
| `sip-pbx/src/ai_voicebot/factory.py` | 수정 | 프리컴파일 시 async 그래프 사용 | |
| `sip-pbx/requirements-ai.txt` | 수정 | `aiosqlite` 명시 | |
| `sip-pbx/docs/reports/2026-04/2026-04-16_1100_ASYNC_SQLITE_CHECKPOINTER_FIX.md` | 추가 | 본 리포트 | |

## 주요 결정 사항

- `get_checkpointer()`는 레거시용 **MemorySaver** 만 반환(동기 호출 안전).
- PBX 경로는 **항상** `get_or_build_compiled_graph_async()` → `AsyncSqliteSaver` 우선, 실패 시 MemorySaver.

## 잔여 과제

- 배포 환경에서 `pip install -r requirements-ai.txt` 로 `aiosqlite` 반영 후 프로세스 재시작.
