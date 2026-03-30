# AI Bot 응답 시간 분석 및 최적화 설계

- **작성일**: 2026-03-30 14:40
- **분석 대상**: `logs/call_data_record_20260329.log` (76건 agent_graph_total)
- **상태**: 분석 완료, 구현 전 설계

---

## 1. 현황 요약

| 지표 | 값 |
|------|-----|
| 분석 건수 | 76건 |
| 평균 응답 시간 | **8.69초** |
| 중위값 | 8.64초 |
| P90 | 14.45초 |
| P95 | 18.26초 |
| 최대 | 20.80초 |
| 5초 이상 비율 | 84% (64/76) |
| 10초 이상 비율 | 33% (25/76) |
| 15초 이상 비율 | 9% (7/76) |

### 응답 시간 분포

```
 0- 2s:   7건  ███████
 2- 5s:   5건  █████
 5- 8s:  22건  ██████████████████████
 8-10s:  17건  █████████████████
10-15s:  18건  ██████████████████
15-25s:   7건  ███████
```

**문제**: 평균 8.69초는 전화 상담 UX에서 **허용 불가** 수준. 목표는 **3초 이내**.

---

## 2. 노드별 병목 분석

### 2.1 LangGraph 실행 파이프라인 (순차 실행)

```
classify_intent → route_utterance → [check_cache / check_greeting_farewell_cache]
    → rewrite_query → adaptive_rag → [step_back] → generate_response
    → hitl_alert → update_cache → update_state → END
```

모든 노드가 **순차 실행** — 병렬 분기 없음.

### 2.2 노드별 평균 시간 (상위 5)

| 순위 | 노드 | 평균 | 최대 | 호출 횟수 | LLM 호출 |
|------|------|------|------|-----------|----------|
| 1 | **generate_response** | 4.60s | 12.54s | 63 | ✅ 매번 |
| 2 | **step_back** | 2.19s | 2.73s | 61 | ✅ LLM + RAG |
| 3 | **check_cache** | 1.62s | 7.25s | 51 | ❌ 벡터 검색 |
| 4 | **classify_intent** | 0.84s | 1.65s | 76 | ✅ 조건부 |
| 5 | **rewrite_query** | 0.82s | 4.67s | 62 | ✅ 조건부 |

### 2.3 인텐트별 평균 응답 시간

| 인텐트 | 평균 | 최대 | 건수 |
|--------|------|------|------|
| complaint | 20.61s | 20.61s | 1 |
| greeting | 14.45s | 14.45s | 1 |
| question | 10.04s | 20.80s | 36 |
| nlu_fallback | 9.85s | 18.26s | 14 |
| farewell | 8.85s | 12.36s | 10 |
| help | 4.49s | 5.58s | 6 |
| repeat | 0.01s | 0.01s | 7 |

---

## 3. 병목 원인 상세 분석

### 3.1 🔴 generate_response (평균 4.60초, 최대 12.5초)

**가장 큰 병목**. 모든 질의에서 Gemini API를 호출하며, RAG 컨텍스트 8건 + 최대 8턴 대화 이력 + 긴 시스템 프롬프트를 포함한 요청을 보냄.

- 현재 모델: `gemini-2.5-flash-lite`
- 긴 컨텍스트 → 입력 토큰 증가 → 지연 증가
- RAG 결과가 많을수록 (최대 10건 × 각 100자) 입력이 비대

### 3.2 🔴 step_back (평균 2.19초, 80% 확률로 실행)

**항상 불필요하게 실행**되는 패턴:

- `_route_after_rag`에서 `confidence < threshold`(0.40)이면 `step_back`으로 보냄
- 현재 RAG 검색 결과의 `confidence`가 대부분 0.1~0.3 수준 (Chroma distance 기반)
- 따라서 **61/76건(80%)에서 step_back 실행** → 매번 LLM 1회 + RAG 1회 추가
- step_back 후 confidence를 인위적으로 +0.15 올리므로, 사실상 **항상 step_back을 거침**

**핵심 문제**: `similarity = 1 / (1 + chroma_distance)` 공식에서 distance가 크면 score가 낮아짐. 현재 임베딩 모델과 데이터 분포에서 0.4 이상 나오기 어려움 → step_back이 거의 항상 트리거됨.

### 3.3 🟡 check_cache (평균 1.62초, 최대 7.25초)

- 벡터 검색(`qa_cache` 컬렉션)이 일반적으로 빠르지만(~100ms), 간헐적으로 **7초까지** 소요
- **콜드 스타트** 시 Chroma 컬렉션 로딩이 원인으로 추정
- `qa_cache` 컬렉션이 비어있을 때도 검색 시도 → 불필요한 지연

### 3.4 🟡 classify_intent + rewrite_query (합산 평균 1.51초)

- `classify_intent`: 키워드 매칭 성공 시 0ms, LLM 호출 시 ~1초
- `rewrite_query`: 5단어 이상 & 비모호 시 스킵(0ms), LLM 호출 시 ~2초
- **순차 실행**이므로 둘 다 LLM 호출되면 합산 3~5초

### 3.5 🟢 farewell/greeting에서의 불필요한 전체 파이프라인 실행

"안녕하세요", "감사합니다 수고하세요" 같은 단순 인사/작별에도:

- greeting: **14.45초** (check_greeting_farewell_cache 6s + generate_response 3.2s + rewrite_query 2.5s + step_back 2.3s)
- farewell: 평균 **8.85초** (generate_response 평균 4.3s + step_back 2.3s + rewrite_query 2.0s)

첫 통화 시 캐시가 비어있으면 전체 파이프라인을 타므로 지연 발생.

---

## 4. 최적화 설계

### Phase 1: 즉시 적용 가능 (예상 효과: 평균 8.69s → ~4.5s)

#### 4.1 `step_back` 조건 개선 — confidence 임계값 조정

**현재**: confidence < 0.40 → step_back (80% 실행)
**개선**: confidence 임계값을 **0.15**로 하향, 또는 **RAG 결과가 0건일 때만** step_back 실행

```python
# agent.py: _route_after_rag 수정
def _route_after_rag(state):
    confidence = state.get("confidence", 0)
    rag_results = state.get("rag_results", [])
    # RAG 결과가 아예 없을 때만 step_back
    if not rag_results:
        return "step_back"
    return "generate_response"
```

**예상 효과**: step_back 실행 빈도 80% → ~10%, 절감 **~1.8초**

#### 4.2 `greeting`/`farewell` 고정 응답 (LLM 호출 제거)

인사·작별은 **정적 응답**으로 충분하며, LLM이 불필요:

```python
# response_shortcuts.py에 추가
GREETING_RESPONSES = [
    "안녕하세요, {org_name} AI 비서입니다. 무엇을 도와드릴까요?",
]
FAREWELL_RESPONSES = [
    "감사합니다. 좋은 하루 되세요.",
]
```

`route_utterance`에서 greeting/farewell을 `template_response` 노드로 직접 라우팅:

```python
# route_utterance.py 수정
if intent in ("greeting", "farewell"):
    return {"rag_mode": "skip", "response": TEMPLATE_MAP[intent]}
```

**예상 효과**: greeting 14.45s → **0.01s**, farewell 8.85s → **0.01s**

#### 4.3 `check_cache` 빈 컬렉션 스킵

`qa_cache` 컬렉션이 비어있을 때 검색하지 않고 바로 미스로 처리:

```python
# semantic_cache.py 수정
if not self._cache_populated:
    return {"rag_cache_hit": False}
```

**예상 효과**: 콜드 스타트 시 캐시 검색 지연 제거 **~1.5초** (최대 7초 → 0초)

### Phase 2: 구조적 개선 (예상 효과: 평균 ~4.5s → ~2.5s)

#### 4.4 `classify_intent` + `rewrite_query` 병렬 실행

현재는 순차:
```
classify_intent(1s) → route → check_cache → rewrite_query(2s) = 3s 순차
```

설계 변경:
```
classify_intent + rewrite_query 병렬 시작 → route에서 rewrite 결과 활용
```

**구현**: `classify_intent` 노드에서 동시에 query rewrite도 수행 (하나의 LLM 호출로 합침):

```python
# 합친 프롬프트
CLASSIFY_AND_REWRITE_PROMPT = """
다음 사용자 발화를 분석하세요.
1) 의도(intent): greeting/farewell/question/...
2) 검색용 질의(search_query): 핵심 키워드로 변환

JSON으로 응답: {"intent": "...", "search_query": "..."}
"""
```

**예상 효과**: LLM 호출 2회 → 1회, 절감 **~1.5초**

#### 4.5 RAG 컨텍스트 축소

현재 최대 **10건 × 100자 = 1000자** 이상의 RAG 컨텍스트를 LLM에 전달.
상위 **3건**으로 제한하면 입력 토큰 감소 → LLM 응답 시간 단축:

```python
# generate_response.py 수정
MAX_RAG_CONTEXT_FOR_LLM = 3
rag_for_llm = rag_results[:MAX_RAG_CONTEXT_FOR_LLM]
```

**예상 효과**: generate_response 입력 축소 → **~0.5-1초** 절감

#### 4.6 시스템 프롬프트 축소

현재 시스템 프롬프트가 매우 길음 (기관 정보 + 규칙 + 대화 이력 8턴).
대화 이력을 **3턴**으로 줄이고, 불필요한 규칙 제거:

```python
MAX_CONVERSATION_TURNS = 3  # 현재 8 → 3
```

**예상 효과**: 입력 토큰 30-50% 감소 → generate_response **~1초** 절감

### Phase 3: 고급 최적화 (예상 효과: 평균 ~2.5s → ~1.5s)

#### 4.7 모델 변경 검토

- 현재: `gemini-2.5-flash-lite` (저비용, 느림)
- 검토: `gemini-2.5-flash` (비용 ↑, 속도 ↑↑)
- generate_response만 더 빠른 모델 사용, 분류/변환은 flash-lite 유지

#### 4.8 Semantic Cache 적중률 향상

현재 `qa_cache` 적중 조건이 `score >= 0.92`로 엄격:
- 0.85로 완화하면 캐시 히트율 증가
- 동일/유사 질문의 반복 처리 제거

#### 4.9 스트리밍 LLM 응답 + 점진적 TTS

LLM 응답을 **스트리밍**으로 받아 첫 문장이 완성되면 바로 TTS 시작:
- 현재: LLM 전체 응답 → TTS → RTP
- 개선: LLM 스트리밍 → 문장 단위 TTS → RTP
- 체감 지연 대폭 감소 (첫 발화까지 ~1초)

---

## 5. 예상 효과 요약

| Phase | 주요 항목 | 현재 평균 | 목표 | 절감 |
|-------|-----------|-----------|------|------|
| Phase 1 | step_back 조건, greeting/farewell 고정, 캐시 스킵 | 8.69s | ~4.5s | -4.2s |
| Phase 2 | intent+rewrite 병합, RAG/프롬프트 축소 | ~4.5s | ~2.5s | -2.0s |
| Phase 3 | 모델 변경, 스트리밍 TTS | ~2.5s | ~1.5s | -1.0s |

### Phase 1 적용 시 예상 응답 시간 분포

```
 0- 2s:  ~25건  (greeting/farewell/repeat/help 즉시 응답)
 2- 5s:  ~30건  (step_back 제거 + 캐시 최적화)
 5- 8s:  ~15건  (일반 질의)
 8-10s:   ~5건  (복잡한 질의)
10-15s:   ~1건  (매우 복잡)
```

---

## 6. 구현 우선순위

1. **[긴급]** `greeting`/`farewell` 고정 응답 (코드 변경 최소, 효과 최대)
2. **[긴급]** `step_back` 실행 조건 개선 (RAG 0건 시에만)
3. **[중요]** `check_cache` 빈 컬렉션 스킵
4. **[중요]** `classify_intent` + `rewrite_query` 합침 (LLM 1회 호출)
5. **[중요]** RAG 컨텍스트 3건 제한 + 대화 이력 3턴 제한
6. **[선택]** 모델 변경 검토 (`gemini-2.5-flash`)
7. **[선택]** 스트리밍 LLM + 점진적 TTS

---

## 7. 위험 요소

| 항목 | 위험 | 완화 |
|------|------|------|
| greeting 고정 응답 | 페르소나별 인사말 차이 | 페르소나 이름을 템플릿에 삽입 |
| step_back 제거 | RAG 검색 품질 저하 | RAG 0건 시에만 step_back 유지 |
| RAG 3건 제한 | 정보 누락 | top-3이 이미 가장 관련성 높은 결과 |
| intent+rewrite 병합 | 프롬프트 복잡도 증가 | 별도 테스트 케이스로 검증 |
| 대화 이력 3턴 | 맥락 손실 | 전화 상담 특성상 3턴이면 충분 |

---

## 부록: 10초 이상 걸린 대표 케이스

### Case 1: 20.80초 — "기상 기간의 관측값들은 공개되는지 궁금해요?"
- generate_response: 9.7초
- check_cache: 7.2초 (콜드 스타트?)
- step_back: 2.1초
- **개선 적용 시**: check_cache 최적화(-6s) + step_back 제거(-2s) = ~12초 → ~6초

### Case 2: 20.61초 — "접수한 건도 별 이상이 없는데 처리가 되지 않나요?" (complaint)
- generate_response: 12.5초 (RAG 컨텍스트 과다?)
- rewrite_query: 4.7초
- step_back: 2.3초
- **개선 적용 시**: step_back 제거(-2s) + rewrite 병합(-2s) + RAG 축소(-2s) = ~14초

### Case 3: 14.45초 — "여보세요!" (greeting)
- check_greeting_farewell_cache: 6.1초
- generate_response: 3.2초
- rewrite_query: 2.6초
- step_back: 2.3초
- **개선 적용 시**: 고정 응답 → **0.01초**
