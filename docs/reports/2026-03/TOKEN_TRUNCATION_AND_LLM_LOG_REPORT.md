# 토큰 잘림(MAX_TOKENS) 및 LLM 출력 로깅 리포트

**대상 로그**
- `app.log` 662–666 (통화 XCJp3RJVQQ, 2026-03-14 15:53, 지식 추출 Pipeline v2)

---

## 1. 요약

- **지식 정제(유용성 판단) LLM** 응답이 `max_output_tokens=2048` 한도에서 잘려 **JSON이 중간에 끊김**.
- 그 결과 **JSON 파싱 실패** → `extracted_info` 복구 불가 → **knowledge_count: 0** 으로 종료.
- 동시에 로그에 **실제 LLM 전체 출력(response_full)** 이 잘려서 기록되어, 디버깅 시 원본 응답을 확인하기 어려움.

**권장**
1. **judgment_max_output_tokens** (지식 정제용)를 **2048 → 4096 이상**으로 상향.
2. **모든 LLM/RAG 관련 로그**에서 `response_full`, `json_full`, `user_text_full` 등을 **잘리지 않고 전부** 기록하도록 수정.

---

## 2. 로그에서 보이는 현상

| 시각 | 이벤트 | 내용 |
|------|--------|------|
| 15:53:06 | llm_judgment_request | 지식 정제 요청 (max_tokens=2048, prompt_length=2649) |
| 15:53:24 | llm_judgment_response | **finish_reason: "MAX_TOKENS"**, response_length=172 (실제로는 172자만 로그에 기록) |
| 15:53:24 | llm_judgment_truncated | "응답이 max_output_tokens에서 잘림, JSON 복구 시도" |
| 15:53:24 | JSON parse failed | **Unterminated string** (line 7 column 15) — `extracted_info[0].text` 문자열이 중간에 끊김 |
| 15:53:24 | llm_judgment_completed | extracted_info_count=0, is_useful=false (복구 실패로 빈 결과) |

**잘린 응답 예시 (로그에 찍힌 response_full):**

```json
"response_full": "```json\n{\n  \"is_useful\": true,\n  \"confidence\": 0.9,\n  \"reason\": \"기상청 방문 위치, 길 안내, 날씨 예보 등 재사용 가능한 정보 추출\",\n  \"extracted_info\": [\n    {\n      \"text\": \"저희 기상청은 판교로 방문을 하시면 됩니다"
```

→ 여기서 `"text"` 값이 닫히지 않아 파서가 **Unterminated string** 을 보고, 이후 `]`, `}` 등이 없어 JSON 복구도 불가.

---

## 3. 원인 정리

1. **max_output_tokens=2048**
   - 지식 정제 프롬프트는 “extracted_info 최대 5개, 각 text 200자 이내” 등으로 꽤 긴 JSON을 요구.
   - 2048 토큰이면 한국어+JSON 구조에서 5개 항목을 다 채우다가 **중간에 잘릴 가능성이 큼**.

2. **로그 쪽 잘림**
   - 코드에서 `response_full` / `json_full` 등을 **길이 제한(예: 2000자)** 으로 잘라서 로그에 넣고 있음.
   - 실제 LLM이 반환한 **전체 문자열**이 로그에 남지 않아, 잘림 위치·원본 응답 확인이 어려움.

---

## 4. 조치 사항

### 4.1 설정 (지식 추출/정제 파이프라인)

- **judgment_max_output_tokens** (또는 해당 LLM 호출의 `max_tokens`):
  - **2048 → 4096** (또는 8192) 으로 상향.
- 지식 정제용 모델이 다른 설정 파일/환경 변수를 쓰는 경우, 해당 위치의 **max_tokens / max_output_tokens** 도 동일하게 상향.

### 4.2 로깅 (LLM·RAG 공통)

- **무조건 전체 출력을 로그에 남기도록** 수정:
  - **LLM 응답**: `response_full` 에 **전체 응답 문자열** 그대로 기록 (길이 제한 제거).
  - **JSON 파싱 실패 시**: `json_full` 에 **파서에 넘긴 원본 문자열 전체** 기록.
  - **RAG/대화 LLM**: `rag_processor.py` 등에서 `user_text_full`, `response_full` 을 **잘리지 않게** 항상 전체 전달.
- 필요 시:
  - 매우 긴 페이로드는 **별도 이벤트**(예: `llm_response_full_body`)로 분리해 로그하고,
  - 기존 이벤트에는 `response_length` 만 두어도 됨. (중요한 것은 **한 곳에서는 전체가 반드시 남는 것**.)

### 4.3 적용 범위 및 구현 상태

- **RAG/대화 LLM** (`sip-pbx/src/ai_voicebot/pipecat/processors/rag_processor.py`) — **적용 완료**
  - `llm_exchange_full`, `langgraph_agent_result`, `llm_response_sent`: `response_full`, `user_text_full` **잘림 없이 전체** 로깅.
  - `farewell_closing_pushed`: `response_full` 추가.
  - `hitl_timeout_message_refined`: `refined_text_full` 추가 (preview는 유지).
  - 레거시 RAG 경로: `llm_legacy_response` 이벤트 추가, `user_text_full`, `response_full` 전체 로깅.
  - RAG 검색 결과: `rag_search_results` 에 `top_doc_full` 추가.
- **지식 추출(extraction) 파이프라인** (`src/ai_voicebot/ai_pipeline/llm_client.py` `judge_usefulness`) — **적용 완료**
  - **judgment_max_output_tokens**: 설정에 없으면 **4096** 사용. (기존: `max_output_tokens`/`max_tokens` 폴백으로 200 등 소값이 적용되어 response_length=174 수준으로 잘림 발생 가능 → 제거 후 judgment 전용 기본값 4096만 사용)
  - **response_full** / **json_full**: 코드에서 잘리지 않고 **전부** 전달. `llm_judgment_json_failed` 시 `raw_response_full`/`json_attempt_full`도 2000자 제한 제거하여 전체 로깅.
  - 로그에 여전히 짧게 보이면 structlog/파일 핸들러 등 로깅 백엔드 쪽 제한 여부 확인. `response_length`/`json_length`로 원본 길이 확인 가능.

---

## 5. 참고

- `app.log` 662–666: 동일 통화에서 **요청 프롬프트(prompt_full)** 는 전체가 로그에 남아 있음. 반면 **응답(response_full)** 만 잘려 있음.
- 디버깅 규칙(`.cursor/rules/debug-logging.mdc`): 추론한 결과가 로그에 반영되어야 하고, 잘림으로 인해 다른 원인 판단이 어렵지 않도록 **충분한 정보**를 남기는 것이 원칙.
