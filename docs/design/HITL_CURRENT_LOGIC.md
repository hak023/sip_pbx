# HITL( Human-In-The-Loop ) 현재 로직 정리
> **클러스터 안내**: 세부·히스토리 설계 문서입니다. 통합 관점·경계는 아래 대표 문서를 우선 참고하세요.
> 
> **대표 문서**: [`HITL_OPERATOR_RESPONSE_FLOW.md`](HITL_OPERATOR_RESPONSE_FLOW.md)
>
---


**작성일**: 2026-03-16  
**목적**: HITL 변경 전 현재 동작 방식 정리.

---

## 1. 전체 흐름 개요

```
[사용자 발화] → STT → LangGraph Agent → generate_response → hitl_alert
                                                                    ↓
                                            needs_human? → [HITLManager] → [HITLService]
                                                                    ↓
                                            [WebSocket: hitl_requested] → 대시보드
                                                                    ↓
                                            [Fallback Timer 20초] → hitl_timeout → TTS
                                                                    ↓
                                            [운영자 응답] → submit_hitl_response → 큐 → TTS
```

- **트리거**: LangGraph의 `hitl_alert` 노드에서 `needs_human` 판단.
- **실행**: RAGLLMProcessor가 Agent 결과 수신 후 `needs_human==True`이면 HITLManager·HITLService·WebSocket·타이머·기록을 순서대로 수행.
- **운영자 응답**: WebSocket `submit_hitl_response`로 받아 해당 통화의 응답 큐에 넣으면, RAGLLMProcessor의 consumer가 TTS로 재생.

---

## 2. HITL 발동 조건 (hitl_alert_node)

**파일**: `src/ai_voicebot/langgraph/nodes/hitl_alert.py`

| 순서 | 조건 | reason 예시 |
|------|------|-------------|
| 0 | `needs_follow_up == True` | "AI가 모르는 내용으로 응답했습니다. 확인이 필요합니다." |
| 1 | `intent == "transfer"` | "고객이 상담원 연결을 요청했습니다." |
| 2 | `intent == "complaint"` 이고 `confidence < 0.5` | "고객 불만 상태이며 답변 신뢰도가 낮습니다 (confidence=...)." |
| 3 | `confidence < 0.3` (HITL_CONFIDENCE_THRESHOLD) | "답변 신뢰도가 매우 낮습니다 (confidence=...). 적절한 정보를 찾지 못했습니다." |

- **우선순위**: 위 순서대로 먼저 만족하는 조건 하나만 사용. `needs_follow_up`가 True면 나머지(intent/confidence)는 보지 않음.
- **출력**: `needs_human` (bool), `hitl_reason` (str). 이 값들이 state에 올라가고 RAGLLMProcessor로 전달됨.

---

## 3. needs_follow_up 설정 (generate_response_node)

**파일**: `src/ai_voicebot/langgraph/nodes/generate_response.py`

- **True가 되는 경우**
  1. LLM이 에러/폴백 문구를 준 경우 → `RESPONSE_UNKNOWN_NEEDS_FOLLOWUP`("해당 내용은 확인이 필요합니다. 잠시만 기다려 주세요.")로 치환하고 `needs_follow_up = True`.
  2. `_is_unknown_content_response(response)`가 True인 경우 (예: "잠시만 기다려" + "확인", "모르는 내용" + "확인이 필요" 등).

- **정리**: “모르는 내용 / 확인 필요” 유도의 응답이 나오면 무조건 `needs_follow_up=True` → hitl_alert에서 0번 조건으로 `needs_human=True`가 됨.

---

## 4. LangGraph 내 HITL 위치

**파일**: `src/ai_voicebot/langgraph/agent.py`

- **경로**: `generate_response` → **hitl_alert** → `update_cache` → `update_state` → END.
- **특징**: RAG 경로(question 등)를 탄 모든 턴이 항상 `hitl_alert`를 거침. intent가 greeting/farewell 등 단축 응답이면 `generate_response`를 타지 않으므로 hitl_alert도 실행되지 않음.

---

## 5. RAGLLMProcessor에서의 HITL 처리

**파일**: `src/ai_voicebot/pipecat/processors/rag_processor.py`

### 5.1 Agent 결과 수신 후

- `result`에서 `needs_human`, `hitl_reason`, `intent`, `confidence`, `response`, `response_chunks` 등을 읽음.

### 5.2 needs_human == True 일 때 수행 순서

1. **HITLManager.handle_hitl_result**
   - `call_id`, `needs_human=True`, `hitl_reason`, `intent`, `confidence`, `user_text` 전달.
   - 반환 메시지(`hitl_message`)가 있고 기존 `response`가 비어 있으면 `response = hitl_message`로 덮음.

2. **HITLManager 반환 메시지 (사용자 TTS용)**
   - `intent == "transfer"`: `"담당자에게 연결해 드리겠습니다. 잠시만 기다려 주세요."`
   - `intent == "complaint"`: `"불편을 드려 죄송합니다. 더 정확한 안내를 위해 담당자를 연결해 드릴까요?"`
   - 그 외(낮은 신뢰도/모르는 내용): `"확인해보겠습니다. 잠시만 기다려 주세요."`

3. **WebSocket**: `emit_hitl_requested(call_id, question=user_text, context={...}, urgency=...)`
   - `urgency`: `"transfer"` | `"complaint"` | `"low_confidence"`

4. **통화 이력 기록**: `record_hitl_request(call_id, callee_id, user_question, ai_confidence, caller_id)`
   - `call_history` 모듈의 메모리 딕셔너리 `_hitl_requests`에 pending으로 저장.

5. **Fallback 타이머**: `get_hitl_service().start_fallback_timer(call_id, timeout_sec=20.0)`
   - 20초 후 해당 통화 큐에 `{ "type": "hitl_timeout", "text": "...", "needs_llm_refinement": True }` 를 넣음.
   - 타임아웃 시 `_on_timeout_callback(call_id)`도 호출(설정된 경우).

### 5.3 HITL 응답 큐 소비

- **등록**: RAGLLMProcessor 생성 시 `call_id`가 있으면 `hitl_response_queue`를 만들고 `get_hitl_service().register_call(call_id, queue)`로 등록.
- **소비**: `_start_hitl_response_consumer()`로 비동기 태스크가 큐를 get.
  - `type == "hitl_response"`: 운영자가 보낸 응답 → (옵션) LLM 정제 후 TextFrame으로 push → TTS.
  - `type == "hitl_timeout"`: `needs_llm_refinement`면 LLM으로 문구 다듬은 뒤 TextFrame → TTS, 그리고 `emit_hitl_timeout(call_id)` 발송.

### 5.4 Fallback 긍정 응답

- 사용자가 “별도 연락 드릴까요?” 후 “네/예” 등으로 긍정하면 `get_hitl_service().consume_fallback_affirm(call_id, intent)`로 한 번만 True 처리.
- 이때 `emit_hitl_fallback_available(call_id)`로 프론트에 알림.

### 5.5 needs_follow_up 후처리

- `needs_follow_up`이고 `follow_up_user_query`가 있으면 `follow_up_service.save_pending_follow_up(...)`로 대시보드/후처리용으로 저장.

---

## 6. HITLManager (hitl_processor.py)

**파일**: `src/ai_voicebot/pipecat/processors/hitl_processor.py`

- **역할**: Agent의 `needs_human`/`hitl_reason`/intent 등에 따라
  - 사용자에게 재생할 안내 문구 반환,
  - `on_alert` 콜백 호출(선택),
  - `intent == "transfer"`일 때 `on_transfer_request` 콜백 호출(선택).
- **통계**: `total_alerts`, `transfer_requests`, `complaint_alerts`, `low_confidence_alerts` 누적.
- **상태**: `pending_transfer` 플래그. `reset()`으로 초기화.

---

## 7. HITLService (services/hitl.py)

**파일**: `src/services/hitl.py`

| 기능 | 설명 |
|------|------|
| `register_call(call_id, queue)` | 통화별 asyncio.Queue 등록. RAGLLMProcessor가 생성한 큐를 등록. |
| `start_fallback_timer(call_id, timeout_sec)` | 해당 통화 큐에 `hitl_timeout` 메시지를 넣는 타이머 시작. 기존 타이머는 취소 후 재시작. |
| `cancel_timer(call_id)` | 해당 통화 타이머 취소 (BYE/정리 시). |
| `unregister_call(call_id)` | 큐 제거 + 타이머 취소 + fallback_affirm 제거. |
| `consume_fallback_affirm(call_id, intent)` | “별도 연락 드릴까요?”에 대한 긍정 한 번만 True로 소비. |
| `register_on_hitl_timeout(callback)` | 타임아웃 시 호출할 전역 콜백 (예: AI 재연결). |
| `set_config(timeout_seconds, timeout_message)` | 기본 타임아웃(기본 20초), 타임아웃 시 넣을 메시지 설정. |

- **주의**: 현재 `HITLService`에는 `get_response_queue(call_id)` 메서드가 **없음**. WebSocket의 `submit_hitl_response`에서 `hitl_service.get_response_queue(call_id)`를 호출하고 있으므로, 실제 동작하려면 `get_response_queue(call_id) -> self._queues.get(call_id)` 같은 메서드가 필요함.

---

## 8. WebSocket 이벤트

**파일**: `src/websocket/server.py`

| 이벤트 | 방향 | 용도 |
|--------|------|------|
| `hitl_requested` | 서버→프론트 | HITL 발동 시 대시보드에 요청 표시 (call_id, question, context, urgency). |
| `hitl_fallback_available` | 서버→프론트 | “별도 연락 드릴까요?” 후 사용자 긍정 시. |
| `hitl_timeout` | 서버→프론트 | 20초 내 운영자 응답 없을 때. |
| `hitl_resolved` | 서버→프론트 | 운영자가 HITL 응답 제출 후. |
| `submit_hitl_response` | 프론트→서버 | 운영자 HITL 응답 제출 (call_id, response_text, save_to_kb, category, question 등). |

- `submit_hitl_response` 처리 흐름:
  1. (선택) LLM으로 고객용 문장 정제.
  2. `get_hitl_service().get_response_queue(call_id)`로 큐 취득 후 `put({ "type": "hitl_response", "text": refined_response, ... })`.
  3. `save_to_kb`이고 `question`이 있으면 `knowledge_service.add_from_hitl(...)` 호출.
  4. `emit("hitl_resolved", ...)` 전송.

---

## 9. 통화 이력·API

**파일**: `src/api/routers/call_history.py`

- `record_hitl_request(call_id, callee_id, user_question, ai_confidence, caller_id)`: 메모리 `_hitl_requests`에 pending HITL 건 추가 (키: `call_id_ts`).
- `GET /follow-ups`: 후속 조치/팔로업 목록 (HITL과 별도이지만 같은 라우터).

**파일**: `src/api/routers/hitl.py`

- Mock 구현: `GET /hitl/queue`, `POST /hitl/response`, `GET /hitl/history`. 실제 파이프라인과의 연동은 WebSocket `submit_hitl_response`가 담당.

---

## 10. 요약 표

| 구간 | 담당 | 핵심 |
|------|------|------|
| **발동 조건** | hitl_alert_node | needs_follow_up / transfer / complaint+저신뢰 / confidence<0.3 |
| **follow_up 플래그** | generate_response_node | “확인 필요”·에러 폴백 응답 시 True |
| **그래프 위치** | agent.py | generate_response → hitl_alert → update_cache → update_state |
| **실행** | rag_processor.py | needs_human 시 Manager·WS·record·타이머·큐 소비 |
| **사용자 안내 문구** | HITLManager | transfer/complaint/기타별 고정 문구 |
| **타이머·큐** | HITLService | 20초 fallback, 큐 등록/해제, fallback_affirm |
| **운영자 응답** | WebSocket submit_hitl_response | 큐에 put, (선택) 지식 저장, hitl_resolved |

---

## 11. 알려진 갭/주의사항

1. **HITLService.get_response_queue**: WebSocket에서 사용하지만 현재 서비스 클래스에는 메서드 없음. `get_response_queue(call_id)` 추가 필요.
2. **record_hitl_request**: 메모리 저장만 하며, 재시작 시 소실. Redis 등 영속화는 미구현.
3. **transfer 실제 전환**: `on_transfer_request` 콜백이 설정되어 있어야 SIP 전환 등이 동작. 파이프라인 빌더에서 어떻게 넘기는지 확인 필요.
4. **hitl_alert는 RAG 경로만 통과**: greeting/farewell/단축 응답 경로는 hitl_alert를 타지 않음.

이 문서는 “현재 로직 정리”용이며, 변경 시 이 흐름을 기준으로 diff를 두고 수정하는 것을 권장합니다.
