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

> 분류 경로 표기: `keyword` = 키워드 매칭, `llm_merged` = LLM 병합 호출, `persona` = 페르소나 유사도

---

### 5.1 question (RAG 경로 — 정상 응답)

```
사용자: "기상감정서 발급하려면 어떻게 해요?"
→ classify_intent: intent=question, search_query="기상감정서 발급 방법"
   path=llm_merged, confidence=0.95
→ check_cache: miss (qa_cache 유사도 0.72 < 0.85)
→ rewrite_query: 이미 search_query 설정됨 → 스킵
→ adaptive_rag: ChromaDB 검색 8건 → Small-to-Big 확장 → 압축 → 3건 LLM 전달
→ generate_response: "기상감정서는 날씨마루 홈페이지에서 온라인으로 신청하실 수 있으며,
                      발급까지 약 7~14일 소요됩니다."
   confidence=0.82, needs_follow_up=False
→ hitl_alert: confidence=0.82 ≥ 0.3 → HITL 불필요
→ update_cache → update_state → END
   (LLM 1회, ~2.5초)
```

---

### 5.2 question (RAG 경로 — 시맨틱 캐시 히트)

```
사용자: "기상감정서 신청 방법 알려줘"  ← 위 질문과 유사
→ classify_intent: intent=question, search_query="기상감정서 신청 방법"
→ check_cache: hit (유사도 0.91 ≥ 0.85, TTL 미만료)
→ 응답: (캐시 저장된 답변 즉시 반환)
→ update_state → END
   (RAG·LLM 스킵, ~0.1초)
```

---

### 5.3 question (RAG 경로 — HITL 에스컬레이션)

```
사용자: "다음 주 수요일 김 대리님 만날 수 있나요?"
→ classify_intent: intent=question, search_query="수요일 김 대리님 미팅 가능 여부"
→ check_cache: miss
→ adaptive_rag: ChromaDB 검색 0건 → step_back 실행
   (step_back: 쿼리 일반화 → 재검색 → 여전히 0건)
→ generate_response: "죄송합니다. 해당 내용은 제가 알지 못하는 내용입니다.
                      다른 도움이 필요하시면 말씀해 주세요."
   needs_follow_up=True, confidence=0.0
→ hitl_alert: needs_follow_up=True → HITL 트리거
   → 운영자 대시보드 🔔 알림 전송
→ update_state → END
   (LLM 1회, ~2.5초 + 운영자 개입 대기)
```

---

### 5.4 greeting (KB 직접 조회)

```
사용자: "안녕하세요"
→ classify_intent: intent=greeting (키워드 "안녕" 매칭, confidence=1.0)
   path=keyword
→ route_utterance: utterance_lane=greeting_farewell
→ greeting_farewell_kb: ChromaDB knowledge 컬렉션 greeting 카테고리 조회
→ 응답: "안녕하세요. KT 기상청 AI 봇입니다. 무엇을 도와드릴까요?"
→ update_state → END
   (LLM 0회, ~0.01초)
```

---

### 5.5 greeting (인사+질문 동시 — question 우선)

```
사용자: "안녕하세요, 내일 날씨 알려주세요"
→ classify_intent: greeting 키워드 감지 → QUESTION_PATTERNS("알려") 포함
   → question으로 오버라이드 (path=keyword_greeting_to_question)
   intent=question, confidence=1.0
→ check_cache → adaptive_rag → generate_response → ...
   (인사 응답 없이 바로 질문 처리)
```

---

### 5.6 farewell (KB 직접 조회)

```
사용자: "감사합니다, 끊을게요"
→ classify_intent: intent=farewell (키워드 "끊을게" 매칭, confidence=1.0)
   path=keyword
→ greeting_farewell_kb: ChromaDB farewell 카테고리 조회
→ 응답: "좋은 하루 보내세요. 이용해 주셔서 감사합니다."
→ update_state → END
   (LLM 0회, ~0.01초)
```

---

### 5.7 affirm (템플릿 응답)

```
사용자: "네, 알겠어요"
→ classify_intent: intent=affirm (키워드 "네" 매칭, confidence=1.0)
   path=keyword
→ template_response: INTENT_RESPONSE_TEMPLATES["affirm"] 중 랜덤 선택
→ 응답: "네, 알겠습니다. 더 필요하시면 말씀해 주세요."
   (또는 "좋습니다. 다른 궁금한 점 있으시면 말씀해 주세요.")
→ update_state → END
   (LLM 0회, ~0.001초)
```

---

### 5.8 deny (템플릿 응답)

```
사용자: "아니요, 필요 없어요"
→ classify_intent: intent=deny (키워드 "아니요" 매칭, confidence=1.0)
   path=keyword
→ template_response: INTENT_RESPONSE_TEMPLATES["deny"] 중 랜덤 선택
→ 응답: "알겠습니다. 다른 건 도와드릴까요?"
→ update_state → END
   (LLM 0회, ~0.001초)
```

---

### 5.9 gratitude (템플릿 응답)

```
사용자: "고마워요, 도움이 많이 됐어요"
→ classify_intent: intent=gratitude (키워드 "고마워요" 매칭, confidence=1.0)
   path=keyword
→ template_response: INTENT_RESPONSE_TEMPLATES["gratitude"] 중 랜덤 선택
→ 응답: "도움이 되었다니 다행이에요. 좋은 하루 되세요."
→ update_state → END
   (LLM 0회, ~0.001초)
```

---

### 5.10 doubt (템플릿 응답)

```
사용자: "글쎄요, 잘 모르겠어요"
→ classify_intent: intent=doubt (키워드 "글쎄요" 매칭, confidence=1.0)
   path=keyword
→ template_response: INTENT_RESPONSE_TEMPLATES["doubt"] 중 랜덤 선택
→ 응답: "괜찮아요. 정하시면 말씀해 주세요."
→ update_state → END
   (LLM 0회, ~0.001초)
```

---

### 5.11 positive_reaction (템플릿 응답)

```
사용자: "좋아요, 맘에 들어요"
→ classify_intent: intent=positive_reaction (키워드 "좋아요" 매칭, confidence=1.0)
   path=keyword
→ template_response: INTENT_RESPONSE_TEMPLATES["positive_reaction"] 중 랜덤 선택
→ 응답: "감사합니다. 더 궁금하신 점 있으시면 편하게 말씀해 주세요."
→ update_state → END
   (LLM 0회, ~0.001초)
```

---

### 5.12 negative_reaction (템플릿 응답)

```
사용자: "별로예요, 답변이 마음에 안 들어요"
→ classify_intent: intent=negative_reaction (키워드 "별로예요" 매칭, confidence=1.0)
   path=keyword
→ template_response: INTENT_RESPONSE_TEMPLATES["negative_reaction"] 중 랜덤 선택
→ 응답: "불편을 드려 죄송합니다. 다른 방법으로 안내해 드릴까요?"
→ update_state → END
   (LLM 0회, ~0.001초)
```

---

### 5.13 repeat (마지막 발화 재생)

```
사용자: "다시 말해줘"
→ classify_intent: intent=repeat (키워드 "다시 말해" 매칭, confidence=1.0)
   path=keyword
→ repeat_response: messages에서 마지막 assistant 발화 추출
→ 응답: (직전 AI 응답 그대로 재생)
   "기상감정서는 날씨마루 홈페이지에서 온라인으로 신청하실 수 있으며..."
→ update_state → END
   (LLM 0회, ~0.001초)

※ 직전 AI 발화 없을 경우: "방금 말씀드린 내용을 다시 안내드릴게요." (기본 문장)
```

---

### 5.14 clarification (명확화 요청)

```
사용자: "무슨 뜻이에요?"
→ classify_intent: intent=clarification (키워드 "무슨 뜻이에요" 매칭, confidence=1.0)
   path=keyword
→ clarification_response: 직전 AI 발화 앞 80자 추출 + 명확화 문장 조합
→ 응답: "제가 '기상감정서는 날씨마루 홈페이지에서 온라인으로...' 말씀드렸는데,
         더 알고 싶으신 게 있으신가요?"
→ update_state → END
   (LLM 0회, ~0.001초)
```

---

### 5.15 help (테넌트 RAG + LLM 항목 선정)

```
사용자: "뭘 도와줄 수 있어요?"
→ classify_intent: intent=help (키워드 "도와줄 수 있어요" 매칭, confidence=1.0)
   path=keyword
→ help_response:
   1. 테넌트 지식베이스 전체 RAG 검색 (top_k=20)
   2. 검색된 문서 최대 14건 → LLM에 전달
   3. LLM이 안내 가능한 항목 최대 5개 JSON으로 선정
      {"items": ["내일 날씨 안내", "태풍 정보", "기상감정서 발급", "찾아오는 길", "상담원 연결"]}
→ 응답: "저는 내일 날씨 안내, 태풍 정보, 기상감정서 발급, 찾아오는 길,
         상담원 연결을 할 수 있어요. 어떤 것을 도와드릴까요?"
→ update_state → END
   (LLM 1회, RAG 포함 ~2초)

※ RAG 0건 시: "어떤 내용이 궁금하신지 말씀해 주시면 안내해 드릴게요." (기본 문장)
```

---

### 5.16 complaint (RAG 경로 + HITL 우선 처리)

```
사용자: "왜 이렇게 답변이 틀려요, 화가 나요"
→ classify_intent: intent=complaint (키워드 "화가 나요" 매칭, confidence=1.0)
   path=keyword
→ check_cache → adaptive_rag → generate_response:
   "불편을 드려 정말 죄송합니다. 말씀하신 내용을 확인해 드리겠습니다."
   confidence=0.45
→ hitl_alert: intent=complaint + confidence=0.45 < 0.5 → HITL 트리거
   → 운영자 대시보드 🔔 알림 전송
→ update_state → END
   (LLM 1회, ~2.5초 + 운영자 개입 권장)
```

---

### 5.17 transfer (즉시 HITL — 운영자 연결)

```
사용자: "담당자 연결해 주세요"
→ classify_intent: intent=transfer (키워드 "담당자" 매칭, confidence=1.0)
   path=keyword
→ check_cache → adaptive_rag → generate_response:
   "담당자 연결 요청을 확인했습니다. 잠시만 기다려 주세요."
→ hitl_alert: intent=transfer → 조건 무관하게 즉시 HITL 트리거
   → 운영자 대시보드 🔔 알림 전송 (reason: "고객이 상담원 연결을 요청했습니다.")
→ update_state → END
   (운영자가 [호 전환] 클릭 시 RTP Bridge 모드 전환, <500ms)
```

---

### 5.18 chitchat (페르소나 기반 — 잡담)

```
사용자: "오늘 날씨 좋다"
→ classify_intent: persona 유사도 검사 → 업무 무관 → chitchat
   path=persona, _chitchat_template 설정
→ route_utterance: utterance_lane=social_direct, rag_mode=skip
→ generate_response: RAG 스킵, LLM에 chitchat 규칙 주입
   ("1~2문장으로 짧게 공감, 한계 멘트 금지")
→ 응답: "네, 정말 좋은 날씨네요. 다른 궁금한 점 있으시면 말씀해 주세요."
→ update_state → END
   (LLM 1회 단, 짧은 응답, ~1초)
```

---

### 5.19 out_of_scope (범위 외 — 고정 멘트)

```
사용자: "오늘 점심 뭐 먹을까요?"
→ classify_intent: persona 유사도 낮음 → out_of_scope
   path=llm_merged, confidence=0.6
→ route_utterance: utterance_lane=social_direct, rag_mode=skip
→ generate_response: RAG 스킵, LLM으로 가볍게 답변
   (chitchat 규칙 적용: 한계 멘트 금지)
→ 응답: "저는 날씨 관련 안내를 전문으로 하고 있어요.
         다른 궁금한 점 있으시면 말씀해 주세요."
→ update_state → END
   (LLM 1회, ~1초 / HITL 억제: social_direct 경로)
```

---

### 5.20 nlu_fallback (분류 불가 — 고정 멘트 + HITL)

```
사용자: "으으으으" (또는 빈 발화, 잡음)
→ classify_intent: 키워드 미매칭, LLM 분류 실패 또는 빈 쿼리
   intent=nlu_fallback, confidence=0.0
→ fallback_response: 고정 멘트 반환
→ 응답: "확인해보겠습니다. 잠시만 기다려 주세요."
   needs_human=True (FALLBACK_NEEDS_HITL_DEFAULT=True)
→ hitl_alert: HITL 트리거
   → 운영자 대시보드 🔔 알림 전송
   (reason: "의도 분류 불명 또는 업무 범위 외 발화. 확인이 필요합니다.")
→ update_state → END
   (LLM 0회, ~0.001초)
```

---

## 5.21 Intent 처리 요약표

| Intent | 분류 경로 | 처리 노드 | LLM 호출 | 응답 시간 | HITL |
|---|---|---|---|---|---|
| `question` (캐시 히트) | llm_merged | check_cache | 0회 | ~0.1초 | ✗ |
| `question` (RAG 정상) | llm_merged | adaptive_rag → generate | 1회 | ~2.5초 | ✗ |
| `question` (모름) | llm_merged | adaptive_rag → generate | 1회 | ~2.5초 | ✅ |
| `greeting` | keyword | greeting_farewell_kb | 0회 | ~0.01초 | ✗ |
| `farewell` | keyword | greeting_farewell_kb | 0회 | ~0.01초 | ✗ |
| `affirm` | keyword | template_response | 0회 | ~0.001초 | ✗ |
| `deny` | keyword | template_response | 0회 | ~0.001초 | ✗ |
| `gratitude` | keyword | template_response | 0회 | ~0.001초 | ✗ |
| `doubt` | keyword | template_response | 0회 | ~0.001초 | ✗ |
| `positive_reaction` | keyword | template_response | 0회 | ~0.001초 | ✗ |
| `negative_reaction` | keyword | template_response | 0회 | ~0.001초 | ✗ |
| `repeat` | keyword | repeat_response | 0회 | ~0.001초 | ✗ |
| `clarification` | keyword | clarification_response | 0회 | ~0.001초 | ✗ |
| `help` | keyword | help_response (RAG+LLM) | 1회 | ~2초 | ✗ |
| `complaint` | keyword | adaptive_rag → generate | 1회 | ~2.5초 | ✅ (conf<0.5) |
| `transfer` | keyword | adaptive_rag → generate | 1회 | ~2.5초 | ✅ 즉시 |
| `chitchat` | persona | generate (RAG 스킵) | 1회 | ~1초 | ✗ |
| `out_of_scope` | llm_merged | generate (RAG 스킵) | 1회 | ~1초 | ✗ |
| `nlu_fallback` | 분류 실패 | fallback_response | 0회 | ~0.001초 | ✅ |

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
