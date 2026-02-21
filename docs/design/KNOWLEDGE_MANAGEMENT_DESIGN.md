# 지식 관리 로직 설계서 (Knowledge Management Design)

**목적**: 통화·HITL에서 나온 정보를 지식 DB로 정제·저장·검색하는 전 과정을 현재 로직 기준으로 정리하고, 개선 방향을 명시한다.

**용어 정책 (이 설계서부터 적용)**  
- ❌ "LLM이 유용성을 **판단**한다"  
- ✅ "통화정보 중 **지식정보를 정제**한다" (추출·분류·저장 후보 결정)

---

## 1. 개요

### 1.1 지식 관리 흐름 요약

| 구분 | 입력 | 처리 | 출력 |
|------|------|------|------|
| **일반 통화** | 착신자(callee) 발화 전사 | 지식 정제(LLM) → 카테고리·복수 항목 → 중복 검사 → 저장 | VectorDB (owner=착신자) |
| **HITL** | 운영자 입력 Q&A | (현재: 무정제 저장) → **설계: LLM 정제 후** 저장 | VectorDB (owner=착신자) |
| **Frontend** | 수동 입력/수정/삭제 | Knowledge API (owner 필터) | 동일 스키마 |

**설계 요구사항 (1.1 관련)**  
- **저장 후보**: 착신자(callee) 발화만 지식 후보로 사용.  
- **LLM 맥락**: 발신자(caller) 통화 내용도 LLM에 함께 넣어 **맥락 파악**이 되도록 해야 함.  
- **긴 통화**: 통화가 길어질 수 있으므로 **토큰/길이 제한** 처리 필요.

### 1.1a 점검: 맥락(발신자 포함) 및 토큰/길이 처리

| 항목 | 현재 구현 | 점검 결과 |
|------|-----------|-----------|
| **LLM에 발신자 맥락 포함** | v1: 화자 필터 후 **착신자 텍스트만** `judge_usefulness(transcript=speaker_text)` 로 전달. v2: 동일하게 필터된(착신자만) transcript 전달. | ❌ **미반영** — LLM은 착신자 발화만 받음. 발신자 질문/맥락 없음. |
| **토큰/길이 처리** | `llm_client.judge_usefulness` 프롬프트에 `transcript[:2000]` **고정 2000자**만 사용. summarizer, qa_extractor, entity_extractor, hallucination_checker도 모두 `transcript[:2000]` 또는 `original[:2000]` 사용. | ⚠️ **부분만 반영** — 문자 2000자로 잘라서 사용. 토큰 단위 제한·슬라이딩 윈도우·요약 후 병합 등 없음. 긴 통화는 **앞 2000자만** LLM에 들어감. |

**결론**  
1. **맥락**: “저장 후보는 착신자만”이지만, **LLM에는 전체 대화(발신자+착신자)** 를 넣어 맥락을 주고, 추출/분류 시 “착신자 발화 중 저장할 것”만 `extracted_info` 로 내도록 변경이 필요함.  
2. **길이**: 2000자 고정 절단 대신, **토큰 상한**(또는 문자 상한 설정 가능)·**슬라이딩 윈도우**·**요약 후 정제** 등 중 한 가지 이상 도입이 필요함.

### 1.2 설계 원칙

- **착신자 중심**: 사용자 간 통화에서는 **착신자(callee)** 발화만 지식 후보로 사용 (현재 구현과 동일).
- **정제 우선**: "판단"이 아니라 **통화/입력 텍스트에서 지식으로 쓸 부분을 정제(추출·분류)** 하는 역할로 LLM 사용.
- **자동 저장**: 사용자 동의 절차 없이, 정제 결과가 기준을 만족하면 자동 저장 (기존 동작 유지).
- **계정별 격리**: 모든 저장·조회는 **owner(착신번호/테넌트 ID)** 기준으로 격리.

---

## 2. 사용자 간 통화 → 지식 정제 (현재 로직 기준)

### 2.1 트리거 조건

- **일반 SIP 통화**(사람–사람)가 종료된 경우에만 실행.
- AI 보이스봇 응대 통화는 지식 추출 대상에서 제외 (이미 구현됨: `is_ai_call` 시 스킵).

### 2.2 입력

| 항목 | 설명 |
|------|------|
| `transcript_path` | 전사 파일 경로 (예: `./recordings/{dir}/transcript.txt`) |
| `owner_id` | 착신자 ID (통화의 callee, 지식 소유자) |
| `speaker` | **"callee"** 고정 — 착신자 발화만 사용 |

전사 형식: `발신자: ...`, `착신자: ...` 라인 구분.  
현재: `_filter_by_speaker(transcript, "callee")` 로 **착신자 라인만** 추출한 뒤 그 문자열만 LLM에 전달함 (발신자 맥락 없음).

### 2.2a LLM 입력: 맥락(발신자 포함) 및 토큰/길이 (설계 요구사항)

- **맥락**  
  - **LLM에는 전체 전사(발신자+착신자)** 를 넘겨서, “무슨 질문에 대한 답인지” 맥락을 알 수 있게 한다.  
  - **저장 후보**는 “착신자 발화에서 나온 부분만”으로 한정 (프롬프트에 “착신자 발화 중 지식으로 저장할 부분만 extracted_info에 넣어라” 명시).  
  - 즉, 입력은 **전체 transcript**, 출력 `extracted_info[].text` 는 **착신자 원문만** 사용.

- **토큰/길이**  
  - 통화가 길면 **토큰(또는 문자) 상한**을 두고 처리해야 함.  
  - 옵션 예:  
    1. **상한만**: 전체 transcript를 설정 가능한 문자/토큰 상한으로 자르고 (예: 4000자 또는 1024 토큰), 한 번에 LLM 호출.  
    2. **슬라이딩 윈도우**: 상한 단위로 잘라 여러 구간에 대해 정제 호출 후 결과 병합·중복 제거.  
    3. **요약 후 정제**: 긴 통화는 먼저 요약(또는 토픽별 청킹)한 뒤, 구간별로 정제 호출.  
  - 현재처럼 **앞 2000자만** 쓰는 방식은 긴 통화에서 뒷부분이 무시되므로, 위 옵션 중 하나로 대체하는 것을 권장.

### 2.3 지식 정제(LLM) — 프롬프트 점검

현재 `llm_client.judge_usefulness()` 가 수행하는 역할을 **"통화정보 중 지식정보 정제"** 로 해석한다.

**기준 문서**: `docs/reports/USEFULNESS_JUDGMENT_DESIGN.md`, `USEFULNESS_PROMPT_RECOMMENDATIONS.md`

- **저장할 것**: 실행 가능한 Q&A, FAQ 성격 대화, 이슈 해결 내용, 약속·일정·연락처·업무 지시·선호도 (PII는 별도 정책).
- **저장하지 말 것**: PII만 있는 경우, 인사/맞장구만, 미해결·유보만, 원문에 없는 환각.

**현재 프롬프트 반영 여부**  
- `llm_client.py` 의 `judge_usefulness` 프롬프트는 위 설계와 대체로 일치함 (유용/비유용 기준, category 규칙, `extracted_info` 형식, 원문만 사용 지침).
- **점검 권장**:  
  - "당신은 통화 기록을 분석하여 지식 베이스에 **저장할 가치가 있는지 판단**" → "통화 기록에서 **저장할 지식 정보를 정제(추출·분류)**" 로 문구 정리 시 용어 정책과 일치.
  - `reason` 50자 이내, `extracted_info[].text` 는 원문만 사용 등은 유지.

### 2.4 LLM 출력 스키마 (정제 결과)

한 통화에서 **여러 개의 지식 항목**이 나올 수 있음.

```json
{
  "is_useful": true,
  "confidence": 0.85,
  "reason": "판단 이유 (50자 이내)",
  "extracted_info": [
    {
      "text": "원문에 나온 문장 또는 한 단위로 정리한 텍스트",
      "category": "FAQ|이슈해결|약속|정보|지시|선호도|기타",
      "keywords": ["키워드1", "키워드2"],
      "contains_pii": false
    }
  ]
}
```

| 필드 | 의미 |
|------|------|
| `is_useful` | 이 통화에서 저장할 지식이 있으면 true |
| `confidence` | 정제 신뢰도 (min_confidence 미만 시 저장 스킵) |
| `extracted_info` | **복수 가능** — 저장할 지식 단위별 text, category, keywords, contains_pii |

**카테고리**  
- FAQ, 이슈해결, 약속, 정보, 지시, 선호도, 기타 (프롬프트에 동일하게 명시됨).

---

## 3. 저장 정책 (자동 저장, 카테고리·중복)

### 3.1 자동 저장

- 사용자 동의 절차 없이, 정제 결과가 다음을 만족하면 **자동**으로 VectorDB에 저장:
  - `is_useful == true`
  - `confidence >= min_confidence` (설정값, 예: 0.7)
  - (v2 파이프라인) 환각 검사·품질 게이트·중복 검사 통과

### 3.2 카테고리

- LLM이 내려준 `extracted_info[].category` 를 그대로 메타데이터에 저장.
- RAG/검색 시 `category` 필터 사용 가능 (API·VectorDB where 조건).

### 3.3 중복 처리

- **v1 (KnowledgeExtractor)**: 중복 전용 단계 없음. 동일 통화에서 나온 복수 항목만 저장.
- **v2 (ExtractionPipeline)**:  
  - `SemanticDeduplicator` 로 기존 VectorDB와 유사도 비교.  
  - 유사도 높으면 `skip` 또는 `merge` 정책에 따라 저장 생략 가능.  
- **개선 권장**: v1 경로에서도 (선택) 임베딩 유사도 기반 중복 검사 도입 검토.

### 3.4 PII

- `contains_pii == true` 인 항목은 (설정 시) **검토 대기열**에만 넣고 VectorDB에는 넣지 않는 파이프라인 지원됨 (§7).

---

## 4. Frontend · Knowledge API

### 4.1 계정(owner)별 지식 관리

- **owner** = 착신번호(테넌트 ID). 모든 지식 항목 메타데이터에 `owner` 저장.
- **API**  
  - `GET /api/knowledge/` : `owner`, `category`, `search` 쿼리 지원.  
  - `search` 있으면 벡터 검색 후 **메타데이터로 owner 필터** (클라이언트 측 필터).  
  - `search` 없으면 `get_all_knowledge` 후 **동일하게 owner 필터**.
- **Frontend**: 로그인 계정에 해당하는 `owner` 로 요청해, **자신의 지식만** 조회·추가·수정·삭제.

### 4.2 CRUD

| 동작 | API | 비고 |
|------|-----|------|
| 목록/검색 | `GET /api/knowledge/?owner=...&category=...&search=...` | owner 필수 권장 |
| 단건 조회 | `GET /api/knowledge/{id}` | - |
| 수동 추가 | `POST /api/knowledge/` + body, `owner` 쿼리 | metadata.source=manual |
| 수정 | `PUT /api/knowledge/{id}` + body, `owner` 쿼리 | 삭제 후 재생성 방식 |
| 삭제 | `DELETE /api/knowledge/{id}` | - |

### 4.3 서비스 레이어 개선 권장

- `get_all_knowledge(category, limit)` 에 **owner** 인자를 추가하고, ChromaDB `where` 에 `{"owner": owner}` 를 넣어 **DB 레벨에서** 필터링하면 성능·일관성에 유리함.
- `search_knowledge(query, top_k, category)` 에 **owner** 인자 추가 후, VectorDB 검색 시 `where` 에 owner 포함 권장.

---

## 5. RAG 활용을 위한 스키마 설계

### 5.1 공통 메타데이터 (지식 항목)

| 필드 | 용도 |
|------|------|
| `owner` | 테넌트/계정 격리, RAG 검색 시 owner 필터 |
| `category` | FAQ/이슈해결/약속/정보/지시/선호도/기타 — 필터·통계 |
| `keywords` | 검색·필터 보조 (문자열 또는 리스트 저장 방식은 DB에 맞게) |
| `extraction_source` | "call" \| "hitl" \| "manual" |
| `extraction_call_id` | 통화 기원 시 call_id (선택) |
| `source` | "manual" \| "hitl" 등 (API 수동 추가 시) |
| `created_at` | 생성 시각 |

### 5.2 RAG 검색 시 사용

- **검색**: 쿼리 임베딩 + `where: { "owner": owner_id }` (필수).  
  필요 시 `category` 도 where에 추가.
- **정렬**: 유사도 점수 순. 필요 시 `created_at` 등으로 2차 정렬.

### 5.3 v2 파이프라인 확장 메타데이터

- `doc_type`: "knowledge" | "qa_pair" | "entity"
- `confidence_score`, `hallucination_check`, `dedup_status`, `review_status` 등 품질/리뷰용 필드 (설계서 3·4와 병행 사용).

---

## 6. HITL → 지식 DB 저장

### 6.1 현재 동작

- 운영자가 HITL 응답을 제출할 때 `save_to_kb=True` 이면 `KnowledgeService.add_from_hitl(question, answer, call_id, operator_id, category, owner_id)` 호출.
- **현재**: 질문+답변을 `"Q: ...\nA: ..."` 형태로 그대로 임베딩·저장. **LLM 정제 없음.**

### 6.2 설계 방향 (HITL도 지식 정제 후 저장)

- HITL 원문(운영자 입력)을 **LLM으로 한 번 정제**한 뒤 저장:
  - 저장할 문장 단위로 정리 (한 문장 또는 Q&A 한 쌍).
  - **카테고리·키워드** 부여 (기존 category Enum 동일).
  - 필요 시 **중복 검사** (기존 VectorDB와 유사도 비교 후 저장/스킵).
- 구현 시 권장:
  - `add_from_hitl` 내부에서 (또는 전용 함수에서) `llm_client` 의 정제용 메서드 호출 (예: `refine_knowledge_from_text(raw_text)` 형태).
  - 정제 결과 `extracted_info` 1건 이상을 기존 지식 저장 로직과 동일한 메타데이터(owner, category, extraction_source="hitl")로 저장.

---

## 7. 용어 및 로직 변경 (판단 → 지식 정제)

### 7.1 용어 변경

| 기존 | 변경 후 |
|------|---------|
| 유용성 **판단** (judge usefulness) | 통화정보 중 **지식정보 정제** (refine / extract knowledge) |
| "LLM이 유용하다고 판단" | "LLM이 통화/입력에서 지식으로 쓸 정보를 정제(추출·분류)" |

### 7.2 코드/주석 변경 권장

- **이름 유지 + 역할 재정의** (하위 호환):  
  - `judge_usefulness()` 메서드명은 그대로 두고, docstring과 로그 메시지를 **"통화 내용에서 지식 정보를 정제(추출·분류)"** 로 바꾼다.
- **또는 별도 메서드 추가**:  
  - `refine_knowledge_from_transcript()` (또는 `extract_knowledge_from_transcript()`) 를 두고, 내부에서 기존 `judge_usefulness` 로직을 호출. 대외 문서·API 설명에는 새 이름만 사용.
- **KnowledgeExtractor / ExtractionPipeline**  
  - 로그·주석에서 "유용성 판단" → "지식 정제", "judgment" → "정제 결과(refinement result)" 등으로 통일.

### 7.3 문서

- `USEFULNESS_JUDGMENT_DESIGN.md` 등 기존 문서는 **설계 기준**으로 유지하되, "판단" 대신 "정제" 용어를 쓰는 개정판 또는 본 설계서를 상위 참조로 두는 것을 권장.

---

## 8. 요약 체크리스트

| # | 항목 | 현재 상태 | 비고 |
|---|------|-----------|------|
| 1 | 사용자 간 통화 → 착신자 발화만 지식 후보 | ✅ speaker="callee" | 유지 |
| 1a | LLM에 **발신자+착신자 전체** 맥락 전달 | ✅ 반영 | v1/v2 모두 전체 전사 전달, 프롬프트에 "착신자 발화만 저장" 명시 |
| 1b | 긴 통화 **토큰/길이** 처리 | ✅ 반영 | judgment_max_input_chars(기본 6000)로 설정 가능, config.yaml·sip_endpoint 전달 |
| 2 | 프롬프트가 USEFULNESS 설계와 일치 | ✅ 대체로 일치 | 문구만 "정제"로 정리 권장 |
| 3 | LLM 복수 항목 + 카테고리 응답 | ✅ extracted_info[] | 유지 |
| 4 | 자동 저장, 카테고리·중복 반영 | ✅ (v2에서 중복) | v1 중복 검사 선택 도입 권장 |
| 5 | Frontend Knowledge API, owner별 관리 | ✅ owner 쿼리/필터 | 서비스에 owner 조건 전달 권장 |
| 6 | HITL도 LLM 정제 후 저장 | ❌ 미구현 | 설계 반영 필요 |
| 7 | 용어: 판단 → 지식 정제 | ✅ 반영됨 | docstring·로그 정리 완료 |

---

## 9. 참조 문서

- `docs/reports/USEFULNESS_JUDGMENT_DESIGN.md` — 정제(판단) 입출력·카테고리·기준
- `docs/reports/USEFULNESS_PROMPT_RECOMMENDATIONS.md` — 프롬프트 권장사항
- `src/ai_voicebot/knowledge/knowledge_extractor.py` — v1 추출
- `src/ai_voicebot/knowledge/extraction_pipeline.py` — v2 파이프라인
- `src/ai_voicebot/ai_pipeline/llm_client.py` — judge_usefulness (정제 로직)
- `src/services/knowledge_service.py` — add_knowledge, add_from_hitl, search, get_all
- `src/api/routers/knowledge.py` — Knowledge API
