# ChromaDB 카테고리 구현 로직 점검 결과

**대상**: CHROMADB_CATEGORY_DESIGN.md 설계 기반 백엔드·프론트엔드 구현  
**점검일**: 구현 후 로직 일관성·엣지 케이스·수정 사항 정리

---

## 1. 백엔드 점검

### 1.1 chromadb_client.py

| 항목 | 상태 | 비고 |
|------|------|------|
| `search_collection(..., where=...)` | ✅ | where 정규화 후 `coll.query(..., where=w)` 전달. |
| `_normalize_where` | ✅ | `$and`/`$or` 리스트 재귀 정규화, `$in` 등 연산자 유지. 단순 값은 `$eq` 래핑. |
| `query` / `get` | ✅ | 기존대로 where 지원, knowledge 컬렉션 대상. |

**결론**: 설계대로 intent/category 필터 적용 가능.

---

### 1.2 rag_engine.py

| 항목 | 상태 | 비고 |
|------|------|------|
| INTENT_CATEGORY_MAP | ✅ | greeting, farewell, question, complaint, transfer, unknown 매핑. |
| filter_dict 구성 | ✅ | owner만 / intent만 / 둘 다 시 `$and` 또는 단일 조건으로 전달. |
| intent=None | ✅ | category 조건 없이 기존과 동일(owner만 또는 None). |
| adaptive_rag / step_back | ✅ | `intent=state.get("intent")` 전달. |

**주의**: 기존 문서에 `category`가 없으면 RAG 검색 시 걸리지 않음. 마이그레이션으로 `category="question"` 등 부여 필요.

---

### 1.3 semantic_cache.py

| 항목 | 상태 | 비고 |
|------|------|------|
| check_cache where | ✅ | `where={"intent": state.get("intent")}`. intent 빈 문자열이면 where=None(전체 검색, 하위 호환). |
| update_cache category | ✅ | intent→category 매핑 후 metadata에 `category` 저장. |
| TTL=0 (만료 없음) | ✅ 수정됨 | `_is_expired`에서 `ttl_seconds <= 0` 이면 `False` 반환하도록 반영. |

**결론**: intent별 캐시 검색·저장 로직 일치.

---

### 1.4 greeting_farewell_cache.py

| 항목 | 상태 | 비고 |
|------|------|------|
| 진입 조건 | ✅ | `intent in ("greeting", "farewell")` 만 처리. |
| embedder 호출 | ✅ | `embed_text` sync 시 `fn(query)`, async 시 `await fn(query)` 분기. |
| qa_cache 검색 | ✅ | `where={"intent": intent}`. |
| TTL 만료 | ✅ 수정됨 | `ttl_seconds <= 0` 이면 만료 없음 처리 추가. |
| cached_at 빈 값 | ✅ | `if cached_at and _is_expired(...)` 로 빈 문자열이면 TTL 스킵. |

**결론**: 인사/종료 전용 캐시 검색·응답 반환 정상.

---

### 1.5 agent.py

| 항목 | 상태 | 비고 |
|------|------|------|
| greeting/farewell 분기 | ✅ | `check_greeting_farewell_cache`로 진입. |
| _route_after_greeting_farewell_cache | ✅ | 히트 → update_state, greeting 미스 → generate_response, farewell 미스 → update_state. |
| 노드·엣지 등록 | ✅ | `check_greeting_farewell_cache` 노드 및 조건부 엣지 존재. |

**결론**: 설계한 흐름과 동일.

---

### 1.6 knowledge_service.py

| 항목 | 상태 | 비고 |
|------|------|------|
| add_knowledge 검증 | ✅ | text, owner, category 필수. category는 VALID_CATEGORIES 내. |
| metadata | ✅ | owner, category, source, call_id(선택). |
| 즉시 캐시 플래그 | ✅ | greeting_phase1/2, farewell 이고 answer 있으면 `needs_immediate_cache` + _cache_* 반환. |
| immediate_cache_for_knowledge | ✅ | intent=greeting|farewell, category·ttl 설정 후 qa_cache upsert. |
| list_knowledge where | ✅ | owner/category 단일 또는 `$and` 구성. vector_db.get(where) 호출. |
| doc_id (캐시) | ⚠️ | `hash(query_text)` 는 프로세스별로 달라질 수 있음. 동일 세션 내 동일 쿼리는 동일 doc_id로 upsert되어 동작에는 문제 없음. |

**결론**: 저장·즉시 캐싱·목록 조회 로직 일치.

---

### 1.7 knowledge_router.py (FastAPI)

| 항목 | 상태 | 비고 |
|------|------|------|
| POST /knowledge | ✅ | body 검증, embedder 없으면 503. add_knowledge 후 needs_immediate_cache 시 immediate_cache_for_knowledge await. |
| 응답 정리 | ✅ | `_` 접두사 키 제거 후 반환. |
| GET /knowledge | ✅ | owner, category 쿼리 → list_knowledge 호출. |
| Depends | ✅ | get_vector_db_dep, get_knowledge_embedder 사용. |

**결론**: API 계약 및 즉시 캐싱 연동 정상.

---

## 2. 프론트엔드 점검

### 2.1 app/knowledge/page.tsx

| 항목 | 상태 | 비고 |
|------|------|------|
| tenant/로그인 | ✅ | localStorage tenant 없으면 /login 리다이렉트. |
| 폼 필드 | ✅ | category(필수), text(필수), answer(인사/종료 시 표시). owner는 tenant.owner 사용. |
| POST 요청 | ✅ | text, owner, category, answer(trim 후 없으면 undefined), source. |
| 성공 시 | ✅ | 메시지 표시, text/answer 초기화, fetchList() 호출. |
| 목록 조회 | ✅ | filterOwner, filterCategory 쿼리로 GET /api/knowledge. |
| 응답 형식 | ✅ | data.items 배열로 setItems. |
| 목록 실패 시 | ✅ 수정됨 | res.ok 아님 시 에러 메시지 표시(detail/error/HTTP status). 성공 시 setMessage(null). |
| KNOWLEDGE_CATEGORIES | ✅ | types와 일치, needsAnswer와 연동. |

**결론**: 등록·목록·필터·에러 표시 로직 일치.

---

### 2.2 types/index.ts

| 항목 | 상태 | 비고 |
|------|------|------|
| KNOWLEDGE_CATEGORIES | ✅ | question, greeting_phase1/2, farewell, chitchat, complaint, transfer. |
| KnowledgeItem | ✅ | id, text, metadata(owner, category, source, call_id). |

**결론**: API 응답과 맞춤.

---

## 3. 수정 반영 사항 요약

1. **semantic_cache.py**  
   - `_is_expired`: `ttl_seconds <= 0` 이면 만료 없음(`False`) 처리.

2. **greeting_farewell_cache.py**  
   - `_is_expired`: 동일하게 `ttl_seconds <= 0` 이면 만료 없음 처리.

3. **frontend app/knowledge/page.tsx**  
   - GET /api/knowledge 실패 시 에러 메시지 표시.  
   - 목록 로드 성공 시 이전 에러 메시지 제거.  
   - detail가 객체/배열일 수 있음에 대비해 `typeof detail === 'string' ? detail : JSON.stringify(detail)` 처리.

---

## 4. 권장 사항 (선택)

| 항목 | 권장 |
|------|------|
| check_cache intent 빈 값 | intent가 빈 문자열일 때 where=None 대신 `where={"intent": "question"}` 등 기본값을 두면, 다른 intent 캐시가 잘못 히트하는 경우를 줄일 수 있음. |
| 기존 knowledge 문서 | RAG에서 검색되려면 기존 문서에 `category`(예: question) 메타데이터 추가 마이그레이션 권장. |
| 지식 API embedder | 메인 앱 기동 시 `set_knowledge_embedder(embedder)` 호출 필요. 미설정 시 POST /api/knowledge는 503. |

---

## 5. 종합

- **백엔드**: ChromaDB where, RAG intent→category, 시맨틱 캐시 intent/category, greeting/farewell 전용 캐시, 지식 추가·즉시 캐싱·목록 API 모두 설계와 일치. TTL=0 만료 처리 보완 완료.
- **프론트엔드**: 지식 등록·목록·필터·에러 메시지 표시 일치. 목록 실패 시 사용자 피드백 보완 완료.

추가로 의도한 동작과 다르게 보이는 구간이 있으면, 해당 노드/API와 요청·응답 예시를 알려주면 이어서 점검할 수 있습니다.
