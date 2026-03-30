# Intent별 처리 로직 설계

**참조**: `src/ai_voicebot/langgraph/agent.py`, `classify_intent.py`, `response_shortcuts.py`
**최종 수정**: 2026-03-30 (병합 LLM 호출, greeting/farewell KB 노드 반영)

---

## 1. 의도 분류 방식 (classify_intent)

### 1.1 5단계 분류 파이프라인

```
사용자 발화
    │
    ▼
[1단계] 키워드 매칭 (INTENT_KEYWORDS)
    │   "감사합니다"→farewell, "다시 말해줘"→repeat 등
    │   confidence=1.0
    │
    ▼ (매칭 실패)
[2단계] 특수 규칙
    │   인사+질문 패턴 → question (인사 안에 질문 포함 시)
    │   도움 키워드+기관 질문 → question
    │   방문/교통 관련 → question (transfer 아님)
    │
    ▼ (해당 없음)
[3단계] 페르소나 기반 분류
    │   persona.check_query_relevance(similarity_threshold=0.6)
    │   무관 → chitchat + _chitchat_template
    │   관련 → question
    │
    ▼ (LLM 없는 환경 또는 짧은 발화)
[4단계] 기본 폴백
    │   짧은 발화 → question (confidence=0.7)
    │
    ▼ (LLM 사용 가능)
[5단계] LLM 병합 호출 (최적화 4.4)
        단일 LLM 요청으로 intent + search_query 동시 생성
        max_output_tokens=128, JSON 응답
```

### 1.2 LLM 병합 호출 (최적화 4.4)

기존에는 `classify_intent`(LLM 1회) + `rewrite_query`(LLM 1회) = 2회 호출이었으나,
단일 LLM 호출로 의도 분류와 검색 쿼리 변환을 동시 수행한다.

```json
// LLM 요청 프롬프트
"의도 분류 + 검색 쿼리 변환기. JSON으로 답하세요: {intent, search_query}"

// LLM 응답 예시
{"intent": "question", "search_query": "기상감정서 발급 방법"}
```

- **마크다운 코드블록 자동 제거**: LLM이 ````json ... ```` 으로 감싸도 정규식으로 추출
- **유효하지 않은 intent 폴백**: `VALID_INTENTS`에 없으면 → `question` (confidence=0.7)
- `rewrite_query` 노드는 이미 `rewritten_query`가 있으면 LLM 호출 스킵

### 1.3 VALID_INTENTS

```
greeting, farewell, affirm, deny, gratitude, doubt,
positive_reaction, negative_reaction, chitchat, repeat,
clarification, help, question, complaint, transfer,
out_of_scope, nlu_fallback
```

---

## 2. Intent → 노드 라우팅

### 2.1 전체 분기 도표

```
                         ┌──────────────────┐
                         │  classify_intent  │
                         │ (키워드→LLM 병합) │
                         └────────┬─────────┘
                                  │
                                  ▼
                         ┌──────────────────┐
                         │  route_utterance  │
                         │ (레인 결정)       │
                         └────────┬─────────┘
                                  │
                    ┌─────────────┼──────────────────┐
                    ▼             ▼                   ▼
              rag_mode=skip   greeting/farewell     knowledge 레인
                    │             │                   │
                    ▼             ▼                   ▼
           generate_response  greeting_farewell_kb  _route_after_intent
           (RAG 없이 LLM)    (ChromaDB 직접 조회)       │
                                  │             ┌──────┴──────┐
                                  ▼             ▼             ▼
                            update_state   B그룹 반응     check_cache
                                           template      (시맨틱 캐시)
                                                              │
                                                    ┌─────────┼─────────┐
                                                    ▼                   ▼
                                              cache hit          rewrite_query
                                                    │                   │
                                                    ▼                   ▼
                                             update_state        adaptive_rag
                                                                       │
                                                              ┌────────┼────────┐
                                                              ▼                 ▼
                                                         RAG 0건            RAG N건
                                                              │                 │
                                                              ▼                 ▼
                                                         step_back      generate_response
                                                              │                 │
                                                              ▼                 ▼
                                                      generate_response    hitl_alert
                                                                               │
                                                                               ▼
                                                                         update_cache
                                                                               │
                                                                               ▼
                                                                         update_state
                                                                               │
                                                                               ▼
                                                                              END
```

### 2.2 Intent → 다음 노드 매핑 (요약표)

| Intent | 다음 노드 | 처리 방식 |
|--------|-----------|-----------|
| `greeting` | **greeting_farewell_kb** | ChromaDB `greeting` 카테고리에서 직접 조회. LLM 없이 ~0.01초 응답 |
| `farewell` | **greeting_farewell_kb** | ChromaDB `farewell` 카테고리에서 직접 조회 |
| `affirm`, `deny`, `gratitude`, `doubt`, `positive_reaction`, `negative_reaction` | **template_response** | 고정 템플릿 1문장 랜덤 선택 |
| `repeat` | **repeat_response** | 마지막 AI 발화 그대로 재생 |
| `clarification` | **clarification_response** | "조금만 더 말씀해 주세요" 안내 |
| `help` | **help_response** | 가능 기능 안내 (capability 기반) |
| `chitchat` | **generate_response** (RAG 스킵) | LLM으로 짧게 공감 응답, 페르소나 템플릿 우선 |
| `out_of_scope` | **generate_response** (RAG 스킵) | LLM으로 가볍게 답변 |
| `question`, `complaint`, `transfer`, `nlu_fallback` | **check_cache** → RAG 경로 | 시맨틱 캐시 → 쿼리 재작성 → ChromaDB RAG → LLM → HITL |

### 2.3 greeting/farewell KB 노드 (최적화 4.2)

기존에는 LLM을 통해 인사/작별 응답을 생성했으나, ChromaDB에 저장된 인사말을
직접 조회하여 LLM 호출 없이 즉시 응답한다.

```
greeting_farewell_kb 노드:
  1. ChromaDB 'knowledge' 컬렉션에서 owner별 greeting/farewell 문서 조회
  2. 문서 있으면 → 즉시 응답 (confidence=1.0, LLM 스킵)
  3. 문서 없으면 → rewrite_query → adaptive_rag → generate_response 경로로 폴백
```

---

## 3. 시맨틱 캐시 (check_cache)

### 3.1 동작 방식

| 조건 | 처리 |
|---|---|
| `qa_cache` 컬렉션 비어있음 | 즉시 스킵 (벡터 검색 비용 절감, 최적화 4.3) |
| 유사도 ≥ 0.85 + TTL 미만료 + 비폴백 답변 | cache hit → 즉시 응답 |
| 그 외 | cache miss → RAG 경로 진행 |

### 3.2 파라미터

| 파라미터 | 값 | 설명 |
|---|---|---|
| `SIMILARITY_THRESHOLD` | 0.85 | 캐시 히트 임계값 (최적화 4.8: 0.92→0.85) |
| TTL (FAQ) | 86,400초 | 24시간 |
| TTL (기타) | 3,600초 | 1시간 |
| `top_k` | 1 | 최상위 1건만 비교 |

---

## 4. RAG 경로 상세

### 4.1 adaptive_rag 노드

1. **1단계**: ChromaDB 벡터 검색 (`SENTENCE_TOP_K=10`, owner+category 필터)
2. **2-pass 검색**: STT 원문과 rewrite 쿼리가 다르면 양쪽 결과 병합
3. **Small-to-Big Expansion**: 검색된 문장의 상위 문맥 확장
4. **Contextual Compression**: 키워드 매칭으로 관련 문장만 추출 (`COMPRESSION_MAX_CHARS=1200`)
5. **Confidence 산출**: top_score 70% + avg_score 30% 가중 평균 × 1.1

### 4.2 step_back 조건

RAG 결과가 **0건**일 때만 실행 (이전: confidence 임계값 기반 → 제거됨, 최적화 4.1)

### 4.3 generate_response 노드

- LLM에 RAG 컨텍스트 최대 **3건** 전달 (`MAX_RAG_CONTEXT_FOR_LLM=3`)
- 대화 기록 최대 **3턴** (`HISTORY_MAX_TURNS=3`, 최적화 4.6)
- 스트리밍 LLM 응답 → 문장 단위 수집 (최적화 4.9)
- LLM이 정상 답변 + `needs_follow_up=False` → confidence 최소 0.5 보장

### 4.4 HITL 트리거

| 조건 | 동작 |
|---|---|
| `confidence < 0.3` | HITL 요청 (운영자에게 질문 전달) |
| `needs_follow_up = True` | HITL 요청 |
| `intent = greeting/chitchat/out_of_scope` | HITL 면제 |

---

## 5. Intent별 예제

### 5.1 question (RAG 경로)

```
사용자: "지진 정보 알려줘"
→ classify_intent: intent=question, search_query="지진 정보"
→ check_cache: miss
→ rewrite_query: (LLM 병합으로 이미 설정됨, 스킵)
→ adaptive_rag: ChromaDB 검색, 11건 → 압축 → 3건 LLM 전달
→ generate_response: "기상청에서 공식 통보된 지진 정보를 안내해 드립니다..."
→ hitl_alert: confidence=0.5+ → HITL 불필요
→ update_cache → update_state → END
```

### 5.2 greeting (KB 직접 조회)

```
사용자: "안녕하세요"
→ classify_intent: intent=greeting (키워드 매칭, confidence=1.0)
→ greeting_farewell_kb: ChromaDB greeting 문서 조회
→ 응답: "안녕하세요. KT 기상청 AI 봇입니다. 무엇을 도와드릴까요?"
→ update_state → END  (LLM 호출 0회, ~0.01초)
```

### 5.3 chitchat (페르소나 기반)

```
사용자: "오늘 날씨 좋다"
→ classify_intent: persona 분류 → chitchat + _chitchat_template
→ generate_response: 페르소나 템플릿 응답 (LLM 스킵)
→ "네, 좋은 날씨예요. 다른 궁금한 점 있으시면 말씀해 주세요."
→ update_state → END
```

---

## 6. 관련 코드 위치

| 내용 | 파일 |
|---|---|
| 의도 분류 (키워드·LLM 병합) | `src/ai_voicebot/langgraph/nodes/classify_intent.py` |
| Intent → 노드 분기 | `src/ai_voicebot/langgraph/agent.py` — `_route_after_intent`, `_route_after_utterance` |
| Greeting/Farewell KB | `src/ai_voicebot/langgraph/nodes/greeting_farewell_kb.py` |
| 시맨틱 캐시 | `src/ai_voicebot/langgraph/nodes/semantic_cache.py` |
| RAG 검색 | `src/ai_voicebot/langgraph/nodes/adaptive_rag.py` |
| LLM 응답 생성 | `src/ai_voicebot/langgraph/nodes/generate_response.py` |
| HITL 판단 | `src/ai_voicebot/langgraph/nodes/hitl_alert.py` |
| 템플릿/반복/명확화/도움 | `src/ai_voicebot/langgraph/nodes/response_shortcuts.py` |
