# HITL·후속 대응 로직 점검
> **클러스터 안내**: 세부·히스토리 설계 문서입니다. 통합 관점·경계는 아래 대표 문서를 우선 참고하세요.
> 
> **대표 문서**: [`HITL_OPERATOR_RESPONSE_FLOW.md`](HITL_OPERATOR_RESPONSE_FLOW.md)
>
---


## 설계 의도

- **AI가 모르는 내용** → HITL(운영자 알림) → 운영자 실시간 응답 또는
- **그래도 해결 안 되면** → Frontend에 표시하여 **이후 사람이 후속 대응**할 수 있도록 함.

---

## 1. 구현된 부분

### 1.1 AI 모름 → HITL 요청

| 단계 | 구현 위치 | 상태 |
|------|-----------|------|
| needs_human 판단 | RAGLLMProcessor (LangGraph Agent 결과) | ✅ intent/confidence 기반 |
| HITLManager.handle_hitl_result | hitl_processor.py | ✅ TTS 안내문 반환 |
| emit_hitl_requested | websocket/server.py | ✅ 운영자에게 hitl_requested 이벤트 |
| start_fallback_timer(20초) | hitl.py | ✅ 미응답 시 "별도 연락 드릴까요?" 큐 투입 → TTS |
| 발신자 긍정 시 | hitl.consume_fallback_affirm + emit_hitl_fallback_available | ✅ Frontend에 fallback 가능 표시 |

### 1.2 운영자 실시간 응답

| 단계 | 구현 위치 | 상태 |
|------|-----------|------|
| submit_hitl_response (WebSocket) | server.py on_submit_hitl_response | ✅ |
| HITLService.submit_response | hitl.py | ✅ queue에 답변 put → 파이프라인에서 TTS |
| hitl_resolved 브로드캐스트 | server.py | ✅ |

### 1.3 Frontend 표시 (이후 사람이 대응)

| 항목 | 구현 위치 | 상태 |
|------|-----------|------|
| 통화 이력 페이지 | frontend/app/call-history/page.tsx | ✅ |
| "미처리 HITL" 탭 | unresolved_hitl filter, Badge 카운트 | ✅ |
| 목록: 질문, AI 신뢰도, 상태(hitl_status) | call-history 테이블 | ✅ |
| 상세: 사용자 질문, AI 신뢰도, 메모, 처리 완료 | 상세 다이얼로그, POST note, PUT resolve | ✅ |
| API: GET /api/call-history?unresolved_hitl=unresolved | call_history.py | ✅ 필터 로직 있음 |
| API: POST note, PUT resolve | call_history.py | ✅ |

---

## 2. 끊긴 부분 (미구현·단절)

### 2.1 HITL 발생 시 통화 이력에 기록 안 됨

- **상황**: `emit_hitl_requested` 로 운영자에게는 실시간 알림이 가지만, **통화 이력 저장소(call_history)에는 HITL 발생 건이 기록되지 않음**.
- **원인**: `append_call_history()` 를 호출하는 코드가 **전체 소스에 없음**. 통화 시작/종료 또는 HITL 발생 시 이력을 append 하는 연동이 없음.
- **결과**: "미처리 HITL" 탭은 **데이터 소스가 비어 있어** 목록이 항상 비어 있을 수 있음.

**권장**:  
- HITL 발생 시(예: `emit_hitl_requested` 호출 직전/직후) 해당 통화를 **통화 이력에 한 건 추가**하고,  
  - `hitl_status`: `"pending"` 또는 `"unresolved"`,  
  - `user_question`, `ai_confidence`, `call_id`, `callee_id`, `caller_id`, `start_time` 등  
  을 넣어 두거나,  
- 통화 종료 시점에 "이 통화에 HITL이 있었고 미해결"이면 이력에 추가/갱신하는 방식으로 연동.

### 2.2 follow_up_service 미구현

- **상황**: RAGLLMProcessor에서 `needs_follow_up` 일 때 `get_follow_up_service().save_pending_follow_up(...)` 호출.
- **원인**: `src/services/follow_up_service.py` **미존재** → import 시 예외, 로그만 남김.
- **결과**: "AI가 모르는 내용으로 응답한 건 저장 → 대시보드에서 나중에 처리" 경로가 동작하지 않음.

**권장**:  
- follow_up_service 모듈 구현 후 `save_pending_follow_up(call_id, user_question, ai_response, callee_id)` 에서 DB 또는 call_history와 연동된 저장소에 저장.  
- 또는 당장은 **통화 이력(call_history)에 HITL 건만 기록**해 두고, "후속 조치 필요"는 이력의 메모/상태로 표현하는 방식으로 통합해도 됨.

### 2.3 Follow-ups API 미구현

- **상황**: 대시보드가 `GET /api/call-history/follow-ups`, `PATCH /api/call-history/follow-ups/{id}` 호출.
- **원인**: `src/api/routers/call_history.py` 에 해당 **엔드포인트 없음**.
- **결과**: 대시보드의 후속 조치 목록/상태 갱신이 404 등으로 동작하지 않음.

**권장**:  
- follow_up_service 구현 시, 같은 데이터를 조회·갱신하는 **GET/PATCH follow-ups API** 를 call_history 라우터 또는 별도 라우터에 추가.

---

## 3. 요약 표

| 설계 의도 | 구현 여부 | 비고 |
|-----------|-----------|------|
| AI 모름 → HITL 요청(운영자 알림) | ✅ 구현됨 | emit_hitl_requested, fallback 타이머, fallback_available |
| 운영자 실시간 답변 → TTS | ✅ 구현됨 | submit_hitl_response, queue, hitl_resolved |
| 해결 안 되면 Frontend에 표시 | ⚠️ UI·API는 있음, **데이터 연동 끊김** | 미처리 HITL 탭은 있으나, HITL 발생 시 이력 저장이 없어 목록 비어 있음 |
| 이후 사람이 후속 대응 | ⚠️ 부분 | 통화 이력 상세에서 메모/처리완료는 가능. follow_up_service·follow-ups API 없음 |

---

## 4. 권장 조치 (우선순위) — 구현 상태

1. **HITL 발생 시 통화 이력 기록** — ✅ 구현됨  
   - 설계: **docs/design/HITL_CALL_HISTORY_INTEGRATION.md**  
   - `record_hitl_request(call_id, callee_id, user_question, ai_confidence, ...)` in `call_history.py`.  
   - RAGLLMProcessor에서 `emit_hitl_requested` 직후 `record_hitl_request` 호출.  
   - 필드: `hitl_status="pending"`, `user_question`, `ai_confidence`, `is_ai_handled=True` 등.

2. **follow_up_service / follow-ups API** — ⏳ 미구현 (선택)  
   - "후속 조치 필요" 건을 별도로 다루려면: `follow_up_service` + `GET/PATCH /api/call-history/follow-ups` 구현.  
   - 단기: "미처리 HITL = 후속 조치 필요"로 통화 이력 + 기존 call-history API로 후속 대응 가능.

3. **통화 종료 시 미해결 HITL 반영** — ✅ 구현됨  
   - `mark_pending_hitl_unresolved(call_id)` in `call_history.py`.  
   - `emit_call_ended` 내에서 호출. `hitl_status == "pending"` 이면 `"unresolved"` 로 갱신.  
   - 운영자 응답 시: `on_submit_hitl_response` 성공 후 `mark_hitl_resolved(call_id)` 호출로 `resolved` 반영.

위 1·3 연동으로 "AI 모름 → HITL → 해결 안 되면 Frontend 표시 → 사람이 후속 대응" 흐름이 동작함.
