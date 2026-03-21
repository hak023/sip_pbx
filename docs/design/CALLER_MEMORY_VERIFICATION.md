# 발신자 맥락(Caller Memory) 로직 검증

설계: `CALLER_MEMORY_DESIGN.md`  
구현: `src/db/`, `src/api/routers/call_history.py`, `src/ai_voicebot/pipecat/processors/rag_processor.py`, `src/websocket/server.py`

---

## 1. 전체 흐름 요약

```
[통화 시작] → (SIP/오케스트레이터가 RAGLLMProcessor 생성 시 owner, call_id, caller_id 전달)
       ↓
[첫 번째 사용자 발화 (STT final)] → _ensure_call_history_entry() 1회
       ↓                              → append_call_history({ call_id, caller_id, callee_id, start_time, is_ai_handled })
       ↓                              → INSERT OR IGNORE (이미 행 있으면 무시)
[LLM 응답 경로]
       ├─ LangGraph: _get_caller_context_sync() → process_utterance(..., caller_context=...)
       └─ Legacy:    _get_caller_context_sync() → _build_system_prompt(..., caller_context)
[HITL 발생 시] → record_hitl_request(..., caller_id) → UPDATE or INSERT (call_history)
       ↓
[통화 종료] → emit_call_ended(call_id)
       ↓     → mark_pending_hitl_unresolved(call_id)
       ↓     → end_call_and_save_summary(call_id)
       ↓         → UPDATE call_history SET end_time
       ↓         → SELECT caller_id, callee_id, user_question
       ↓         → (call_summaries에 해당 call_id 없으면) save_call_summary(callee_id, caller_id, call_id, summary)
       ↓
[다음 통화] 동일 발신자 재통화 시 → _get_caller_context_sync()가 call_summaries에서 최근 5건 조회 → [이전 통화 맥락] 주입
```

---

## 2. 지점별 검증

### 2.1 통화 이력 행 생성

| 항목 | 구현 | 검증 |
|------|------|------|
| 시점 | 첫 번째 **최종(STT final)** 사용자 발화가 RAG로 들어올 때 | ✅ 발화가 있어야 이력 행이 생김. 발화 없이 끊기면 행 없음(의도된 동작). |
| 중복 | `append_call_history_row` → `INSERT OR IGNORE` | ✅ HITL이 먼저 발생해 이미 행이 있으면 INSERT 무시. 이후 record_hitl_request가 UPDATE로 caller_id 등 반영. |
| caller_id 없음 | `_ensure_call_history_entry`에서 `caller_id=""` 로 INSERT 가능 | ✅ 통화 종료 시 `if caller_id and callee_id`에서 걸러져 요약만 저장 안 함. 이력 행은 남음. |

### 2.2 HITL 발생 시

| 항목 | 구현 | 검증 |
|------|------|------|
| 행 없음 | `record_hitl_request_row`: SELECT 후 없으면 INSERT | ✅ 첫 발화 전에 HITL이 나오는 경우는 없음. 보통은 _ensure_call_history_entry로 이미 행 존재. |
| 행 있음 | hitl_status, user_question, ai_confidence, (선택) caller_id, start_time UPDATE | ✅ 기존 행 갱신. caller_id가 나중에 들어와도 UPDATE로 반영됨. |

### 2.3 통화 종료 시

| 항목 | 구현 | 검증 |
|------|------|------|
| 순서 | mark_pending_hitl_unresolved → end_call_and_save_summary | ✅ 먼저 HITL 상태를 unresolved로 바꾼 뒤 end_time 갱신·요약 저장. |
| end_time | UPDATE call_history SET end_time = ? WHERE call_id = ? | ✅ 해당 call_id만 갱신. |
| 요약 저장 조건 | row 존재 & caller_id & callee_id 비어 있지 않음 | ✅ caller_id가 ""이면 요약 미저장(정상). |
| 중복 방지 | call_summaries에 동일 call_id 있으면 save_call_summary 스킵 | ✅ emit_call_ended 이중 호출 시 요약 1회만 저장. |

### 2.4 발신자 맥락 조회

| 항목 | 구현 | 검증 |
|------|------|------|
| 조건 | owner(착신), caller_id 둘 다 있을 때만 조회 | ✅ _get_caller_context_sync()에서 미리 검사. |
| 저장소 | get_recent_summaries_by_caller(tenant_id, caller_id, limit=5) | ✅ (tenant_id, caller_id) 기준 최근 5건. 인덱스로 정렬·제한. |
| Legacy | _build_system_prompt(..., caller_context)에 "[이전 통화 맥락]" 블록 | ✅ 시스템 프롬프트에만 추가. 기존 org/rag 블록과 순서 유지. |
| LangGraph | process_utterance(..., caller_context=caller_context), TypeError 시 인자 제거 후 재호출 | ✅ Agent가 인자를 받지 않아도 호출 실패하지 않음. |

### 2.5 API·DB 일관성

| 항목 | 구현 | 검증 |
|------|------|------|
| list_call_history | list_call_history_rows(callee, unresolved_hitl, page, limit) | ✅ WHERE/ORDER BY/LIMIT/OFFSET 일치. |
| unresolved 필터 | hitl_status != 'resolved' AND resolved = 0 | ✅ pending, unresolved 모두 포함. |
| get_call_detail | get_call_history_row(call_id) | ✅ 404 시 HTTPException. |
| save_note / resolve | update_call_note_row / resolve_call_row, rowcount로 404 처리 | ✅ 행 없으면 404. |

---

## 3. 발견·수정한 이슈

### 3.1 (수정됨) 통화 종료 이중 호출 시 요약 중복

- **문제**: `emit_call_ended(call_id)`가 같은 call_id로 두 번 호출되면 `save_call_summary`가 두 번 호출되어 동일 통화에 대해 call_summaries에 행이 2개 생길 수 있음.
- **조치**: `end_call_and_save_summary` 내부에서 `call_summaries`에 해당 `call_id`가 이미 있는지 SELECT한 뒤, 없을 때만 `save_call_summary` 호출하도록 변경함.

---

## 4. 엣지 케이스 정리

| 케이스 | 동작 | 비고 |
|--------|------|------|
| 사용자가 한 마디도 안 하고 끊음 | call_history 행 없음 → end_call_and_save_summary에서 row 없음 → 요약 없음 | 의도된 동작. |
| caller_id를 파이프라인에 안 넘김 | 이력에는 caller_id=""로 저장 가능. 요약은 caller_id and callee_id 조건으로 저장 안 함. 맥락 조회 시 빈 문자열이면 get_recent_summaries_by_caller에서 [] 반환. | 정상. |
| HITL만 있고 사용자 발화는 STT 필터에 걸려 무시됨 | _ensure_call_history_entry는 “최종 발화가 RAG에 도달할 때”만 호출. STT 필터로 모두 드롭되면 호출 안 됨. record_hitl_request는 HITL 시 호출되므로 그때 INSERT됨. | 통화 이력 행은 HITL 시점에 생김. |
| 동일 call_id로 record_hitl_request 여러 번 | 매번 UPDATE. user_question, ai_confidence 등 최신 값으로 유지. | 정상. |
| init_db() 미호출 | call_history 라우터 import 시 init_db() 호출. API 서버 기동 시 라우터 로드되므로 테이블 생성됨. | 단, DB만 쓰는 워커/스크립트는 init_db()를 한 번 호출해야 함. |

---

## 5. 결론

- **흐름**: 통화 시작(첫 발화) → 이력 행 확보 → (HITL 시 갱신) → 통화 종료 시 end_time 갱신·요약 1회 저장 → 다음 통화 시 발신자 맥락 조회·주입까지 설계와 일치함.
- **로직**: 이력 생성·HITL 반영·통화 종료·요약 저장·맥락 조회·API 응답이 서로 맞고, 엣지 케이스와 이중 호출 시 요약 중복만 위와 같이 보완하면 됨.
- **추가 권장**: 파이프라인을 생성하는 쪽(SIP/오케스트레이터)에서 **caller_id**를 SIP From 등에서 추출해 `RAGLLMProcessor(..., caller_id=...)`에 넘기면, 요약 저장과 맥락 주입이 모두 동작함.
