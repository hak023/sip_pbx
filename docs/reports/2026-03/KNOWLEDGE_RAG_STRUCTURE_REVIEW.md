# 지식베이스·RAG·통화 후 추출 구조 점검 리포트

**작성일**: 2026-03-21  
**버전**: 1.0  
**상태**: 점검 완료  
**관련 코드**: `src/ai_voicebot/knowledge/*`, `src/api/knowledge_router.py`, `src/sip_core/call_manager.py`, `frontend/app/knowledge/*`

---

## 1. 목적

1. 유저 간 통화 종료 후 LLM 판단으로 ChromaDB에 저장된 값이 AI 봇 RAG에서 활용되는지 여부와 개선점.
2. 프론트 지식베이스(예: 테넌트 1004) 저장값이 AI 봇 지식검색에 쓰이지 않는 것으로 보일 때의 원인과 올바른 저장 방식·프론트 개선안.

---

## 2. 아키텍처 요약

| 구간 | 역할 |
|------|------|
| `POST /api/knowledge` | `add_knowledge` → Chroma `knowledge` 컬렉션, `metadata.owner` + `category` 등 |
| 통화 후 추출 | `ExtractionPipeline` / `KnowledgeExtractor` → 동일 컬렉션 저장 의도 |
| AI 응대 | LangGraph `adaptive_rag_node` → `RAGEngine.search(query, owner_filter=_owner, intent=...)` |

RAG 테넌트 격리 키는 **`owner` 문자열이 통화 시 `_owner`와 동일**해야 조회에 포함된다.

---

## 3. 통화 후 추출 → Chroma → AI RAG

### 3.1 설계상 연결

- 일반 SIP 통화 종료 시 `CallManager`가 `knowledge_extractor.extract_from_call(..., owner_id=callee_id, ...)` 스케줄.
- `callee_id`는 한 경로에서 `call_session.get_callee_uri()`(전체 SIP To URI)일 수 있음.
- AI Pipecat 경로는 `callee_username`(예: `"1004"`)을 `owner`로 사용.

### 3.2 `owner` 불일치 리스크

- 저장: `sip:1004@…` 또는 `sip:1004@unknown`
- RAG: `"1004"`
- Chroma `where={"owner": ...}` 가 문자열 일치이므로 **서로 다르면 동일 테넌트라도 검색에서 제외**됨.

**권장**: 추출·저장 전 `owner`를 **내선 ID로 정규화**하는 단일 유틸(예: 기존 `_tenant_id_to_owner`와 동일 규칙)을 CallManager·트리거·API에 통일 적용.

### 3.3 파이프라인 ↔ `get_vector_db()` 계약 불일치 (중요)

`ExtractionPipeline` Stage 4는 `await self.vector_db.upsert(...)` 호출.

- `chromadb_client._VectorDbWrapper`에는 **`upsert` 메서드가 없음** → 저장 단계에서 `AttributeError` 가능성.
- `SemanticDeduplicator`는 `await self.vector_db.search(vector=..., top_k=...)` 호출.
- `_VectorDbWrapper`에 **`search`도 없음** → Stage 3에서도 실패 가능성.

**권장**: `_VectorDbWrapper`에 `upsert` / `search`(또는 내부 `query` 래핑) 구현, 또는 파이프라인을 `add` + `query` 기반으로 통일.

### 3.4 의도(intent)별 `category` 필터

`RAGEngine.INTENT_CATEGORY_MAP`에 따라 `complaint` / `transfer`는 `category ∈ {question, complaint, transfer}` 로 제한.

- 추출 파이프라인은 LLM이 준 `category`(예: `"정보"`, `"기타"`, 엔티티 타입)를 그대로 메타데이터에 넣을 수 있음.
- **`question` 의도**는 category 필터 없음 → 추출 문서가 후보에 들어가기 쉬움.
- **`complaint` / `transfer`** 는 위 카테고리 밖이면 **필터에서 제외**될 수 있음.

**권장**: 추출 저장 시 `category`를 `VALID_CATEGORIES`/`question` 등 RAG 설계 집합에 매핑하거나, 해당 intent 검색 조건 완화 검토.

---

## 4. 프론트 지식베이스 vs RAG

### 4.1 올바른 경로: `frontend/app/knowledge/page.tsx`

- `POST /api/knowledge`에 `text`, `owner`(테넌트 `owner`), `category`, `doc_type`, `source` 등 **백엔드 스펙과 일치**.
- 로그인 테넌트가 `1004`이면 `owner: "1004"` 저장 → AI 통화 시 `_owner`가 `"1004"`이면 RAG 필터와 일치.

### 4.2 문제 가능 경로: `frontend/app/knowledge/add/page.tsx`

- `owner` 누락, `category`가 `faq`/`product` 등 **백엔드 `VALID_CATEGORIES`와 불일치**.
- `keywords`, `metadata` 객체는 현재 `KnowledgeCreateRequest`에 없음 → 검증 실패 또는 무의미한 저장 시도.

**권장**: 해당 페이지를 폐기하거나 `page.tsx`와 동일 API 스펙으로 통일; 네비에서 구 경로 제거.

### 4.3 RAG에 “안 잡히는” 체감 원인 후보

1. **유사도 임계값** `similarity_threshold` — 질의·문서 임베딩 유사도 부족(코드에 soft fallback 존재).
2. **의도**가 `complaint`/`transfer`일 때 **category 필터**로 `question`만 등록한 문서 제외.
3. **API만 별도 프로세스** 실행 시 `set_knowledge_embedder` 미설정 → POST 503 (통합 `main.py` 기동 시에는 설정됨).
4. **`CHROMA_DB_PATH` / 프로세스별 작업 디렉터리** 차이로 API와 SIP가 **서로 다른 Chroma 파일** 참조.

---

## 5. 권장 조치 요약

| 우선순위 | 조치 | 상태 (2026-03-21) |
|----------|------|-------------------|
| 높음 | `_VectorDbWrapper`에 `upsert`·`search` 구현 | ✅ `chromadb_client.py` — `async upsert`, `async search`(유사도 `1/(1+d)`), dedup용 |
| 높음 | 통화 후 추출 `owner_id` 정규화 (username만, `@` 앞 + `sip:` 제거) | ✅ `src/common/sip_owner.py`, CallManager·추출 파이프라인·`add_knowledge`·`list_knowledge`·`RAGEngine.search`·`pipeline_builder` |
| 중간 | 추출 `category`와 RAG 필터 정합성 | ✅ `extraction_category.py` — 비표준 라벨은 `question` 등으로 저장 |
| 중간 | 프론트 `knowledge/add` 스펙 정리 | ✅ `knowledge/add/page.tsx`를 `/api/knowledge`·`KNOWLEDGE_CATEGORIES`와 동일 폼으로 통일 |
| 낮음 | RAG 0건 시 진단 로그 | ✅ `adaptive_rag_empty_debug` + 기존 `rag_search_owner_normalized` |

---

## 6. Chroma 기존 DB 마이그레이션 (owner / category)

- 스크립트: `scripts/migrate_chroma_knowledge_metadata.py`
- 동작: `knowledge` 컬렉션 전체에 대해 `metadata.owner` 정규화(username), `category`가 비었거나 `VALID_CATEGORIES` 밖이면 `question`. `qa_cache`는 존재 시 `owner` 정규화 및 잘못된 `category`만 수정.
- 실행 (sip-pbx 루트):  
  `python -m scripts.migrate_chroma_knowledge_metadata --dry-run`  
  `python -m scripts.migrate_chroma_knowledge_metadata`
- 적용 DB 경로: `get_chroma_persist_path()` (`CHROMA_DB_PATH` 또는 `data/chroma`). 실행 전 `data/chroma` 백업 권장.

## 7. 참고 코드 위치

- 지식 API: `src/api/knowledge_router.py`, `src/ai_voicebot/knowledge/knowledge_service.py`
- Chroma 래퍼: `src/ai_voicebot/knowledge/chromadb_client.py`
- RAG: `src/ai_voicebot/ai_pipeline/rag_engine.py`, `src/ai_voicebot/langgraph/nodes/adaptive_rag.py`
- 추출: `src/ai_voicebot/knowledge/extraction_pipeline.py`, `src/sip_core/call_manager.py`
- LangGraph owner 주입: `src/ai_voicebot/langgraph/agent.py`

---

*최종 업데이트: 2026-03-21*
