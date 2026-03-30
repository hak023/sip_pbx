# 통화 지연 분석: call_id `Qjr033OLV8` (AI 봇 응대·LLM 구간)

| 항목 | 내용 |
|------|------|
| 작성일 | 2026-03-26 |
| 상태 | 분석 완료 |
| 데이터 소스 | `sip-pbx/logs/call_data_record_20260325.log`, `sip-pbx/logs/app.log` |
| 관련 코드 | `sip-pbx/src/ai_voicebot/langgraph/agent.py`, `nodes/greeting_farewell_cache.py`, `nodes/step_back_prompt.py` |

---

## 1. 요약

해당 통화에서 사용자의 **유일한 발화**는 **「반갑습니다.」**(인사)였고, 의도 분류는 **키워드 경로로 `greeting`**으로 즉시 확정되었다. 그럼에도 **전체 에이전트 그래프가 약 27.6초** 소요되었고, 체감상 “봇이 느리다”로 이어질 수 있는 수준이다.

**느림의 본질**: 단순 인사인데도 **`greeting_farewell` 시맨틱 캐시 미스** 후 **질의 재작성(rewrite) → RAG → 신뢰도 낮음 → Step-back(LLM) → 최종 응답 생성(generate)** 의 **풀 파이프라인**이 실행되었고, 그 안에 **LLM 호출이 최소 3회**(rewrite, step_back, generate) 포함되었다.

---

## 2. 타임라인 (CDR 기준)

| 시각 (로컬) | 이벤트 | 비고 |
|-------------|--------|------|
| 02:52:46.428 | `call_connected` | 무응답 10초 후 AI 인수 등 |
| 02:52:46.942 | `greeting_phase1_sent` | TTS 인사 1 |
| 02:52:51.505 | `greeting_phase2_sent` | TTS 인사 2 |
| 02:53:02.206 | `stt_final` | 사용자: 「반갑습니다.」 |
| 02:53:03.206 | `stt_to_llm` | LLM 그래프 진입 시점 |
| 02:53:03.289 | `intent_classify` | `path: keyword`, `intent: greeting`, **elapsed_sec: 0** |
| 02:53:18.468 | `rewrite_query` | **`elapsed_sec: 10.688`**, `path: llm` |
| 02:53:30.721 | `llm_generate_response` | **`elapsed_sec: 7.361`** |
| 02:53:30.867 | `agent_graph_total` | **`total_elapsed_sec: 27.579`** |
| 02:53:30.869 | `tts_text_pushed` | 최종 TTS 문장 푸시 |
| 02:54:12.595 | `call_ended` | 이후 추가 사용자 턴 없음 |

**사용자 관점 지연**: `stt_to_llm` → `tts_text_pushed` ≈ **27.66초**.

---

## 3. 에이전트 그래프 구간 분해 (`agent_graph_node_durations_sec`)

CDR에 기록된 노드별 시간(초, 합계 ≈ 27.58s):

| 노드 | 소요(초) | 성격 |
|------|----------:|------|
| `rewrite_query` | **10.706** | **LLM** (질의 재작성) |
| `generate_response` | **7.364** | **LLM** (최종 답변) |
| `step_back` | **4.710** | **LLM + RAG 재검색** (신뢰도 낮을 때) |
| `check_greeting_farewell_cache` | **4.474** | 임베딩 + `qa_cache` 벡터 검색 (**LLM 아님**, 네트워크/임베딩 비용) |
| `adaptive_rag` | 0.161 | 지식 검색 |
| `update_cache` | 0.143 | 캐시 갱신 등 |
| `classify_intent` | 0.018 | 키워드 분류 |
| 기타 | < 0.01 | `update_state`, `hitl_alert` |

**LLM에 해당하는 구간만 합산**하면 대략 **10.7 + 4.7 + 7.4 ≈ 22.8초** 수준이며, 나머지 **약 4.5초**는 인사 전용 캐시 검색 등 **비 LLM** 구간이다.

> 참고: LangGraph `astream` 업데이트 구간을 노드에 나누어 배분하는 타이밍 방식이라, 노드 합계와 wall clock 사이에 소수 초 단위 오차가 있을 수 있다. 다만 CDR의 `rewrite_query` / `llm_generate_response`의 **명시적 elapsed**도 각각 ~10.7s, ~7.4s로 **LLM이 병목의 대부분**임을 뒷받침한다.

---

## 4. 왜 풀 파이프라인이 탔는가 (코드·로그 정합)

### 4.1 라우팅

- `classify_intent` 이후 `intent == "greeting"`이면 **`check_greeting_farewell_cache`** 로 진입한다 (`agent.py`의 `_route_after_intent`).
- 캐시 **미스** 시 `_route_after_greeting_farewell_cache`는 **`rewrite_query`** 로 폴백한다.

```155:161:c:\work\workspace_sippbx\sip-pbx\src\ai_voicebot\langgraph\agent.py
def _route_after_greeting_farewell_cache(state: ConversationState) -> str:
    """캐시 히트 시 update_state. 미스 시 knowledge RAG(인사/종료 category)로 폴백."""
    if state.get("rag_cache_hit"):
        return "update_state"
    if state.get("intent") in ("greeting", "farewell"):
        return "rewrite_query"
    return "update_state"
```

즉, **인사라도 `qa_cache`에서 임베딩 유사도 ≥ 0.85 히트가 없으면** 곧바로 **RAG+LLM 경로**로 들어간다.

### 4.2 Step-back이 붙은 이유

- RAG 결과 **confidence ≈ 0.121** (CDR `rag_search_done`)이 **`_route_after_rag`의 임계값 0.4 미만**이어서 `step_back` 분기가 실행되었다 (`agent.py` 147–152행, `step_back_prompt.py`의 `CONFIDENCE_THRESHOLD = 0.4`).

인사·환영류 질의는 지식 히트 점수가 구조적으로 낮게 나오기 쉬워 **불필요한 Step-back LLM**이 자주 유발될 수 있다.

### 4.3 `check_greeting_farewell_cache`가 ~4.5초 걸린 의미

- 해당 노드는 **`embed_text` + Chroma `qa_cache` 검색**이다 (`greeting_farewell_cache.py`).
- 4초대는 **임베딩 API RTT** 또는 **로컬/원격 벡터 DB 지연** 가능성이 크다. (동일 통화에서 “느리다”의 원인 중 하나이나, **순수 LLM만의 문제는 아님**.)

---

## 5. 결론: “LLM이 느린가?”

- **맞다 — 다만 LLM만의 문제는 아니다.**
  - **가장 큰 비중**: `rewrite_query` + `generate_response` + `step_back` 내 **연쇄 LLM 호출**(합 ~20초대).
  - **부수적 병목**: `check_greeting_farewell_cache` **~4.5초**(임베딩+검색).
- **근본 원인**: **키워드로 이미 `greeting`으로 확정된 짧은 인사**에 대해, **캐시 미스 시 설계상 풀 RAG·저신뢰 Step-back까지 포함한 경로**가 강제된다.

---

## 6. 개선 포인트 (우선순위 제안)

### P0 — 인사·짧은 greeting 전용 “즉시 경로”

- **키워드/룰로 `greeting`이 확정된 경우**:
  - `rewrite_query` / `step_back` **스킵**.
  - 테넌트별 고정 멘트(이미 TTS에 쓰는 `greeting_phase1/2`와 정합) 또는 **단일 경량 LLM 호출**만 허용.
- 효과: 이번 케이스처럼 **~27s → 수백 ms ~ 수 초**대로 수축 가능.

### P0 — `greeting` 의도에서 Step-back 비활성화 또는 임계값 완화

- 인사·작별은 RAG confidence가 낮아도 **정상**인 경우가 많음.
- `intent in ("greeting", "farewell")` 이면 `step_back` **건너뛰기** 또는 **별도 임계값** 적용 권장.

### P1 — `qa_cache` 시딩 / 임계값 튜닝

- 「반갑습니다」「안녕하세요」 등 **고빈도 인사**를 `qa_cache`에 넣고, 또는 greeting 전용으로 **유사도 임계 완화**(짧은 발화는 임베딩 분산이 커서 0.85가 과도할 수 있음).

### P1 — `rewrite_query` 조건부 스킵

- `intent == greeting` 이고 `user_query` 길이·패턴이 단순하면 `rewritten_query = user_query` 로 두고 **rewrite LLM 호출 생략**.

### P2 — 모델·API 레벨

- rewrite / step-back용 **더 작고 빠른 모델** 또는 **타임아웃·폴백**(실패 시 고정 멘트).
- 가능하면 **인사 경로는 LLM 0~1회**로 제한.

### P2 — 임베딩 지연 관측

- `greeting_farewell_cache`에 **임베딩 단계만의 elapsed** 로그를 분리하면, 4초대가 API인지 DB인지 판별이 쉬움 (디버깅 규칙: 추론 지점별 로그).

---

## 7. 부록: 본 통화 맥락 (app.log)

- 착신 무응답 후 **AI 인수**(`no_answer_timeout_activating_ai`)로 연결된 통화.
- 파이프라인: Pipecat, `rag_llm` 프로세서 체인 정상 기동.
- 본 분석은 **첫 사용자 발화 「반갑습니다.」에 대한 응답 지연**에 초점을 맞춤.

---

*본 문서는 점검·분석 결과를 월별 리포트 위치 규칙에 따라 `sip-pbx/docs/reports/2026-03/` 에 보관한다.*
