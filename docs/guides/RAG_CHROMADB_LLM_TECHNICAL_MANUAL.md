# RAG · ChromaDB · LLM 질의/응답 테크니컬 메뉴얼

실제 파라미터와 데이터 흐름에 따른 질의/응답 결과가 어떻게 나오는지 상세 정리.

---

## 1. 개요

- **RAG**: 사용자 발화(질의) → 쿼리 변환 → Vector DB 검색 → 검색 결과를 LLM 컨텍스트로 전달 → LLM이 답변 생성.
- **ChromaDB**: 지식 컬렉션(`knowledge_base`)과 Semantic Cache 컬렉션(`qa_cache`) 저장소.
- **LLM**: Google Gemini (설정에 따라 `gemini-2.5-flash` 등). 시스템 프롬프트 + RAG 컨텍스트 + 대화 기록 + 사용자 질문으로 최종 프롬프트 조립 후 `generate_content` 호출.

---

## 2. ChromaDB

### 2.1 설정 (config)

| 경로 | 키 | 기본값 | 설명 |
|------|-----|--------|------|
| `ai_voicebot.vector_db.provider` | provider | `"chromadb"` | 벡터 DB 프로바이더. |
| `ai_voicebot.vector_db.chromadb.persist_directory` | persist_directory | `"./data/chromadb"` | 로컬 DB 저장 경로. |
| (코드 고정) | collection_name | `"knowledge_base"` | 지식 검색용 기본 컬렉션. |

- **클라이언트**: `get_chromadb_client(persist_directory, collection_name="knowledge_base", client_mode="local")` 로 프로세스당 싱글톤 생성.
- **컬렉션 메타데이터**: `{"hnsw:space": "cosine"}` → 코사인 유사도 사용.

### 2.2 지식 컬렉션 `knowledge_base`

- **역할**: RAG 검색 시 사용. 문서 저장 시 `upsert(doc_id, embedding, text, metadata)`.
- **검색 API**: `search(vector, top_k, filter)`.
  - 내부: `collection.query(query_embeddings=[vector], n_results=min(top_k, collection.count()), where=filter, include=["documents","metadatas","distances"])`.
  - **거리 → 유사도 변환**: `score = 1.0 / (1.0 + distance)` (ChromaDB가 반환하는 거리값을 0~1 유사도로 변환).
- **필터**: RAG 검색 시 `owner`(착신번호)로 테넌트 격리. `where={"owner": owner_filter}`.

### 2.3 Semantic Cache 컬렉션 `qa_cache`

- **역할**: 유사 질문 재사용. 캐시 히트 시 Vector 검색/LLM 호출 없이 저장된 답변 반환.
- **컬렉션 이름**: `CACHE_COLLECTION = "qa_cache"` (코드 상수).
- **검색**: `search_collection(collection_name="qa_cache", vector=query_embedding, top_k=1)`.
- **저장**: `upsert_to_collection("qa_cache", doc_id, embedding, text=query, metadata={answer, confidence, intent, cached_at, ttl})`.
- **캐시 히트 조건**: 상위 1건의 `score >= 0.92` 이고, `cached_at` 기준 TTL 미만이며, `answer`가 완결 문장으로 판단될 때.
- **TTL**: FAQ(intent=question/greeting) 86400초(24h), 그 외 3600초(1h).

### 2.4 ChromaDB 카테고리별 데이터 저장·조회

같은 `knowledge_base` 컬렉션 안에 **메타데이터(doc_type, owner, category 등)** 로 종류를 나누어 저장한다. RAG 검색 시에는 **owner만** 필터로 쓰고, doc_type/category로는 검색 필터를 걸지 않는다(유사도로 상위 문서가 자연스럽게 지식/FAQ 위주로 걸림).

#### 2.4.1 doc_type·역할 요약

| doc_type | 저장 주체 | 역할 | 조회 방식 |
|----------|-----------|------|-----------|
| **tenant_config** | 시드/API | 테넌트(착신번호)별 설정 1건. **인사말·끝인사 템플릿**은 이 문서의 **metadata** 안에 JSON 문자열로 보관. | `collection.get(where={"$and":[{"doc_type":"tenant_config"},{"owner": owner}]})` → metadata 파싱. |
| **capability** | 시드/API | AI가 제공하는 서비스 목록(메뉴 안내, 예약, 날씨 예보 등). metadata에 display_name, category, keywords, owner. | `get_all_capabilities(owner)` 등으로 별도 조회. RAG 검색 시에도 동일 컬렉션에서 owner로 걸리면 나올 수 있음. |
| **(없음 또는 faq)** | 시드/지식추출 | 일반 지식·FAQ. metadata에 category, keywords, owner, source, created_at. FAQ는 doc_type=faq, question 등. | RAG 검색 시 `filter={"owner": owner}` 로만 조회. 반환 문서의 metadata.category는 로깅/표시용. |

#### 2.4.2 인사말·끝인사는 별도 문서가 아님

- **처음 인사말(Phase1)**: ChromaDB에 “인사말” 전용 문서를 두지 않는다. **tenant_config 한 건**의 metadata에 `greeting_templates`(JSON 배열 문자열)로 여러 문장을 넣어 두고, 통화 시작 시 `OrganizationInfoManager.get_random_greeting_template()`으로 그중 하나를 랜덤 선택해 TTS로 재생한다.
- **끝 인사(마무리 멘트)**: 마찬가지로 **tenant_config** metadata의 `closing_templates`(JSON 배열 문자열). farewell 의도일 때 `get_random_closing_template()`으로 하나 골라 TTS로 재생한다.

즉, “카테고리별로 인사말/끝인사 문서를 넣고 꺼내 쓰는” 구조가 아니라, **테넌트 설정 1건(tenant_config)의 metadata 필드**로 인사말·끝인사 목록을 보관하고, **메타데이터만 파싱해서** 꺼내 쓴다.

#### 2.4.3 현재 보관 데이터 기반 예시 (시드 기준)

**테넌트 1004 (기상청)**

- **tenant_config 1건**  
  - id: `tenant_config_1004`  
  - text(임베딩용): `"기상청 (Korea Meteorological Administration): 대한민국의 기상 및 기후 정보를 제공하는 정부 기관"`  
  - metadata 예:  
    - `doc_type`: `"tenant_config"`  
    - `owner`: `"1004"`  
    - **greeting_templates**: JSON 문자열. 파싱 시 예:  
      - `"안녕하세요. 기상청 AI 통화 비서입니다. 무엇을 도와드릴까요?"`  
      - `"안녕하세요. 기상청 AI 상담원입니다. 어떤 도움이 필요하신가요?"`  
      - `"기상청에 전화해 주셔서 감사합니다. AI 비서가 도와드리겠습니다."`  
      - `"안녕하세요. 기상청입니다. 날씨와 관련된 문의를 도와드리겠습니다."`  
    - **closing_templates**: JSON 문자열. 파싱 시 예:  
      - `"감사합니다. 기상 정보가 필요하시면 언제든 연락 주세요. 좋은 하루 되세요."`  
      - `"감사합니다. 필요하시면 다시 전화 주세요."`  
    - 그 외: tenant_name, system_prompt_template, description, business_hours 등.

- **지식 문서** (category로 구분, RAG 검색 대상)  
  - 예: `category: "weather_forecast"`, text: `"날씨 예보는 기상청 홈페이지(www.kma.go.kr), 날씨누리 앱, 또는 131번 자동응답전화에서 확인할 수 있습니다..."`  
  - 예: `category: "weather_warning"`, text: `"기상 특보는 주의보와 경보로 나뉩니다. 호우, 대설, 한파..."`  
  - 예: `category: "historical_data"`, text: `"과거 기상 데이터는 기상자료개방포털(data.kma.go.kr)에서 무료로 조회하실 수 있습니다..."`

- **FAQ** (doc_type=faq, RAG 검색 대상)  
  - metadata: doc_type=faq, owner=1004, question, category="faq"  
  - text: `"Q: 내일 날씨 어떤가요?\nA: 실시간 날씨 정보는 기상청 홈페이지..."`  
  - 유사 질문 검색 시 이 문서가 걸리면 LLM 컨텍스트로 전달됨.

**테넌트 1003 (이탈리안 비스트로)**

- **tenant_config**  
  - **greeting_templates** 예:  
    - `"안녕하세요! 이탈리안 비스트로입니다. 무엇을 도와드릴까요?"`  
    - `"이탈리안 비스트로에 전화 주셔서 감사합니다. AI 비서가 안내해 드리겠습니다."`  
  - **closing_templates** 예:  
    - `"감사합니다. 또 방문해 주세요. 좋은 하루 되세요."`  
    - `"감사합니다. 필요하시면 언제든 연락 주세요."`

- **지식 문서** category 예: menu, hours, location, parking, reservation, policy, event 등.  
  - 예: category=menu, text: `"파스타 메뉴: 까르보나라 16,000원, 알리오올리오 14,000원..."`

#### 2.4.4 꺼내 쓰는 흐름 요약

| 용도 | 데이터 위치 | 꺼내는 방법 |
|------|-------------|-------------|
| 처음 인사말 | tenant_config metadata → greeting_templates | `OrganizationInfoManager.get_random_greeting_template()` (통화 시작 시 1회) |
| 끝 인사말 | tenant_config metadata → closing_templates | `OrganizationInfoManager.get_random_closing_template()` (farewell 시 1회) |
| RAG 질의 답변 | knowledge_base 문서 (지식/FAQ 등) | `vector_db.search(vector=embed(query), top_k=..., filter={"owner": owner})` → 상위 문서를 LLM 컨텍스트로 전달 |
| 테넌트 이름·시스템 프롬프트 | tenant_config metadata | `collection.get(where=doc_type+owner)` → metadata.tenant_name, system_prompt_template 등 |
| 서비스 목록(Phase2 인사말 안내) | capability 문서 또는 tenant_config 연동 | `KnowledgeService.get_all_capabilities(owner)` 등 |

정리하면, **카테고리별로 넣고 꺼내 쓰는 것**은 (1) **지식/FAQ**는 같은 컬렉션에 category/metadata로 구분해 두고, 검색은 **owner만** 걸어서 유사도로 꺼내고, (2) **인사말·끝인사**는 별도 문서가 아니라 **tenant_config 한 건의 metadata**에 넣어 두고, **get(where=doc_type+owner)** 로 그 문서만 조회한 뒤 metadata에서 파싱해 쓴다.

#### 2.4.5 카테고리: 고정 vs 가변, 저장 및 RAG 활용

- **카테고리는 고정이 아니라 가변(자유 문자열)입니다.**  
  코드에 “허용된 category 목록” 같은 enum 검증이 없으며, metadata에 넣는 `category` 값은 **아무 문자열**이어도 됩니다.

- **저장 방식**
  - 문서를 ChromaDB에 넣을 때 **metadata** 안에 `"category": "<문자열>"` 로 저장합니다.
  - **시드 데이터** (`seed_data.py`): 지식/FAQ 삽입 시 category를 지정 (예: menu, hours, weather_forecast, faq, reservation, policy 등).
  - **지식 추출** (`extraction_pipeline`): 통화에서 추출한 Q&A·엔티티·일반 지식에 category 부여 (예: "약속", "위치", "시간", "가격", "절차", "정보", "기타" 또는 entity_type).
  - **API/수동 입력**: `KnowledgeService.add_knowledge(..., category=...)`, `add_from_hitl(..., category="faq")` 등으로 넣을 때 호출자가 정한 문자열이 그대로 metadata에 저장됩니다.

- **RAG에서의 활용**
  - **통화 중 RAG 검색** (`rag_engine.search`)에서는 **category를 필터로 사용하지 않습니다.**  
    검색 시 사용하는 필터는 `filter={"owner": owner_filter}` 뿐입니다.  
    즉, 착신번호(owner)로만 테넌트 격리를 하고, **유사도로 상위 문서**를 가져옵니다.
  - **category가 쓰이는 곳**  
    - **로깅·표시**: `rag_engine`에서 검색 결과를 DB에 기록할 때 `doc.metadata.get("category", "unknown")` 으로 category를 로그/표시용으로 사용합니다.  
    - **지식 품질 검증**: 품질 게이트 등에서 category별 규칙(예: "기타" + 낮은 신뢰도 시 거부)에 활용할 수 있습니다.  
    - **관리용 API**: `KnowledgeService.search_knowledge(query, category=...)`, `get_all_knowledge(category=...)` 는 **category로 필터링**해 조회하는 **관리·대시보드용** API이며, 통화 중 LLM에 넘기는 RAG 검색 경로와는 별개입니다.

**요약**: 카테고리는 **가변 문자열**로 **문서 metadata에 저장**되고, **RAG 검색 필터로는 사용되지 않으며**, **로깅·표시·품질 검증·관리 API**에서만 사용됩니다.

### 2.5 현재 ChromaDB에 들어 있는 내용 (실제 조회 기준)

`scripts/inspect_chromadb.py`로 `knowledge_base` 컬렉션을 조회한 결과를 요약한다. 시드가 한 번이라도 돌아간 환경에서는 아래와 비슷한 구조다.

#### 2.5.1 knowledge_base 문서 수·구성

| 구분 | 문서 수 | doc_id 패턴 | 설명 |
|------|---------|-------------|------|
| tenant_config | 2 | `tenant_config_1003`, `tenant_config_1004` | 테넌트별 설정 1건. metadata에 greeting_templates, closing_templates(JSON), system_prompt_template 등. |
| capability | 10 | `cap_1003_*`, `cap_1004_*` | 서비스 안내(메뉴, 예약, 날씨 예보, 담당자 연결 등). owner·category로 구분. |
| 지식(knowledge) | 18 | `kb_seed_1003_001`~`010`, `kb_seed_1004_001`~`008` | 시드 지식. category: menu, hours, location, weather_forecast, weather_warning 등. |
| FAQ | 10 | `faq_seed_1003_001`~`005`, `faq_seed_1004_001`~`005` | doc_type=faq. Q/A 한 쌍이 text에 "Q: ...\nA: ..." 형태. |
| **합계** | **40** | | |

#### 2.5.2 owner(테넌트)별 보관 예

**owner 1003 (이탈리안 비스트로)**

- **tenant_config_1003**  
  - text(임베딩용): `"이탈리안 비스트로 (Italian Bistro): 정통 이탈리아 요리를 선보이는 캐주얼 다이닝 레스토랑"`  
  - greeting_templates 예: `"안녕하세요! 이탈리안 비스트로입니다. 무엇을 도와드릴까요?"`, `"이탈리안 비스트로에 전화 주셔서 감사합니다. AI 비서가 안내해 드리겠습니다."` 등 3건.  
  - closing_templates 예: `"감사합니다. 또 방문해 주세요. 좋은 하루 되세요."`, `"감사합니다. 필요하시면 언제든 연락 주세요."` 2건.
- **capability** 5건: menu, reservation, hours, location, transfer.
- **지식** 10건: category별 menu(파스타/피자/메인 가격, 런치 세트), hours(영업시간·브레이크타임), location(주소·강남역), parking, reservation, policy, event.
- **FAQ** 5건: 주차 가능 여부, 예약, 런치 세트, 영업시간, 단체 예약.

**owner 1004 (기상청)**

- **tenant_config_1004**  
  - text(임베딩용): `"기상청 (Korea Meteorological Administration): 대한민국의 기상 및 기후 정보를 제공하는 정부 기관"`  
  - greeting_templates 예: `"안녕하세요. 기상청 AI 통화 비서입니다. 무엇을 도와드릴까요?"` 등 4건.  
  - closing_templates 예: `"감사합니다. 기상 정보가 필요하시면 언제든 연락 주세요. 좋은 하루 되세요."` 등 2건.
- **capability** 5건: weather_forecast, weather_warning, historical_data, transfer, weather_knowledge.
- **지식** 8건: weather_forecast(홈페이지·앱·131), weather_warning(특보·태풍), historical_data(기상자료개방포털), service_info(131·운영시간), weather_knowledge(장마·미세먼지), application(기상감정서).
- **FAQ** 5건: 내일 날씨, 태풍 정보, 과거 날씨 데이터, 기상감정서 발급, 담당자 연결.

#### 2.5.3 qa_cache

- Semantic Cache용 컬렉션. 유사 질문이 이전에 응답된 적 있으면 여기서 답변을 꺼내 쓴다.
- 조회 시점 예: 문서 수 16건 (통화 중 캐시 적재분). metadata에 answer, confidence, intent, cached_at, ttl 등.

#### 2.5.4 실제 내용 조회 방법

프로젝트 루트에서 다음으로 현재 DB 내용을 다시 볼 수 있다.

```bash
cd sip-pbx
python scripts/inspect_chromadb.py
```

---

## 3. Embedding

### 3.1 설정 (config)

| 경로 | 키 | 기본값 | 설명 |
|------|-----|--------|------|
| `ai_voicebot.embedding.model` | model | `"paraphrase-multilingual-mpnet-base-v2"` | Sentence Transformers 모델. |
| `ai_voicebot.embedding.dimension` | dimension | `768` | 임베딩 차원. |
| `ai_voicebot.embedding.batch_size` | batch_size | `32` | 배치 크기. |

- **사용처**: 쿼리/문서 임베딩 생성. RAG 검색·Semantic Cache 검색·지식 추출 시 동일 embedder 사용.
- **입출력**: `embedder.embed(text: str) -> List[float]` (길이 768).

---

## 4. RAG (검색) 파라미터와 결과

### 4.1 RAG 엔진 설정 (config)

| 경로 | 키 | 기본값 | 설명 |
|------|-----|--------|------|
| `ai_voicebot.rag.top_k` | top_k | `3` | **최종 반환** 문서 수. |
| `ai_voicebot.rag.similarity_threshold` | similarity_threshold | `0.7` | 이 유사도 미만 문서 제거. |
| `ai_voicebot.rag.reranking_enabled` | reranking_enabled | `false` | 재순위화 사용 여부. |

### 4.2 RAG 검색 흐름 (RAGEngine.search)

1. **입력**: `query`, `owner_filter`(착신번호), `call_id`, `top_k_override`(선택).
2. **쿼리 임베딩**: `query_embedding = await embedder.embed(query)`.
3. **Vector DB 검색**:  
   `vector_db.search(vector=query_embedding, top_k=effective_top_k * 2, filter={"owner": owner_filter})`.  
   - **effective_top_k**: `top_k_override`가 있으면 그 값, 없으면 `rag.top_k`(기본 3).  
   - **2배 검색**: 재순위화를 위해 2배 수만큼 가져온 뒤, 임계값 필터 후 상위 `effective_top_k`만 사용.
4. **유사도 필터**: `score >= similarity_threshold` 인 문서만 유지.
5. **재순위화**: `reranking_enabled`면 `_rerank(query, documents)` 호출(현재 기본 false).
6. **반환**: 상위 `effective_top_k`개 `Document(id, text, score, metadata)`.

### 4.3 Adaptive RAG (LangGraph)에서의 실제 사용 파라미터

- **노드**: `adaptive_rag_node`.
- **검색 호출**: `rag_engine.search(query, owner_filter=owner, call_id=call_id, top_k_override=SENTENCE_TOP_K)`.
  - **SENTENCE_TOP_K = 6** (문장 레벨 검색 수, 코드 상수).
- **추가 처리**:
  - Small-to-Big: 검색 결과의 `metadata.parent_text` 있으면 해당 문단으로 확장.
  - Contextual Compression: 질문 단어와 겹치는 문장 위주로 압축, **COMPRESSION_MAX_CHARS = 800** 제한.
- **Confidence**: 검색 결과 점수들의 평균에 1.1 곱한 뒤 min(1.0, 값). 이 confidence가 낮으면 step_back 노드로 분기.

### 4.4 질의/검색 결과 요약

| 단계 | 파라미터 | 값 | 결과에 미치는 영향 |
|------|----------|-----|---------------------|
| Vector 검색 요청 수 | top_k | 6 (adaptive_rag) | 최대 12건 검색(6*2) 후 임계값 필터. |
| 유사도 필터 | similarity_threshold | 0.7 | 0.7 미만 문서 제거. |
| 최종 문서 수 | effective_top_k | 6 | 상위 6건만 LLM 컨텍스트로 전달(압축 후). |
| 압축 후 최대 길이 | COMPRESSION_MAX_CHARS | 800 | 문맥 압축 후 총 문자 수 상한. |

---

## 5. LLM (Gemini) 질의/응답

### 5.1 LLM 설정 (config)

| 경로 | 키 | 기본값 | 설명 |
|------|-----|--------|------|
| `ai_voicebot.google_cloud.gemini.model` | model | `"gemini-2.5-flash"` | Gemini 모델명. |
| `ai_voicebot.google_cloud.gemini.api_key` | api_key | (필수) | Gemini API 키. |
| `ai_voicebot.google_cloud.gemini.temperature` | temperature | `0.5` | 생성 다양성 (0~1). |
| `ai_voicebot.google_cloud.gemini.max_output_tokens` | max_output_tokens | `1024` | 응답 최대 토큰 수. |
| `ai_voicebot.google_cloud.gemini.top_p` | top_p | (미지정 시 1.0) | nucleus sampling. |
| `ai_voicebot.google_cloud.gemini.top_k` | top_k | (미지정 시 1) | 토큰 후보 수. |

- **GenerationConfig**: `temperature`, `top_p`, `top_k`, `max_output_tokens` 로 `genai.types.GenerationConfig` 생성 후 `generate_content(prompt, generation_config=...)` 에 전달.

### 5.2 대화 응답 생성 시 프롬프트 조립 (generate_response_node → LLMClient.generate_response)

1. **시스템 프롬프트 (RESPONSE_SYSTEM_PROMPT)**  
   - 플레이스홀더: `{org_name}`, `{org_context}`, `{history}`, `{rag_context}`.  
   - `org_context`: 테넌트(착신번호) 기관 정보.  
   - `history`: 최근 6턴(12개 메시지) 형식 `"사용자: ... / AI: ..."`.  
   - `rag_context`: Adaptive RAG 결과를 `_format_rag_context(rag_results)` 로 `[1] ... \n [2] ...` 형태 문자열.

2. **최종 프롬프트 (LLMClient._build_conversation_prompt)**  
   - 구성: `system_prompt` + `**참고 정보:**` + context_docs 최대 3개 + `**이전 대화:**` (최근 10개 메시지) + `**현재 질문:** 사용자: {user_text} / AI:`.

3. **API 호출**  
   - `model.generate_content(prompt, generation_config=self.generation_config)`.  
   - 반환: `response.text` → 후처리(빈 응답/에러 문구/모르는 내용 문구 처리) 후 TTS로 전달.

### 5.3 질의/응답 결과에 영향을 주는 파라미터 요약

| 항목 | 파라미터 | 값 | 결과에 미치는 영향 |
|------|----------|-----|---------------------|
| 모델 | model | gemini-2.5-flash | 응답 속도·품질·비용. |
| 일관성 | temperature | 0.5 | 낮을수록 일관된 답변. |
| 응답 길이 상한 | max_output_tokens | 1024 | 이 토큰 수 초과 시 잘림. |
| RAG 맥락 양 | rag_results | 압축 후 최대 800자×문서 수 | 검색된 지식만 답변에 반영. |
| 대화 맥락 | history | 최근 6턴 | 이전 질문/답변 참고. |

---

## 6. 전체 질의→응답 파이프라인 (LangGraph)

1. **classify_intent**  
   - 사용자 질문 의도 분류 (farewell / greeting / question 등).  
   - farewell → update_state → 종료. greeting → generate_response(인사). 그 외 → check_cache.

2. **check_cache**  
   - `qa_cache`에서 `top_k=1`, 유사도 ≥ 0.92, TTL 내, 완결 문장이면 캐시 히트 → 응답으로 사용 후 update_state.

3. **rewrite_query**  
   - LLM으로 쿼리 보정(선택). `rewritten_query`가 상태에 설정됨.

4. **adaptive_rag**  
   - `rewritten_query` 또는 `user_query`로 RAG 검색 (top_k_override=6, owner_filter=착신번호).  
   - Small-to-Big → Contextual Compression(800자 제한).  
   - confidence 산출. 낮으면 step_back, 아니면 generate_response.

5. **step_back** (confidence 낮을 때)  
   - Step-back 쿼리 생성 후 다시 generate_response에서 RAG 컨텍스트 사용.

6. **generate_response**  
   - 시스템 프롬프트 + rag_context + history + user_query 로 프롬프트 조립 → `llm.generate_response(...)` → 응답 텍스트 반환.

7. **hitl_alert**  
   - confidence/needs_human 등에 따라 HITL 알림.

8. **update_cache**  
   - 캐시 미스였고, 응답이 완결/에러 아님일 때 `qa_cache`에 (query, response, metadata) 저장.

---

## 7. 설정 변경 시 예상 효과

| 목적 | 변경 위치 | 권장 값 | 효과 |
|------|-----------|---------|------|
| 검색 결과 더 많이 사용 | `rag.top_k` | 5~6 | LLM에 더 많은 지식 전달. |
| 검색 엄격하게 | `rag.similarity_threshold` | 0.75~0.8 | 낮은 유사도 문서 제외. |
| 캐시 히트 늘리기 | semantic_cache.py `SIMILARITY_THRESHOLD` | 0.90 | 더 넓은 유사 질문 캐시 히트. |
| 응답 길이 늘리기 | `gemini.max_output_tokens` | 1024~2048 | 긴 답변 잘림 완화. |
| 답변 더 일관되게 | `gemini.temperature` | 0.3~0.5 | 변동 감소. |

---

## 8. 참고 코드 위치

| 기능 | 파일 |
|------|------|
| ChromaDB 클라이언트·검색·거리→유사도 | `src/ai_voicebot/knowledge/chromadb_client.py` |
| tenant_config 조회·인사말/끝인사 템플릿 | `src/ai_voicebot/knowledge/organization_info.py` |
| 시드 데이터(tenant_config·지식·FAQ·인사말/끝인사 예시) | `src/services/seed_data.py` |
| RAG 검색·임계값·top_k | `src/ai_voicebot/ai_pipeline/rag_engine.py` |
| Adaptive RAG·Small-to-Big·압축 | `src/ai_voicebot/langgraph/nodes/adaptive_rag.py` |
| Semantic Cache 검색/저장 | `src/ai_voicebot/langgraph/nodes/semantic_cache.py` |
| Embedding | `src/ai_voicebot/knowledge/embedder.py` |
| LLM 설정·프롬프트·generate_response | `src/ai_voicebot/ai_pipeline/llm_client.py` |
| 응답 생성·시스템 프롬프트·rag_context 조립 | `src/ai_voicebot/langgraph/nodes/generate_response.py` |
| 설정 로드 (RAG/embedding/gemini) | `config/config.yaml` (ai_voicebot.*), `src/ai_voicebot/factory.py` |

---

**작성일**: 2026-02-22  
**버전**: config 및 코드 기준 (sip-pbx)
