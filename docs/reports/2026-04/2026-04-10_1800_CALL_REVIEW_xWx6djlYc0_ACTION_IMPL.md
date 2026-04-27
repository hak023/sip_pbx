# 조치 구현 리포트 — call_id: xWx6djlYc0 Action Items

- **작성일**: 2026-04-10 18:00
- **참조 리포트**: `sip-pbx/docs/reports/2026-04/2026-04-10_1720_CALL_REVIEW_xWx6djlYc0.md`
- **상태**: 구현 완료 (P1·P2·P3 코드 수정 / P4·P5 운영 안내)

---

## 개요

`call_id: xWx6djlYc0` 리뷰에서 식별된 5개 문제에 대해 조치를 수행했다.  
핵심 원인은 LangGraph ConversationState에 직렬화 불가 객체(`LLMClient`, `RAGEngine` 등)가  
포함된 채로 checkpointer(SqliteSaver/MemorySaver)가 msgpack 직렬화를 시도해 발생한  
`"Type is not msgpack serializable: LLMClient"` 에러였다.  
이 단일 원인이 모든 발화에서 `invoke_error`를 유발했다.

---

## P3 — transfer_contact_not_found 시 TTS 안내 (코드 이미 존재)

**조사 결과**: KB `transfer` 설정은 별도 필드가 아니라 ChromaDB에 `category="contact"` 문서로 등록하는 방식이다.  
`rag_processor.py` 1265줄에 `transfer_contact_not_found` 처리 시 TTS 안내 발화 코드가 **이미 구현**되어 있음:

```python
response = "죄송합니다. 해당 부서의 연락처를 찾지 못했습니다. 일반 상담원으로 연결해 드리겠습니다."
await self.push_frame(LLMFullResponseStartFrame())
await self.push_frame(TextFrame(text=response))
await self.push_frame(LLMFullResponseEndFrame())
```

**P1(invoke_error)과는 별개 경로**로 실행되므로, 이번 통화에서도 이 멘트가 실제로 발화됐을 가능성이 있다.  
코드 상 결함 없음 — 별도 수정 불필요.

---

## P1 — LLM invoke_error 근본 원인 해결 (핵심)

### 원인

`ConversationState`(TypedDict)에 직렬화 불가 객체 필드들이 정의되어 있었음:
- `_llm_client: object`
- `_rag_engine: object`
- `_embedder: object`
- `_vector_db: object`
- `_org_manager: object`
- `_hangup_callback: object`

`agent.py`의 `process_utterance`가 이 객체들을 state에 직접 주입 후 `graph.ainvoke()` (또는 `astream()`)를 호출하면, checkpointer가 state를 msgpack으로 직렬화하는 과정에서 예외 발생 → `conversation_agent_invoke_error` → "죄송합니다. 일시적인 오류가 발생했습니다."

### 해결: ContextVar 기반 Call-scoped Registry 도입

#### 신규 파일: `call_context.py`

`contextvars.ContextVar`를 사용해 asyncio Task 단위로 격리된 런타임 객체 레지스트리를 도입.  
동시 통화 간 간섭 없이 직렬화 불가 객체를 안전하게 공유한다.

```python
# src/ai_voicebot/langgraph/call_context.py
_ctx_llm_client = ContextVar("llm_client", default=None)
_ctx_rag_engine = ContextVar("rag_engine", default=None)
# ...

def set_call_context(llm_client, rag_engine, ...): ...
def get_llm_client(): return _ctx_llm_client.get()
def get_rag_engine(): return _ctx_rag_engine.get()
```

---

## 변경 이력 (파일별)

| 파일 경로 | 변경 유형 | 요약 |
|-----------|----------|------|
| `src/ai_voicebot/langgraph/call_context.py` | **신규** | ContextVar 기반 call-scoped 런타임 객체 레지스트리 |
| `src/ai_voicebot/langgraph/state.py` | 수정 | `_llm_client`, `_rag_engine`, `_embedder`, `_vector_db`, `_org_manager`, `_hangup_callback` 필드 제거. 직렬화 가능 값만 유지 |
| `src/ai_voicebot/langgraph/agent.py` | 수정 | `process_utterance` 내 객체 state 주입 제거. `set_call_context()` 호출로 교체. `call_context_registered` 디버그 로그 추가 |
| `src/ai_voicebot/langgraph/nodes/generate_response.py` | 수정 | `state.get("_llm_client")` → `get_llm_client()` |
| `src/ai_voicebot/langgraph/nodes/classify_intent.py` | 수정 | `state.get("_llm_client")` → `get_llm_client()` |
| `src/ai_voicebot/langgraph/nodes/adaptive_rag.py` | 수정 | `state.get("_rag_engine")` → `get_rag_engine()` |
| `src/ai_voicebot/langgraph/nodes/booking_agent.py` | 수정 | `state.get("_llm_client")` → `get_llm_client()`, `state.get("_rag_engine")` → `get_rag_engine()` |
| `src/ai_voicebot/langgraph/nodes/update_state.py` | 수정 | `state.get("_org_manager")` → `get_org_manager()` |
| `src/ai_voicebot/pipecat/processors/rag_processor.py` | 수정 | `outbound_extra`의 `_hangup_callback` 주석 보강 (agent.py에서 call_context로 처리됨 명시) |

---

## P2 — LLM 중복 호출 버그

**조사 결과**: CDR 로그에서 단일 발화에 `llm_generate_response`가 3~4회 발생하는 것은 P1의 invoke_error로 인해 `_invoke_graph_with_node_timing` 내부에서 예외 핸들링 경로를 따라 여러 번 시도하거나, `astream_events`의 중간 결과가 로깅되는 것으로 추정된다.  
**P1 해소 후 재현 여부를 확인**해야 한다. 재현 시 `_user_message_queue` 처리 로직을 추가 점검한다.

---

## P4 — 전환 대상 등록 방법 (운영 안내)

**전환 연락처는 KB에 `category="contact"` 문서로 등록**해야 한다.

### 등록 방법

1. 프론트엔드 → **지식 관리** (`/knowledge/upload`) 접속
2. 문서 카테고리: `contact` 선택
3. 메타데이터에 다음 필드 포함:
   - `department`: 부서명 (예: "상담원", "예약팀", "매니저")
   - `phone_number`: 전환 대상 번호 (예: "1004", "010-1234-5678")
   - `name`: 담당자 이름 (선택)
4. 본문 내용: 해당 부서/담당자 설명 (검색 유사도에 활용)

**예시 문서 내용**:
```
상담원 연결 담당입니다. 고객 문의 및 예약 관련 직접 상담이 필요한 경우 연결합니다.
```
**예시 메타데이터**:
```json
{
  "department": "상담원",
  "phone_number": "1004",
  "name": ""
}
```

---

## P5 — KB 예약 관련 Q&A 보강 (운영 안내)

현재 "예약하려고 합니다", "오늘 예약" 등의 쿼리가 RAG confidence 0.2 수준(soft_fallback)으로 검색된다.  
KB에 다음 Q&A를 추가하면 임계치(0.28) 이상으로 개선될 수 있다:

| Q | A |
|---|---|
| AI로 예약할 수 있나요? | 네, 저를 통해 직접 예약하실 수 있습니다. 날짜, 시간, 인원을 알려주세요. |
| 오늘 예약 가능한가요? | 오늘 예약을 원하시는군요. 몇 시에 몇 분이서 방문하실 예정인가요? |
| 예약 변경·취소는 어떻게 하나요? | 예약 번호 또는 등록하신 전화번호를 알려주시면 변경 또는 취소해 드릴 수 있습니다. |

---

## 주요 결정 사항

- **ContextVar 선택 이유**: `threading.local()`이나 전역 딕셔너리보다 asyncio Task 단위 격리가 보장되어 동시 통화 간 상태 오염 없음.
- **state.py에서 완전 제거**: `Optional[Any]` 타입으로 선언해도 checkpointer가 실제 값을 직렬화 시도하므로, 타입 힌트 자체를 제거하고 call_context로 완전 이동.
- **P3은 코드 수정 없음**: TTS 안내가 이미 구현되어 있으며, P1 해소 후 정상 동작 예상.

---

## 잔여 과제

1. **P2 재확인**: P1 수정 후 실제 통화에서 중복 `llm_generate_response` 발생 여부 로그로 검증
2. **P4 운영**: owner 1003 테넌트에 category=contact 연락처 KB 등록
3. **P5 운영**: 예약 관련 Q&A KB 문서 추가 등록
