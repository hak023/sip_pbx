# HITL → 지식베이스 반영 점검 및 수정

| 항목 | 내용 |
|------|------|
| 작성일 | 2026-03-28 (로컬) |
| 상태 | 코드 점검 + 동작 개선 반영 |

---

## 1. 기존 동작 요약

| 경로 | 조건 | 결과 |
|------|------|------|
| `submit_hitl_response` | `save_to_kb=True` 이고 `question` 비어 있지 않음 | 즉시 `KnowledgeService.add_from_hitl` |
| 동일 | `save_to_kb=False`(기존 기본) 이고 질문 있음 | `queue_hitl_kb_for_call_end` → BYE 시 `flush_hitl_kb_for_call` |
| 동일 | `question` 없음 | **즉시/대기열 모두 스킵** (`hitl_kb_question_empty`) |

통화 종료 훅: `sip_endpoint._cleanup_call`에서 Pipecat cancel **전에** `flush_hitl_kb_for_call(original_call_id, kb_owner)` 호출 (설계대로).

---

## 2. “안 되는 것처럼” 보이던 원인

1. **`save_to_kb` 기본값 `False`**  
   프론트에서 생략 시 **통화 종료까지** Chroma에 안 올라감. 기대가 “제출 즉시 반영”이면 미반영으로 느껴짐.

2. **`owner` 미설정**  
   RAG는 `owner_filter`로 Chroma `where`를 거는데, 메타에 `owner` 없으면 **해당 테넌트 검색 결과에 절대 안 나옴** (저장은 됐는데 검색만 안 됨).

3. **owner 해석 범위가 좁았음**  
   `hitl_requested`의 `context.owner` 미사용, `get_session_by_sip_call_id` 미시도로 세션 조회 실패 가능.

4. **통화 종료 flush 시 owner**  
   대기열에는 owner를 안 넣고 BYE 시 SIP `call_info`만 썼음. 제출 시점에는 세션에서 owner를 알았는데 BYE 시 비어 있으면 flush도 owner 없이 저장.

5. **즉시 저장 실패 시**  
   `add_from_hitl`이 `success: False`여도 성공 로그만 남을 수 있는 구조였음 → 수정 후 실패 시 `error` 로그.

---

## 3. 적용한 수정 (요약)

- `_resolve_hitl_kb_owner`: `context.owner` → `get_session_by_sip_call_id` 보강.
- `queue_hitl_kb_for_call_end(..., owner=...)`: 제출 시점 owner를 pending에 보관, flush 시 **pending owner 우선**.
- `save_to_kb` 기본값: 환경변수 `HITL_SAVE_TO_KB_DEFAULT` (기본 `true`). 명시 `save_to_kb: false`로 이전 “통화 종료만” 동작 유지 가능.
- 즉시 저장: `result.success` 검사 및 실패 시 에러 로그, 성공 시에만 `emit_knowledge_updated`.

---

## 4. 변경 이력 (파일별)

| 파일 경로 | 변경 유형 | 요약 |
|-----------|-----------|------|
| `src/websocket/server.py` | 수정 | owner 해석 보강, save_to_kb 기본값·즉시 저장 성공 판별, 대기열에 owner 전달 |
| `src/services/hitl.py` | 수정 | pending에 owner 저장, flush 시 item owner 우선 |

---

## 5. 운영 체크리스트

- 로그: `hitl_knowledge_saved` / `hitl_knowledge_save_failed` / `hitl_kb_queued_for_call_end` / `hitl_kb_flushed_at_call_end` / `hitl_kb_owner_unresolved`.
- 프론트: `submit_hitl_response`에 가능하면 `tenant_id` 또는 `owner`, 또는 `hitl_requested`와 동일한 `context.owner` 포함.
- 통화 종료만 반영을 유지하려면: `save_to_kb: false` 또는 서버 환경 `HITL_SAVE_TO_KB_DEFAULT=false`.
