# 대시보드에 greeting 1·2 미표시 — 원인 및 수정

- **작성일**: 2026-03-28 (로컬)
- **상태**: 수정 반영
- **관련**: `rag_processor.py`, `pipeline_builder.py`, `server.py`

## 원인

`RAGLLMProcessor.send_greeting()` 안에서 `emit_ai_greeting`은 **`if self._call_id:` 일 때만** 호출되었다.  
`self._call_id`가 비어 있어도 `pipeline_builder`가 `tts_sync_context["_call_id"]`에는 동일 통화 ID를 넣는 경우가 있어, **인사 TTS(TextFrame)는 나가도 WebSocket `ai_greeting`은 전혀 나가지 않는** 상태가 될 수 있다. 대시보드는 `ai_greeting`으로만 인사 줄을 그리므로 빈 화면으로 보였다.

## 수정 요약

1. **`_effective_call_id_for_ws()`**: `self._call_id`가 없으면 `tts_sync_context["_call_id"]`를 사용.
2. **`_emit_greeting_to_dashboard()`**: Phase1/2 공통으로 `set_greeting` + `emit_ai_greeting` 호출; call_id 없으면 `greeting_dashboard_emit_skipped_no_call_id` 경고 로그.
3. **`pipeline_builder`**: 초기 인사를 `pipeline.processors` 순회 대신 **`pipeline._rag_llm.send_greeting()`** 으로 명시 호출 (조립 시점에 `_rag_llm`이 항상 설정됨).
4. **`emit_ai_greeting`**: 송출 직전 `emit_ai_greeting_dispatch` INFO 로그로 서버에서 실제 디스패치 여부 확인 가능.

## 확인 방법

통화 한 건 후 `app.log`에서 `greeting_dashboard_emit_ok`, `emit_ai_greeting_dispatch`가 Phase 1·2에 대해 찍히는지 본다. `greeting_dashboard_emit_skipped_no_call_id`가 나오면 여전히 ID 결손이므로 미디어 세션·빌드 경로를 추가 점검한다.
