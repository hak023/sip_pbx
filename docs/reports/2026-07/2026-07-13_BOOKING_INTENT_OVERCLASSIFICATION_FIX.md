# Booking Intent 과잉 분류 버그 수정

**작성일**: 2026-07-13  
**버전**: 1.0  
**상태**: 완료  
**관련 문서**:
- [INTENT_HANDLING_DESIGN.md](../../design/INTENT_HANDLING_DESIGN.md)
- [booking_intent_heuristic.py](../../../src/ai_voicebot/langgraph/booking_intent_heuristic.py)
- [classify_intent.py](../../../src/ai_voicebot/langgraph/nodes/classify_intent.py)

---

## 1. 버그 요약

**증상**: "가게에 주차 가능한가요?" 질문이 예약(booking) 의도로 오분류되어 RAG 검색이 스킵됨.

**로그 근거**:
```
classify_intent_persona_scope_keyword → intent="question" (정확)
route_utterance_booking_direct        → intent="booking"  (오분류)
booking_agent_node_enter              → RAG 스킵, booking_agent 실행
```

---

## 2. 근본 원인

`booking_intent_heuristic.py`의 `apply_booking_intent_override`에서 `booking_context`가 활성 상태이면 모든 `question` 의도를 무조건 `booking`으로 승격하는 로직:

```python
if booking_active and intent in _PROMOTABLE_FROM:
    return "booking", "booking_context_active"  # 발화 내용 무관하게 무조건 승격
```

추가 문제: `classify_intent`의 1차/2차 fast-path가 LLM을 건너뛰고 `question`을 반환해도, `merge_booking_intent_into_result`에서 즉시 `booking`으로 덮어씌워짐.

```
0.5차: "LLM 3차 분류 시 booking 힌트 주입 예정"이라고 로그 → LLM 실행 의도
1차:   scope_keyword 매칭 → LLM 건너뜀
merge: booking_active=True → question을 booking으로 강제 승격 (LLM 실행 안됨)
```

---

## 3. 수정 내용

### 3.1 booking_agent.py — `last_activity_at` 타임스탬프 기록

```python
booking_context["last_activity_at"] = datetime.utcnow().isoformat() + "Z"
```

booking_agent가 응답할 때마다 마지막 활동 시각을 저장.

### 3.2 booking_intent_heuristic.py — 2개 게이트 추가

**Gate 1: `_llm_classified` 플래그**
```python
if result.get("_llm_classified"):
    return result  # LLM이 직접 분류한 경우 booking 승격 차단
```

**Gate 2: TTL 만료 (15분)**
```python
def _is_booking_context_expired(bc: dict) -> bool:
    # last_activity_at 기준 BOOKING_CONTEXT_TTL_MINUTES(기본 15분) 초과 시 True
```

환경변수 `BOOKING_CONTEXT_TTL_MINUTES`로 임계값 조정 가능.

### 3.3 classify_intent.py — booking_active 시 fast-path 스킵

`_booking_active=True`이면 1차(scope_keyword), 2차(persona_question) fast-path를 건너뛰고 LLM 3차 분류 강제 실행:

```python
elif _booking_active:
    logger.info("classify_intent_booking_active_skip_scope_keyword", ...)
    # LLM 3차 분류로 fall-through
```

### 3.4 classify_intent.py — LLM 프롬프트 명확화

```
"예약 대화 진행 중. 예약과 무관한 정보 질문(주차, 메뉴, 위치 등)이면 question으로 분류"
```

### 3.5 classify_intent.py — `_llm_classified=True` 플래그

LLM 3차 분류 결과에 `_llm_classified=True`를 포함하여 `merge_booking_intent_into_result`에서 booking 승격을 차단.

---

## 4. 수정 후 흐름

```
booking_active=True + "가게에 주차 가능한가요?"

[Gate 2] TTL 확인 → 15분 이내 → booking_active=True 유지
[1차] scope_keyword "주차" 매칭
      → booking_active=True 감지 → LLM 3차 강제 (fast-path 스킵)
[LLM 3차] 힌트: "예약 무관 질문이면 question"
           → intent="question", _llm_classified=True
[merge] _llm_classified=True → booking 승격 차단
[route] question → RAG 조회 → 정상 답변 ✅
```

---

## 5. 검증

```
TTL=15 min
20min elapsed: True  (기대: True)  ✅
just now: False      (기대: False) ✅
no timestamp: False  (기대: False, 레거시 호환) ✅
_llm_classified=True intent: question  (기대: question) ✅
no _llm_classified intent: booking     (기대: booking, 기존 동작 유지) ✅
```

---

## 6. 영향 범위

| 경로                                   | 변경                                            |
| -------------------------------------- | ----------------------------------------------- |
| booking_active + scope_keyword 매칭    | fast-path 스킵 → LLM 3차 실행 (지연 +100~300ms) |
| booking_active + persona_question 매칭 | fast-path 스킵 → LLM 3차 실행                   |
| booking_active + TTL 초과              | booking_active=False → fast-path 정상 작동      |
| affirm/deny + booking_active           | 기존 동작 유지 (단답 booking 유지)              |

*최종 업데이트: 2026-07-13*
