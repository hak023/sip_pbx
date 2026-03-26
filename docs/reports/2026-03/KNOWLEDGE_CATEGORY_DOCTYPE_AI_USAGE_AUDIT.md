# 지식베이스 카테고리·문서 유형 — AI 응대 사용 여부 점검

- **작성일**: 2026-03-23  
- **갱신**: 2026-03-23 — §10 요약 비저장 정책·전사 10000자·검색 접두·메타 정렬 반영  
- **상태**: 코드 기준 점검  
- **관련**: `frontend/types/index.ts` (`KNOWLEDGE_CATEGORIES`, `DOC_TYPES`), `src/ai_voicebot/ai_pipeline/rag_engine.py`, `src/ai_voicebot/langgraph/agent.py`, `src/ai_voicebot/langgraph/nodes/generate_response.py`, `src/ai_voicebot/knowledge/contact_extractor.py`, `src/services/knowledge_service.py` (`add_from_hitl`), `src/websocket/server.py` (`submit_hitl_response`), `src/ai_voicebot/knowledge/knowledge_extractor.py`, `src/ai_voicebot/knowledge/extraction_pipeline.py`, `src/ai_voicebot/knowledge/extraction_category.py`

---

## 1. 프론트에서 선택 가능한 값

| 구분 | 값 |
|------|-----|
| **카테고리** | `question`, `greeting_phase1`, `greeting_phase2`, `farewell`, `chitchat`, `complaint`, `transfer`, `contact` |
| **문서 유형(doc_type)** | `knowledge`, `faq` |

---

## 2. RAG에서의 카테고리 사용 (`RAGEngine.INTENT_CATEGORY_MAP`)

`rag_engine.py` 기준:

| 분류된 intent | Chroma `category` 조건 |
|---------------|-------------------------|
| `greeting` | `greeting_phase1`, `greeting_phase2` 만 |
| `farewell` | `farewell` 만 |
| `question` | **없음** (owner만 → 테넌트 전체 지식 후보) |
| `unknown` | **없음** |
| `chitchat`, `nlu_fallback`, `out_of_scope` | **없음** (분류기 출력과 `INTENT_CATEGORY_MAP` 키 정합) |
| `complaint`, `transfer` | `question`, `complaint`, `transfer`, `chitchat`, `contact` |

`transfer` + 방문/길안내류 질의는 의도 완화로 category 제한이 풀릴 수 있음 (`looks_like_visit_or_direction_info_query`).

---

## 3. LangGraph 라우팅과의 관계 (`agent.py`)

- **`chitchat` / `nlu_fallback` / `out_of_scope`** → **`check_cache` → `rewrite_query` → `adaptive_rag` → `generate_response`** (question 계열과 동일).  
  - `chitchat`은 `generate_response`의 **`chitchat_rule`** 으로 여전히 짧은 응답을 유도하되, **RAG 컨텍스트는 주입될 수 있음**.
- **`nlu_fallback` / `out_of_scope`** 는 예전에는 `fallback_response` 단축 노드로 갔으나, **지식 검색 후 LLM** 경로로 통일됨 (§8 구현).

**연락처(`contact`)**  
- 일반 RAG: `complaint`/`transfer` 시 위 표의 `$in` 목록에 포함.  
- 호 전환 등: `ContactKnowledgeExtractor`가 **`category == "contact"`** 로 별도 검색 (`contact_extractor.py`).

---

## 4. 문서 유형 `doc_type` (`knowledge` vs `faq`)

- **기본**: `doc_type`으로 **필터하지 않음** (과거와 동일).
- **선택**: `config.yaml` 의 `ai_voicebot.rag.doc_type_allowlist`(문자열 배열 또는 쉼표 구분 문자열)를 두면 Chroma `where`에 **`doc_type` $in** 이 추가됨 (`factory.py` → `RAGEngine`).  
  - 예: FAQ·지식만: `doc_type_allowlist: [knowledge, faq]`  
  - **주의**: 메타에 `doc_type`이 없는 구문서는 allowlist 사용 시 **검색에서 제외**될 수 있음.

---

## 5. 결론 요약

| 항목 | AI 응대에서 “안 쓰인다”고 말할 수 있는가 |
|------|-------------------------------------------|
| **카테고리 전체** | **완전 미사용 카테고리는 없음.** `chitchat` 의도도 **RAG 경로를 탄다** (§3). |
| **`doc_type: faq` / `knowledge`** | 기본은 **구분 없이 검색**. `doc_type_allowlist` 설정 시 **목록에 있는 유형만** 후보. |

---

## 6. 권장 해석 (운영)

- 잡담 턴에도 **지식 주입**이 필요하면 현재 구조에서 **`chitchat` → RAG** 가 동작함 (프롬프트는 짧게 유지).
- FAQ만 검색하려면 **`ai_voicebot.rag.doc_type_allowlist: [faq]`** 등으로 제한 (메타 없는 구문서는 제외될 수 있음).

---

## 7. 통화에서 도출된 정보의 지식 저장 → RAG 후보 여부

**한 줄 요약**: 통화·HITL로 Chroma **knowledge 컬렉션**에 올라간 문서는, **`owner`가 이후 통화의 착신 테넌트와 일치**하고 **의도별 `category` 필터**를 통과하면 **일반 대시보드에서 등록한 지식과 동일하게 RAG 후보**가 된다. RAG는 **`source` / `extraction_source`로는 걸러지지 않는다**. `doc_type`은 **기본 미필터**, `doc_type_allowlist` 설정 시에만 `where`에 반영(§4).

### 7.1 적재 경로 개요

| 경로 | 트리거 | 저장 텍스트·메타(요지) | RAG에 들어가려면 |
|------|--------|------------------------|------------------|
| **HITL 저장** | 운영자가 `save_to_kb=True`로 제출 (`submit_hitl_response`) | `Q: …\nA: …` 한 덩어리, `doc_type=knowledge`, `source=hitl`, `category`=요청 값(미지정 시 **`question`**) | Chroma 메타 **`owner`**: 요청 `owner`/`tenant_id` 또는 세션 착신 URI(§7.4). |
| **통화 후 자동 추출 (레거시 `KnowledgeExtractor`)** | 통화 종료 후 `extract_from_call` (예: `call_manager.trigger_knowledge_extraction`) | 저장 전 **`normalize_extraction_category`** 로 표준화, 메타 **`doc_type=knowledge`**, `extraction_source: "call"` | `owner` 일치 + §2의 intent별 `category` 규칙 (비표준 라벨은 `question` 등으로 정규화). |
| **파이프라인 v2 `ExtractionPipeline`** | 설정에 따라 통화 후 멀티스텝 추출 | `normalize_extraction_category`로 **표준 카테고리 또는 `question`으로 정규화**, `doc_type`은 `knowledge` / `qa_pair` / `entity`, `extraction_source: "call"` | 동일하게 **RAG는 `doc_type` 미필터** → 후보에 포함. `owner`는 메타에 명시. |

### 7.2 저장 형식 예시

**예시 A — HITL에서 지식 저장**  
- 발신자 질문: “주차는 몇 시까지 되나요?”  
- 운영자 답: “밤 10시까지 무료입니다.”  
- 저장 문서(`documents`):  
  `Q: 주차는 몇 시까지 되나요?\nA: 밤 10시까지 무료입니다.`  
- 메타데이터(코드 기준, `add_from_hitl`):  
  `category`=(요청값; 미지정 시 **`question`**), `doc_type=knowledge`, `source=hitl`, `call_id`, `operator_id`, **`owner`**(요청 또는 세션 착신에서 해석)  
- **이후 RAG**: `intent=question`이면 **category 조건 없이** owner만 맞으면 검색 후보. `complaint`/`transfer`면 메타 `category`가 `question|complaint|transfer|chitchat|contact` 중 하나여야 필터를 통과.  
  - 참고: 클라이언트가 **`category`에 문자열 `faq`만 넣는 것**은 문서 유형 `faq`와 혼동되고, RAG `$in`에 **`faq`가 없어** 불만/전환 의도 검색에서 빠질 수 있다 → **표준 카테고리(`question` 등) 사용**.

**예시 B — 통화 추출 파이프라인 v2**  
- **`qa_pair`**: 임베딩용 `documents`는 코드상 **`Q: …\nA: …`** (예시 A와 동일 패턴).  
- **`knowledge`**(`judge_usefulness`의 `extracted_info`): 서술형 한 덩어리 예 — “영업시간은 평일 9시부터 6시까지입니다.”  
- 정규화 후 `category=question`(LLM 라벨이 `VALID_CATEGORIES`에 없을 때 기본값).  
- 메타: `owner=<착신자 ID>`, `doc_type=qa_pair|knowledge|entity`, `extraction_source=call`, `review_status` 등.  
- **이후 RAG**: 위와 동일. **`doc_type_allowlist` 미설정 시 `qa_pair`/`entity`도 검색 후보**.

**예시 C — 레거시 추출에서 LLM이 `category=기타` 를 준 경우**  
- 저장 시 **`normalize_extraction_category` → `question`** 등으로 바뀌므로, **complaint/transfer RAG `$in`에 포함될 수 있음** (구현 반영 후).

### 7.3 PII 검토 대기열

`KnowledgeExtractor`에서 `contains_pii`이고 PII 검토 큐가 켜져 있으면 **당장 VectorDB에 안 올라가고** 대기열만 적재될 수 있다. 이 경우 **승인·적재 전까지는 RAG 후보가 아님**.

### 7.4 운영 시 확인 포인트 (HITL·owner)

- **반영됨 (코드)**: `submit_hitl_response`에서 `owner`/`tenant_id`가 오면 그걸 쓰고, 없으면 **`CallManager.get_session(call_id).get_callee_uri()`** 를 `normalize_owner_username` 해서 `add_from_hitl(..., owner=...)`에 넘긴다. 여전히 세션이 없는 타이밍(통화 종료 직후 등)이면 `owner`가 비어 저장될 수 있으므로, 프론트에서 **`tenant_id`(로그인 내선)를 함께 보내는 것**을 권장한다.
- 로그: `hitl_kb_owner_resolved` / `hitl_kb_owner_unresolved` 로 추론 검증 가능.

---

## 8. 개선사항 정리 (구현 상태)

| # | 이슈 | 조치 요약 |
|---|------|-----------|
| 1 | HITL 저장 시 `owner` 누락 | **구현됨** — §7.4 (`server.py` + `add_from_hitl`). |
| 2 | HITL 기본 `category="faq"` | **구현됨** — 미지정 시 **`question`** (`server.py`). |
| 3 | `chitchat`에 RAG 없음 | **구현됨** — `agent.py`에서 **`check_cache` 경로** (`generate_response`의 chitchat_rule 유지). |
| 4 | `doc_type` RAG 제어 | **구현됨** — `ai_voicebot.rag.doc_type_allowlist` → `RAGEngine` Chroma `where` (`factory.py`, `rag_engine.py`). |
| 5 | 레거시 추출 비표준 `category` | **구현됨** — `KnowledgeExtractor`에서 **`normalize_extraction_category`** + 메타 **`doc_type=knowledge`**. |
| 6 | `unknown` vs `nlu_fallback` | **구현됨** — `INTENT_CATEGORY_MAP`에 **`chitchat`/`nlu_fallback`/`out_of_scope`**: None; **`nlu_fallback`·`out_of_scope`** 는 **`check_cache` 경로**로 변경 (`agent.py`). |
| 7 | HITL 이벤트에 `owner` 없음 | **구현됨** — `rag_processor.py` `emit_hitl_requested`의 **`context.owner`**. |
| 8 | 프론트 HITL `tenant_id` | **구현됨** — `dashboard/page.tsx`: **`tenant_id` + `category: question`** (owner 우선). |

---

## 9. 변경 이력 (문서·코드)

| 파일 경로 | 변경 유형 | 요약 | 비고 |
|-----------|------------|------|------|
| `sip-pbx/docs/reports/2026-03/KNOWLEDGE_CATEGORY_DOCTYPE_AI_USAGE_AUDIT.md` | 수정 | §2–§8 갱신, §8 전 항목 구현 반영 | — |
| `sip-pbx/src/ai_voicebot/ai_pipeline/rag_engine.py` | 수정 | `doc_type_allowlist`, `INTENT_CATEGORY_MAP` 확장, `where` 조립 방식 | trace 필드 추가 |
| `sip-pbx/src/ai_voicebot/factory.py` | 수정 | `rag.doc_type_allowlist` 파싱 후 `RAGEngine` 전달 | — |
| `sip-pbx/src/ai_voicebot/langgraph/agent.py` | 수정 | `chitchat`/`nlu_fallback`/`out_of_scope` → `check_cache`; 그래프에서 `fallback_response` 노드 제거 | 조건부 엣지 맵 정리 |
| `sip-pbx/src/ai_voicebot/langgraph/nodes/generate_response.py` | 수정 | `chitchat`일 때 `rag_search_trace` 비우기 제거 | — |
| `sip-pbx/src/ai_voicebot/knowledge/knowledge_extractor.py` | 수정 | `normalize_extraction_category`, `doc_type` 메타 | — |
| `sip-pbx/src/ai_voicebot/pipecat/processors/rag_processor.py` | 수정 | HITL `context.owner` + 로그 | — |
| `sip-pbx/frontend/app/dashboard/page.tsx` | 수정 | HITL `owner` 보관, `submit_hitl_response`에 `tenant_id`/`category` | — |
| `sip-pbx/src/websocket/server.py` | 수정 | (이전) HITL owner·category 기본값 | §7.4 |
| `sip-pbx/docs/reports/2026-03/KNOWLEDGE_CATEGORY_DOCTYPE_AI_USAGE_AUDIT.md` | 수정 | §10 저장·맥락·예시 A/B 정합 고찰 | — |
| `sip-pbx/docs/reports/2026-03/KNOWLEDGE_CATEGORY_DOCTYPE_AI_USAGE_AUDIT.md` | 수정 | §10 요약 비저장·10000자·접두·메타 정렬 | — |
| `sip-pbx/src/ai_voicebot/knowledge/prompt_limits.py` | 추가 | `TRANSCRIPT_PROMPT_MAX_CHARS=10000` | — |
| `sip-pbx/src/ai_voicebot/knowledge/rag_knowledge_text.py` | 추가 | 서술형 지식 검색 접두 | — |
| `sip-pbx/src/ai_voicebot/knowledge/extraction_pipeline.py` | 수정 | knowledge 접두·메타 `source`/`call_id`/`created_at` | — |
| `sip-pbx/src/ai_voicebot/knowledge/knowledge_extractor.py` | 수정 | 접두·메타 정렬 | — |
| `sip-pbx/src/ai_voicebot/knowledge/qa_extractor.py` 등 | 수정 | 전사 프롬프트 10000자 | summarizer, entity_extractor |
| `sip-pbx/src/services/knowledge_service.py` | 수정 | HITL 메타 `extraction_*` | — |
| `sip-pbx/src/ai_voicebot/knowledge/knowledge_service.py` | 수정 | API 적재 `extraction_*` | — |
| `sip-pbx/frontend/types/index.ts` | 수정 | `KnowledgeItem.metadata` 확장 | — |

---

## 10. 통화 추출·저장 형식 — 맥락 결손 RAG 고찰

### 10.1 질문/답이 전사에 명시적으로 없을 때 (유저 간 대화)

**파이프라인 v2 (`ExtractionPipeline`) 동작 요약 (코드 기준):**

| 경로 | 입력 맥락 | 산출·저장 | 명확한 Q/A 없을 때 |
|------|-----------|-----------|---------------------|
| **`judge_usefulness`** | **`full_transcript`** (발신+착신)로 맥락 판단, 저장 후보는 설계상 착신 중심 | `doc_type=knowledge`, **`documents` = `고객이 알 수 있어야 할 정보: ` + 서술형 문장** | **가능**: 질문 형태가 없어도 선언적 지식으로 검색. |
| **`QAPairExtractor`** | 전사 앞 **`TRANSCRIPT_PROMPT_MAX_CHARS`(10000자)** 만 프롬프트에 사용 (`prompt_limits.py`) | `doc_type=qa_pair`, 임베딩 텍스트는 **`Q: …\nA: …`** (HITL과 동일 패턴) | **암묵적 질문** 규칙이 프롬프트에 있으나, **추출 실패 시 빈 배열** → 해당 턴은 QA 청크 없음. |
| **`ConversationSummarizer`** | 동일 **10000자** 상한 | **`result.summary` 등 파이프라인 결과만** — **지식베이스(Chroma)에는 넣지 않음** (정책: 통화량·관리 부담 방지) | 내부/로그용 맥락. RAG 검색 문서로 쓰지 않음. |
| **`EntityExtractor`** | 전사 **10000자** 상한 | 짧은 **`entity_type: value (context)`** 형태 | 사실 단편·연락처류 보완. |

**정리**: “정확한 질문/답 문자열이 전사에 없다”는 것만으로 **지식 적재가 불가능한 것은 아님**. **서술형 `knowledge` 청크**(검색용 접두 규약 적용, §10.3)에 의존하며, **요약은 의도적으로 KB에 넣지 않음**. 전사 프롬프트 상한은 **10000자**(슬라이딩 윈도는 미적용).

### 10.2 예시 A(HITL) vs 예시 B(파이프라인) — “다른 방식”의 실체

- **예시 A (`add_from_hitl`)**: 한 덩어리 **`Q: …\nA: …`** + 메타.
- **예시 B**를 한 가지로 단정하면 안 됨:
  - **`qa_pair` 항목**은 코드상 이미 **`Q: …\nA: …`** 로 저장됨 (`extraction_pipeline.py` 246–247행 부근). → **예시 A와 임베딩 패턴이 동일**.
  - **`knowledge` 항목**(`judge`의 `extracted_info`)은 **서술형 단문**에 **`고객이 알 수 있어야 할 정보: ` 접두**를 붙여 저장됨 (`rag_knowledge_text.py`). → 문서의 “예시 B” 서술형은 이 케이스.

즉 **“A와 B가 완전히 다른 포맷”이 아니라, B 안에 Q/A 포맷(`qa_pair`)과 서술 포맷(`knowledge`)이 공존**한다.

### 10.3 검색·저장 정책 (반영 상태)

- **벡터 RAG**: `qa_pair`·HITL은 **`Q:\nA:`**; 서술형 **`knowledge`** 는 **`고객이 알 수 있어야 할 정보: `** 접두로 임베딩·저장 (`apply_rag_knowledge_prefix`) — 파이프라인 v2 `judge` 산출·레거시 `KnowledgeExtractor` 청크에 적용.
- **요약(`ConversationSummarizer`)**: **지식베이스에 upsert 하지 않음** — 통화 건수가 많을 때 KB 혼잡·운영자 관리 부담을 피하기 위한 **제품 정책**. (내부 파이프라인 결과·로그용으로만 사용.)
- **메타 스키마 정렬 (구현)**: Chroma 메타에 공통으로 **`source`**, **`call_id`**, **`created_at`**, **`category`**, **`doc_type`** 및 하위 호환용 **`extraction_source`**, **`extraction_call_id`**, **`extraction_timestamp`** — HITL(`add_from_hitl`), 통화추출 파이프라인, 대시 API(`ai_voicebot.knowledge_service.add_knowledge`)에 반영. 프론트 `KnowledgeItem.metadata` 타입 확장.
- **전사 LLM 입력 상한**: QA·요약·엔티티 추출 프롬프트는 **`TRANSCRIPT_PROMPT_MAX_CHARS = 10000`** (`prompt_limits.py`). 슬라이딩 윈도·병합은 **미적용**.

**결론**: 전 문서를 `Q:\nA:`로 강제할 필요는 없음. **서술형은 접두 규약**, **요약은 KB 비적재**, **메타 키 통일**, **전사 10000자**로 정리한다.

