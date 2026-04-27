# search_faq Tool 구현 리포트

- **작성일**: 2026-04-09 18:50
- **상태**: 구현 완료
- **관련 문서**: `docs/reports/2026-04/2026-04-09_1400_VOICEBOT_TOOL_EXPANSION_BEYOND_BOOKING.md` (B-1)
- **변경 파일**:
  - `sip-pbx/src/ai_voicebot/langgraph/tools/booking_tools.py`
  - `sip-pbx/src/ai_voicebot/langgraph/nodes/booking_agent.py`
  - `sip-pbx/src/ai_voicebot/langgraph/nodes/classify_intent.py`

---

## 1. 배경 및 목적

### 문제 정의

기존 시스템에서 지식베이스(KB) 검색은 두 개의 분리된 경로로 동작하고 있었다.

```
question intent  → adaptive_rag 노드 → rag_engine.search() (파이프라인 인스턴스)
booking intent   → booking_agent_node
                     └─ search_knowledge_tool
                           └─ VectorDB(owner=owner)  ← 매번 새 인스턴스 생성 (문제)
```

이로 인해 다음 문제가 발생했다.

1. **인스턴스 불일치**: `booking_agent` 내 KB 검색이 파이프라인의 RAG 엔진을 재사용하지 못하고 매번 새 VectorDB 인스턴스를 생성 → 커넥션 오버헤드, 설정 불일치 위험
2. **예약 대화 흐름 단절**: 예약 진행 중 고객이 "예약하고 주차는 되나요?" 같은 혼합 질문을 하면 `classify_intent`가 `question`으로 분류 → `adaptive_rag` 경로로 우회 → 예약 컨텍스트(날짜, 인원 등) 소실
3. **category 필터 미지원**: `search_knowledge_tool`에 카테고리 필터가 없어 전체 KB를 검색해야 했음

---

## 2. 설계 결정

### 핵심: ContextVar 기반 RAG 엔진 공유

LangChain `@tool` 함수는 signature를 LLM JSON Schema로 노출하므로 `rag_engine` 같은 비직렬화 객체를 인자로 전달할 수 없다. 이를 해결하기 위해 Python `contextvars.ContextVar`를 활용한다.

```
booking_agent_node 진입 시:
  _RAG_ENGINE_CONTEXT.set(state["_rag_engine"])   ← 파이프라인 인스턴스 주입

_search_knowledge() 실행 시:
  rag_engine = _RAG_ENGINE_CONTEXT.get()           ← 동일 인스턴스 획득
  rag_engine.search(query, owner_filter=owner)
```

**ContextVar 동시성 안전성**: asyncio Task 단위로 격리되므로 동시 통화 간 간섭 없음.

### 2단계 탐색 구조

```
1순위: _RAG_ENGINE_CONTEXT.get() → rag_engine.search()
       (adaptive_rag와 동일 인스턴스, 설정·캐시·커넥션 재사용)
       ↓ 실패 or None (파이프라인 미구성 환경)
2순위: VectorDB(owner=owner) 직접 접근 (기존 fallback 유지)
```

### 예약 흐름 유지 (0.5차 분류)

```
booking_context 활성 상태
  ├─ 흐름 전환 키워드 없음 → booking intent 즉시 반환 (LLM 스킵)
  └─ 흐름 전환 키워드 감지 (끝/상담원/화나 등) → LLM 분류 위임
```

---

## 3. 구현 상세

### 3-1. `booking_tools.py` — ContextVar 및 `_search_knowledge` 개선

#### ContextVar 선언 (모듈 최상위)

```python
from contextvars import ContextVar
from typing import Any, Optional

_RAG_ENGINE_CONTEXT: ContextVar[Optional[Any]] = ContextVar("_rag_engine_ctx", default=None)
```

#### `_search_knowledge` 함수 개선

| 항목 | 기존 | 변경 |
|------|------|------|
| 인자 | `owner, query` | `owner, query, category=""` |
| 1순위 검색 | 없음 (항상 VectorDB 직접) | `_RAG_ENGINE_CONTEXT` → `rag_engine.search()` |
| 2순위 검색 | `VectorDB(owner=owner)` | 동일 (fallback으로 유지) |
| 카테고리 필터 | 없음 | `category` 파라미터 → where 필터 적용 |
| 응답 필드 | `found, query, snippets` | `found, query, category, source, snippets` |
| 로그 | 없음 | `hit_count`, `source` 기록 |

**`category` 파라미터 활용 예시:**
```
LLM이 호출: search_knowledge_tool(owner="1004", query="주차", category="FAQ")
  → ChromaDB where={"category": "FAQ"} 필터로 정밀 검색
```

빈 문자열이면 전체 KB 대상 검색 (기존 동작과 동일).

**응답 구조:**

```json
// 검색 성공
{
  "found": true,
  "query": "주차",
  "category": "FAQ",
  "source": "rag_engine",
  "snippets": ["지하 1층 무료 주차 가능합니다.", ...]
}

// 검색 실패
{
  "found": false,
  "query": "주차",
  "category": "FAQ",
  "message": "서비스에서 '주차'에 대한 정보를 찾지 못했습니다. 직접 문의해 주세요."
}
```

---

### 3-2. `booking_agent_node` — RAG 엔진 주입

```python
from src.ai_voicebot.langgraph.tools.booking_tools import BOOKING_TOOLS, _RAG_ENGINE_CONTEXT

# 노드 진입 시 ContextVar 설정
rag_engine = state.get("_rag_engine")
_rag_ctx_token = _RAG_ENGINE_CONTEXT.set(rag_engine)

try:
    llm_with_tools = raw_llm.bind_tools(BOOKING_TOOLS)
except Exception as e:
    _RAG_ENGINE_CONTEXT.reset(_rag_ctx_token)  # 예외 시에도 정리
    return await _fallback_text_booking(...)

# ... tool call loop ...

# 노드 완료 시 ContextVar 정리
_RAG_ENGINE_CONTEXT.reset(_rag_ctx_token)
```

로그에 `rag_engine_injected: bool` 필드 추가하여 주입 여부 추적 가능.

---

### 3-3. `classify_intent.py` — 예약 진행 중 혼합 질문 처리 (0.5차 분류)

기존 분류 흐름:
```
0차: _BOOKING_KEYWORDS 조기 분류 (비활성화)
→ 1차: 페르소나 scope_keywords 매칭
→ 2차: 페르소나 유사도
→ 3차: LLM 분류
```

변경 후 흐름:
```
0차: _BOOKING_KEYWORDS 조기 분류 (비활성화)
→ 0.5차: booking_context 활성 상태 확인  ← NEW
→ 1차: 페르소나 scope_keywords 매칭
→ 2차: 페르소나 유사도
→ 3차: LLM 분류
```

**0.5차 로직:**

```python
_BOOKING_CONTEXT_BREAK_KEYWORDS = frozenset([
    "끊", "끝", "종료", "취소할게", "그만", "나중에", "다시",  # farewell 신호
    "화나", "짜증", "이상해", "왜이래", "불만",               # complaint 신호
    "연결해줘", "상담원", "사람", "직원",                     # transfer 신호
])

_booking_ctx = state.get("booking_context") or {}
_booking_active = bool(_booking_ctx.get("messages") or _booking_ctx.get("collected_slots"))

if _booking_active:
    _break_kw = next((kw for kw in _BOOKING_CONTEXT_BREAK_KEYWORDS if kw in _query_lower), None)
    if not _break_kw:
        return {"intent": "booking", "slots": {}, "confidence": 0.95}
    # 전환 키워드 감지 시 LLM 분류 위임
```

**`booking_context` 활성 판단 기준:**
- `booking_context.messages` 비어있지 않음: 이전 예약 대화 턴이 있음
- `booking_context.collected_slots` 비어있지 않음: 날짜/인원 등 일부 정보 수집됨

---

## 4. 전체 동작 흐름 (변경 후)

```
고객: "3명으로 예약하고 싶은데요. 그런데 주차는 되나요?"

STT → classify_intent:
  booking_context.messages 존재 (이전 예약 대화)
  "주차" ∉ BREAK_KEYWORDS
  → intent = "booking" (0.5차, LLM 스킵, ~0ms)

booking_agent_node:
  _RAG_ENGINE_CONTEXT.set(rag_engine)
  SystemMessage 구성 (날짜, 발신자 번호, 예약 히스토리 포함)

  [Round 0] LLM 판단:
    → check_available_slots(owner, slot_date, party_size=3)
    → tool 결과: "14:00, 16:00 가능"

  [Round 1] LLM 판단:
    → search_knowledge_tool(owner, query="주차", category="FAQ")
      rag_engine.search("주차", owner_filter="1004")  ← 파이프라인 인스턴스 재사용
      → [{"content": "지하 1층 무료 주차 가능합니다."}]

  [Round 2] LLM 판단:
    → 최종 응답 생성 (예약 슬롯 + 주차 정보 통합)

  _RAG_ENGINE_CONTEXT.reset()

TTS: "14시, 16시에 예약 가능합니다. 주차는 지하 1층에 무료로 이용하실 수 있어요."
```

---

## 5. 로그 이벤트

| 이벤트명 | 발생 조건 |
|----------|-----------|
| `classify_intent_booking_context_active` | 0.5차에서 booking 유지 결정됨 |
| `classify_intent_booking_context_break` | 전환 키워드 감지 → LLM 위임 |
| `booking_tool_search_knowledge_rag_engine_hit` | 1순위(rag_engine) 검색 성공 |
| `booking_tool_search_knowledge_vectordb_hit` | 2순위(VectorDB) 검색 성공 |
| `booking_tool_search_knowledge_not_found` | 양쪽 모두 결과 없음 |
| `booking_agent_node_complete` | `rag_engine_injected` 필드로 주입 여부 확인 |

---

## 6. 개선 효과 요약

| 항목 | 기존 | 변경 |
|------|------|------|
| KB 검색 인스턴스 | 매 호출마다 새 VectorDB 생성 | 파이프라인 인스턴스 재사용 |
| 카테고리 필터 | 없음 | `category` 파라미터로 정밀 검색 |
| 예약 중 FAQ 질문 | intent=question → 예약 컨텍스트 소실 | booking 유지 → search_knowledge_tool 처리 |
| 0.5차 분류 응답 시간 | LLM 분류 (~1.6s) | 즉시 반환 (~0ms) |
| 동시 통화 안전성 | N/A | ContextVar로 Task 단위 격리 |

---

## 7. 키워드 감지 방식의 문제점 및 개선 방향

### 7-1. 현재 키워드 감지 현황

이번 구현에서 키워드 기반 로직이 두 곳에 잔존한다.

#### (A) `_BOOKING_CONTEXT_BREAK_KEYWORDS` — 0.5차 흐름 전환 감지

```python
_BOOKING_CONTEXT_BREAK_KEYWORDS = frozenset([
    "끊", "끝", "종료", "취소할게", "그만", "나중에", "다시",   # farewell/cancel-session
    "화나", "짜증", "이상해", "왜이래", "불만",                  # complaint
    "연결해줘", "상담원", "사람", "직원",                        # transfer
])
```

**동작**: `booking_context` 활성 상태에서 이 키워드가 있으면 LLM 분류 위임, 없으면 즉시 `booking` 반환.

#### (B) `_build_persona_question_keywords` — 1차 scope_keywords 매칭

```python
dyn_kws = _build_persona_question_keywords(_loaded_persona.scope_keywords)
matched_kw = next((kw for kw in dyn_kws if kw in main_clause_lower), None)
```

**동작**: 페르소나에 설정된 scope_keywords 중 하나라도 포함되면 LLM 스킵 후 즉시 `question` 반환.

---

### 7-2. 키워드 감지의 구체적 오류 시나리오

#### `_BOOKING_CONTEXT_BREAK_KEYWORDS` 오류 예시

| 고객 발화 | 키워드 감지 결과 | 실제 의도 |
|-----------|----------------|-----------|
| "다시 날짜를 확인하고 싶어요" | "다시" 감지 → LLM 위임 | booking 유지 (날짜 재확인) |
| "그만큼 비용이 드나요?" | "그만" 감지 → LLM 위임 | booking 유지 (비용 문의) |
| "나중에 예약 가능한 시간 있나요?" | "나중에" 감지 → LLM 위임 | booking 유지 (시간 확인) |
| "사람이 몇 명까지 예약 가능해요?" | "사람" 감지 → LLM 위임 | booking 유지 (인원 확인) |
| "이상해요, 원하는 날짜가 안 나오네요" | "이상해" 감지 → LLM 위임 | booking 유지 + complaint 복합 |

키워드가 단어 경계 없이 **부분 문자열 매칭** 방식이므로 단어가 다른 문맥에 포함되면 오발동한다.

#### `scope_keywords` 매칭 오류 예시

페르소나 scope_keywords에 "예약"이 있고 고객이 "예약하지 않아도 되나요?" 발화 시:
- 키워드 "예약" 매칭 → 즉시 `question` 반환
- 실제로는 부정 맥락의 예약 관련 질문 → LLM이 더 정확히 분류 가능

---

### 7-3. LLM 기반 대체 방안

#### 방안 1: 0.5차 분류 전체를 LLM으로 대체

`booking_context`가 활성일 때, 흐름 전환 여부를 LLM에게 질의한다.

```python
# 현재 (키워드)
_break_kw = next((kw for kw in _BOOKING_CONTEXT_BREAK_KEYWORDS if kw in _query_lower), None)
if not _break_kw:
    return {"intent": "booking", ...}

# 개선안 (LLM)
_should_break = await _llm_check_booking_break(
    query=query,
    history_snippet=history_snippet,
    llm=llm,
)
if not _should_break:
    return {"intent": "booking", ...}
```

**`_llm_check_booking_break` 프롬프트 설계:**

```
고객이 예약 대화를 진행 중입니다.
아래 발화가 예약 흐름을 완전히 끊으려는 의도(통화 종료·상담원 전환·강한 불만)인지 판단하세요.

판단 기준:
- 예약을 마무리하거나 계속하려는 발화 → false
- 예약 관련 추가 질문이 포함된 발화 → false
- 명확히 통화 종료/상담원 연결/거부 의사 → true

발화: "{query}"

JSON으로만 응답: {"break": true | false}
```

**비용/지연**: 이 질의는 `gpt-4o-mini` 기준 ~400ms, 토큰 약 80개 소모.

#### 방안 2: LLM 분류 프롬프트에 booking_context 힌트 추가 (현행 3차 활용)

`_BOOKING_CONTEXT_BREAK_KEYWORDS` 키워드 감지를 제거하고, `booking_context` 활성 여부를 기존 3차 LLM 분류 프롬프트의 힌트로 전달한다.

> **LLM 호출은 발생한다.** "추가 호출이 없다"는 의미가 아니라, 별도의 이진 분류용 LLM을 새로 추가하지 않고 기존 3차 분류 LLM 호출을 그대로 사용한다는 뜻이다.

```python
# 0.5차 키워드 감지 제거 후 → 항상 3차 LLM 분류로 넘어감
if _booking_active:
    _compound_note += (
        "\n⚠️ 현재 예약 대화가 진행 중입니다. "
        "발화가 예약 흐름의 연장선이면 반드시 booking으로 분류하세요. "
        "통화 종료·상담원 연결 의도가 명확할 때만 farewell/transfer로 분류하세요.\n"
    )
# → 이후 3차 LLM 분류 수행 (LLM 호출 1회)
```

**흐름 비교:**

| 구분 | 키워드 없을 때 | 키워드 있을 때 |
|------|--------------|--------------|
| 현재 (키워드 감지) | 즉시 booking 반환 (LLM 0회) | 3차 LLM 분류 (LLM 1회) |
| 방안 2 | 3차 LLM 분류 (LLM 1회) | 3차 LLM 분류 (LLM 1회) |

**장점**: 키워드 오발동 제거. 별도 LLM을 추가하지 않아 코드 단순.  
**단점**: 키워드가 없던 케이스(즉시 booking 반환)도 LLM 호출로 바뀌어 ~1.6s 지연 발생.

#### 방안 3: 경량 LLM (fast model) 활용한 이진 분류

```
입력: query (50자 이내 트런케이트)
출력: {"break": true | false}
모델: gemini-flash / gpt-4o-mini
목표 지연: < 300ms
```

3차 LLM 분류(~1.6s)보다 훨씬 빠르면서 키워드보다 정확한 중간 지점.

---

### 7-4. 권장 개선 방향

| 구분 | 현재 | 권장 |
|------|------|------|
| `_BOOKING_CONTEXT_BREAK_KEYWORDS` | 키워드 부분 매칭 | **방안 2** (3차 프롬프트 힌트 추가) 또는 **방안 3** (경량 LLM 이진 분류) |
| `scope_keywords` 1차 매칭 | 키워드 부분 매칭 → question | 현행 유지 (관리자가 명시적으로 설정한 키워드라 오발동 가능성 낮음) |

**단기 권장 (방안 2)**:
- `_BOOKING_CONTEXT_BREAK_KEYWORDS` 제거
- `booking_context` 활성 시 0.5차 즉시 반환 없이 3차 LLM 분류로 위임 (LLM 호출 1회 발생)
- 프롬프트에 `booking_context` 힌트 추가하여 정확도 향상
- 키워드 오발동 제거의 대가로 ~1.6s 지연이 항상 발생하는 트레이드오프 감수

**중기 권장 (방안 3)**:
- `booking_context` 활성 시 경량 LLM으로 흐름 전환 여부를 이진 판단
- 판단 결과에 따라 즉시 `booking` 반환 또는 3차 LLM 분류 위임

---

### 7-5. scope_keywords 1차 매칭 유지 근거

`scope_keywords`는 관리자가 페르소나 설정에서 **명시적으로 정의**한 키워드다.  
예약 키워드(`_BOOKING_KEYWORDS`)처럼 범용 단어가 아닌 서비스 특화 도메인어이므로 오발동 위험이 상대적으로 낮다.  
다만, 이 역시 LLM의 임베딩 유사도(2차 분류)와 중복되는 경우가 많아 향후 통합 검토 여지가 있다.

---

## 8. 변경 이력 (파일별)

| 파일 경로 | 변경 유형 | 요약 | 비고 |
|-----------|-----------|------|------|
| `src/ai_voicebot/langgraph/tools/booking_tools.py` | 수정 | `_RAG_ENGINE_CONTEXT` ContextVar 추가, `_search_knowledge`에 `category` 파라미터·1순위 rag_engine 검색 추가 | 설계대로 |
| `src/ai_voicebot/langgraph/nodes/booking_agent.py` | 수정 | `_RAG_ENGINE_CONTEXT.set/reset` 노드 진입·퇴출 시 처리, `rag_engine_injected` 로그 추가 | 설계대로 |
| `src/ai_voicebot/langgraph/nodes/classify_intent.py` | 수정 | 0.5차 `_BOOKING_CONTEXT_BREAK_KEYWORDS` 키워드 감지 제거 → `booking_context` 활성 플래그만 남기고 3차 LLM 프롬프트 힌트로 주입 (방안 2 적용) | 키워드 감지 제거 완료 |
