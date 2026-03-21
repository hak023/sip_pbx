# HITL 통화 이력 연동 설계

## 1. 목적

- HITL 발생 건을 **통화 이력**에 기록해 Frontend "미처리 HITL" 탭에 노출.
- 운영자 응답 시 **처리 완료(resolved)** 반영, 통화 종료 시 미해결이면 **unresolved** 반영.
- "AI 모름 → HITL → 해결 안 되면 Frontend 표시 → 사람이 후속 대응" 흐름 완성.

참고: `docs/design/HITL_AND_FOLLOWUP_VERIFICATION.md` §4 권장 조치.

---

## 2. 데이터 모델 (통화 이력 1건)

| 필드 | 타입 | 설명 |
|------|------|------|
| call_id | str | 통화 ID (PK) |
| caller_id | str | 발신자 (선택, 없으면 "") |
| callee_id | str | 착신번호(owner) |
| start_time | str | 통화 시작 시각 (ISO 또는 "") |
| end_time | str | 통화 종료 시각 (선택) |
| hitl_status | str | "pending" \| "unresolved" \| "resolved" |
| user_question | str | HITL 발생 시 사용자 질문 |
| ai_confidence | float | HITL 발생 시 AI 신뢰도 |
| is_ai_handled | bool | True (AI 응대 통화) |
| resolved | bool | 처리 완료 여부 |
| operator_note | str | 메모 (POST note로 갱신) |
| transcripts | list | (선택) 트랜스크립트 |

---

## 3. 연동 시점 및 API

### 3.1 HITL 발생 시 (통화 이력 기록)

- **시점**: `emit_hitl_requested` 호출 직후 (RAGLLMProcessor).
- **동작**: 해당 call_id가 이력에 없으면 **추가**, 있으면 **갱신**.
  - 추가 시: `call_id`, `callee_id`(owner), `caller_id`(가능 시), `start_time`(가능 시), `hitl_status="pending"`, `user_question`, `ai_confidence`, `is_ai_handled=True`, `resolved=False`.
  - 갱신 시: `hitl_status="pending"`, `user_question`, `ai_confidence` 갱신.
- **함수**: `record_hitl_request(call_id, callee_id, user_question, ai_confidence, caller_id=None, start_time=None)`  
  - 제공: `src.api.routers.call_history`

### 3.2 운영자 HITL 응답 시 (처리 완료 반영)

- **시점**: WebSocket `submit_hitl_response` 처리 성공 직후.
- **동작**: 해당 call_id 이력 항목에 `hitl_status="resolved"`, `resolved=True` 설정.
- **함수**: `mark_hitl_resolved(call_id)`  
  - 제공: `src.api.routers.call_history`

### 3.3 통화 종료 시 (미해결 HITL → unresolved)

- **시점**: `emit_call_ended(call_id)` 호출 시 (통화 종료).
- **동작**: 해당 call_id 이력이 있고 `hitl_status == "pending"` 이면 `hitl_status="unresolved"` 로 변경. (이미 resolved면 변경 없음.)
- **함수**: `mark_pending_hitl_unresolved(call_id)`  
  - 제공: `src.api.routers.call_history`

---

## 4. 호출 위치

| 연동 | 호출 위치 |
|------|-----------|
| record_hitl_request | RAGLLMProcessor, `emit_hitl_requested` 호출 직후 |
| mark_hitl_resolved | websocket/server.py, `on_submit_hitl_response` 내 submit_response 성공 직후 |
| mark_pending_hitl_unresolved | websocket/server.py, `emit_call_ended` 내 (unregister_call 전/후) |

---

## 5. Frontend 동작 (기존 유지)

- `GET /api/call-history?unresolved_hitl=unresolved`: `hitl_status` 가 "resolved"가 아니고 `resolved` 가 False인 항목 반환 → "미처리 HITL" 탭에 표시.
- 상세에서 메모 저장(POST note), 처리 완료(PUT resolve) → 기존 API 그대로 사용.

---

## 6. follow_up_service / follow-ups API

- **단기**: "미처리 HITL = 후속 조치 필요"로 간주하고, 위 연동만으로 통화 이력 + 기존 call-history API로 후속 대응 흐름 완성.
- **추가 시**: 별도 `follow_up_service` 및 `GET/PATCH /api/call-history/follow-ups` 설계·구현은 별도 문서로 진행.
