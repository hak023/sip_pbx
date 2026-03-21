# Intent별 처리 로직 상세 (예제·도표)

**참조**: `src/ai_voicebot/langgraph/agent.py` (`_route_after_intent`), `classify_intent.py`, `response_shortcuts.py`  
**관련**: [SYSTEM_OVERVIEW.md](../SYSTEM_OVERVIEW.md) — 대화 파이프라인 개요

---

## 1. Intent → 다음 노드 매핑 (요약표)

| Intent | 다음 노드 | 설명 |
|--------|-----------|------|
| `farewell` | **update_state** | 작별 → 상태만 갱신 후 종료 (별도 응답 없음 또는 짧은 인사) |
| `greeting` | **generate_response** | 인사 → RAG/캐시 없이 LLM이 인사 응답 생성 |
| `affirm`, `deny`, `gratitude`, `doubt`, `positive_reaction`, `negative_reaction` | **template_response** | 반응/피드백 → 고정 템플릿 문장 1개 랜덤 선택 |
| `repeat` | **repeat_response** | "다시 말해줘" → 마지막 AI 발화 그대로 반복 |
| `clarification` | **clarification_response** | "무슨 뜻이에요" → 안내 문장 1개 |
| `help` | **help_response** | "뭘 할 수 있어요" → 도움말/가능 기능 안내 |
| `out_of_scope`, `nlu_fallback` | **fallback_response** | 범위 외/분류 실패 → 고정 멘트 + (선택) HITL |
| `chitchat` | **generate_response** | 잡담 → RAG 없이 LLM 응답 |
| `question`, `complaint`, `transfer`, `unknown` | **check_cache** | 질문/불만/전환 요청/미분류 → 시맨틱 캐시 → RAG → LLM |

---

## 2. 전체 분기 도표

```
                    ┌─────────────────────┐
                    │   classify_intent   │
                    │   (키워드 or LLM)   │
                    └──────────┬──────────┘
                               │
         ┌─────────────────────┼─────────────────────┐
         │                     │                     │
         ▼                     ▼                     ▼
   farewell              greeting              B 그룹 반응
         │                     │                (affirm, deny,
         ▼                     ▼                gratitude, doubt,
   update_state        generate_response      positive/negative)
         │                     │                     │
         │                     │                     ▼
         │                     │              template_response
         │                     │                     │
         ▼                     ▼                     ▼
   [대화 상태만 갱신]    [인사 응답 생성]      [템플릿 1문장]
         │                     │                     │
         └─────────────────────┴─────────────────────┘
                               │
                               ▼
                         update_state → END
                               │
    ┌──────────────────────────┼──────────────────────────┐
    │                          │                          │
    ▼                          ▼                          ▼
 repeat                 clarification                 help
    │                          │                          │
    ▼                          ▼                          ▼
repeat_response      clarification_response      help_response
(마지막 AI 발화 반복)   (조금만 더 말씀해 주세요)   (가능 기능 안내)
    │                          │                          │
    └──────────────────────────┴──────────────────────────┘
                               │
                               ▼
                    out_of_scope / nlu_fallback
                               │
                               ▼
                      fallback_response
                    (확인해보겠습니다… / HITL)
                               │
    ┌──────────────────────────┴──────────────────────────┐
    │                                                      │
    ▼                                                      ▼
chitchat                                    question, complaint,
    │                                        transfer, unknown
    ▼                                                      │
generate_response                                          ▼
(RAG 없이 LLM)                                    check_cache
                                                          │
                                            ── cache hit ──► update_state
                                            ── cache miss ──► rewrite_query
                                                                  → adaptive_rag
                                                                  → (confidence<0.4 → step_back)
                                                                  → generate_response
                                                                  → hitl_alert(필요 시)
                                                                  → update_cache → update_state
```

---

## 3. Intent별 예제 및 처리 내용

### 3.1 farewell (작별)

- **예시 발화**: "감사합니다", "고마워요", "끊을게요", "그만할게요", "바이바이"
- **다음 노드**: `update_state` → 곧바로 종료. (별도 TTS 응답은 파이프라인 설계에 따라 생략되거나 짧은 인사만 재생)
- **예시 동작**:  
  사용자: "감사합니다. 끊을게요."  
  → intent=farewell  
  → update_state만 수행 후 턴 종료 (필요 시 "안녕히 가세요" 등 짧은 인사는 다른 레이어에서 처리 가능)

---

### 3.2 greeting (인사)

- **예시 발화**: "안녕하세요", "여보세요", "반갑습니다"
- **주의**: "안녕하세요, 영업시간이 궁금해요"처럼 **질문 패턴이 같이 있으면** `question`으로 분류되어 RAG 경로로 감.
- **다음 노드**: `generate_response` (RAG/캐시 없이 LLM이 인사 응답)
- **예시 동작**:  
  사용자: "안녕하세요."  
  → intent=greeting  
  → generate_response  
  → AI: "안녕하세요. 무엇을 도와드릴까요?" (등 LLM 생성 인사)

---

### 3.3 B 그룹 반응/피드백 (affirm, deny, gratitude, doubt, positive_reaction, negative_reaction)

- **예시 발화**  
  - affirm: "네", "예", "알겠어요", "좋아요"  
  - deny: "아니요", "필요 없어요", "취소할게요"  
  - gratitude: "감사해요", "고마워요"  
  - doubt: "글쎄요", "잘 모르겠어요"  
  - positive_reaction: "좋아요", "맘에 들어요"  
  - negative_reaction: "별로예요", "안 좋아요"
- **다음 노드**: `template_response` → intent별 **고정 템플릿**에서 랜덤 1문장 선택.
- **예시 응답 (템플릿)**  
  - affirm: "네, 알겠습니다. 더 필요하시면 말씀해 주세요."  
  - deny: "알겠습니다. 다른 건 도와드릴까요?"  
  - gratitude: "천만에요. 더 필요하시면 말씀해 주세요."  
  - negative_reaction: "불편을 드려 죄송합니다. 다른 방법으로 안내해 드릴까요?"

---

### 3.4 repeat (다시 말해줘)

- **예시 발화**: "다시 말해줘", "뭐라고?", "한번 더", "못 들었어요"
- **다음 노드**: `repeat_response` → **마지막 AI 발화**를 그대로 다시 재생. 없으면 "방금 말씀드린 내용을 다시 안내드릴게요."
- **예시 동작**:  
  이전 턴 AI: "평일 오전 9시부터 오후 6시까지 영업합니다."  
  사용자: "다시 말해줘"  
  → intent=repeat  
  → repeat_response  
  → 동일 문장 그대로 TTS 재생

---

### 3.5 clarification (무슨 뜻이에요)

- **예시 발화**: "무슨 뜻이에요", "뭔 소리야", "이해가 안 가요", "어느 부분이요"
- **다음 노드**: `clarification_response` → "어떤 점이 궁금하신지 조금만 더 말씀해 주시면 안내해 드릴게요." 등 고정 안내.

---

### 3.6 help (도와줘 / 뭘 할 수 있어요)

- **예시 발화**: "도와줘", "어떻게 해요", "뭘 할 수 있어요"
- **다음 노드**: `help_response` → "어떤 내용이 궁금하신지 말씀해 주시면 안내해 드릴게요." 또는 capability 기반 도움말.

---

### 3.7 out_of_scope / nlu_fallback (범위 외·분류 실패)

- **예시**: 의도 분류 실패, 업무 범위 밖 발화, 빈 발화 등.
- **다음 노드**: `fallback_response`  
  - 고정 멘트: "확인해보겠습니다. 잠시만 기다려 주세요."  
  - (설정에 따라) HITL 요청으로 운영자에게 전달.
- **예시 동작**:  
  사용자: (노이즈 또는 인식 불가)  
  → intent=nlu_fallback  
  → fallback_response  
  → "확인해보겠습니다. 잠시만 기다려 주세요." + HITL 알림(옵션)

---

### 3.8 chitchat (잡담)

- **예시 발화**: "오늘 날씨 좋다", "요즘 바빠?" (질문이 아닌 일상 말)
- **다음 노드**: `generate_response` (RAG·캐시 없이 LLM이 짧게 응답).
- **예시 동작**:  
  사용자: "오늘 날씨 좋네요."  
  → intent=chitchat  
  → generate_response  
  → AI: "네, 좋은 날씨예요. 다른 궁금한 점 있으시면 말씀해 주세요." (등)

---

### 3.9 question, complaint, transfer, unknown (RAG 경로)

- **예시 발화**  
  - question: "영업시간이 언제예요?", "오늘 날씨 알려줘"  
  - complaint: "불만이에요", "왜 이래요"  
  - transfer: "담당자 연결해 줘", "사람이랑 통화하고 싶어요"
- **다음 노드**: `check_cache` → (미스 시) `rewrite_query` → `adaptive_rag` → (confidence<0.4면 `step_back`) → `generate_response` → (필요 시) `hitl_alert` → `update_cache` → `update_state`.
- **흐름 요약**  
  1. 시맨틱 캐시 조회 → 히트 시 캐시 응답으로 즉시 응답.  
  2. 미스 시 쿼리 rewrite → ChromaDB RAG 검색 → 검색 결과 + 대화 기록으로 LLM 응답 생성.  
  3. RAG 신뢰도가 낮으면 step_back(재검색) 또는 HITL 요청.

**예시 (question)**  
- 사용자: "오늘 날씨 알려줘"  
- intent=question  
- check_cache (미스) → rewrite_query → adaptive_rag (지식 검색) → generate_response  
- AI: "오늘 날씨 예보는 기상청 홈페이지에서 확인하실 수 있습니다. …"

**예시 (transfer)**  
- 사용자: "기상청 담당자 연결해 줘"  
- intent=transfer  
- 동일 RAG 경로를 타되, transfer 의도에 맞는 응답(연결 안내·전환 시도 등)은 LLM/전환 로직에서 처리.

---

## 4. 의도 분류 방식 (classify_intent)

- **1차**: **키워드 매칭** (`INTENT_KEYWORDS`) — "감사합니다" → farewell, "다시 말해줘" → repeat 등.  
  - 단, "안녕하세요" + 질문 패턴(QUESTION_PATTERNS)이 있으면 **question** 우선.
- **2차**: LLM 없으면 짧은 발화는 **question**으로 간주.
- **3차**: **LLM 분류** — 키워드로 안 잡히면 LLM에 "가능한 의도: greeting, farewell, …" 프롬프트로 한 단어 분류.

가능한 의도 집합:  
`greeting`, `farewell`, `affirm`, `deny`, `gratitude`, `doubt`, `positive_reaction`, `negative_reaction`, `chitchat`, `repeat`, `clarification`, `help`, `question`, `complaint`, `transfer`, `out_of_scope`, `nlu_fallback`.

---

## 5. 관련 코드 위치

| 내용 | 파일 |
|------|------|
| Intent → 다음 노드 분기 | `src/ai_voicebot/langgraph/agent.py` — `_route_after_intent` |
| 의도 분류 (키워드·LLM) | `src/ai_voicebot/langgraph/nodes/classify_intent.py` |
| B 그룹 템플릿·repeat/clarification/help/fallback | `src/ai_voicebot/langgraph/nodes/response_shortcuts.py` |
| RAG·캐시·LLM 경로 | `agent.py` (check_cache → rewrite_query → adaptive_rag → generate_response 등) |

이 문서는 **intent별 처리 로직**을 예제와 도표로 정리한 자료이며, 시스템 전체 개요는 [SYSTEM_OVERVIEW.md](../SYSTEM_OVERVIEW.md)를 참고하면 됩니다.
