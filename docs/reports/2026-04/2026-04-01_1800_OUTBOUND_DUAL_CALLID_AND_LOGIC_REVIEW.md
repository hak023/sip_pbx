# Outbound Call — call_id 중복 이슈 및 AI 로직 설계 검토 리포트

| 항목 | 내용 |
|------|------|
| 작성일 | 2026-04-01 18:00 |
| 상태 | 분석 완료 |
| 대상 로그 | `logs/call_data_record_20260401.log` (라인 14, 24~51) |
| 관련 설계서 | `docs/design/ai-outbound-call.md`, `docs/reports/2026-03/2026-03-31_2200_OUTBOUND_CALL_DESIGN.md` |

---

## 1. call_id가 두 개로 보이는 원인 분석

### 1.1 로그 파일 손상 (실제 원인)

로그 파일 14번 라인을 보면 아래와 같이 **두 call_id의 JSON이 한 줄에 합쳐져 있다:**

```
{"ts":"2026-04-01T13:10:34.407","call_id":"outbound-ob-9ae67cdb-51372347","category":"call_event","event":"call{"ts":"2026-04-01T15:19:00.985","call_id":"outbound-ob-ac766156-50807332","category":"call_event","event":"call_connected","callee":"1004"}
```

- `outbound-ob-9ae67cdb-51372347`의 `call_ended` JSON이 **중간에 잘려서(truncated)** 다음 call_id(`outbound-ob-ac766156-50807332`)의 JSON과 한 줄에 붙었음
- 이는 **실제로 call_id가 두 개**인 게 아니라 **로그 파일 기록 중 버퍼 flush 실패 또는 파일 write 경쟁(race condition)**으로 인한 손상임
- 전화는 분명 별개의 두 통화 (`9ae67cdb` 14:26 종료, `ac766156` 15:19 연결)이며 call_id가 겹치는 건 없음

### 1.2 로그 손상 상세 — 라인별 재구성

| 라인 | call_id | 시각 | 이벤트 | 비고 |
|------|---------|------|--------|------|
| 11 | `9ae67cdb` | 13:10:19 | call_connected | |
| 12 | `9ae67cdb` | 13:10:20 | greeting_phase1_sent | |
| 13 | `9ae67cdb` | 13:10:24 | greeting_phase2_sent | |
| **14** | `9ae67cdb` + `ac766156` | 13:10:34 + 15:19:00 | **call_ended** (잘림) + **call_connected** (붙음) | **⚠ 손상된 라인** |
| 15~ | `ac766156` | 15:19:01~ | 정상 로그 계속 | |

### 1.3 근본 원인 추정

`call_data_record_logger.py`의 현재 구현:

```python
# 한 줄을 만들어 씀
line = json.dumps(payload, ...) + "\n"
with _lock:
    f.write(line)
    f.flush()
```

- `buffering=1` (line-buffering) + `f.flush()`를 사용하지만,  
  **call_ended 이벤트와 다음 call_connected 이벤트가 동시에 비동기로 발생**할 때  
  OS 버퍼 레벨에서 write가 원자적이지 않을 수 있음
- 또는 **서버 재시작/비정상 종료**로 인해 `9ae67cdb`의 `call_ended` JSON 끝 부분이 누락되고  
  이후 재오픈된 파일에 `ac766156` JSON이 이어서 기록되었을 가능성

### 1.4 결론

> **실제 버그는 call_id 중복이 아니라 로그 파일 기록 손상이다.**  
> 두 통화는 서로 다른 call_id를 가진 정상적인 별도 발신 통화임.

---

## 2. Outbound AI 로직 설계 vs 실제 동작 비교

### 2.1 설계서 요약 (ai-outbound-call.md + 2026-03-31 설계서)

설계서에서 정의한 아웃바운드 AI 처리 원칙:

```
착신자 응답 → STT
    ↓
[아웃바운드 전용 프롬프트]
  - 페르소나(persona) 정보
  - 통화 목적(purpose)
  - 확인 질문(questions) 목록
    ↓
LLM → 답변 수집 + 미션 완료 판단
    ↓
미완료 → 다음 질문 push
완료 → KB farewell TTS → BYE
```

**핵심 원칙:** RAG는 착신자 질문에 대한 KB 참조가 아니라, **페르소나 정보와 아웃바운드 컨텍스트만** 전달. intent classify → rewrite query → 일반 KB RAG 검색 파이프라인은 **불필요**.

---

### 2.2 실제 동작 (로그 분석)

`outbound-ob-98df573b-30841689` (14:26 통화) 실제 흐름:

```
greeting_phase2: "서비스 만족도 조사 서비스 만족도 점수를 몇 점 주시겠습니까? 1점부터 5점까지 가능합니다."
착신자: "편점이요." (5점 의도 — STT 오인식)

→ intent_classify: "question"  ← ❌ 설계 위반 (아웃바운드 답변을 inbound question으로 분류)
→ semantic_cache: miss (5.0초 낭비)
→ rewrite_query: "편점이요." → "편의점"  ← ❌ 완전 엉뚱한 rewrite
→ rag_search: owner=1004, query="편의점", confidence=0.296 (기상청 KB 검색)
→ llm_exchange: "죄송합니다. 해당 내용은 제가 알지 못하는 내용입니다."  ← ❌ 설계 위반 응답

착신자: "오점이요." (5점 의도 — 반복)
→ intent_classify: "question"  ← ❌ 동일 오류
→ rewrite_query: "오점이요." → "5점입니다"  ← 이번엔 맞음
→ rag_search: query="5점입니다", 기상청 KB 검색  ← ❌ 무의미한 KB 검색
→ llm_exchange: "죄송합니다. 해당 내용은 제가 알지 못하는 내용입니다."  ← ❌ 동일 오류
```

`outbound-ob-ac766156-50807332` (15:19 통화)도 동일 패턴:

```
착신자: "오요." → intent: "question" → RAG 기상청 KB 검색 → "죄송합니다"
llm_rag_context_source: "llm_generation_error"  ← ❌ LLM 생성 오류까지 발생
```

---

### 2.3 현재 동작의 문제점 요약

| # | 문제 | 설계서 기대 | 실제 동작 | 영향 |
|---|------|------------|-----------|------|
| **P1** | intent 분류 오작동 | 착신자 답변 → 아웃바운드 컨텍스트로 처리 | "5점이요" → `intent: question` 분류 | 엉뚱한 파이프라인 진입 |
| **P2** | query rewrite 비적용 | 아웃바운드는 rewrite 불필요 | "편점이요" → "편의점" (완전 오인식) | RAG 품질 저하 |
| **P3** | 일반 KB RAG 검색 | 아웃바운드 컨텍스트(persona/purpose/questions)만 LLM에 전달 | 기상청 FAQ KB 전체 검색 | 무관한 문서 노이즈 |
| **P4** | 폴백 응답 | 착신자 답변 수집 + 미션 체크 | "죄송합니다. 알지 못하는 내용입니다." | 통화 목적 달성 불가 |
| **P5** | 응답 시간 과대 | 빠른 응답 (아웃바운드 simple) | 14.1초 (classify+cache+rewrite+rag+llm 전체) | UX 심각 저하 |
| **P6** | outbound_purpose가 LLM에 미전달 | LLM이 통화 목적/질문 목록을 알고 응답 | LLM이 purpose/questions를 모름 | 미션 수행 불가 |

---

### 2.4 코드 추적 — 왜 이렇게 동작하는가?

현재 `rag_processor.py`의 `process_utterance()` 흐름:

```
착신자 발화 → process_utterance()
    ↓
self._agent.process_utterance(text, outbound_purpose=..., outbound_questions=...)
    ↓
agent.py: invoke_state에 outbound_purpose 병합 → LangGraph 호출
    ↓
LangGraph 노드 순서:
  1. classify_intent    ← ❌ 아웃바운드도 intent 분류 실행
  2. route_utterance    ← 일부 affirm/deny는 social_direct로 보내지만 "편점이요"는 question으로 분류됨
  3. check_cache        ← ❌ 캐시 미스 (5초)
  4. rewrite_query      ← ❌ 쿼리 rewrite (무의미)
  5. adaptive_rag       ← ❌ 기상청 KB RAG 검색
  6. generate_response  ← outbound 분기 있으나 rag_results가 없어서 폴백 응답
```

`generate_response.py`의 `_is_outbound` 분기:

```python
_is_outbound = bool(state.get("outbound_purpose"))
# ...
if intent == "question" and not rag_results and not _is_outbound:
    # 아웃바운드는 이 폴백 제외 ← 이것만 수정됨
```

하지만 실제로는 `rag_results`가 11~12개 반환되므로 이 조건이 False → **아웃바운드용 LLM 프롬프트가 아닌 일반 RAG 컨텍스트로 생성**되어도, 기상청 KB가 "5점"을 답할 수 없어 결국 폴백 응답을 내놓음.

---

## 3. 설계 방향 (To-Be)

### 3.1 핵심 원칙 재정립

> **아웃바운드 AI는 인바운드 RAG 파이프라인을 타지 않는다.**  
> 착신자의 발화는 "미션 컨텍스트 내 답변"으로 처리한다.  
> RAG는 페르소나/아웃바운드 정보 로딩에만 사용하고, 실시간 KB 검색은 스킵한다.

### 3.2 변경 필요 위치

| 파일 | 변경 내용 | 우선순위 |
|------|-----------|----------|
| `langgraph/agent.py` | `outbound_purpose` 있으면 LangGraph invoke 전에 **early return** — 아웃바운드 전용 단순 LLM 호출 경로로 분기 | **긴급** |
| `langgraph/nodes/classify_intent.py` | 아웃바운드 모드 시 intent classify 스킵 → `outbound_answer`로 직행 | 높음 |
| `langgraph/nodes/route_utterance.py` | 아웃바운드 모드 시 무조건 `social_direct` (RAG skip) | 높음 |
| `langgraph/nodes/rewrite_query.py` | 아웃바운드 모드 시 rewrite 스킵 | 높음 |
| `langgraph/nodes/adaptive_rag.py` | 아웃바운드 모드 시 KB RAG 검색 완전 스킵 | **긴급** |
| `langgraph/nodes/generate_response.py` | 아웃바운드 전용 프롬프트로 LLM 호출 (purpose + questions + 대화이력) | **긴급** |
| `rag_processor.py` | `process_utterance()` 호출 전 `is_outbound` 체크 → outbound 전용 경량 경로 분리 | 높음 |

### 3.3 이상적인 아웃바운드 처리 흐름 (구현 완료)

```
착신자 발화 → STT
    ↓
classify_intent_node
  → outbound_purpose 있으면 LLM 분류 완전 스킵 (intent="outbound_answer", ~0ms)
    ↓
_route_after_classify
  → outbound_purpose 있으면 route/cache/rewrite/RAG 전체 스킵
    ↓
generate_response_node (아웃바운드 전용 프롬프트)
  ┌─────────────────────────────────────────────────┐
  │ [통화 목적] {purpose}                           │
  │ [진행 상황]                                     │
  │   답변 완료: {answered Q&A 목록}                │
  │   미수집: {unanswered 목록}                     │
  │ [대화 기록] {history}                           │
  │                                                 │
  │ 규칙 (미수집 질문 있을 때):                     │
  │  1. 착신자 발화에 자연스럽게 반응 (1문장)       │
  │  2. 다음 미수집 질문을 이어서 질문              │
  │  → 응대+질문을 하나의 TTS로 출력               │
  │                                                 │
  │ 규칙 (모든 질문 수집 완료):                     │
  │  1. 반응 1문장 + 감사 마무리                    │
  └─────────────────────────────────────────────────┘
    ↓ TTS 출력 (응대 + 다음 질문 포함)
    ↓
[비동기] _check_outbound_mission_complete
  → 대화 이력에서 답변 수집 여부 LLM 판단
  → answers 딕셔너리 업데이트
  → 미완료: 로그만 기록 (generate_response가 이미 다음 질문 발화함)
  → 완료: farewell TTS → TTS 완료 대기 → SIP BYE
```

### 3.4 예상 효과

| 지표 | 현재 | 개선 후 |
|------|------|---------|
| 평균 응답 시간 | 11~15초 | 2~4초 |
| 불필요한 KB 검색 | 매 턴 실행 | 0 |
| 미션 달성률 | 0% (항상 "죄송합니다") | 정상 동작 |
| LLM 호출 비용 | classify + rewrite + rag + generate (4단계) | generate 1단계 |

---

## 4. 로그 파일 손상 방지 방안

### 4.1 현재 코드 문제

```python
# call_data_record_logger.py
line = json.dumps(payload, ...) + "\n"
with _lock:
    f.write(line)  # ← OS 버퍼에 씌워짐
    f.flush()      # ← flush하지만 비정상 종료 시 마지막 라인 손상 가능
```

### 4.2 개선 방안

1. **write 원자성 강화**: 각 이벤트를 `call_ended` 시점에 별도 파일 sync (`os.fsync`) 호출
2. **개행 기준 검증**: 로그 로딩 시 잘린 JSON 라인 무시 처리 (call_history_reader에 이미 try/except 있음)
3. **별도 로그 파일 per call_id** (선택): 각 call_id별 독립 파일 → 충돌 최소화

---

## 5. 요약 및 우선순위

| # | 이슈 | 심각도 | 조치 |
|---|------|--------|------|
| 1 | call_id 중복처럼 보이는 문제 | 낮음 (실제 중복 아님) | 로그 파일 손상 방지 처리 |
| 2 | 아웃바운드 착신자 답변을 inbound question으로 분류 | **긴급** | outbound early-exit 경로 구현 |
| 3 | 기상청 KB RAG 검색 불필요하게 실행 | **긴급** | outbound 모드 시 RAG skip |
| 4 | LLM에 통화목적/질문 미전달로 "죄송합니다" 응답 | **긴급** | outbound 전용 generate 프롬프트 적용 |
| 5 | 응답 시간 11~15초 (전체 파이프라인 실행) | 높음 | 경량 경로로 2~4초로 단축 |
| 6 | 미션 완료 판단 및 다음 질문 push 미동작 | 높음 | outbound FSM 로직 검증 |
