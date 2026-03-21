# Query Rewrite 스킵 이유 & RAG/ChromaDB 응답이 안 나온 이유

## 로그 기준 흐름 (call_id XTxtwliPDh, "오늘의 날씨를 알려주세요.")

1. `rag_llm_user_input` → query "오늘의 날씨를 알려주세요."
2. **query_rewrite_skip_candidate** (complexity=simple) → rewrite 스킵
3. classify_intent (question)
4. **check_cache** → **hit=true**
5. **semantic_cache_hit** (query 동일, score 0.972)
6. **cache_hit=true** 로 응답 반환 → "해당 내용은 확인이 필요합니다. 잠시만 기다려 주세요."
7. **RAG 검색(rag_search_*), generate_response(LLM) 미실행**

---

## 1. Rewrite를 스킵한 이유

### 로그

```text
event: query_rewrite_skip_candidate
complexity: "simple"
note: "간단한 query → rewrite 스킵 가능"
query_preview: "오늘의 날씨를 알려주세요."
```

### 이유 (추정)

- 쿼리가 **"simple"(간단)** 으로 분류되어 **rewrite 단계를 건너뜀**.
- **목적**: 짧고 명확한 문장은 그대로 벡터 검색해도 되므로, **rewrite용 LLM 호출을 생략**해 지연·비용을 줄이기 위함.

### Rewrite가 하는 일 (일반적 구현)

- **입력**: 사용자 발화 (예: "오늘의 날씨를 알려주세요.")
- **출력**: RAG 검색에 더 잘 맞는 문장 (예: "오늘의 날씨", "날씨 예보")으로 다듬기.
- **스킵 시**: 원문 "오늘의 날씨를 알려주세요." 그대로 RAG 쿼리로 사용.

### 현재 구현 추정 (코드 없이 로그만으로)

| 단계 | 동작 |
|------|------|
| **복잡도 판단** | 쿼리 길이·형태 등 휴리스틱 또는 소량 LLM으로 "simple" vs "complex" 구분. |
| **simple** | `query_rewrite_skip_candidate` 로그 남기고 **rewrite LLM 호출 생략** → 원문을 RAG 쿼리로 사용. |
| **complex** | rewrite LLM 호출 → 변환된 쿼리로 RAG 검색. |

즉, **스킵 이유 = “간단한 쿼리”로 판단해서 rewrite를 생략한 것**이며, 스킵해도 **원문으로 RAG는 수행될 수 있음**.  
이번 호에서는 **그 다음 단계에서 캐시 히트**가 나서 RAG가 아예 호출되지 않음.

### simple 판단 기준선 (기준이 뭔지)

- **이 워크스페이스에는 simple을 판단하는 코드가 없음.**  
  `query_rewrite_skip_candidate` / `complexity: "simple"` 를 남기는 위치와 기준은 **백엔드(다른 저장소·서비스)** 에 있음.
- **확인하려면**: 백엔드에서 `query_rewrite_skip_candidate` 또는 `complexity`·`simple` 로그를 남기는 모듈을 찾아, 그 안의 조건(문자 수, 단어 수, 문장 수, 키워드 목록, LLM 호출 여부 등)을 보면 됨.
- **일반적으로 있을 수 있는 기준 (추정)**  
  - **문자/바이트 수**: 예) N자 이하면 simple (예: 20자, 30자).  
  - **단어/어절 수**: 예) M개 이하면 simple.  
  - **문장 수**: 1문장이면 simple.  
  - **키워드/패턴**: “~해 주세요”, “~알려주세요” 등 짧은 요청형만 simple.  
  - **소량 LLM**: “이 쿼리는 검색용으로 쓸 만한가?” 같은 1회 호출로 simple vs complex 분류.  

**정리**: **정확한 기준선(임계값·규칙)은 백엔드 구현을 봐야 하고**, 여기서는 “simple이면 rewrite 스킵”이라는 동작만 로그로 확인된 상태임.

### Rewrite 스킵 소스 위치 (이 저장소 기준)

- **파일**: `sip-pbx/src/ai_voicebot/langgraph/nodes/rewrite_query.py`
- **동작**:
  - `needs_rewrite = (len(words) < 5) or (대명사/모호 패턴 포함)`  
    → **5단어 미만**이거나 `AMBIGUOUS_PATTERNS`("이거","그거","저거","뭐","아까","그때","거기") 포함 시에만 LLM rewrite 수행.
  - **스킵 조건**: `not needs_rewrite` → 즉 **5단어 이상**이고 위 패턴이 없으면 **rewrite 생략**, `rewritten_query`에 원문 그대로 사용.
- **로그**: 이 파일에서는 스킵 시 `logger.debug("query_rewrite_skipped", query=...)` 와 `timing_segment` (segment="rewrite_query", skip=True) 만 남김.
- **참고**: 로그에 나온 `query_rewrite_skip_candidate` / `complexity: "simple"` 를 **남기는 코드는 이 저장소에 없음**. 다른 배포본·서비스에서 나온 로그이거나, 로그 키가 추후 변경되었을 수 있음.

---

## 2. 기대했던 로직 vs 실제 동작

### 기대

- RAG로 **ChromaDB(벡터 DB)** 검색 → 검색된 지식으로 **LLM이 응답** → 그 내용이 TTS로 재생.

### 실제

- **RAG 검색이 수행되지 않음** (로그에 `rag_search_start` / `rag_search_completed` 없음).
- **semantic_cache_hit** (score 0.972) 발생 → **캐시된 응답**을 그대로 반환.
- 반환된 문장: **"해당 내용은 확인이 필요합니다. 잠시만 기다려 주세요."**  
  → 이전에 **비슷한 질의**(예: "오늘의 날씨가 궁금합니다")에 대해 **RAG 0건 + LLM 폴백**으로 나온 응답이 캐시에 들어 있었고, 그게 재사용된 것.

### ChromaDB에 내용이 있어도 이렇게 된 이유 (두 가지)

| 원인 | 설명 |
|------|------|
| **1) 시맨틱 캐시 선반영** | LangGraph 흐름이 **classify_intent 뒤에 check_cache**를 타고, **캐시 히트 시 곧바로 캐시 응답 반환**. 이 경로에서는 **RAG 검색·generate_response가 호출되지 않음**. 그래서 이번 요청에서는 ChromaDB를 조회하지도 않음. |
| **2) 1004 지식 0건** | 같은 호에서 RAG를 타더라도, 현재 **owner=1004 ChromaDB 지식은 0건**이라 RAG 결과는 비어 있고, LLM은 동일한 폴백 문장을 만들었을 것. 그 과거 결과가 캐시에 들어 있었고, 이번에는 캐시만 써서 같은 응답이 나온 것. |

정리하면,

- **직접적 이유**: **시맨틱 캐시 히트** 때문에 RAG/LLM 경로가 실행되지 않고, 예전 “RAG 0건일 때의 폴백 응답”이 그대로 나온 것.
- **구조적 이유**: 1004 테넌트에 ChromaDB 지식이 없어서, 캐시가 없었더라도 RAG 기반 “지식 답변”은 나올 수 없었을 상태.

---

## 3. 해결 방향

| 목표 | 조치 |
|------|------|
| **ChromaDB 내용으로 답하게** | 1) **1004용 지식 시드** 실행 (`scripts/seed_knowledge_1004_via_api.py` 등)으로 ChromaDB에 문서 적재. 2) **캐시 정책 조정**: RAG를 타기 전에 캐시를 쓰지 않거나, RAG 결과가 있을 때만 캐시를 쓰도록 하면, 지식이 들어간 뒤에는 RAG 기반 응답이 나올 수 있음. |
| **Rewrite 동작 이해/변경** | simple 시 rewrite 스킵은 “원문으로 검색”이므로, 지식이 DB에 있고 캐시가 가로막지 않으면 RAG는 동작 가능. “날씨” 같은 짧은 키워드가 문서에 있으면 원문 쿼리로도 검색될 수 있음. 필요하면 simple이라도 rewrite를 태우거나, simple 판단 기준을 조정. |
| **캐시로 인한 폴백 고정 해제** | **시맨틱 캐시**에서 “오늘의 날씨” 유사 질의에 대해 예전 폴백 응답이 묶여 있으므로, (a) 해당 쿼리/유사 쿼리 캐시를 비우거나, (b) RAG 우선(캐시 후순위) 정책으로 변경하면, 지식 추가 후에는 RAG 결과가 나오게 할 수 있음. |

---

## 4. 요약

| 질문 | 답변 |
|------|------|
| **Rewrite 스킵 이유** | 쿼리가 **"simple"** 로 분류되어, rewrite LLM 호출을 생략하고 **원문을 그대로 RAG 쿼리로 쓰기 위해** 스킵함. |
| **Rewrite 현재 구현** | (코드 없이 추정) complexity=simple → rewrite 스킵 후 원문으로 RAG, complex → rewrite LLM 호출 후 변환 쿼리로 RAG. |
| **RAG/ChromaDB 응답이 안 나온 이유** | **시맨틱 캐시 히트**로 인해 **RAG 검색·LLM 생성이 실행되지 않고**, 예전 “RAG 0건 시 폴백” 응답이 그대로 반환됨. 1004 ChromaDB에 지식이 0건인 것도 별도 원인. |

---

## 5. 1004 전용 tenant config — 언제 만들어지는가?

### 이 워크스페이스에서 확인한 것

- **tenant config를 생성하는 코드는 이 저장소(sip-pbx)에 없음.**  
  (tenant / 1004 / config 생성 로직으로 검색한 결과, 해당 코드가 없거나 다른 저장소/서비스에 있음.)
- 로그·문서상으로는 **owner=1004** 가 다음 용도로만 쓰이는 것이 확인됨:
  - RAG 검색 시 `owner_filter="1004"` (ChromaDB)
  - 인사말/Phase2 등에서 `org_manager_capabilities_loaded`, owner=1004

### “자동으로 만들어지는 시점”에 대해

- **이 코드베이스만으로는 “1004 전용 tenant config가 자동으로 생성되는 시점”을 특정할 수 없음.**  
  실제 생성 로직은 백엔드(또는 설정 배포 스크립트)에 있을 가능성이 큼.
- 일반적으로 tenant config가 생기는 시점은 다음 중 하나일 수 있음:
  1. **서버/서비스 기동 시**  
     설정 파일(예: YAML/JSON)이나 DB에서 tenant 목록을 읽고, 1004 등에 대한 config를 메모리/캐시에 로드.
  2. **해당 tenant로 첫 요청이 들어올 때 (lazy)**  
     owner=1004 로 첫 호출이 오면 그 시점에 config를 생성하거나 기본값으로 초기화.
  3. **관리 API 호출 시**  
     예: “테넌트 1004 등록” 같은 API가 호출될 때만 1004용 config/DB 레코드 생성.

### 로그로 알 수 있는 것

- `org_manager_capabilities_loaded` count=0, owner=1004  
  → **통화(AI 터크오버) 시점에** 1004에 대한 capability를 **조회**는 함.  
  → “config 생성” 시점을 가리키는 로그는 아니며, “이미 존재하는 1004용 무언가를 로드했는데 0건이었다”로 해석됨.

**정리**: 1004 전용 tenant config가 **언제** 만들어지는지는, 이 워크스페이스 코드만으로는 알 수 없고, **백엔드/설정 배포 쪽에서 “tenant 등록·config 로드”가 어떻게 구현돼 있는지** 확인해야 함.  
자동 생성이 있다면 보통은 (1) 기동 시 설정 로드, (2) 첫 요청 시 lazy 생성 중 하나인 경우가 많음.

---

## 6. 시맨틱 캐시 — 적재·만료·검색 로직

**소스**: `sip-pbx/src/ai_voicebot/langgraph/nodes/semantic_cache.py`  
**저장소**: ChromaDB 컬렉션 `qa_cache`.

### 검색 (언제 검색하는지)

| 항목 | 내용 |
|------|------|
| **시점** | LangGraph 흐름에서 **classify_intent 직후** `check_cache_node` 호출. (의도가 question 등 RAG 경로일 때만.) |
| **동작** | `check_cache_node`: 사용자 쿼리를 임베딩 → `qa_cache` 컬렉션에 `top_k=1` 유사도 검색. |
| **히트 조건** | (1) **유사도 ≥ 0.92** (코사인, `SIMILARITY_THRESHOLD`), (2) **TTL 미만** (`cached_at` + `ttl` 초 이내), (3) 캐시된 `answer`가 완결 문장으로 판단될 때. |
| **히트 시** | `rag_cache_hit=True`, `response`에 캐시된 답변 설정 → 이후 **rewrite_query / adaptive_rag / generate_response 없이** `update_state`로 직행. |
| **미스 시** | `rag_cache_hit=False` → `rewrite_query` → `adaptive_rag` → … → `generate_response` → `update_cache` → `update_state`. |

### 적재 (언제 넣는지)

| 항목 | 내용 |
|------|------|
| **시점** | **캐시 미스**였을 때만. 흐름이 `generate_response`까지 진행된 뒤 `update_cache_node` 호출. |
| **조건** | (1) `rag_cache_hit`가 False였고, (2) `rewritten_query` 또는 `user_query`, (3) `response`(LLM 응답), (4) `_vector_db`, `_embedder` 존재. (5) 응답이 완결 문장처럼 보이고, 오류 메시지가 아닐 때만 저장. |
| **저장 내용** | 쿼리 임베딩 + 메타데이터: `answer`, `confidence`, `intent`, `cached_at`(ISO 시각), `ttl`. |
| **TTL** | intent가 `question` 또는 `greeting`이면 **86400초(24시간)**, 그 외 **3600초(1시간)**. |

### 사라짐(만료) — 언제 쓰지 않게 되는지

| 항목 | 내용 |
|------|------|
| **방식** | **TTL 기반 만료**. 별도 삭제(eviction) 배치 없음. 검색 시마다 `_is_expired(cached_at, ttl)`로 판단. |
| **만료 조건** | `(now - cached_at).total_seconds() > ttl` 이면 “만료”로 보고 해당 항목은 **히트로 사용하지 않음** (상위 1건이 만료면 결과 없음으로 처리). |
| **물리 삭제** | 코드 상에는 **만료된 문서를 qa_cache에서 삭제하는 로직 없음**. 오래된 문서는 ChromaDB에 남아 있고, 검색 시 유사도/만료 체크로만 무시됨. |

요약: **검색**은 classify_intent 직후, **적재**는 캐시 미스 후 generate_response 완료 시, **사라짐**은 TTL 초과 시 검색에서 제외(물리 삭제는 없음).

---

## 7. Rewrite 수행 시점 고찰 및 속도 방안 (리서치)

### RAG·ChromaDB 검색 시 rewrite를 쓰는 것이 좋은 이유

- 구어체/대명사/모호 표현은 **벡터 검색과 잘 맞지 않음**. rewrite로 “검색에 적합한 문장”으로 바꾸면 **검색 정확도·리콜이 개선**된다는 사례가 많음 (리서치에서 30~45% 수준 개선 보고).
- RAG 실패 원인 중 상당수가 **쿼리 형식** 문제라고 할 때, ChromaDB 적재·검색 모두 **rewritten query를 쓰는 쪽이 일관된 품질**에 유리함.

### 속도 염려 — 어떻게 쓰는 게 좋은지

| 방안 | 설명 |
|------|------|
| **조건부 적용(현행 유지·보강)** | “이미 검색에 적합한 쿼리”는 rewrite 생략해 **지연·비용 절감**. 짧지만 명확한 쿼리(예: 5단어 이상, 대명사 없음)는 스킵하는 현재 로직이 합리적. |
| **경량 판단** | simple vs complex를 **문자/단어 수·패턴만**으로 나누면 LLM 호출 없이 즉시 스킵 가능. 필요 시 **소형 모델·짧은 프롬프트**로 “rewrite 필요 여부”만 판단하는 1회 호출도 선택지. |
| **병렬화** | rewrite와 **다른 경량 작업**(예: 임베딩 준비)을 병렬로 돌려서 체감 지연을 줄일 수 있음. (실제로는 classify_intent 다음에 rewrite가 오므로, 그래프 구조 변경이 필요.) |
| **품질 검증 후 폴백** | rewrite를 항상 시도하되, **rewritten 쿼리로 검색 결과가 나쁘면 원문으로 재검색**하는 “corrective retrieval” 패턴. 정확도는 올리지만 지연·복잡도는 증가. |
| **템플릿 기반 확장** | Elastic 등에서는 “전문 rephrase” 대신 **키워드 추출·동의어 확장·pseudo-answer** 등 제한된 출력을 템플릿에 끼워 넣는 방식을 권장. LLM 출력 범위를 좁혀 지연·드리프트를 줄임. |

### 리스크 — 무조건 rewrite가 좋은 것은 아님

- Query rewriting은 **의도 드리프트·엔티티 바꿈·과도한 필터링** 등 **새로운 실패 모드**를 만든다. “해 harmless한 다듬기”가 사용자 의도와 어긋날 수 있음.
- **권장**: 이미 잘 정형화된·도메인 특화 쿼리는 rewrite 스킵; 적용 시에는 **rewrite 후 검색 품질을 평가하는 단계**를 두고, 나쁘면 원문으로 fallback.

### 현재 코드와의 정합성

- **`rewrite_query.py`**: 5단어 미만 또는 대명사/모호 패턴일 때만 LLM rewrite. **RAG 검색·ChromaDB 적재**에는 `rewritten_query`(또는 없으면 `user_query`)가 쓰이므로, “검색에는 rewritten를 쓴다”는 목표와 맞음.
- **속도**: rewrite 스킵 시 추가 지연 없음. rewrite 수행 시 LLM 1회 호출(~수백 ms~수 초)이 붙으므로, **스킵 조건(5단어 이상·패턴 없음)을 유지하거나**, 휴리스틱을 더 넓혀 “명확히 검색용인 문장”일 때 스킵하는 쪽이 속도 면에서 유리함.

**정리**: RAG/ChromaDB 검색에는 **rewritten query를 쓰는 것이 품질상 유리**하고, **속도는 “조건부 스킵(현행처럼 5단어 이상·대명사 없으면 스킵)”으로 맞추는 것**이 좋다. 필요 시 경량 판단·템플릿 기반 확장·품질 검증 후 fallback을 단계적으로 도입할 수 있음.

---

## 8. 시맨틱 캐시 활용 방안 (서브에이전트 결과 요약)

시맨틱 캐시를 **언제 쓰고, 언제 쓰지 말며, 어떻게 적재·만료할지**에 대한 상세 제안은 아래 문서와 코드 반영으로 정리되어 있음.

**상세 문서**: `docs/reports/SEMANTIC_CACHE_IMPROVEMENT_PROPOSAL.md`

### 서버 재시작 시 동작

- **기본 동작 (적용됨)**: 서버 기동 시 **시맨틱 캐시(qa_cache)를 삭제**함. ChromaDB 초기화 직후 `qa_cache` 컬렉션만 제거되며, 지식베이스(`knowledge`)는 그대로 유지됨.
- **설정**: 환경변수 **`CLEAR_QA_CACHE_ON_START`**
  - **`1`**(기본), `true`, `yes` → 기동 시 qa_cache 초기화.
  - **`0`**, `false`, `no` → 기동 시 삭제하지 않음(캐시 유지).
- 구현: `src/ai_voicebot/knowledge/chromadb_client.py` — `_should_clear_qa_cache_on_start()`, `_clear_qa_cache_on_start()`.

### 요약

| 구분 | 권장 |
|------|------|
| **검색 시** | 유사도 ≥ 0.92, TTL 내, 완결 문장이면 히트. **단, 캐시된 답변이 폴백 문장**(“해당 내용은 확인이 필요합니다…”)이면 **히트로 쓰지 않고** 미스 처리 → RAG 경로로 진행. |
| **적재 시** | **폴백/오류 응답은 저장하지 않음.** **RAG 0건 + question 의도**인 경우도 저장 스킵. (선택) `confidence`가 일정 이상일 때만 저장. |
| **TTL/임계치** | TTL은 FAQ 24h·그 외 1h 등 상수로 분리. 유사도 0.92 유지, 필요 시 0.94 등 상향 실험. |
| **만료 항목** | 검색 시 TTL 체크로 이미 제외됨. 디스크 부담 시에만 만료 항목 **물리 삭제** 스크립트/스케줄러 도입 검토. |

**코드 반영** (서브에이전트 적용분): `src/ai_voicebot/langgraph/nodes/semantic_cache.py`  
- `_is_fallback_message()` 추가  
- `check_cache_node`: 폴백이면 히트 미사용, 미스 처리  층
- `update_cache_node`: 폴백 저장 스킵, RAG 0건(question) 저장 스킵, confidence 하한(선택) 적용  
- TTL/임계치 상수화  

이에 따라 **RAG 0건 폴백 응답이 캐시에 쌓이지 않고**, 이미 들어간 폴백은 **캐시 히트로 쓰이지 않아** 지식 추가 후 RAG 경로로 새 답이 나가도록 되어 있음.
