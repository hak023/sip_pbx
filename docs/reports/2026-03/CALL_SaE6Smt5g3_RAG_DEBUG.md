# call_id: SaE6Smt5g3 — RAG 미검색 원인 및 수정 요약

**작성일**: 2026-03-16  
**통화**: 1003 → 1004 (AI 응대), ChromaDB 지식 질의 시 검색 결과 0건

---

## 로그 기반 진단

### 확인된 사실

1. **RAG는 호출됨**  
   - `rag_search_completed` 이벤트 존재 (call_id=SaE6Smt5g3)  
   - 쿼리 예: "오늘의 날씨 정보.", "어떤 종류의 날씨 정보를 제공하나요?"

2. **항상 결과 0건**  
   - `results_count`: 0  
   - `top_score`: 0.0  
   - `top_doc_preview`: ""

3. **LLM 응답**  
   - "해당 내용은 확인이 필요합니다. 잠시만 기다려 주세요." (confidence 0.000, needs_human true)  
   - 즉, RAG 컨텍스트가 비어 있어 fallback 응답만 발생

---

## 근본 원인: intent별 category 필터 불일치

### RAG 검색 시 사용하던 조건

- **intent**: `"question"` (사용자 질문)
- **INTENT_CATEGORY_MAP["question"]**: `["question", "complaint", "transfer"]`
- **실제 쿼리 조건**:  
  `where = { "$and": [ {"owner": "1004"}, {"category": {"$in": ["question", "complaint", "transfer"]}} ] }`

### ChromaDB에 저장된 1004 지식의 category

- 시드/지식 데이터: `weather_forecast`, `weather_warning`, `historical_data`, `service_info`, `weather_knowledge`, `application`  
- FAQ: `category: "faq"`  
- capability: `weather_forecast`, `weather_warning` 등

**정리**:  
`category`가 `question`/`complaint`/`transfer`인 문서가 1004 테넌트에 없어서, **ChromaDB가 where 조건에 맞는 문서를 한 건도 반환하지 않음** → RAG 결과가 항상 0건.

---

## 적용한 수정 사항

### 1. `rag_engine.py` — question/unknown 시 category 제한 제거

- **변경 전**:  
  `"question"` / `"unknown"` 도 `["question", "complaint", "transfer"]` 로 category 제한  
- **변경 후**:  
  - `"question"`, `"unknown"` → **category 필터 없음** (해당 intent일 때는 owner만 적용)  
  - 테넌트(1004)의 **모든 지식/FAQ/capability**를 검색 대상으로 사용

```python
# question/unknown: category 제한 없음(owner만 필터)
INTENT_CATEGORY_MAP = {
    "greeting": ["greeting_phase1", "greeting_phase2"],
    "farewell": ["farewell"],
    "question": None,   # 전체 지식 검색 (owner만 적용)
    "complaint": ["question", "complaint", "transfer"],
    "transfer": ["question", "complaint", "transfer"],
    "unknown": None,   # 전체 지식 검색 (owner만 적용)
}
```

- **category 적용 로직**:  
  `cats`가 `None`이거나 빈 리스트일 때는 `category` 조건을 추가하지 않도록 수정  
  (`if cats is not None and cats:` 로만 `$in` 조건 추가)

### 2. RAG 검색 디버깅 로그 추가

- **이벤트**: `rag_search_debug`
- **로그 필드**  
  - `raw_count_before_threshold`: ChromaDB에서 받은 문서 수 (유사도 필터 전)  
  - `after_threshold_count`: 유사도 threshold 적용 후 문서 수  
  - `filter_where`: 실제 사용한 `where` 조건  
  - `intent`, `first_raw_distance`  
- **해석**:  
  - `raw_count_before_threshold > 0` 인데 `after_threshold_count == 0` → threshold 또는 스코어 계산 의심  
  - `raw_count_before_threshold == 0` → **where 조건(owner/category) 불일치** 의심 (이번 케이스)

---

## 수정 후 기대 동작

- 1003 → 1004 통화에서 "오늘 날씨", "날씨 정보" 등 질의 시:
  - **owner=1004** 만 조건으로 적용되고,
  - `weather_forecast`, `weather_knowledge`, `faq` 등 **모든 category**가 검색 대상이 되어
  - ChromaDB에서 문서가 반환되고, RAG 컨텍스트가 LLM에 전달되며,
  - "해당 내용은 확인이 필요합니다" 대신 **ChromaDB에 있는 날씨/기상 안내 문구**가 반영된 응답이 나와야 함.

---

## 재현·확인 방법

1. 백엔드 재시작 후 동일 시나리오(1003→1004, 날씨 질의)로 통화  
2. 로그에서 다음 확인:  
   - `rag_search_debug`: `raw_count_before_threshold` > 0, `after_threshold_count` ≥ 1  
   - `rag_search_completed`: `results_count` ≥ 1, `top_doc_preview`에 내용 존재  
   - `langgraph_agent_result`: `response_full`에 지식 기반 안내 문장 포함

---

## 관련 파일

- `src/ai_voicebot/ai_pipeline/rag_engine.py` (INTENT_CATEGORY_MAP, search 시 filter 및 `rag_search_debug` 로그)
- `src/services/seed_data.py` (1004 KNOWLEDGE_DATA category 정의)
