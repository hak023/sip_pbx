# 설계: 검색 전 라우터(1번) · 이중 임계치(3번) · 잡담 HITL 완화

- **작성일**: 2026-03-28 (로컬)
- **상태**: 구현 전 설계안
- **근거 리포트**: `2026-03-28_1945_HITL_CHITCHAT_ESCALATION_RESEARCH.md` §5 항목 1·3
- **관련 코드**: `langgraph/agent.py` (`_route_after_intent`, `_route_after_rag`), `nodes/classify_intent.py`, `nodes/adaptive_rag.py`, `nodes/step_back_prompt.py`, `nodes/generate_response.py`, `nodes/hitl_alert.py`, `langgraph/state.py`

## 0. 현상·원인 (코드 기준)

| 현상 | 원인 |
|------|------|
| 잡담인데 HITL이 잦음 | `chitchat`·`out_of_scope` 등이 **`check_cache` → `rewrite_query` → `adaptive_rag`** 를 그대로 탐. RAG 점수가 낮으면 **`_route_after_rag`에서 `step_back`** 으로 이어지고, 불필요한 재검색·저신뢰도가 쌓임. |
| `needs_follow_up` 과다 | `intent == "question"` 이고 **`rag_results`가 비면** `generate_response`가 LLM 없이 고정 멘트 + **`needs_follow_up=True`** (`generate_response.py` 상단 분기). 잡담이 **`question`으로 오분류**되면 동일 경로로 HITL까지 연결됨. |
| 잡담인데 낮은 confidence로 HITL | `hitl_alert`는 **`confidence < 0.3`** 이면 HITL. RAG에서 온 `confidence`가 먼저 깔리고, `generate_response`가 `greeting`/`chitchat`에만 0.9로 덮어쓰지만, **`needs_follow_up`이 이미 True**면 0번 규칙으로 먼저 HITL 처리됨. |

**결론**: 상위에서 **발화 레인(lane)을 분리**하고, **지식 질의에만 엄격한 RAG·HITL 임계치**를 적용하는 것이 목표다.

---

## 1. 검색 전 라우터 (리포트 1번)

### 1.1 목표

- **`social_light` 레인**: RAG(또는 무거운 RAG)를 생략하거나 최소화하고, LLM이 **짧은 일상 응답**만 생성 → **`needs_follow_up`·HITL 트리거가 걸리지 않게** 한다.
- **`knowledge` 레인**: 기존과 같이 캐시 → rewrite → adaptive_rag → (step_back) → generate → hitl_alert.

### 1.2 상태 필드 추가 (`ConversationState`)

| 필드 | 타입 | 의미 |
|------|------|------|
| `utterance_lane` | `str` | `"knowledge"` \| `"social_direct"` \| `"explicit_human"` (선택) |
| `domain_question_signal` | `bool` | 이 턴이 **조직 업무·지식 답변 기대** 질문이면 `True` (키워드·패턴 또는 소형 분류기) |
| `rag_mode` | `str` | `"full"` \| `"skip"` — 초기에는 `skip`은 social_direct 전용 |

**기본값**: 미설정 시 `utterance_lane="knowledge"`, `rag_mode="full"`, `domain_question_signal=False` 로 해석 (기존 동작 유지).

### 1.3 누가 무엇을 쓰는가

**권장: `classify_intent_node` 직후 전용 노드 `route_utterance_node` (얇은 레이어)**

- 입력: `intent`, `user_query`, (선택) `messages` 1~2턴
- 출력: `utterance_lane`, `rag_mode`, `domain_question_signal`

이유: 의도(`intent`)와 **“RAG를 탈지”** 는 목적이 달라 분리하면 프롬프트·테스트가 쉽다. `classify_intent` 안에 넣어도 되나, 파일 비대화와 회귀 범위를 줄이려 분리 권장.

### 1.4 레인 결정 규칙 (초기 정책)

1. **`intent in {"transfer"}`**  
   - `utterance_lane = "explicit_human"` (이름만; 실제 그래프는 기존처럼 `hitl_alert`에서 처리).  
   - 또는 레인 없이 기존 분기 유지.

2. **`intent in {"chitchat", "out_of_scope"}`**  
   - `utterance_lane = "social_direct"`, `rag_mode = "skip"`.

3. **`intent == "question"`**  
   - `utterance_lane = "knowledge"`, `rag_mode = "full"`.  
   - `domain_question_signal`: 별도 휴리스틱(아래 3.2)으로 설정.

4. **`intent in {"greeting", "farewell"}`**  
   - 기존 `check_greeting_farewell_cache` 경로 유지.  
   - 레인 필드는 `social_light`에 가깝지만 **캐시·RAG 폴백**이 있으므로 `utterance_lane="knowledge"` 또는 `"greeting_cache"` 같이 **그래프 분기와 1:1 매핑**되는 값으로 정의해 혼동을 막는다. (구현 시 한 표로 고정.)

5. **템플릿 의도** (`affirm`, `repeat`, …)  
   - 레인 불필요 (이미 `hitl_alert` 미경유).

6. **`nlu_fallback`**  
   - 보수적 기본: `knowledge` + `domain_question_signal=False` 이거나, 짧은 발화면 `social_direct` 후보를 LLM 한 번으로만 판별 (비용 대비 효과 검토).

### 1.5 그래프 변경 (`agent.py`)

- 엔트리: `classify_intent` → **`route_utterance`** → 조건부 분기.

**새 분기 함수 `_route_after_utterance_lane(state)`**

- `rag_mode == "skip"` **且** 템플릿 의도 아님 → **`generate_response`** 로 직행 (신규 엣지).  
  - 진입 시 상태: `rag_results=[]`, `confidence=0.85` 등 **사전 주입**해 `adaptive_rag`·`step_back`을 타지 않음.
- 그 외 → 기존 `_route_after_intent`와 동일한 타깃으로 합류 (또는 `_route_after_intent` 로직을 레인을 고려해 재배치).

**주의**: `generate_response`의 **`intent == "question" and not rag_results`** 분기가 잡담 직행 경로를 막지 않는지 확인한다.  
→ `social_direct`에서는 **`intent != "question"`** 이 대부분이므로 안전.  
→ **`out_of_scope`가 직행 시** 동일하게 `question`이 아니므로 LLM 경로로 들어가 `chitchat_rule` 확장이 필요할 수 있음 (`out_of_scope`용 짧은 응답 규칙).

### 1.6 `generate_response` 정책 (social_direct)

- `utterance_lane == "social_direct"` 또는 `rag_mode == "skip"` 이면:
  - 프롬프트에 **“지식 근거 없이 짧게 일상 대화”** 규칙 강화 (`chitchat`·`out_of_scope` 공통).
  - **`_is_unknown_content_response`가 True여도** `needs_follow_up=False` 로 **강제**할지 정책 결정 권장: 일상 레인에서는 “모른다” 멘트 대신 **재질문·가벼운 전환** 유도.

---

## 2. 이중 임계치 (리포트 3번)

### 2.1 목표

- **지식형 질문** (`question` + `domain_question_signal=True`): 현재보다 **엄격**하게 RAG 품질·HITL을 볼 수 있음.
- **비지식·모호** (`question` + signal=False, 또는 social): **step_back 생략** 또는 **완화된 임계치**, **저신뢰도만으로 HITL 금지**.

### 2.2 `domain_question_signal` 휴리스틱 (초안)

다음 중 하나라도 만족하면 `True`:

- `QUESTION_PATTERNS` (`classify_intent.py`)와 유사한 **업무 키워드**: 예) 기관명, `문의`, `예약`, `시간`, `위치`, `비용`, `절차`, `신청` …
- `should_treat_as_question_not_transfer` 가 True인 **방문·교통**류
- RAG **쿼리**에 테넌트 `org_context`의 핵심 토큰 포함 (선택)

`False`이면 “가벼운 질문/잡담에 가까운 question”으로 취급해 임계치 완화.

### 2.3 RAG 후 분기 `_route_after_rag` 개선

상수 단일 `0.4` 대신:

| 조건 | Step-back 진입 임계 (`T_step`) | 비고 |
|------|----------------------------------|------|
| `intent == "question"` and `domain_question_signal` | `0.40` (기존 유지 가능) | 필요 시 `0.35`로 조정 |
| `intent == "question"` and not signal | `0.25` ~ `0.30` | 불필요한 step-back 감소 |
| `intent in {"chitchat", "out_of_scope"}` | — | **1번 설계로 RAG 자체를 스킵**하면 이 분기에 도달하지 않음 |
| 기타 | `0.40` | 기본 |

구현 시 `adaptive_rag` 산출 `confidence`와 동일 스케일 유지.

### 2.4 `hitl_alert` 이중 정책 + 잡담 저신뢰도 제외

**상수**

- `HITL_CONFIDENCE_STRICT = 0.30` — 지식형에만 적용
- `HITL_CONFIDENCE_RELAXED = 0.15` — 비지식 question에만 적용 (또는 **미적용: 저신뢰도 HITL 끔**)

**의도 집합**

- `SOCIAL_OR_LIGHT_INTENTS = {"chitchat", "out_of_scope", "greeting", "farewell"}` (+ 필요 시 `doubt`, `positive_reaction`, `negative_reaction`은 템플릿 경로라 제외)

**규칙 (우선순위 재정렬 제안)**

1. **`needs_follow_up`**  
   - `if needs_follow_up and (utterance_lane == "social_direct" or intent in SOCIAL_OR_LIGHT_INTENTS)` → **HITL 제외**, 로그만 (`hitl_suppressed_social_follow_up`).  
   - `if needs_follow_up and intent == "question" and not domain_question_signal` → **1차 제외** 또는 **2연속 시에만 HITL** (리포트 2번과 연계 시 명시).

2. **`intent == "transfer"`** → 기존 유지 (항상 HITL).

3. **`complaint` + 낮은 confidence** → 기존 유지.

4. **`confidence < threshold`**  
   - `if intent in SOCIAL_OR_LIGHT_INTENTS or utterance_lane == "social_direct"` → **HITL 제외**.  
   - `elif intent == "question" and domain_question_signal` → `confidence < HITL_CONFIDENCE_STRICT` 일 때만 HITL.  
   - `elif intent == "question" and not domain_question_signal` → `confidence < HITL_CONFIDENCE_RELAXED` 일 때만 HITL **또는** 해당 규칙 비활성.

**로그 (디버깅 규칙)**

- `hitl_eval`: `intent`, `utterance_lane`, `domain_question_signal`, `needs_follow_up`, `confidence`, `rule_matched`, `suppressed_reason`.

---

## 3. `needs_follow_up` ↔ HITL 디커플링 (요청사항 반영)

- **의미 분리**  
  - `needs_follow_up`: “고객에게 확인 후 연락·재안내” 같은 **대화 정책**.  
  - `needs_human`: **운영자 큐(HITL)** 진입.

- **구현 옵션 (택1)**  
  - **A**: `generate_response`는 기존처럼 `needs_follow_up` 설정, `hitl_alert`에서 **레인·의도·domain_signal로 필터**해 `needs_human` 결정.  
  - **B**: 상태에 `follow_up_operator_queue: bool` 추가, LLM/규칙이 명시적으로 True일 때만 HITL.

초기 구현은 **A**가 변경 범위가 작다.

---

## 4. `classify_intent` 보강 (상위 분리와 함께)

- LLM 분류 프롬프트에 **잡담·날씨·감상 예시**를 늘리고, **업무 질문은 `question`** 으로 붙도록 예시 대비.  
- 키워드 1차에 **`chitchat` 후보** (날씨, 식사, 주말 등)를 **짧은 발화 한정**으로 추가할지 검토 (오탐: “오늘 영업 시간” → `question` 유지).

---

## 5. 구현 순서 제안

1. `state.py` 필드 추가 + 기본값 처리 (`update_state` 병합 확인).  
2. `route_utterance_node` + `agent.py` 엣지 (`social_direct` → `generate_response`).  
3. `generate_response`: `rag_mode`/`utterance_lane`에 따른 프롬프트·`needs_follow_up` 억제.  
4. `_route_after_rag` intent·`domain_question_signal` 반영.  
5. `hitl_alert` 억제 규칙 + 구조화 로그.  
6. 골든 발화 세트(잡담 / 업무 질문 / 상담원 요청)로 회귀.

---

## 6. Pipecat `rag_processor` 동기화

통화 경로가 LangGraph 외에 **RAGLLMProcessor**를 쓰면, 동일한 **`utterance_lane` / `domain_question_signal` / HITL 억제 규칙**을 해당 프로세서의 `invoke` 결과 처리부에 복제하거나, **공유 모듈**(`hitl_policy.py` 등)로 단일화한다.

---

## 7. 오픈 이슈

- `out_of_scope`를 **완전 무RAG**로 보낼 때 컴플라이언스·브랜드 톤.  
- `question` + `domain_question_signal=False`에서 **완전 HITL 제외** 시, 실제 업무 질문 놓침 위험 → **2연속 `needs_follow_up`** 조건 권장.  
- `nlu_fallback`을 social로 보낼지 knowledge로 보낼지 A/B.
