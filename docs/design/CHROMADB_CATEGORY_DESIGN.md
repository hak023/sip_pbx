# ChromaDB 카테고리 분류 설계 (Intent 연동)

**목적**: 저장 시 분류(category)로 적재하고, RAG/캐시 검색 시 intent에 따라 적절한 문서만 검색. greeting/farewell 등 자주 바뀌지 않는 메시지는 입력 즉시 캐싱해 효율적으로 사용.

**참조**: [INTENT_HANDLING_DESIGN.md](./INTENT_HANDLING_DESIGN.md), [chromadb_client.py](../../src/ai_voicebot/knowledge/chromadb_client.py), [semantic_cache.py](../../src/ai_voicebot/langgraph/nodes/semantic_cache.py)

---

## 1. 개요

| 구분 | 내용 |
|------|------|
| **knowledge 컬렉션** | 지식 문서 저장. 기존 `owner` 필터에 더해 **category** 메타데이터로 intent 유형별 분류. |
| **qa_cache 컬렉션** | 이미 `intent` 메타데이터 저장 중. 검색 시 **intent/category 필터** 추가 시 동일 intent 캐시만 히트. |
| **캐싱 정책** | greeting phase1/phase2, farewell 은 “입력 즉시 qa_cache에 적재”(TTL 길게) → 자주 바뀌지 않는 메시지 효율 사용. |

---

## 2. 카테고리 체계 (Intent 연동)

### 2.1 category 값 정의

Intent와 1:1 또는 N:1로 매핑. **저장 시** 문서에 부여하는 값.

| category | 설명 | 사용처 (입력 소스) | 검색 시 intent |
|----------|------|---------------------|----------------|
| `question` | 질의·FAQ 지식 | 유저 간 통화 요약, API Q&A 입력 | question, complaint, transfer, unknown |
| `greeting_phase1` | 통화 시작 인사 (예: "안녕하세요, OO입니다") | API/프론트 입력 | greeting |
| `greeting_phase2` | 인사 후 첫 응답 (예: "무엇을 도와드릴까요?") | API/프론트 입력 | greeting |
| `farewell` | 종료 인사 (예: "감사합니다. 안녕히 가세요.") | API/프론트 입력 | farewell |
| `chitchat` | 잡담용 참고 문장 | API 입력 (선택) | chitchat |
| `complaint` | 불만 대응 참고 | API 입력 (선택) | complaint |
| `transfer` | 전환/연결 안내 참고 | API 입력 (선택) | transfer |

- **유저 간 통화**에서 추출되는 지식은 대부분 `question` (질문-답변 쌍).
- **API/프론트** 입력은 위 표의 모든 category를 지정 가능.

### 2.2 메타데이터 스키마

**knowledge 컬렉션** (문서 추가 시):

| 필드 | 타입 | 필수 | 설명 |
|------|------|------|------|
| `owner` | str | 예 | 착신번호(테넌트). 기존과 동일. |
| `category` | str | 예 | 위 표의 category 값. |
| `source` | str | 선택 | `api` \| `human_call_summary` (출처 구분). |
| `call_id` | str | 선택 | 통화 기반 추출 시 통화 ID. |

**qa_cache 컬렉션** (이미 존재하는 필드 + 정리):

| 필드 | 타입 | 설명 |
|------|------|------|
| `answer` | str | 캐시된 응답 문장. |
| `confidence` | float | 신뢰도. |
| `intent` | str | 의도 (캐시 저장 시점 intent). |
| `cached_at` | str | ISO 8601 시각. |
| `ttl` | int | 만료 초 단위. |
| `category` | str | (신규) 위와 동일한 category. greeting_phase1 등. |

- 검색 시 **where** 에 `category` 또는 `intent` 조건을 넣어 intent별로만 검색.

---

## 3. 저장 로직 (입력별 상세)

### 3.1 유저 간 통화 → ChromaDB 입력

- **트리거**: 통화 종료 후, 전사본 LLM 요약·QA 추출 파이프라인.
- **저장 대상**: 추출된 “질문-답변” 또는 요약 문장.
- **메타데이터**:
  - `owner`: 착신번호 (또는 통화 주체 식별자).
  - `category`: `question` (통화 추출은 대부분 질의 응답).
  - `source`: `human_call_summary`.
  - `call_id`: 해당 통화 ID (선택).
- **컬렉션**: `knowledge` 만. 이 경로에서는 qa_cache 즉시 적재하지 않음 (대량 추출이므로 캐시는 RAG/대화로 자연스럽게 쌓이게 둠).

### 3.2 API/프론트를 통한 입력

- **트리거**: 지식 관리 API (예: POST /api/knowledge 또는 동등한 엔드포인트).
- **입력 필드 예시**: `text`, `owner`, **`category`** (필수), `answer`(캐시용 시 사용), 기타.
- **category별 동작**:

| category | knowledge 저장 | qa_cache 즉시 캐싱 |
|----------|-----------------|---------------------|
| `greeting_phase1`, `greeting_phase2`, `farewell` | 예 (검색용) | **예** — 입력 즉시 upsert, TTL 길게(예: 7일 또는 0=만료 없음). |
| `question` | 예 | 선택(기본은 아니고, “즉시 캐시” 옵션만 허용). |
| `chitchat`, `complaint`, `transfer` | 예 | 선택. |

- **즉시 캐싱** 상세:
  - API로 `category in (greeting_phase1, greeting_phase2, farewell)` 인 문서가 들어오면:
    1. `knowledge`에 `owner`, `category`, `source=api` 로 저장.
    2. 동일 내용으로 **qa_cache**에 upsert.
       - `metadata`: `answer` = 해당 인사/종료 문장, `intent` = greeting 또는 farewell, `category` = 동일, `ttl` = 긴 값(예: 604800 = 7일) 또는 0(무제한).
  - 이렇게 하면 “자주 바뀌지 않는 인사/종료 메시지”는 다음 통화부터 **캐시에서 즉시 히트** 가능.

### 3.3 저장 흐름 요약

```
[유저 간 통화 종료]
  → 전사 → LLM 요약/QA 추출
  → knowledge.add( text, metadata={ owner, category="question", source="human_call_summary", call_id? } )

[API/프론트 입력]
  → category 수신
  → knowledge.add( text, metadata={ owner, category, source="api" } )
  → if category in (greeting_phase1, greeting_phase2, farewell):
       qa_cache.upsert( query=text 또는 고정 키, answer=응답문, intent=greeting|farewell, category=..., ttl=긴값 )
```

---

## 4. 검색 로직 (Intent별 분류 검색)

### 4.1 RAG 검색 (knowledge 컬렉션)

- **현재**: `vector_db.query( where={"owner": owner_filter} )` 만 사용.
- **변경**: intent에 따라 **where** 에 `category` 조건 추가.

**intent → category 매핑 (검색 시)**:

| intent | where 조건 (owner 외 추가) |
|--------|----------------------------|
| greeting | `category` in `["greeting_phase1", "greeting_phase2"]` |
| farewell | `category` = `"farewell"` |
| question, complaint, transfer, unknown | `category` = `"question"` 또는 `category` in `["question", "complaint", "transfer"]` (정책에 따라) |

- ChromaDB where 다중 조건: `{"$and": [{"owner": {"$eq": owner}}, {"category": {"$in": ["greeting_phase1", "greeting_phase2"]}}]}` 형태로 전달.
- **하위 호환**: 기존 문서에 `category`가 없을 수 있으므로, 초기에는 “category 없음 = question과 동일 취급” 또는 마이그레이션으로 기존 문서에 `category="question"` 부여.

### 4.2 시맨틱 캐시 검색 (qa_cache)

- **현재**: `search_collection(collection_name="qa_cache", vector=..., top_k=1)` — where 없음.
- **변경**: intent가 정해진 경우 **같은 intent(또는 category) 문서만** 검색하도록 where 전달.

**옵션 A (권장)**  
- `check_cache_node` 진입 시점에 이미 `intent`가 있음 (classify_intent 후 check_cache로 오는 경로는 question, complaint, transfer, unknown).
- **greeting / farewell** 은 현재 agent에서 check_cache를 타지 않고 바로 `generate_response` / `update_state`로 감.
- 따라서 “greeting/farewell용 캐시”를 쓰려면:
  1. **경로 확장**: intent=greeting 또는 farewell 일 때도 “전용 캐시 검색”을 한 번 수행하고, 히트 시 해당 문장으로 응답 후 종료.
  2. **전용 검색**: `search_collection(..., where={"intent": "greeting"} 또는 {"category": {"$in": ["greeting_phase1", "greeting_phase2"]}})`.

**옵션 B**  
- check_cache는 기존처럼 전 컬렉션 검색.
- greeting/farewell만 “별도 노드”에서 intent별로 search_collection(where=...) 호출.

**정리**: intent=greeting → “greeting 전용 캐시” 검색 → 히트 시 해당 인사로 응답. intent=farewell → “farewell 전용 캐시” 검색 → 히트 시 해당 종료 인사로 응답. 나머지(question 등)는 기존 check_cache에서 **where={"intent": state["intent"]}** 추가하면 intent별로 캐시 검색 가능.

### 4.3 greeting / farewell “즉시 캐싱” 요약

- **저장**: API로 greeting_phase1/2, farewell 입력 시 → knowledge 저장 + qa_cache 즉시 upsert (TTL 길게).
- **검색**: intent=greeting → qa_cache를 `category`/`intent`로 필터해 검색 → 히트 시 즉시 응답(캐시 우선). intent=farewell → 동일.
- **효과**: 자주 바뀌지 않는 인사/종료 문구를 한 번 입력해 두면, 다음부터는 RAG/LLM 호출 없이 캐시로 빠르게 응답.

---

## 5. 구현 시 변경 포인트

### 5.1 chromadb_client.py

- **search_collection**: `where: Optional[Dict] = None` 인자 추가. `coll.query(..., where=w)` 에 전달.
- **query** (기존): 이미 `where` 지원. 호출하는 쪽에서 `filter_dict`에 `category` 조건 추가만 하면 됨.

### 5.2 rag_engine.py (RAG 검색)

- **search()**: `filter_dict` 구성 시 `owner` 뿐 아니라 **intent → category** 매핑 테이블을 두고, `category` 조건을 추가.
- 예: `intent="greeting"` → `where={"$and": [{"owner": owner}, {"category": {"$in": ["greeting_phase1", "greeting_phase2"]}}]}`.
- question 계열은 `category in ["question", "complaint", "transfer"]` 또는 기존처럼 category 없이 owner만(하위 호환).

### 5.3 semantic_cache.py

- **check_cache_node**:  
  - state에서 `intent` 읽기.  
  - `search_collection(..., where={"intent": intent})` 또는 `{"category": ...}` 전달(가능 시).
- **update_cache_node**: 이미 `intent`를 metadata에 저장 중. `category`도 intent에서 유도해 저장 (예: greeting → category=greeting_phase2 등, 정책에 따라).

### 5.4 지식 추가 API (존재 시)

- 요청 body에 **category** 필수.
- `greeting_phase1`, `greeting_phase2`, `farewell` 인 경우: knowledge 추가 후 동일 클라이언트에서 qa_cache upsert (같은 텍스트를 query/answer로, TTL 7일 등).

### 5.5 유저 간 통화 → ChromaDB 저장 파이프라인

- 지식 추출 시 메타데이터에 `category="question"`, `source="human_call_summary"`, `owner`, `call_id` 설정.

---

## 6. 데이터 일관성·마이그레이션

- **기존 문서**: `category` 필드가 없으면 검색 시 `$or` 로 (category 없음 OR category=question) 포함하거나, 일괄 업데이트로 `category="question"` 부여.
- **qa_cache**: 기존 항목은 `intent`만 있고 `category` 없을 수 있음. 검색 시 intent만으로 필터해도 동작하도록 하면 됨.

---

## 7. 요약 표

| 항목 | 내용 |
|------|------|
| **저장 시 분류** | knowledge: `owner` + **category** (question, greeting_phase1/2, farewell, chitchat, complaint, transfer) + source, call_id. |
| **유저 간 통화** | 추출 지식 → category=question, source=human_call_summary. |
| **API 입력** | category 지정 가능. greeting_phase1/2, farewell → knowledge + **즉시 qa_cache** upsert (TTL 길게). |
| **RAG 검색** | intent에 따라 where에 **category** 조건 추가 (owner + category). |
| **캐시 검색** | intent별 where 조건 추가 (같은 intent/category만 히트). |
| **greeting/farewell 효율** | 입력 즉시 캐싱 → 다음부터 캐시에서 즉시 응답. |

이 설계대로 구현하면 ChromaDB에 intent와 연동된 카테고리로 저장·검색이 이루어지고, 인사/종료 메시지는 입력 즉시 캐싱해 효율적으로 사용할 수 있습니다.

---

## 8. 관련 코드 위치

| 목적 | 파일 | 비고 |
|------|------|------|
| ChromaDB 래퍼 (get/query/add, search_collection) | `src/ai_voicebot/knowledge/chromadb_client.py` | query/get에 where 지원. search_collection에 where 추가 필요. |
| RAG 검색 (owner 필터) | `src/ai_voicebot/ai_pipeline/rag_engine.py` | filter_dict에 category 조건 추가. |
| 시맨틱 캐시 검색/저장 | `src/ai_voicebot/langgraph/nodes/semantic_cache.py` | search_collection 호출 시 where 전달; metadata에 category 저장. |
| Intent 분기 | `src/ai_voicebot/langgraph/agent.py` | greeting/farewell 시 캐시 선검색 분기 추가 시 수정. |
| Intent 목록·분류 | `src/ai_voicebot/langgraph/nodes/classify_intent.py` | category ↔ intent 매핑 참고. |
| 지식 API (추가 시) | 예: `routes/knowledge.py` 또는 동등 | 요청에 category 필수, greeting/farewell 시 qa_cache upsert. |
