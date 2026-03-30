# HITL Q&A → 지식베이스 (통화 종료 시) 설계

- **작성일**: 2026-03-26  
- **상태**: 구현 반영  
- **관련 코드**: `src/services/hitl.py`, `src/services/hitl_kb_category.py`, `src/websocket/server.py` (`submit_hitl_response`), `src/ai_voicebot/pipecat/processors/rag_processor.py`, `src/sip_core/sip_endpoint.py` (`_cleanup_call`), `src/services/knowledge_service.py` (`add_from_hitl`)

## 목표

HITL로 처리한 **질문/답변**을 Chroma 지식 컬렉션에 넣되, **카테고리**는 RAG 필터(`VALID_CATEGORIES`)와 맞고, 기본 동작은 **통화 종료(BYE) 시점**에 일괄 반영한다.

## 카테고리 규칙

- 운영자가 `submit_hitl_response`에 유효한 `category`를 주면 그대로 사용 (`VALID_CATEGORIES`).
- 없거나 무효하면 에이전트 **intent**로 기본값:
  - `complaint` → `complaint`
  - `transfer` → `transfer`
  - 그 외 → `question`

Intent는 `needs_human` 시점에 `HITLService.note_hitl_request`로 FIFO에 쌓고, 운영자가 응답할 때 `pop_hitl_request_context`로 짝을 맞춘다 (통화당 FIFO).

## 저장 시점

1. **`save_to_kb: true`**: 기존과 같이 제출 직후 `add_from_hitl` (메타 `kb_timing=immediate`).
2. **`save_to_kb: false` 또는 생략**: 동일 Q&A를 `_pending_kb_at_call_end`에 넣고, **`_cleanup_call`**에서 `flush_hitl_kb_for_call`로 저장 (메타 `kb_timing=call_end`).

## 통화 종료 훅

- B2BUA BYE 정리: `sip_endpoint._cleanup_call`에서 Pipecat 취소 직후 `await flush_hitl_kb_for_call(original_call_id, owner)`.
- 레거시 `CallManager.cleanup_terminated_call` 경로: `asyncio.create_task(flush_hitl_kb_for_call(...))` (이벤트 루프 있을 때).

Flush 후 응답 큐는 `_detach_response_queue`로 제거한다 (기존에는 `unregister_call`이 거의 호출되지 않아 큐가 남을 수 있던 부분 보완).

## 로그·관측

- `submit_hitl_response_category_resolved`, `hitl_kb_queued_for_call_end`, `hitl_kb_flushed_at_call_end`, `hitl_call_end_kb_flush_done`
- 실패 시 `hitl_kb_flush_*` 경고/에러로 원인 구분
