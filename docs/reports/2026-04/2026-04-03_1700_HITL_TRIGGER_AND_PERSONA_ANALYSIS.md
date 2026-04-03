# HITL 발동 조건 점검 및 페르소나 연동 분석

**작성일**: 2026-04-03 17:00  
**상태**: 분석 완료 → 문제점 및 개선 방안 도출  
**관련 파일**: `hitl_alert.py`, `hitl_escalation_policy.py`, `route_utterance.py`, `classify_intent.py`

---

## 1. HITL 발동 전체 흐름

```
사용자 발화
  → classify_intent  (intent, confidence 결정)
  → route_utterance  (utterance_lane, domain_question_signal 결정)
  → [RAG 검색]
  → generate_response  (needs_follow_up 결정)
  → hitl_alert_node  (needs_human, hitl_reason 결정)
  → rag_processor   (WebSocket emit, DB 기록)
```

---

## 2. 현재 HITL 발동 조건 (`hitl_alert.py`)

| 순위 | 조건 | 억제 여부 |
|------|------|-----------|
| 0 | `needs_follow_up=True` (AI가 "알지 못하는 내용" 응답) | 잡담·소셜·비도메인 question은 억제 |
| 1 | `intent == "transfer"` (고객 상담원 요청) | 억제 없음 |
| 2 | `intent == "complaint"` + `confidence < 0.5` | 억제 없음 |
| 3 | `confidence < 0.15` (극도로 낮은 신뢰도) | 잡담·소셜·비도메인 question은 억제 |

### needs_follow_up이 True가 되는 시점 (`generate_response.py`)

```python
# generate_response_node 내부
if intent == "question" and not rag_results and not _is_outbound:
    # RAG 0건 → 고정 멘트 + needs_follow_up=True
    return { "needs_follow_up": True, ... }

elif _is_llm_error_fallback(response):        # LLM 오류
    needs_follow_up = True                     # 소셜/잡담은 False 유지

elif _is_unknown_content_response(response):  # "알지 못하는 내용입니다" 패턴
    needs_follow_up = True                     # 소셜/잡담은 False 유지
```

---

## 3. HITL 억제 핵심: `domain_question_signal`

`suppress_hitl_needs_followup()` 와 `suppress_hitl_low_confidence()` 모두 `domain_question_signal`에 의존합니다.

```python
# hitl_escalation_policy.py
def suppress_hitl_needs_followup(state):
    if is_social_direct_path(state):   # chitchat/out_of_scope 레인
        return True                    # → HITL 억제
    intent = state.get("intent")
    if intent == "question" and not state.get("domain_question_signal"):
        return True                    # → 비도메인 question도 억제
    return False                       # → HITL 발동
```

### `domain_question_signal` 계산 (`route_utterance.py`)

```python
def compute_domain_question_signal(intent, query, org_context):
    if intent != "question":
        return False
    # 1. should_treat_as_question_not_transfer 패턴
    if should_treat_as_question_not_transfer(query):
        return True
    # 2. QUESTION_PATTERNS 키워드 (어떻게, 문의, 알려, 위치, 시간, 가격 등)
    if any(p in q for p in QUESTION_PATTERNS):
        return True
    # 3. org_context에서 기관명·식별 토큰이 발화에 포함되면 도메인으로 간주
    for line in org_context.split("\n"):
        token = value.strip().lower()
        if len(token) >= 2 and token in q:
            return True
    return False
```

---

## 4. 문제점: 페르소나와 HITL 연동 미흡

### 4-1. `domain_question_signal`이 페르소나를 활용하지 않음

현재 도메인 시그널은:
- **범용 QUESTION_PATTERNS**: "어떻게", "문의", "알려", "위치", "시간", "가격" 등 도메인 무관 패턴
- **org_context 토큰**: 설정 파일 기반 기관명

**문제**: 페르소나의 `scope_keywords`(레스토랑: "예약", "파스타", "피자" / 기상청: "날씨", "태풍", "특보")가 `domain_question_signal` 계산에 전혀 반영되지 않음.

예시:
```
1003(이탈리안 비스트로) 발화: "파스타 메뉴 알려주세요"
→ classify_intent: persona scope_keyword "메뉴" → question (정상)
→ route_utterance: QUESTION_PATTERNS에 "알려" 있어서 domain_question_signal=True (우연히 맞음)

1003 발화: "테이블 예약이 가능한가요?"
→ classify_intent: scope_keyword "예약" → question
→ route_utterance: QUESTION_PATTERNS에 "가능" 없음 → domain_question_signal=False → HITL 억제!
```

"테이블 예약이 가능한가요?" → RAG miss → needs_follow_up=True → **suppressed** (비도메인 question으로 판단) → **HITL 미발동**

레스토랑 예약은 명백히 업무 범위 내 질문인데 HITL이 발동하지 않는 구조적 문제입니다.

### 4-2. QUESTION_PATTERNS이 기상청 도메인 편향

```python
QUESTION_PATTERNS = [
    "어떻게", "문의", "알려", "되나요", "인가요", "뭐", "무엇", "있어요",
    "해요", "해주", "하고 싶", "알고 싶", "궁금", "주차", "예약", "영업",
    "시간", "가격", "비용", "위치", "연락처", "예약", "취소",
]
```

이 패턴들은 공공기관/기상청 기준으로 설계된 것들이 포함되어 있어, 레스토랑이나 병원 등에서는 도메인 시그널을 놓칠 수 있음.

### 4-3. 소결

| 시나리오 | 현재 동작 | 올바른 동작 |
|----------|-----------|-------------|
| 기상청: "태풍 특보 알려주세요" | domain=True (QUESTION_PATTERNS "알려") → HITL 정상 | 정상 |
| 기상청: "기상감정서 어디서 신청하나요?" | domain=True ("어디서") → HITL 정상 | 정상 |
| 비스트로: "오늘 저녁 2명 예약 가능한가요?" | domain=**False** (QUESTION_PATTERNS 미매칭) → HITL **억제** | domain=True → HITL 발동해야 |
| 비스트로: "파스타랑 피자 중에 뭐가 맛있어요?" | domain=True ("뭐") → HITL 정상 | 정상 |
| 비스트로: "테이블 창가 자리 있나요?" | domain=**False** → HITL **억제** | domain=True → HITL 발동해야 |

---

## 5. 개선 방안

### 방안 A (권장): `compute_domain_question_signal`에 페르소나 scope_keywords 추가

`route_utterance.py`의 `compute_domain_question_signal`에 페르소나 `scope_keywords` 매칭을 추가합니다.

```python
async def compute_domain_question_signal(intent, query, org_context, persona=None):
    # ... 기존 로직 ...
    # 페르소나 scope_keywords 매칭 추가
    if persona and persona.scope_keywords:
        q_lower = query.lower()
        if any(kw.lower() in q_lower for kw in persona.scope_keywords):
            return True
    return False
```

단, `compute_domain_question_signal`이 현재 동기 함수이고 `route_utterance_node`에서 호출되므로:
- 페르소나 조회는 `classify_intent`에서 이미 로드된 `_loaded_persona`를 state에 저장해 재사용하거나
- `route_utterance_node`를 async로 전환하고 직접 페르소나 조회

### 방안 B (단순): `route_utterance_node`에서 `_persona_owner`로 scope_keywords 조회

```python
async def route_utterance_node(state):
    ...
    # 기존 domain_question_signal 계산 후
    if not domain and intent == "question":
        persona_owner = state.get("_persona_owner") or state.get("_owner") or ""
        if persona_owner:
            from src.ai_voicebot.knowledge.persona_service import get_persona_service
            ps = get_persona_service()
            if ps:
                p = await ps.get_persona(persona_owner)
                if p and p.enabled and p.scope_keywords:
                    q_lower = query.lower()
                    if any(kw.lower() in q_lower for kw in p.scope_keywords):
                        domain = True  # 페르소나 업무 범위 키워드 → 도메인 시그널
```

### 방안 C (중기): classify_intent 결과를 state에 저장해 재활용

`classify_intent`에서 이미 페르소나를 로드하고 scope_keywords 매칭을 했습니다.  
`classify_intent`가 `_persona_scope_matched: bool`을 state에 저장하면,  
`route_utterance`에서 추가 페르소나 조회 없이 이 값을 domain_question_signal 산출에 반영 가능.

---

## 6. 현재 상태 요약

| 항목 | 상태 |
|------|------|
| transfer 요청 → HITL | ✓ 정상 (항상 발동) |
| complaint + 저신뢰 → HITL | ✓ 정상 |
| 기상청 도메인 질문 RAG miss → HITL | ✓ 대부분 정상 (QUESTION_PATTERNS 우연 매칭) |
| 레스토랑 예약/메뉴 질문 RAG miss → HITL | ✗ 미발동 (domain_question_signal=False로 억제) |
| chitchat/잡담 → HITL 억제 | ✓ 정상 |
| 페르소나 scope_keywords → domain_signal 반영 | ✗ 미반영 |

**결론**: 페르소나 인프라(`scope_keywords`)가 분류(classify_intent)에는 반영됐지만,  
HITL 발동 여부를 결정하는 `domain_question_signal` 계산에는 미반영.  
→ 업무 범위 내 질문이지만 QUESTION_PATTERNS에 걸리지 않으면 HITL이 억제될 수 있음.
