# 시맨틱 캐시 개선 제안

**대상**: `sip-pbx/src/ai_voicebot/langgraph/nodes/semantic_cache.py`  
**참조**: `check_cache_node`, `update_cache_node`, `qa_cache`(ChromaDB), `SIMILARITY_THRESHOLD`, TTL

---

## 1. 시맨틱 캐시를 언제 쓰고 언제 쓰지 말아야 할지

### 1.1 검색(캐시 조회) 조건 — `check_cache_node`

| 구분 | 쓰는 경우 (캐시 히트 허용) | 쓰지 말아야 할 경우 |
|------|----------------------------|----------------------|
| **의도** | `intent`가 `question`, `greeting` 등 RAG 경로일 때만 그래프에서 호출 (현재와 동일 유지). | `complaint`, `transfer` 등 RAG가 아닌 경로에서는 `check_cache_node` 진입 자체를 하지 않음. |
| **유사도** | `score >= SIMILARITY_THRESHOLD`(0.92) 이고, 동일/유사 질문으로 볼 수 있을 때. | 임계치 미만이면 미스 처리 (현재 동작 유지). |
| **TTL** | `cached_at` + `ttl` 이내인 항목만 히트로 인정. | 만료된 항목은 히트로 쓰지 않음 (현재 `_is_expired` 유지). |
| **저장된 응답 품질** | `answer`가 완결 문장(`_looks_complete_sentence`)일 때만 히트. | 잘린 문장/오류/폴백 문장은 **저장 단계에서 막는 것**이 우선; 이미 들어간 항목은 **검색 시 제외**할 수 있음(아래 2·3절과 연계). |

**권장 정리**

- **캐시 검색은 유지**: 지연·비용 절감을 위해 `classify_intent` 직후 `check_cache_node` 호출은 유지.
- **히트 시에도 “폴백 응답”이면 무시**: 캐시된 `answer`가 폴백 문장(예: "해당 내용은 확인이 필요합니다…")이면 **히트로 사용하지 않고** 미스처럼 다음 노드(rewrite → RAG → generate_response)로 진행하도록 변경 권장.  
  → 구현: `check_cache_node`에서 `cached_answer`에 대해 `_is_fallback_message(cached_answer)`가 True면 히트 반환하지 않고 `rag_cache_hit: False` 반환.

### 1.2 적재(캐시 저장) 조건 — `update_cache_node`

| 구분 | 넣어도 되는 경우 | 넣지 말아야 할 경우 |
|------|------------------|----------------------|
| **캐시 히트 여부** | `rag_cache_hit is False`인 경우만 (현재와 동일). | `rag_cache_hit is True`인 경우 저장하지 않음 (현재와 동일). |
| **RAG 결과** | RAG 검색 결과가 **1건 이상** 있거나, 의도가 `greeting` 등 RAG가 아닌 안정 응답일 때. | **RAG 0건**이고 의도가 `question`인 경우 → 폴백 응답이므로 **저장하지 않음**. |
| **응답 내용** | 완결 문장이고, 오류/폴백 문구가 아닐 때. | `_is_error_message(response)` 또는 **폴백 문장**(`_is_fallback_message(response)`)이면 저장하지 않음. |
| **신뢰도** | (선택) `confidence`가 일정 이상일 때만 저장. | `confidence`가 낮으면 저장 생략 가능 (튜닝). |

**권장 정리**

- **RAG 0건 + question 의도**: `update_cache_node`에서 **저장 스킵** (폴백이 캐시에 들어가는 근본 원인 제거).
- **폴백/오류 문구**: `_is_fallback_message(response)` 및 `_is_error_message(response)`가 True면 저장하지 않음.

---

## 2. RAG 결과 품질(confidence/건수)에 따른 캐시 적재 제한

### 2.1 state에서 사용 가능한 값

- `state.get("rag_results", [])`: RAG 검색 결과 리스트. 길이가 0이면 RAG 0건.
- `state.get("confidence", 0.0)`: 응답 신뢰도 (generate_response 이후 설정된다고 가정).

### 2.2 제안 로직 (update_cache_node 내부)

```
적재 허용 조건 (모두 만족 시에만 저장):
1. rag_cache_hit is False  (기존)
2. query, response, _vector_db, _embedder 존재  (기존)
3. _looks_complete_sentence(response) and not _is_error_message(response)  (기존)
4. [신규] not _is_fallback_message(response)  — 폴백 문장이면 저장 안 함
5. [신규] RAG 품질 조건 중 하나:
   - intent in ("greeting", ...) 이면 RAG 건수 무관 저장 허용 (인사 등), 또는
   - intent == "question" 이면 len(rag_results) >= 1 그리고 (선택) confidence >= MIN_CONFIDENCE_TO_CACHE
```

- **MIN_CONFIDENCE_TO_CACHE**: 예) 0.6 ~ 0.7. 낮으면 캐시가 잘 쌓이지 않고, 높으면 저장이 너무 보수적일 수 있으므로 운영 중 조정.

### 2.3 구현 포인트 (파일·함수)

- **파일**: `sip-pbx/src/ai_voicebot/langgraph/nodes/semantic_cache.py`
- **함수**: `update_cache_node`
  - `rag_results = state.get("rag_results", [])`
  - `intent = state.get("intent", "question")`
  - `question` 의도이고 `len(rag_results) == 0`이면 → `skip="rag_zero_no_store"` 로그 후 `return {}`.
  - (선택) `confidence < MIN_CONFIDENCE_TO_CACHE`이면 `skip="low_confidence"` 후 `return {}`.
- **신규 헬퍼**: `_is_fallback_message(text: str) -> bool`  
  - "해당 내용은 확인이 필요합니다", "잠시만 기다려 주세요" 등 폴백 패턴 포함 시 True.  
  - `update_cache_node`에서 `_is_fallback_message(response)` True면 저장 스킵.  
  - `check_cache_node`에서 `_is_fallback_message(cached_answer)` True면 히트로 쓰지 않고 미스 처리.

---

## 3. TTL / 임계치(0.92) / 캐시 키(쿼리 vs rewritten_query) 튜닝 제안

### 3.1 TTL

| 항목 | 현재 | 제안 | 비고 |
|------|------|------|------|
| question / greeting | 86400 (24h) | 24h 유지 또는 **12h(43200)** 로 단축 | 지식이 자주 갱신되면 12h로 줄이면 “오래된 답” 히트 감소. |
| 그 외 | 3600 (1h) | 1h 유지 | 동적 답변은 1h면 충분. |

- 상수화: `TTL_FAQ_SECONDS = 86400`, `TTL_OTHER_SECONDS = 3600` (필요 시 43200으로 조정).

### 3.2 유사도 임계치 (SIMILARITY_THRESHOLD = 0.92)

| 값 | 효과 |
|----|------|
| **0.92 유지** | 유사 질문을 꽤 넓게 묶음. 현재 이슈는 “폴백이 캐시에 들어간 것”이므로, 적재 조건 보강이 우선. |
| **0.94~0.95** | 더 비슷한 문장만 히트. 캐시 히트율은 줄고, RAG로 갈 기회는 늘어남. |
| **0.90 이하** | 히트가 많아져 서로 다른 질문까지 같은 답이 나올 위험. 비권장. |

**권장**: 먼저 **폴백/ RAG 0건 적재 차단**을 적용한 뒤, 여전히 “유사한데 다른 질문에 같은 답”이 나오면 **0.94** 정도로 올려서 실험.

### 3.3 캐시 키: user_query vs rewritten_query

- **저장 시**: 현재 `query = state.get("rewritten_query") or state.get("user_query", "")` 로 **rewritten_query 우선** 사용.
  - **장점**: RAG에 실제로 쓰인 쿼리와 동일한 표현으로 캐시하면, 다음에 rewrite 결과가 같을 때 검색 시 유사도가 잘 맞음.
  - **단점**: 사용자 원문과 다를 수 있어, **검색은 user_query 임베딩**인데 **저장은 rewritten_query 임베딩**이면 표현 차이로 미스가 늘 수 있음.

**제안**

- **검색**: 계속 **user_query** 임베딩 사용 (현재 `check_cache_node` 동작 유지).
- **저장**:  
  - **옵션 A (현재 유지)**: `rewritten_query or user_query` → RAG와의 일관성 우선.  
  - **옵션 B**: **user_query만 저장** → 사용자 발화 기준으로만 캐시. rewrite 결과가 바뀌어도 같은 사용자 문장이면 히트.  
  - **옵션 C**: **둘 다 저장**하지 않고, **user_query 기준 1건만 저장**하되 메타에 `rewritten_query`를 넣어 두는 방식은 검색 키와의 일치를 위해 보통 user_query만 벡터로 쓰는 것이 맞음.

**권장**: 우선 **옵션 A 유지**. 문제가 있으면 **옵션 B**(저장 시 `user_query`만 사용)로 바꿔서 비교 테스트.

---

## 4. 만료된 항목 물리 삭제 필요 여부 및 구현 포인트

### 4.1 필요 여부

- **동작상**: 검색 시 `_is_expired(cached_at, ttl)`로 만료 항목을 쓰지 않으므로 **동작에는 문제 없음**.
- **저장소 성장**: 만료된 문서가 ChromaDB `qa_cache`에 계속 쌓이면 디스크/메모리 증가와 검색 시 불필요한 후보가 늘 수 있음.
- **권장**: **물리 삭제 있으면 좋고**, 트래픽이 많지 않다면 우선순위는 “폴백 적재 차단 + RAG 품질 조건”보다 낮게 둬도 됨.

### 4.2 구현 포인트

- **위치**: 별도 스크립트 또는 주기적 태스크에서 `qa_cache` 컬렉션을 스캔해 `cached_at + ttl < now`인 문서 삭제.
- **방법**:
  1. ChromaDB(또는 사용 중인 vector_db 래퍼)에 **메타데이터 조건으로 삭제**하는 API가 있으면:  
     `cached_at < (now - max_ttl)` 인 id 목록 조회 후 삭제.
  2. **전체 문서 id를 iterate**할 수 있으면: 각 문서 메타데이터에서 `cached_at`, `ttl` 읽어 만료된 것만 삭제.
- **주기**: 예) 1일 1회, 또는 서버 기동 시 1회. 부하를 고려해 비피크 시간에 실행.
- **코드 위치**:  
  - `semantic_cache.py`에 `delete_expired_cache_entries(vector_db, collection_name=CACHE_COLLECTION)` 같은 함수를 두고,  
  - 실제 호출은 `scripts/` 또는 스케줄러에서 수행하도록 두면 됨.  
- **전제**: `vector_db`에 `delete_by_ids(collection_name, ids)` 또는 `delete_where(collection_name, where)` 같은 API가 있어야 함. 없으면 ChromaDB 클라이언트 직접 사용해 해당 컬렉션에 대해 삭제 로직 추가 필요.

---

## 5. 실행 가능한 권장사항 리스트 (코드 경로 포함)

| # | 권장사항 | 코드 경로 / 조치 |
|---|----------|-------------------|
| 1 | **폴백 응답을 캐시에 저장하지 않기** | `semantic_cache.py`: `update_cache_node` 내부에서 `_is_fallback_message(response)` True면 저장 스킵. 신규 함수 `_is_fallback_message(text)` 추가 (예: "해당 내용은 확인이 필요합니다", "잠시만 기다려 주세요" 포함 여부). |
| 2 | **캐시에 저장된 폴백 응답은 히트로 쓰지 않기** | `semantic_cache.py`: `check_cache_node`에서 `cached_answer`에 대해 `_is_fallback_message(cached_answer)` True면 히트로 반환하지 말고 `rag_cache_hit: False` 반환해 RAG 경로로 진행. |
| 3 | **RAG 0건일 때(question 의도) 캐시 적재 금지** | `semantic_cache.py`: `update_cache_node`에서 `intent == "question"` 이고 `len(state.get("rag_results", [])) == 0` 이면 저장하지 않고 `skip="rag_zero_no_store"` 로그 후 `return {}`. |
| 4 | **(선택) 낮은 confidence면 저장 스킵** | `semantic_cache.py`: 상수 `MIN_CONFIDENCE_TO_CACHE = 0.6` (또는 0.7) 정의 후, `update_cache_node`에서 `state.get("confidence", 0) < MIN_CONFIDENCE_TO_CACHE` 이면 `skip="low_confidence"` 후 `return {}`. |
| 5 | **오류 메시지 확장** | `semantic_cache.py`: `_is_error_message`에 폴백 문구 하나 더 넣어도 됨 (예: "해당 내용은 확인이 필요합니다" → 오류는 아니지만 `_is_fallback_message`로 별도 처리 권장). |
| 6 | **TTL 상수화** | `semantic_cache.py`: `TTL_FAQ_SECONDS`, `TTL_OTHER_SECONDS` 상수로 빼고, 필요 시 FAQ를 43200(12h)으로 줄여서 실험. |
| 7 | **유사도 임계치 튜닝** | `semantic_cache.py`: 폴백/적재 조건 적용 후에도 유사 질문에 오래된 답이 나오면 `SIMILARITY_THRESHOLD`를 0.94 등으로 상향 실험. |
| 8 | **만료 항목 물리 삭제** | `semantic_cache.py`에 `delete_expired_cache_entries(vector_db)` 추가; vector_db에 delete API가 있으면 스크립트/스케줄러에서 주기 호출. 없으면 ChromaDB delete API 확인 후 구현. |
| 9 | **서버 재시작 시 qa_cache 초기화 (선택)** | 아래 §6 참고. ChromaDB 초기화 직후 `qa_cache` 컬렉션만 삭제하거나, 환경변수로 “캐시 초기화” 모드 시 삭제. |

---

## 6. 서버 재시작 시 시맨틱 캐시 동작 및 초기화

### 6.1 현재 동작 (초기화되지 않음)

- 시맨틱 캐시는 **ChromaDB의 `qa_cache` 컬렉션**에 저장됨.
- ChromaDB는 **PersistentClient**로 **디스크에 저장**됨.  
  - 경로: `CHROMA_DB_PATH` 환경변수 또는 `data/chroma` (프로젝트 루트 기준).  
  - 코드: `chromadb_client.py` → `chromadb.PersistentClient(path=path, ...)`.
- 서버 재시작 시 **같은 경로를 다시 열기만** 하므로, **qa_cache 컬렉션과 그 안의 문서는 그대로 유지됨.**  
  즉, **서버 재시작만으로는 시맨틱 캐시가 초기화되지 않음.**

### 6.2 재시작 시 초기화가 필요할 때

- 배포/재기동 후 **이전 캐시를 비우고** 새로 쌓고 싶을 때.
- 지식/설정을 크게 바꾼 뒤 **과거 질의–응답 캐시를 쓰고 싶지 않을** 때.

### 6.3 구현 방안 (재시작 시 qa_cache 초기화) — 적용됨

**적용된 동작**: 서버 기동 시 **기본으로 qa_cache를 삭제**하고, 환경변수로 끌 수 있음.

| 설정 | 설명 |
|------|------|
| **CLEAR_QA_CACHE_ON_START** | 환경변수. `1`(기본), `true`, `yes` → 기동 시 `qa_cache` 컬렉션 삭제. `0`, `false`, `no` → 삭제하지 않음(캐시 유지). |
| **구현 위치** | `sip-pbx/src/ai_voicebot/knowledge/chromadb_client.py`: `_should_clear_qa_cache_on_start()`, `_clear_qa_cache_on_start(client)`. `initialize()` 및 `get_vector_db()`에서 PersistentClient 생성 직후 호출. |
| **주의** | `qa_cache`만 삭제하며 `knowledge` 컬렉션은 건드리지 않음. |

---

**요약**:  
- **즉시 적용 권장**: (1) 폴백 문장 저장 금지, (2) 저장된 폴백은 히트로 사용하지 않기, (3) RAG 0건(question)일 때 적재 금지.  
- **이후 튜닝**: TTL 단축, SIMILARITY_THRESHOLD 상향, confidence 하한, 캐시 키를 user_query만 쓰는 실험.  
- **선택**: 만료 문서 물리 삭제는 저장소 성장이 문제될 때 구현.
