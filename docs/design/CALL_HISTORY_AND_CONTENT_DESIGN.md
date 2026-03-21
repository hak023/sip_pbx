# 통화 이력 API 및 통화내용·상세정보 설계

## 1. 개요

- **통화 이력**: 과거 통화 목록을 조회하는 API. 각 항목에 **통화내용**(요약/대화 요약)과 **상세정보**(디버깅 수준)가 포함되어야 함.
- **통화내용이 제대로 표시되지 않는 원인**: (1) API 응답에 `content`/`summary` 필드가 없거나, (2) 해당 필드가 채워지는 파이프라인이 없거나, (3) 프론트에서 필드명 불일치.

---

## 2. API 응답 형식 (권장)

### 2.1 통화 이력 목록 (GET /api/call-history 또는 /api/calls/history)

| 필드 | 타입 | 설명 |
|------|------|------|
| `call_id` | string | 통화 ID |
| `caller` | string | 발신 (extension/URI) |
| `callee` | string | 착신 (extension/URI) |
| `started_at` | string (ISO 8601) | 통화 시작 시각 |
| `ended_at` | string (ISO 8601) | 통화 종료 시각 |
| `duration_seconds` | number | 통화 시간(초) |
| `is_ai_handled` | boolean | AI 응대 여부 |
| **`content`** | **string** | **통화내용 (요약 또는 대화 요약). 프론트 표시용.** |
| **`detail`** | **object** | **상세정보 (디버깅 수준). 아래 §2.2, §2.3 참고.** |

### 2.2 사람 간 통화일 때 `detail` (통화 후 LLM → ChromaDB 저장)

통화가 **사람 간 통화**(AI 미응대)로 종료된 경우, 설계상 **통화 종료 후** 다음 파이프라인이 수행된다고 가정한다.

| 단계 | 설명 | 로그/상세에 남겨야 할 내용 (디버깅 레벨) |
|------|------|------------------------------------------|
| 1. 녹음/전사 | 통화 녹음 또는 STT 결과 수집 | `recording_id`, `transcript_raw`(또는 경로), `duration_sec` |
| 2. LLM 요약 | 전사본을 LLM에 넣어 통화 요약·핵심 문장 추출 | **LLM 입력**: 프롬프트 + 전사본(앞뒤 자르기). **LLM 출력**: 요약 문장, 추출된 QA 쌍(질의/응답). **모델명, 토큰 수, 지연(ms)**. |
| 3. ChromaDB 저장 | 요약 또는 추출된 지식을 `knowledge` 컬렉션에 저장 | **저장 대상**: `text`, `category`, `owner`, `call_id`. **ChromaDB**: 컬렉션명, `doc_id`, 임베딩 차원, 저장 성공/실패. **실패 시**: 에러 메시지. |

**detail 구조 예시 (사람 간 통화)**:

```json
{
  "call_type": "human",
  "summary_pipeline": {
    "steps": [
      {
        "step": "transcript",
        "recording_id": "...",
        "transcript_preview": "발신: ... 수신: ...",
        "duration_sec": 120
      },
      {
        "step": "llm_summary",
        "request": {
          "model": "...",
          "prompt_preview": "다음 통화 전사본을 요약하고...",
          "input_text_len": 3000
        },
        "response": {
          "summary": "고객이 날씨 예보 문의 후 담당자 연결 요청.",
          "extracted_qa": [{"q": "...", "a": "..."}],
          "elapsed_ms": 1200,
          "tokens_used": 500
        }
      },
      {
        "step": "chromadb_store",
        "collection": "knowledge",
        "owner": "1004",
        "doc_ids": ["call_xxx_1", "call_xxx_2"],
        "success": true,
        "error": null
      }
    ]
  }
}
```

이 파이프라인이 **아직 구현되지 않은 경우**: `detail.call_type = "human"`, `detail.summary_pipeline = null` 또는 `detail.summary_pipeline.steps = []`로 두고, 추후 단계별 로그를 `call_data_record`에 남기면 통화 이력 API가 이를 읽어 `detail`을 채운다.

### 2.3 AI 응대일 때 `detail` (LLM·RAG·ChromaDB 상세)

AI가 응대한 통화는 **매 턴**에서 다음 정보가 쌓인다.

| 구분 | 기록 내용 (디버깅 레벨) |
|------|-------------------------|
| **STT** | `stt_final` 이벤트: 사용자 발화 원문, `seq`, `text_len`. |
| **Query Rewrite** | rewrite 스킵 여부, 원문/변환 쿼리. (이미 `query_rewrite_skip_candidate` 또는 rewrite 결과 로그 있음.) |
| **시맨틱 캐시** | 캐시 조회 여부, 히트/미스, 유사도 점수, TTL. |
| **RAG (ChromaDB 검색)** | 검색 쿼리, `owner_filter`, `result_count`, 검색 소요 시간, (선택) 상위 1~2건 문서 요약. |
| **LLM** | 의도 분류: `intent`, `confidence`. 응답 생성: `user_text`, `response`(전문), `context_docs_count`, `cache_hit`, `agent_elapsed`. |
| **TTS** | 재생 텍스트, (선택) 첫 오디오 시각. |

**detail 구조 예시 (AI 응대)**:

```json
{
  "call_type": "ai",
  "turns": [
    {
      "seq": 1,
      "stt": { "text": "오늘의 날씨가 궁금합니다.", "ts": "..." },
      "rewrite": { "skipped": true, "query_used": "오늘의 날씨가 궁금합니다." },
      "cache": { "checked": true, "hit": false },
      "rag": {
        "query": "오늘의 날씨를 검색합니다.",
        "owner_filter": "1004",
        "result_count": 3,
        "search_elapsed_sec": 0.049,
        "top_doc_preview": "오늘 날씨 예보는..."
      },
      "llm": {
        "intent": "question",
        "confidence": 0.83,
        "user_text": "오늘의 날씨가 궁금합니다.",
        "response": "오늘의 날씨 예보는...",
        "context_docs_count": 3,
        "cache_hit": false,
        "agent_elapsed_sec": 19.7
      }
    }
  ]
}
```

---

## 3. 데이터 소스

- **1차**: `logs/call_data_record_YYYYMMDD.log` (JSON Lines).  
  - 이미 `call_id`, `category`, `event`, `ts` 및 턴별 `rag_search_done`, `llm_exchange` 등이 기록됨.  
  - 통화 이력 API는 **여러 날짜 로그 파일**을 읽어 `call_id`별로 집계하고, 위 §2의 `content`·`detail`을 생성.
- **2차 (선택)**: CDR DB나 별도 테이블에 `call_id`, `content`, `detail`(JSON)을 저장해 두고 API는 DB만 조회.  
  - 장점: 조회 빠름.  
  - 단점: 통화 종료 시점에 `content`/`detail`을 채우는 워크플로가 필요.

---

## 4. 통화내용(`content`) 생성 규칙

| 통화 유형 | 통화내용 생성 방법 |
|-----------|---------------------|
| **AI 응대** | `call_data_record`에서 해당 `call_id`의 `llm_exchange` 이벤트를 시간순으로 모아, "Q: {user_text}\nA: {response}" 형태로 이어 붙이거나, 첫 1~2턴만 요약 문장으로 만듦. 예: "고객: 오늘 날씨 문의 → AI: 기상청 홈페이지 안내. 고객: 기상청 찾아가는 법 문의 → AI: 담당자 연결 제안." |
| **사람 간** | (1) 통화 후 LLM 요약 파이프라인이 있으면 그 **요약 문장**을 `content`로 사용. (2) 없으면 "일반 통화 (요약 없음)" 또는 녹음/전사 존재 시 "통화 전사 요약 대기 중" 등. |

---

## 5. 사람 간 통화: 통화 후 LLM 요약 → ChromaDB 저장 로직 (상세)

### 5.1 트리거

- 통화 종료 이벤트(`call_ended` 또는 BYE 수신) 시, **AI 응대가 아니었던 통화**에 대해:
  - 녹음 파일 또는 실시간 전사 결과(STT 세그먼트)가 있으면 **비동기 작업**으로 요약 파이프라인 실행.

### 5.2 단계별 상세

1. **입력 수집**  
   - 녹음: `recordings/{call_id}.wav` 등.  
   - 또는 이미 스트리밍 STT로 남긴 텍스트: `call_data_record`의 `stt_final` 이벤트를 `call_id`로 모아 시간순 결합.  
   - 출력: `transcript_raw` (또는 파일 경로), `duration_sec`.

2. **LLM 요약**  
   - 프롬프트 예: "다음 통화 전사본을 2~3문장으로 요약하고, 지식으로 남길 만한 질문-답변 쌍이 있으면 추출하라."  
   - 입력: `transcript_raw` (길면 앞뒤 자르기 + 최대 N자).  
   - 출력: `summary` (문자열), `extracted_qa` (선택, 배열).  
   - **디버깅용 로그**: `call_data_record`에 `category: "knowledge"`, `event: "human_call_llm_summary_request"` / `"human_call_llm_summary_response"` 로 **요청/응답 전문**(또는 요약), `model`, `elapsed_ms`, `tokens_used` 기록.

3. **ChromaDB 저장**  
   - 저장할 텍스트: `summary` 또는 `extracted_qa`의 각 항목을 하나의 문서로.  
   - 메타: `owner`(착신 번호), `call_id`, `category`(예: "통화요약"), `source: "human_call"`.  
   - **디버깅용 로그**: `event: "human_call_chromadb_store"`, `collection`, `doc_ids[]`, `success`, `error` 기록.

이렇게 하면 통화 이력 API가 같은 `call_data_record` 로그에서 `human_call_llm_summary_*`, `human_call_chromadb_store`를 읽어 **사람 간 통화**에 대한 `detail.summary_pipeline`을 채울 수 있다.

---

## 6. 구현 체크리스트 및 점검 결과

| # | 항목 | 상태 | 점검 내용 |
|---|------|------|-----------|
| 1 | **통화 이력 집계 모듈** | ✅ 구현됨 | `src/common/call_history_reader.py` — `read_call_history_from_logs()`, `aggregate_by_call_id()` 존재. 로그 파일 읽어 `content`·`detail` 생성. |
| 2 | **통화 이력 API** | ❌ 미구현 | 이 저장소(sip-pbx) 내에 `GET /api/call-history` (목록 + content/detail 반환) 엔드포인트 없음. 프론트는 `GET /api/call-history?callee=...` 호출함. 백엔드(별도 서버)에서 `call_history_reader.read_call_history_from_logs()` 호출해 `{ items, total }` 반환 필요. |
| 3 | **통화내용 표시** | ✅ 구현됨 | `frontend/app/dashboard/page.tsx` — "통화 이력" 섹션에서 `row.content`를 "통화내용" 컬럼에 표시. API가 `content`를 주면 그대로 표시됨. |
| 4 | **AI 응대 detail** | ✅ 구현됨 | `call_history_reader`가 `rag_search_done`, `llm_exchange` 등으로 `detail.turns` 구성. `generate_response_node`·`adaptive_rag_node`에서 `log_call_data` 호출. |
| 5 | **사람 간 통화** | ❌ 미구현 | 통화 종료 후 LLM 요약 → ChromaDB 저장 파이프라인 없음. `human_call_llm_summary_*`, `human_call_chromadb_store` 이벤트 기록 코드 없음. |
| 6 | **로그 일관성 (call_id)** | ✅ 수정 반영 | `step_back_prompt.py`에서 RAG 재검색 시 `call_id=state.get("_call_id")` 전달하도록 수정함. |

### 6.1 상세 점검 요약

- **통화 이력 API**: 백엔드가 이 repo 밖에 있으면, 해당 서버에 `GET /api/call-history` 를 추가하고 `call_history_reader.read_call_history_from_logs(log_dir=..., from_date=..., to_date=...)` 를 호출해 `items`(각 항목에 `content`, `detail` 포함)·`total` 반환하면 됨.
- **사람 간 통화**: 설계 §5 파이프라인(녹음/전사 → LLM 요약 → ChromaDB 저장) 및 `call_data_record` 이벤트는 추후 구현 시 체크리스트에 맞춰 추가.
- **step_back call_id**: `step_back_prompt.py`에서 RAG 재검색 시 `call_id=state.get("_call_id")` 를 전달하도록 수정 완료.
