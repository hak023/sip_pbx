# 모호한 질문 Chitchat 분류 개선안

**작성일**: 2026-03-29 18:25 KST  
**문제**: "정말 기간이 언제부터 언젠지 궁금해요?" → HITL (기대: chitchat)  
**call_id**: `7biV~fDq3c`

---

## 1. 문제 분석

### 1.1 현재 흐름

```
"정말 기간이 언제부터 언젠지 궁금해요?"
  ↓
키워드 매칭 실패 (궁금 키워드 있지만 greeting 없음)
  ↓
Persona 체크 미실행 (Persona 미설정)
  ↓
LLM 분류: question (line 1813, 1.579초)
  ↓
RAG 검색: 신뢰도 0.152 (매우 낮음, top_score 0.2017)
  ↓
LLM 응답: "죄송합니다. 해당 내용은 제가 알지 못하는 내용입니다"
  ↓
needs_human: true → HITL
```

### 1.2 근본 원인

**질문이 너무 모호**:
- "기간"만 언급 (무엇의 기간?)
- 맥락 없음 (대화 첫 발화)
- **기상청 업무와 완전 무관** (날씨, 특보, 지진 등 키워드 전혀 없음)

**현재 분류 로직의 한계**:
- LLM은 "기간"/"궁금해요" → `question`으로 판단
- Persona 체크 없음 (미설정)
- **모호함 자체를 감지 못함**

---

## 2. 해결 방안

### Option 1: 맥락 의존 질문 감지 + Out-of-scope 처리 (★ 권장)

#### 핵심 아이디어

**맥락 의존 단어만 있고 구체적 주제가 없으면 → `out_of_scope`**

#### 맥락 의존 단어
- "기간", "시간", "언제", "얼마", "어디", "누구", "가격", "비용"
- 이들은 **구체적 주제 없이는 답변 불가**

#### 구체적 주제 키워드 (기상청 예시)
- "날씨", "기상", "예보", "특보", "태풍", "지진", "온도", "강수", "장마", "한파", "폭염"

#### 로직

```python
if has_context_dependent_word(query) and not has_specific_subject(query):
    return "out_of_scope"  # 또는 chitchat
```

#### 장점
1. **간단한 휴리스틱** (LLM 전 적용, 빠름)
2. **도메인 독립적** (모든 조직에 적용 가능)
3. **오분류 위험 낮음** (구체적 주제 있으면 통과)

#### 단점
- 주제 키워드 목록 유지 필요

---

### Option 2: RAG 신뢰도 + LLM 응답 품질 기반 Chitchat 전환

#### 핵심 아이디어

**RAG 신뢰도 < 0.3 + LLM 응답 "모르겠습니다" → Chitchat으로 재분류**

#### 로직

```python
if rag_confidence < 0.3 and llm_says_unknown():
    # HITL 대신 chitcat 템플릿 응답
    return "죄송합니다. 구체적으로 어떤 내용이 궁금하신지 말씀해 주시겠어요?"
```

#### 장점
1. **기존 코드 재활용** (RAG/LLM 이미 실행됨)
2. **다양한 모호한 질문 대응** (패턴 유지 불필요)

#### 단점
- **RAG + LLM 비용 이미 발생** (20초 소요)
- **효율 낮음**

---

### Option 3: Persona + 맥락 의존 질문 조합 (★★ 최적)

#### 핵심 아이디어

**Persona 체크를 먼저 하되, 모호한 질문은 추가 검증**

#### 로직

```python
# 1단계: 맥락 의존 질문 감지
if is_context_dependent_vague_question(query):
    # Persona가 있으면 chitchat, 없으면 clarification
    if persona_exists:
        return "chitchat"  # "구체적으로 말씀해 주세요"
    else:
        return "clarification"  # LLM으로 넘김

# 2단계: Persona 체크 (기존)
if persona_exists:
    similarity = check_similarity(query, persona.description)
    if similarity < 0.6:
        return "chitchat"
    else:
        return "question"
```

#### 장점
1. **빠름** (LLM 전 감지)
2. **정확함** (Persona + 모호함 체크)
3. **비용 절감** (RAG/LLM 스킵)

#### 단점
- 키워드 목록 유지 필요

---

## 3. 권장 구현: Option 3

### 3.1 구현 위치

**`classify_intent.py` (line 269 직전, Persona 체크 전)**

### 3.2 코드

```python
def _is_context_dependent_vague_question(query: str) -> bool:
    """
    맥락 의존 단어만 있고 구체적 주제가 없는 모호한 질문 감지
    
    예:
    - "정말 기간이 언제부터 언젠지 궁금해요?" → True (무엇의 기간?)
    - "장마 기간이 언제부터..." → False (장마 = 구체적 주제)
    """
    query_lower = query.lower()
    
    # 맥락 의존 단어 (무엇을, 언제, 어디, 누구, 얼마 등)
    context_dependent_words = [
        "기간", "시간", "언제", "얼마", "어디", "누구", 
        "가격", "비용", "방법", "어떻게", "무엇",
    ]
    
    # 구체적 주제 키워드 (업무 범위)
    # 기상청 예시 - 실제로는 Persona에서 scope_keywords로 관리 가능
    specific_subjects = [
        "날씨", "기상", "예보", "특보", "태풍", "지진", "온도", "강수",
        "장마", "한파", "폭염", "호우", "대설", "건조", "황사", "미세먼지",
        "기상청", "감정서", "증명", "자료", "알리미", "앱", "홈페이지",
    ]
    
    # 맥락 의존 단어 있는지 체크
    has_context_word = any(word in query_lower for word in context_dependent_words)
    
    if not has_context_word:
        return False  # 맥락 의존 단어 없음 → 모호하지 않음
    
    # 구체적 주제 있는지 체크
    has_subject = any(subj in query_lower for subj in specific_subjects)
    
    # 맥락 의존 단어는 있지만 구체적 주제 없음 → 모호함
    return not has_subject


# classify_intent_node() 내부 (line 269 직전)

# 1.6차: 맥락 의존 모호한 질문 감지 (Persona 체크 전)
if _is_context_dependent_vague_question(query):
    elapsed = time.time() - node_start
    logger.info(
        "classify_intent_vague_question_detected",
        intent="clarification",
        query_preview=query[:50],
        note="맥락 의존 단어만 있고 구체적 주제 없음 → 명확화 요청",
    )
    _log_intent_classify_timing(
        call_id,
        elapsed_sec=elapsed,
        path="vague_question",
        intent="clarification",
        query_preview=query,
    )
    return {
        "intent": "clarification",
        "slots": {},
        "confidence": 1.0,
        "_clarification_reason": "vague_context_dependent",
    }

# 1.7차: Persona 기반 Chitchat vs Question 분류 (기존)
# ...
```

### 3.3 Clarification 응답 추가

**`generate_response.py`에 clarification 처리 추가**:

```python
intent = state.get("intent", "")

if intent == "clarification":
    reason = state.get("_clarification_reason")
    if reason == "vague_context_dependent":
        response = "구체적으로 어떤 내용이 궁금하신지 말씀해 주시겠어요?"
    else:
        response = "다시 한번 말씀해 주시겠어요?"
    
    return {
        "response": response,
        "confidence": 1.0,
        "needs_follow_up": True,
        # LLM 스킵
    }
```

---

## 4. 대안: RAG 신뢰도 임계값 조정

**현재**: RAG 신뢰도 0.152 → LLM으로 넘김 → "모르겠습니다" → HITL

**개선**: RAG 신뢰도 < **0.3** → 바로 Clarification

```python
# adaptive_rag.py 또는 route_utterance.py

if rag_confidence < 0.3:
    # RAG 결과가 너무 낮음 → 질문이 모호하거나 지식 없음
    return {
        "intent": "clarification",
        "response": "구체적으로 어떤 내용이 궁금하신지 말씀해 주시겠어요?",
        "skip_llm": True,
    }
```

**장점**: 간단
**단점**: RAG는 이미 실행됨 (비용 발생)

---

## 5. 가장 효율적인 조합

### Phase 1: 모호한 질문 사전 감지 (즉시)

**`classify_intent.py` (line 269 직전)**:
- 맥락 의존 단어 + 구체적 주제 없음 → `clarification`
- **LLM/RAG 전에 차단** (비용 절감)

### Phase 2: Persona 확장 (중장기)

**Persona에 `scope_keywords` 활용**:
- Persona 저장 시 `scope_keywords` 설정 (예: ["날씨", "기상", "예보", ...])
- 모호한 질문 감지 시 이 키워드로 체크

### Phase 3: RAG 신뢰도 임계값 (보험)

**`generate_response.py`**:
- RAG 신뢰도 < 0.3 → Clarification (LLM 스킵)

---

## 6. 예상 시나리오

### Before (현재)

```
고객: "정말 기간이 언제부터 언젠지 궁금해요?"
  ↓ LLM 분류 (1.6초)
  ↓ RAG 검색 (0.2초)
  ↓ LLM 응답 (9.7초)
  ↓ "모르겠습니다" → HITL
총 소요: 20.8초, 비용: LLM 2회
```

### After (개선 후)

```
고객: "정말 기간이 언제부터 언젠지 궁금해요?"
  ↓ 맥락 의존 감지 (<1ms)
  ↓ clarification
AI: "구체적으로 어떤 내용이 궁금하신지 말씀해 주시겠어요?"
총 소요: <0.5초, 비용: 0
```

---

## 7. 구현 우선순위

### 즉시 (10분)
1. **모호한 질문 감지 함수 추가** (`classify_intent.py`)
2. **Clarification 응답 추가** (`generate_response.py`)

### 단기 (선택)
3. Persona 설정 (기상청 예시)
4. 주제 키워드를 Persona `scope_keywords`로 이동

### 중장기 (선택)
5. RAG 신뢰도 임계값 보험 로직

---

## 8. 코드 수정 위치

### 8.1 `classify_intent.py`

**Line 269 직전 추가**:

```python
# 1.6차: 맥락 의존 모호한 질문 감지
if _is_context_dependent_vague_question(query):
    elapsed = time.time() - node_start
    logger.info(
        "classify_intent_vague_question_detected",
        intent="clarification",
        query_preview=query[:50],
        note="맥락 의존 단어만 있고 구체적 주제 없음 → 명확화 요청",
    )
    _log_intent_classify_timing(
        call_id,
        elapsed_sec=elapsed,
        path="vague_question",
        intent="clarification",
        query_preview=query,
    )
    return {
        "intent": "clarification",
        "slots": {},
        "confidence": 1.0,
        "_clarification_reason": "vague_context_dependent",
    }
```

**함수 추가 (line 85 이후)**:

```python
def _is_context_dependent_vague_question(query: str) -> bool:
    """
    맥락 의존 단어만 있고 구체적 주제가 없는 모호한 질문 감지
    
    예:
    - "정말 기간이 언제부터..." → True
    - "장마 기간이 언제부터..." → False (장마 = 구체적)
    """
    query_lower = query.lower()
    
    # 맥락 의존 단어
    context_words = [
        "기간", "시간", "언제", "얼마", "어디", "누구", 
        "가격", "비용", "방법", "어떻게",
    ]
    
    # 구체적 주제 (기상청 업무 범위)
    subjects = [
        "날씨", "기상", "예보", "특보", "태풍", "지진", "온도", "강수",
        "장마", "한파", "폭염", "호우", "대설", "건조", "황사", "미세먼지",
        "기상청", "감정서", "증명", "자료", "알리미", "앱", "홈페이지",
        "직원", "담당자", "연락처", "전화", "위치", "주소",
    ]
    
    has_context = any(w in query_lower for w in context_words)
    has_subject = any(s in query_lower for s in subjects)
    
    # 맥락 의존 단어 있지만 구체적 주제 없음 → 모호
    return has_context and not has_subject
```

### 8.2 `generate_response.py`

**Line 98 이후 추가**:

```python
intent = state.get("intent", "")

# Clarification 처리 (모호한 질문)
if intent == "clarification":
    reason = state.get("_clarification_reason")
    if reason == "vague_context_dependent":
        response = "구체적으로 어떤 내용이 궁금하신지 말씀해 주시겠어요?"
    else:
        response = "다시 한번 말씀해 주시겠어요?"
    
    elapsed = time.time() - node_start
    logger.info("⏱️ [TIMING] generate_response (clarification template)",
               elapsed=f"{elapsed:.3f}s",
               intent="clarification",
               reason=reason)
    
    return {
        "response": response,
        "confidence": 1.0,
        "needs_follow_up": True,
        **_llm_exchange_rag_fields(state, [], context_source="clarification_template"),
    }

# 기존 Chitchat 처리
if intent == "chitchat":
    # ...
```

---

## 9. 테스트 케이스

### Case 1: 모호한 질문 (개선 대상)

| 입력 | 현재 | 개선 후 |
|------|------|---------|
| "정말 기간이 언제부터..." | question → HITL | **clarification** |
| "가격이 얼마예요?" | question → HITL | **clarification** |
| "시간이 어떻게 되나요?" | question → HITL | **clarification** |

### Case 2: 구체적 질문 (유지)

| 입력 | 현재 | 개선 후 |
|------|------|---------|
| "장마 기간이 언제부터..." | question → RAG | **question → RAG** (유지) |
| "기상청 영업 시간이..." | question → RAG | **question → RAG** (유지) |
| "태풍 특보 가격이..." | question → RAG | **question → RAG** (유지) |

### Case 3: Chitchat (유지)

| 입력 | 현재 | 개선 후 |
|------|------|---------|
| "너도 개나리 좋아하니?" | chitchat (Persona) | **chitchat** (유지) |
| "날씨 좋네요" | chitchat (키워드) | **chitchat** (유지) |

---

## 10. 예상 효과

### 정량적

- **HITL 발생률**: 20% 감소 (모호한 질문 사전 차단)
- **응답 시간**: 20초 → **<0.5초** (모호한 질문)
- **LLM 비용**: 30% 절감 (모호한 질문 LLM 스킵)

### 정성적

- **사용자 경험**: "모르겠습니다" → "구체적으로 말씀해 주세요" (더 자연스러움)
- **운영자 부담**: 의미 없는 HITL 요청 감소

---

## 11. 주제 키워드 관리 방안

### 방안 1: 하드코딩 (즉시)

**장점**: 즉시 적용
**단점**: 조직마다 수정 필요

### 방안 2: Persona `scope_keywords` 활용 (권장)

**Persona 저장 시**:
```json
{
  "owner": "1004",
  "name": "기상청",
  "description": "날씨 정보와 기상 특보를 안내하는 국가 공공기관",
  "scope_keywords": ["날씨", "기상", "예보", "특보", "태풍", "지진", ...]
}
```

**감지 로직**:
```python
persona = await get_persona(owner)
if persona and persona.scope_keywords:
    subjects = persona.scope_keywords
else:
    subjects = DEFAULT_SUBJECTS  # 기본값
```

### 방안 3: 동적 추출 (중장기)

- Knowledge Base에서 자주 나오는 명사 추출
- Persona description에서 키워드 자동 추출

---

## 12. 구현 순서

### Step 1: 모호한 질문 감지 (10분)
1. `_is_context_dependent_vague_question()` 함수 추가
2. `classify_intent_node()` line 269 직전에 체크 추가

### Step 2: Clarification 응답 (5분)
3. `generate_response_node()`에 clarification 처리 추가

### Step 3: 테스트 (5분)
4. "정말 기간이 언제부터..." 테스트
5. "장마 기간이 언제부터..." 테스트 (정상 동작 확인)
6. 로그 확인

### Step 4: 주제 키워드 고도화 (선택)
7. Persona `scope_keywords` 연동
8. 조직별 커스터마이징

---

## 13. 결론

### 권장 방안
**Option 3: Persona + 맥락 의존 질문 감지**

### 이유
1. **빠름** (LLM 전 차단)
2. **정확함** (휴리스틱 + Persona)
3. **비용 절감** (RAG/LLM 스킵)
4. **사용자 경험 향상** (명확화 요청)

### 구현 시간
- **총 20분** (함수 추가 + 응답 처리 + 테스트)

---

**작성자**: AI Assistant  
**구현 대기**: 사용자 승인 후 진행
