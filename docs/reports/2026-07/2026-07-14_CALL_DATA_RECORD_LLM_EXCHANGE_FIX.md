# call_data_record 의사결정 로그 누락 수정

**작성일**: 2026-07-14  
**버전**: 1.0  
**상태**: 완료  
**관련 문서**:
- [call_data_record_logger.py](../../../src/common/call_data_record_logger.py)
- [generate_response.py](../../../src/ai_voicebot/langgraph/nodes/generate_response.py)
- [classify_intent.py](../../../src/ai_voicebot/langgraph/nodes/classify_intent.py)

---

## 1. 문제 요약

"토마토 어느나라꺼야?" 질문에 대해 AI가 최종 응답했으나 `call_data_record` 로그에 의사결정 과정(LLM 프롬프트, RAG 컨텍스트, LLM 응답)이 기록되지 않음.

---

## 2. 근본 원인

`llm_exchange` 이벤트가 `rag_processor.py`(음성 통화 경로)에만 존재했고, **SIP 채팅 경로**는 `rag_processor`를 거치지 않으므로 LLM 의사결정 전체가 기록되지 않았음.

```
[음성 통화]  LangGraph agent → rag_processor → llm_exchange 기록 ✅
[SIP 채팅]   LangGraph agent (직접)           → llm_exchange 기록 없음 ❌
```

### call_data_record에 기록되던 것 (수정 전)

| 이벤트                         | 내용                        |
| ------------------------------ | --------------------------- |
| `timing/intent_classify`       | intent 분류 경로·소요시간만 |
| `rag/semantic_cache_miss`      | 캐시 미스 상세              |
| `timing/rewrite_query`         | 쿼리 재작성 소요시간        |
| `rag/rag_search_done`          | RAG 검색 결과 (상세)        |
| `timing/llm_generate_response` | 응답 생성 소요시간만        |
| `timing/agent_graph_total`     | 전체 소요시간               |

### 누락된 것 (수정 전)

- LLM에 보낸 intent 분류 프롬프트 전체
- LLM이 반환한 raw 응답
- LLM에 보낸 generate_response 프롬프트 컨텍스트
- LLM이 생성한 최종 응답 전체
- booking_context 상태, TTL 체크 결과

---

## 3. 수정 내용

### 3.1 classify_intent.py — `llm/classify_intent_llm` 이벤트 추가

LLM 3차 분류 완료 후 기록:

```python
log_call_data(
    call_id, "llm", "classify_intent_llm",
    prompt_full=classify_prompt,        # LLM에 보낸 전체 프롬프트
    raw_response=raw,                   # LLM 원문 응답
    intent_decided=intent,              # 최종 결정 intent
    search_query=search_query,          # 재작성된 검색 쿼리
    booking_active=_booking_active,     # booking_context 활성 여부
    is_compound=_is_compound,           # 복합 발화 여부
    elapsed_sec=round(elapsed, 3),
    request_sent_at=request_sent_at,
    response_received_at=response_received_at,
)
```

### 3.2 generate_response.py — `llm/llm_exchange` 이벤트 추가

응답 생성 완료 후 confidence 결정 직후에 기록:

```python
log_call_data(
    call_id, "llm", "llm_exchange",
    user_text_full=user_query,          # 사용자 발화 전체
    response_full=response,             # LLM 생성 응답 전체
    intent=intent,
    confidence=confidence,
    needs_follow_up=needs_follow_up,
    rag_hit_count=len(rag_results),
    elapsed_sec=round(elapsed, 3),
    llm_rag_context_source=_rag_src,
    llm_rag_applied=_llm_rag_applied,  # RAG 문서 전체 (LLM 컨텍스트로 전달된 것)
    llm_rag_applied_count=len(_llm_rag_applied),
    rag_search_trace=...,              # ChromaDB 검색 상세 trace
)
```

`_llm_exchange_logged=True` 플래그를 state에 반환해 음성 경로 중복 방지.

### 3.3 rag_processor.py — 중복 방지 처리

`_llm_exchange_logged=True`일 때 event명을 `llm_exchange_tts_final`로 구분:

```python
_exchange_event = (
    "llm_exchange_tts_final"   # TTS override 이후 최종 텍스트
    if result.get("_llm_exchange_logged")
    else "llm_exchange"
)
```

---

## 4. 수정 후 기록되는 이벤트

### SIP 채팅 경로

```
call_data_record 이벤트 순서:
  timing/intent_classify
  llm/classify_intent_llm       ← NEW: LLM 프롬프트 전체 + raw 응답
  rag/semantic_cache_miss
  timing/rewrite_query
  rag/rag_search_done            (RAG 검색 결과 상세)
  timing/llm_generate_response
  llm/llm_exchange               ← NEW: 사용자 발화, LLM 응답, RAG 컨텍스트 전체
  timing/agent_graph_total
```

### 음성 통화 경로

```
  ... (동일) ...
  llm/llm_exchange               ← NEW (generate_response_node)
  tts/tts_text_pushed
  llm/llm_exchange_tts_final     ← rag_processor (TTS override 반영 후)
```

---

## 5. "토마토 어느나라꺼야?" 기록 예시 (수정 후)

```json
{
  "event": "classify_intent_llm",
  "prompt_full": "다음 고객 발화를 분석하세요... ⚠️ 현재 예약 대화가 진행 중입니다...",
  "raw_response": "{\"intent\": \"question\", \"search_query\": \"토마토 원산지\"}",
  "intent_decided": "question",
  "booking_active": true,
  "elapsed_sec": 2.781
}

{
  "event": "llm_exchange",
  "user_text_full": "토마토 어느나라꺼야?",
  "response_full": "저희 비스트로 벨라에서 사용하는 토마토는 이탈리아 피렌체산입니다.",
  "intent": "question",
  "confidence": 0.5,
  "rag_hit_count": 1,
  "llm_rag_applied": [{"rank": 1, "text_preview": "Q: 토마토의 원산지..."}]
}
```

*최종 업데이트: 2026-07-14*
