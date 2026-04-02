# Outbound AI 봇 대화 로직 재설계 및 구현

| 항목 | 내용 |
|------|------|
| 작성일 | 2026-04-01 15:00 |
| 상태 | **구현 완료** |
| 관련 call_id | `outbound-ob-98df573b-30841689` (분석 기준) |
| 관련 설계서 | `docs/reports/2026-03/2026-03-31_2200_OUTBOUND_CALL_DESIGN.md` |

---

## 1. 문제 분석

### 1.1 로그에서 확인된 문제

**call `outbound-ob-98df573b-30841689` 흐름:**

```
착신자 발화: "편점이요." (5점이라는 의미)
  → classify_intent_json_parse_failed  ← LLM JSON 파싱 실패
  → classify_intent_nlu_fallback_to_question  ← question으로 폴백
  → RAG 검색: "편의점" (query rewrite 오류) → confidence 0.29
  → generate_response: question + RAG 0건 → "죄송합니다. 알지 못하는 내용입니다"
```

**착신자 발화: "오점이요." (5점):**
```
  → 동일하게 question 분류 → RAG 검색 → "죄송합니다" 응답
```

### 1.2 근본 원인 (3가지)

| # | 원인 | 영향 |
|---|------|------|
| 1 | `outbound_purpose`/`outbound_questions`가 LangGraph `invoke_state`에 주입되지 않음 | LLM이 통화 목적을 모르고 inbound처럼 처리 |
| 2 | `generate_response_node`의 `intent==question + no_rag` 경로가 outbound에서도 고정 멘트 반환 | 착신자 답변을 "모르는 내용"으로 처리 |
| 3 | outbound 전용 시스템 프롬프트(`_outbound_system_prompt`)가 `call_manager.py`에서 조립되지만 LangGraph의 `invoke_state["system_prompt"]`는 `org_manager.get_system_prompt()`로만 채워짐 | 목적/질문 기반 프롬프트가 LLM에 미반영 |

---

## 2. 설계 방향

### 2.1 사용자 요청 핵심

- outbound 전용: **페르소나 + 통화목적 + 질문목록** 기반 프롬프트 구성
- 불필요한 RAG 검색 최소화 (착신자 답변은 RAG 지식과 무관)
- intent 분류는 유지하되 outbound 답변 의도(affirm/deny 등)는 빠른 경로로 처리
- 통화목적 달성 여부는 기존 `_check_outbound_mission_complete` 유지

### 2.2 처리 흐름 (수정 후)

```
착신자 발화 → STT
  ↓
classify_intent (기존 유지)
  ↓
route_utterance
  ├─ outbound + affirm/deny/doubt 등 → social_direct (RAG 스킵)
  └─ question → knowledge (RAG 검색, 단 question+no_rag 고정멘트 경로 제외)
  ↓
generate_response
  ├─ outbound: 목적/질문/진행상황 기반 프롬프트 → LLM → 자연스러운 응대
  └─ inbound: 기존 RESPONSE_SYSTEM_PROMPT 유지
  ↓
_check_outbound_mission_complete (비동기, 기존 로직 유지)
  └─ achieved=true → farewell TTS → BYE
```

---

## 3. 변경 이력 (파일별)

| 파일 경로 | 변경 유형 | 요약 | 비고 |
|-----------|-----------|------|------|
| `src/ai_voicebot/pipecat/processors/rag_processor.py` | 수정 | `process_utterance` 호출 시 `outbound_purpose`, `outbound_questions`, `outbound_answers`, `_hangup_callback` 전달 | outbound 컨텍스트 주입 |
| `src/ai_voicebot/langgraph/agent.py` | 수정 | kwargs에서 outbound 필드 추출 → `invoke_state`에 주입 + outbound 전용 `system_prompt` 조립 | 인바운드 기존 동작 유지 |
| `src/ai_voicebot/langgraph/nodes/generate_response.py` | 수정 | `_is_outbound` 플래그 추가, outbound 전용 프롬프트 분기, `question+no_rag` 고정멘트 경로 outbound 제외 | 인바운드 기존 동작 유지 |
| `src/ai_voicebot/langgraph/nodes/route_utterance.py` | 수정 | outbound + affirm/deny/doubt/gratitude → `social_direct`(RAG 스킵) 빠른 경로 추가 | 인바운드 영향 없음 |

---

## 4. 파일별 변경 상세

### `rag_processor.py` — `process_utterance` 호출부

- **변경 내용**: `_outbound_purpose`가 있으면 `outbound_extra` dict를 구성해 `agent.process_utterance` kwargs로 전달
- **기존 동작 제거 여부**: 없음 (추가만)
- **설계 대비**: 설계대로

### `agent.py` — `process_utterance`

- **변경 내용**:
  1. kwargs에서 `outbound_purpose`, `outbound_questions`, `outbound_answers`, `outbound_mission_done`, `_hangup_callback` 추출
  2. `outbound_purpose`가 있으면 `system_prompt`를 목적/질문 기반 문자열로 덮어씀 (org_manager 프롬프트 대신)
  3. 추출된 값들을 `invoke_state`에 스프레드 합성 (None/빈값은 미주입 → 기존 state 유지)
- **기존 동작 제거 여부**: 없음. `outbound_purpose`가 없으면 완전히 기존 경로
- **설계 대비**: 설계대로

### `generate_response.py` — `generate_response_node`

- **변경 내용**:
  1. `_is_outbound = bool(state.get("outbound_purpose"))` 플래그 추가
  2. `intent==question and not rag_results` 고정멘트 경로에 `and not _is_outbound` 조건 추가
  3. LLM 프롬프트 조립 시 outbound/inbound 분기:
     - outbound: `system_prompt`(agent.py가 조립한 목적/질문 프롬프트) + 진행상황 + history + rag_context
     - inbound: 기존 `RESPONSE_SYSTEM_PROMPT.format(...)` 유지
- **기존 동작 제거 여부**: 없음. `_is_outbound=False`이면 완전히 기존 경로
- **설계 대비**: 설계대로

### `route_utterance.py` — `route_utterance_node`

- **변경 내용**: outbound 모드에서 `affirm`/`deny`/`doubt`/`gratitude`/`positive_reaction`/`negative_reaction` → `social_direct`(RAG 스킵) 경로 추가
- **기존 동작 제거 여부**: 없음. outbound가 아니면 기존 로직 그대로
- **설계 대비**: 설계서 §3.7 FSM 패턴 반영 (착신자 답변 의도는 RAG 불필요)

---

## 5. 기대 동작 (수정 후)

| 착신자 발화 | 수정 전 | 수정 후 |
|-------------|---------|---------|
| "편점이요." (5점) | "죄송합니다. 모르는 내용입니다." | "5점 주셨군요. 감사합니다." 또는 자연스러운 응대 |
| "오점이요." (5점) | "죄송합니다. 모르는 내용입니다." | mission_check에서 answered 처리 → farewell → BYE |
| "네" / "아니요" | RAG 검색 후 question 경로 | social_direct → LLM 직행 (빠른 응대) |

---

## 6. 미변경 사항 (기존 로직 유지)

- `_check_outbound_mission_complete()`: 기존 JSON Structured Output 미션 판단 유지
- `_trigger_mission_complete()`: KB farewell + TTS 이벤트 대기 + BYE 콜백 유지
- `send_greeting()`: 아웃바운드 p1+p2 인사 로직 유지
- Intent 분류 자체는 변경 없음 (outbound에서도 분류 실행, 라우팅에서 처리)

---

## 7. 미해결 리스크

| 항목 | 내용 |
|------|------|
| STT 오인식 | "편점이요" → "편의점"으로 rewrite되는 문제는 STT/rewrite 품질 문제, 별도 검토 필요 |
| intent 분류 JSON 파싱 실패 | `classify_intent_json_parse_failed` 지속 발생 — LLM 응답 품질 이슈, 분리 검토 |
| mission_check 타이밍 | `_check_outbound_mission_complete`가 비동기로 실행되므로, 응답과 완료 판단 간 타이밍 차이 존재 |
