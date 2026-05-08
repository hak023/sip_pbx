# 지식 추출 Stage 3 품질 검증 및 로깅 설계
> **클러스터 안내**: 세부·히스토리 설계 문서입니다. 통합 관점·경계는 아래 대표 문서를 우선 참고하세요.
> 
> **대표 문서**: [`KNOWLEDGE_MANAGEMENT_DESIGN.md`](KNOWLEDGE_MANAGEMENT_DESIGN.md)
>
---


## 1. 환각(haluc) 로직 필요 여부

### 결론: **필요하되, 검증 방식 변경 필요**

| 항목 | 내용 |
|------|------|
| **필요성** | LLM이 통화 원문에 없는 내용을 지어낼 수 있으므로, **원문 기반 여부 검증은 유지**하는 것이 좋음. |
| **문제** | 기존처럼 **문자열 literal 포함**만 보면, 전사가 조각·비정규 형태일 때 정제된 문장이 전부 환각으로 잘못 스킵됨. |
| **방향** | **의미 기반 검증**(임베딩 유사도 또는 NLI)으로 바꾸고, **비교 대상은 전사를 문장 단위로 재구성한 텍스트**를 사용. |

즉, “환각 검사” 자체는 두고, **검사 방법만** 문자열 일치 → 의미 유사도(전사 재구성본과 비교)로 변경.

---

## 2. Stage 3 조정: 의미 기반 검증 + 전사 재구성

### 2.1 흐름

1. **전사 재구성**  
   - 입력: `"착신자: 오늘의\n발신자: 오늘의\n착신자: 날씨 는\n..."` 형태의 전체 전사.  
   - 착신자 라인만 추출해 공백 하나로 이어 붙임.  
   - (선택) 문장 경계 휴리스틱(마침표, 물음표 등)으로 쪼개어 **문장 단위 리스트** 생성.  
   - 재구성 결과를 **하나의 문자열** 또는 **문장 리스트**로 보관.

2. **의미 기반 검증**  
   - 각 추출 항목 `text`에 대해:  
     - (A) **임베딩 유사도**: 추출 text와 재구성된 전사(전체 또는 문장별)를 임베드한 뒤, **최대 유사도**가 `threshold_grounding` 이상이면 **verified**.  
     - (B) **NLI(선택)**: “전사 문장 → 추출 문장” entailment 점수가 임계값 이상이면 verified.  
   - verified된 항목만 Stage 4 저장 후보로 넘김.  
   - 스킵 시 사유: `skipped_halluc`(유사도/entailment 미달), `skipped_quality`(기타 품질), `skipped_dedup`(아래 3절).

3. **임계값**  
   - `threshold_grounding`: 예) 0.65 ~ 0.75 (임베딩 코사인 유사도).  
   - 너무 높으면 정제 문장이 전사와 형태가 다를 때 오탐(환각으로 잘못 스킵), 너무 낮으면 진짜 환각을 통과시킬 수 있음.

### 2.2 구현 시 주의

- 전사 재구성 시 **착신자만** 사용 (저장 대상이 착신자 발화이므로).  
- 임베딩은 **RAG/지식베이스와 동일한 임베더**를 쓰는 것이 좋음 (공간 일관성).

---

## 3. 지식베이스 중복 제외 (저장 전 dedup)

- **목적**: 이미 지식베이스에 있는 내용은 다시 저장하지 않음.  
- **시점**: Stage 3 통과 항목에 대해, **Stage 4 저장 직전**에 수행.  
- **방법**:  
  - (A) 저장 후보 문장을 임베드한 뒤, **동일 tenant(owner)의 기존 지식 벡터와 유사도** 계산.  
  - (B) `max_similarity >= threshold_dedup` (예: 0.90 ~ 0.95)이면 “이미 존재”로 간주하고 **저장 스킵** (`skipped_dedup`).  
- **로깅**: 항목별로 “저장함” / “중복으로 스킵함” 구분해 로그에 남김 (아래 4절).

---

## 4. 지식베이스 저장·RAG 상세 로그 스펙

아래 이벤트를 사용해 상세 로그를 남기면, 디버깅·분석 시 유리합니다.

### 4.1 Stage 3 품질 검증

| event | 시점 | 권장 필드 (예) |
|-------|------|------------------|
| `knowledge_stage3_start` | Stage 3 시작 | `call_id`, `item_count` |
| `knowledge_stage3_transcript_reconstructed` | 전사 재구성 완료 | `call_id`, `callee_text_length`, `sentence_count` (문장 수 쪼갠 경우) |
| `knowledge_stage3_verification_item` | 항목별 검증 | `call_id`, `index`, `text_preview`, `similarity_max`, `threshold_grounding`, `verified` |
| `knowledge_stage3_complete` | Stage 3 완료 | `call_id`, `verified`, `skipped_halluc`, `skipped_quality`, `skipped_dedup` |

### 4.2 지식베이스 저장 (Stage 4)

| event | 시점 | 권장 필드 (예) |
|-------|------|------------------|
| `knowledge_stage4_start` | Stage 4 시작 | `call_id`, `candidate_count`, `owner` |
| `knowledge_stage4_dedup_check` | 항목별 중복 검사 | `call_id`, `index`, `text_preview`, `max_similarity_existing`, `threshold_dedup`, `skip_reason` ("duplicate" \| null) |
| `knowledge_stage4_stored_item` | 항목 1건 저장 성공 | `call_id`, `owner`, `doc_id`, `text_preview`, `category` |
| `knowledge_stage4_skip_duplicate` | 중복으로 저장 스킵 | `call_id`, `index`, `text_preview` |
| `knowledge_stage4_complete` | Stage 4 완료 | `call_id`, `stored`, `skipped_dedup`, `failed` |

### 4.3 RAG 검색

| event | 시점 | 권장 필드 (예) |
|-------|------|------------------|
| `rag_search_start` | 검색 시작 | `call_id`, `query`, `owner_filter`, `top_k` |
| `rag_search_vector_done` | 벡터 검색 완료 | `call_id`, `results_count`, `owner_filter`, `elapsed_ms` |
| `rag_search_completed` | 검색 완료(기존 유지) | `call_id`, `query`, `owner_filter`, `results_count`, `doc_ids` (선택) |
| `rag_search_no_results` | 0건 시 | `call_id`, `query`, `owner_filter`, `reason` ("zero_results" 등) |
| `rag_search_error` | 예외 시 | `call_id`, `error`, `query`, `owner_filter` |

- `call_id`는 **항상 채워 두는 것** 권장 (step_back 등 보조 검색에서도 동일).

---

## 5. 구현 체크리스트

- [ ] Stage 3: 전사 파싱 → 착신자만 재구성(문장 단위 선택 가능).  
- [ ] Stage 3: 추출 항목별로 재구성 전사와 **임베딩 유사도** 계산, `threshold_grounding` 이상만 verified.  
- [ ] Stage 3: `skipped_halluc` / `skipped_quality` / `verified` 집계 후 `knowledge_stage3_*` 로그 출력.  
- [ ] Stage 4: 저장 전 **기존 KB와 유사도**로 중복 검사, `threshold_dedup` 이상이면 저장 스킵 + `knowledge_stage4_dedup_check` / `skip_duplicate` 로그.  
- [ ] Stage 4: 저장 성공 시 `knowledge_stage4_stored_item`, 완료 시 `stored`/`skipped_dedup`/`failed` 포함해 `knowledge_stage4_complete`.  
- [ ] RAG: 검색 시작/벡터 완료/완료/0건/에러 시 위 표의 이벤트 로그, **모든 경로에서 call_id 설정**.

이 설계를 반영한 검증 모듈: `knowledge_pipeline/stage3_verify.py`, `knowledge_pipeline/logging_events.py`.

### 5.1 통합 호출 예시

```python
from knowledge_pipeline import (
    reconstruct_callee_transcript,
    verify_extracted_items,
    filter_duplicates_for_save,
)
from knowledge_pipeline.logging_events import EVENT_STAGE4_STORED_ITEM

# Stage 2 출력: extracted_items, transcript_raw
callee_text, sentences = reconstruct_callee_transcript(transcript_raw, split_sentences=True)
verified_items, stage3_stats = verify_extracted_items(
    extracted_items,
    callee_text,
    embed_fn=your_embed_fn,
    threshold_grounding=0.70,
    call_id=call_id,
    log_fn=struct_logger,
    transcript_sentences=sentences,
)
to_store, dedup_stats = filter_duplicates_for_save(
    verified_items,
    similarity_to_existing_fn=lambda t: your_kb.max_similarity(owner, t),
    threshold_dedup=0.92,
    call_id=call_id,
    owner=owner,
    log_fn=struct_logger,
)
for item in to_store:
    doc_id = your_vector_store.add(owner, item["text"], item.get("category"), item.get("keywords"))
    struct_logger({"event": EVENT_STAGE4_STORED_ITEM, "call_id": call_id, "owner": owner, "doc_id": doc_id, "text_preview": item["text"][:80], "category": item.get("category")})
```
