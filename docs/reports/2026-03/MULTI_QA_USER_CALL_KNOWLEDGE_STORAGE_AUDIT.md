# 유저 간 통화 → 지식베이스: 복수 QA·지식 항목 저장 구조 점검

- **작성일**: 2026-03-23  
- **갱신**: 2026-03-23 — `doc_id` 예시·시맨틱 중복 점검(§8~§9) 보강; dedup 임계값 기본 완화 및 설정 키(§9.2)  
- **상태**: 코드 기준 점검 완료  
- **관련 코드**: `extraction_pipeline.py`, `qa_extractor.py`, `ai_pipeline/llm_client.py` (`judge_usefulness`), `knowledge_extractor.py`, `knowledge_service.py` (HITL)

---

## 1. 결론 요약

| 경로 | 복수 항목 구조 | 비고 |
|------|----------------|------|
| **파이프라인 v2 (`ExtractionPipeline`)** | **예** — QA·엔티티·서술형 지식 각각 리스트로 받아 **항목마다** 검증 후 **개별 upsert** | LLM·토큰·중복 제거·품질 게이트가 건수를 줄일 수 있음 |
| **레거시 `KnowledgeExtractor`** | **예** — `extracted_info`를 **인덱스 루프**로 처리, 청크마다 upsert | 동일하게 LLM 산출물 크기·품질에 의존 |
| **HITL `KnowledgeService.add_from_hitl`** | **아니오** — 호출 **1회 = 문서 1건** | 운영자가 여러 번 제출하면 여러 건 |

즉, **“말한 내용이 여러 개일 때 여러 개의 벡터 문서로 쌓일 수 있는 구조인가?”**에 대해 **코드 레벨에서는 예**이나, **실제 건수는 모델 출력·설정·후처리에 의해 제한**됩니다.

---

## 2. 파이프라인 v2: 복수 QA → 복수 저장

1. `QAPairExtractor.extract`는 **JSON 배열**을 파싱해 `List[Dict]`를 반환한다.  
2. `extraction_pipeline`에서 **`for qa in qa_pairs`** 로 각각 `ExtractionItem(doc_type="qa_pair", …)`를 쌓는다.  
3. Stage 3에서 **항목 단위**로 환각 검사·품질 게이트·(옵션) 시맨틱 중복 검사를 통과한 것만 `verified_items`에 남긴다.  
4. Stage 4에서 **`for idx, item in enumerate(verified_items)`** 로 `doc_id = f"{call_id}_{item.doc_type}_{idx}"` 형태로 **각각 `vector_db.upsert`** 한다.

→ **한 통화에서 N개의 QA가 추출되면, 구조상 최대 N개의 별도 문서로 저장 가능**하다 (필터링을 모두 통과할 때).

---

## 3. 서술형 지식 (`doc_type=knowledge`, `judge_usefulness`)

- `extracted_info`는 **배열**이며, 파이프라인에서는 **`for info in extracted_list`** 로 각 `text`가 10자 이상일 때 `ExtractionItem(doc_type="knowledge")`를 추가한다.  
- `LLMClient.judge_usefulness` 프롬프트에는 **명시적 상한**이 있다:  
  - **`extracted_info` 최대 5개**  
  - **각 `text` 200자 이내**  
- 또한 **`is_useful`이 true이고 `confidence`가 `min_confidence` 이상**일 때만 서술형 지식 항목이 `items`에 들어간다. (QA/엔티티는 이 판정 **이전**에 이미 `items`에 추가됨.)

---

## 4. “여러 말하기”가 한 건으로 합쳐질 수 있는 지점 (구조 손실 아님, 정책·모델)

1. **QA 추출 프롬프트** (`qa_extractor.py`):  
   - 규칙 4 — **“동일 토픽의 여러 교환은 하나의 QA로 합산”** → 의도적으로 QA **개수를 줄이는** 지시.  
2. **QA 생성 `max_output_tokens=800`** → QA가 많으면 JSON이 잘리거나 일부만 파싱될 위험.  
3. **시맨틱 중복 제거** (`enable_dedup`) → 유사한 Q/A가 기존 KB와 가깝면 **skip**될 수 있음.  
4. **환각 검사·품질 게이트** → 항목별 탈락.  
5. **전사 길이**: QA/엔티티 등은 `TRANSCRIPT_PROMPT_MAX_CHARS`(예: 10000자) 등으로 잘릴 수 있음; `judge_usefulness`는 별도 `judgment_max_input_chars`(기본 6000) 사용.

---

## 5. doc_id·재실행

- 같은 통화에 대해 파이프라인을 **다시** 돌리면 `doc_id`가 `call_id` + `doc_type` + **`verified_items` 내 순번**이라, **항목 수·순서가 바뀌면 기존 id와 충돌/덮어쓰기**가 발생할 수 있다. (구조적 멀티 QA 지원과는 별 이슈.)

---

## 6. HITL

- `add_from_hitl`은 **질문·답변 한 쌍**으로 **문서 1건**만 upsert한다.  
- 한 통화에서 **여러 지식**을 남기려면 운영자 측에서 **여러 번 제출**하거나, 자동 파이프라인 쪽 복수 추출에 의존해야 한다.

---

## 7. 요약 한 줄

**복수 QA·복수 서술형 지식을 “여러 문서”로 넣을 수 있도록 리스트·루프·개별 upsert가 갖춰져 있으나**, **서술형은 최대 5×200자**, **QA는 토픽 합산·출력 토큰·중복/품질 필터** 때문에 실제 저장 건수는 그보다 적을 수 있다.

---

## 8. “upsert”의 의미 — ID 기준 vs 내용(의미) 중복

리포트에서 말하는 **upsert**는 **“지식 내용이 이미 있으면 중복 insert를 하지 않는다”**와 **같은 개념이 아니다.**

| 구분 | 동작 | 이 코드베이스에서의 위치 |
|------|------|-------------------------|
| **Chroma `upsert`** | **`doc_id`(식별자)가 같으면** 해당 행을 **덮어쓰기(갱신)**, 없으면 **새로 넣기**. 문자열·의미 동일 여부는 보지 않음. | `_VectorDbWrapper.upsert` → `collection.upsert(ids=[doc_id], …)` |
| **시맨틱 중복 검사** | 임베딩으로 기존 KB와 **근접 검색** 후, 임계값 이상이면 저장 생략(`skip`) 등. (점수 정의·코사인 여부는 **§9** 참고) | `SemanticDeduplicator` (파이프라인 Stage 3, `enable_dedup` 시) |

### 8.1 `doc_id`가 무엇인지 — 예시

`doc_id`는 Chroma에서 **한 행(row)을 구분하는 문자열 키**이다. **통화 내용 해시**나 **질문 텍스트**가 아니라, **코드가 만든 규칙적 문자열**이다.

| 출처 | 형식(개념) | 예시 (가상) |
|------|------------|-------------|
| **파이프라인 v2** (`ExtractionPipeline` Stage 4) | `{call_id}_{doc_type}_{idx}` — `idx`는 **검증 통과 후** `verified_items`의 **0부터 순번** (타입이 섞여도 한 줄로 증가) | `sip-call-001_qa_pair_0`, `sip-call-001_entity_1`, `sip-call-001_knowledge_2` |
| **HITL** (`KnowledgeService.add_from_hitl`) | `hitl_` + 타임스탬프(µs 포함) | `hitl_20260323_153045_123456` |
| **API 지식 추가** (`add_knowledge`) | `kb_` + 타임스탬프 | `kb_20260323_153045_123456` |
| **greeting/farewell 캐시** (`immediate_cache_for_knowledge`) | `cache_kb_{category}_{owner}_{hash}` | `cache_kb_greeting_phase1_acme_1234567890` |

같은 통화에서 QA 2건이 모두 통과하면 `…_qa_pair_0`, `…_qa_pair_1`처럼 **서로 다른 `doc_id`**로 **두 행**이 생긴다. 반대로 **문장이 달라도** `doc_id`만 같으면 upsert 한 번에 **한 행으로 덮어쓴다**(§5).

정리하면:

- **같은 문서라도 `doc_id`가 다르면** Chroma 입장에서는 **별도 레코드**로 **둘 다 들어갈 수 있다.**
- **내용/의미 측면의 중복 완화**는 §4의 **`enable_dedup` + `SemanticDeduplicator`**(세부는 **§9**)이며, **upsert 호출 전**에 적용된다.
- 원문 §5에서 말한 **재실행 시 덮어쓰기**는 **ID 기준 upsert** 때문이다(같은 `call_id_…_idx`면 갱신).

---

## 9. 시맨틱(벡터) 중복 처리 점검 — 구현 여부와 “코사인” 표현

### 9.1 구현 여부: **되어 있음** (파이프라인 Stage 3)

- `extraction_pipeline.py`에서 `enable_dedup`이 켜져 있으면(설정 `quality.deduplication`, 코드 기본값 `True`) 항목마다 `SemanticDeduplicator.check`를 호출한다.
- 반환값 `action == "skip"`이면 해당 항목은 **`verified_items`에 넣지 않아** Stage 4 upsert가 **실행되지 않는다** → **의미상 중복으로 저장을 막는 경로가 존재**한다.
- 검색 범위: `owner` 메타가 일치하는 문서만 (`owner_filter=owner_id`).

### 9.2 임계값 (기본값·설정)

- **코드 기본값 (구어체 중복에 맞춘 완화안):** `duplicate_threshold = 0.82`, `near_duplicate_threshold = 0.74` (`semantic_deduplicator.py`의 `DEFAULT_*`).  
  - 이 이상이면 각각 `skip` / `merge_candidate` 판정(점수 정의는 §9.3과 동일: `1/(1+dist)`).
- **`knowledge_extraction.quality`에서 재정의 (선택):**  
  - `dedup_duplicate_threshold`  
  - `dedup_near_duplicate_threshold` (반드시 duplicate보다 작게; 잘못되면 코드가 자동으로 낮춤)
- **이전 기본(0.92 / 0.85)** 로 되돌리려면 위 두 키에 각각 `0.92`, `0.85`를 명시하면 된다.
- **주의:** 파이프라인은 **`skip`일 때만** 저장을 막는다. **`merge_candidate`는 그대로 저장**된다(병합 로직 없음).

### 9.3 “코사인 유사도 0.92”와 실제 동작의 차이 (점검 결과)

- `semantic_deduplicator.py` 주석·상수명은 **코사인**을 가정하지만, **`knowledge` 컬렉션**은 `chromadb_client.py`에서 `get_or_create_collection(..., metadata={"description": "call knowledge"})`만 쓰고 **`hnsw:space: cosine`을 지정하지 않는다.** Chroma 기본 거리는 보통 **L2** 계열이다. (`qa_cache` 컬렉션만 별도로 cosine 메타데이터를 준다.)
- 중복 검사 시 쓰는 `_VectorDbWrapper.search`는 Chroma가 준 **거리 `dist`**를 **`score = 1.0 / (1.0 + dist)`** 로 바꿔 `Document.score`에 넣는다. 이 값은 **항상 (0, 1]** 이라 `SemanticDeduplicator`에서는 **`score > 1.0` 분기를 타지 않고**, `similarity = score`로만 비교한다.
- 따라서 임계값은 “코사인 유사도”와 1:1 대응이라고 단정할 수 없고, “**`1/(1+dist)`가 설정값 이상**이면 skip”에 가깝다. 지표 해석 시 혼동을 피할 것.

### 9.4 별도 경로: 관리용 **진짜 코사인** 클러스터링

- `KnowledgeService` 쪽 일부 로직은 저장된 **임베딩 벡터끼리 `_cosine`을 직접 계산**해 클러스터링·메타 갱신을 한다. 이는 **파이프라인 Stage 3 dedup과 다른 API/운영 경로**이다.
