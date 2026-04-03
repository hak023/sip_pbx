# LLM 프롬프트 도메인 하드코딩 점검 및 페르소나 기반 재구성 방안

**작성일**: 2026-04-03 16:00  
**상태**: 분석 완료 → 개선 방안 도출  
**관련 파일**: `classify_intent.py`, `generate_response.py`, `llm_client.py`, `persona_service.py`

---

## 1. 현재 LLM 질의 구조 전체 맵

| 호출처 | 용도 | system_prompt | 하드코딩 도메인 |
|--------|------|--------------|----------------|
| `classify_intent_node` (3차) | 의도 분류 + 검색쿼리 변환 | `"의도 분류 및 쿼리 변환기"` | **있음** (날씨, 태풍, 기상청 예시) |
| `generate_response_node` (인바운드) | 고객 응답 생성 | `RESPONSE_SYSTEM_PROMPT` (org_context 포함) | **없음** (템플릿화 양호) |
| `generate_response_node` (아웃바운드) | 아웃바운드 응대 | 동적 조립 | 없음 |
| `rewrite_query_node` | 구어체→검색쿼리 변환 | `"쿼리 변환기"` | **없음** (범용) |
| `step_back_node` | 상위 개념 쿼리 생성 | `"Step-back 변환기"` | 없음 (제거됨) |
| `llm_client.judge_usefulness` | 통화 후 지식 정제 | 없음 (prompt에 포함) | **있음** (기상청, 강원 날씨 예시) |
| `llm_client.judge_barge_in` | 끼어들기 판단 | 없음 | 없음 |
| `llm_client.format_for_customer` | HITL 답변 포맷팅 | 없음 | 없음 |
| `llm_client._build_conversation_prompt` | 기본 fallback | 하드코딩: `"당신은 친절하고 정확한 AI 비서입니다."` | 없음 |

---

## 2. 하드코딩된 도메인 문제 상세

### 2-1. `classify_intent.py` — 의도 분류 프롬프트

**현재 코드** (418–437행):
```python
"- question: 업무 정보 질문 (날씨 예보·특보·수치, 위치, 운영시간, 연락처 등 답변이 필요한 것)\n"
"  예) '내일 서울 날씨 어때요?', '태풍 특보 나왔나요?' → question\n"
```

**문제**: 기상청 도메인 예시가 박혀 있어, 레스토랑·병원·법률 등 다른 테넌트에서 LLM이 "날씨 예보" 같은 업무 범위를 정보 질문의 기준으로 혼용할 수 있음.

**현재 키워드 목록** (`INTENT_KEYWORDS["question"]`):
```python
"날씨", "기온", "강수", "비", "눈", "태풍", "미세먼지", "황사", "기상", "예보",
"특보", "폭염", "한파", "호우", "낙뢰", "강풍", "기상청",
```

**문제**: 키워드 기반 분류 1차 경로가 기상청 전용 키워드로 꽉 차 있음. 레스토랑 테넌트에서 "메뉴", "예약", "테이블"로 바꿔야 하지만 코드에 고정.

**`_organization_role_question_not_help()`** 함수:
```python
if any(org in query_lower for org in ("기상청", "청은", "공사", "공단", "협회")) ...
```
**문제**: "기상청", "공사", "공단" 등 특정 기관 유형 하드코딩. 레스토랑, 호텔, 병원은 이 패턴과 맞지 않음.

### 2-2. `llm_client.judge_usefulness` — 지식 정제 예시

```python
"  - ❌ STT 원문: \"네 내일 강 원 지 역 날씨 는...\""
"  - ✅ 정제된 텍스트: \"내일 강원 지역 날씨는 오후 한때...\""
"  - ❌ STT 원문: \"기 상 감 정 서 는 기 상 청 홈 페이지 에서...\""
"  - ✅ 정제된 텍스트: \"기상감정서는 기상청 홈페이지에서...\""
```
**문제**: STT 정제 예시에 기상청/강원 날씨가 하드코딩. 다른 도메인 테넌트에서도 같은 예시를 보게 됨. LLM이 예시를 패턴으로 학습하므로 도메인 혼선 없음이 보장되지 않음.

---

## 3. 페르소나 현재 활용도 분석

### 현재 페르소나 데이터 구조

```python
OrganizationPersona:
  owner: str                        # 착신번호 (테넌트 식별자)
  name: str                         # 기관/서비스명 (예: "기상청 AI 비서")
  description: str                  # 업무 범위 설명 (임베딩 대상)
                                    # 예: "기상청 ARS 서비스. 날씨 예보·특보·기상 정보 제공..."
  scope_keywords: List[str]         # 업무 범위 키워드
  chitchat_response_template: str   # 잡담 시 고정 응답 문구
  enabled: bool
```

### 현재 활용 경로

```
[classify_intent 1.6차]
  → PersonaService.check_query_relevance(query, owner=_callee)
  → description 임베딩과 query 임베딩 유사도 비교 (threshold=0.6)
  → is_relevant=False → chitchat (template 적용)
  → is_relevant=True  → question

[generate_response]
  → intent==chitchat && _chitchat_template 있으면 LLM 스킵, template 반환
```

### 현재 한계

| 한계 | 내용 |
|------|------|
| `_callee` 미주입 | `agent.py`가 `_owner`만 state에 주입. `classify_intent`에서 `_callee`를 참조하지만 값이 빈 문자열 → 페르소나 분기 사실상 비동작 |
| description만 활용 | `scope_keywords`는 저장되지만 실제 분류 로직에 활용되지 않음 |
| name이 프롬프트에 미반영 | 페르소나의 `name`(기관명), `description`(업무 설명)이 LLM 프롬프트에 직접 전달되지 않음 |
| chitchat_template 단순 고정 | 모든 잡담에 동일 template. 계절 감상, AI 개인 질문, 업무 외 잡담 등 유형 구분 없음 |
| 분류 프롬프트에 미활용 | LLM 3차 classify_prompt의 `question` 예시가 하드코딩 기상청 예시 → 페르소나 업무 범위와 무관 |

---

## 4. 개선 방안 — 페르소나 기반 프롬프트 재구성

### 4-1. 즉시 수정 (코드 수정 가능)

#### A. `_owner` → `_callee` 주입 버그 수정 (`agent.py`)

```python
# 현재 (agent.py process_utterance)
"_owner": self._owner,

# 수정: _callee도 주입 (페르소나 분류용)
"_owner": self._owner,
"_callee": self._owner,   # owner == callee (착신번호)
```

> 실제로 `_callee`가 의미하는 것이 착신번호(수신 측)이고, `owner`가 착신번호 기반 테넌트 식별자이므로 동일한 값을 `_callee`로도 넣어주면 됨.

#### B. 분류 프롬프트 `question` 예시를 페르소나 기반으로 동적화 (`classify_intent.py`)

**현재**:
```python
"- question: 업무 정보 질문 (날씨 예보·특보·수치, 위치, 운영시간, 연락처 등 답변이 필요한 것)\n"
"  예) '내일 서울 날씨 어때요?', '태풍 특보 나왔나요?' → question\n"
```

**개선**: `org_context`나 페르소나 `description`에서 업무 예시를 동적으로 주입

```python
# classify_intent_node 내부
persona_desc = ""
persona_name = "AI 서비스"
persona_scope = ""
if owner:
    persona_svc = get_persona_service()
    if persona_svc:
        persona = await persona_svc.get_persona(owner)
        if persona and persona.enabled:
            persona_name = persona.name
            persona_desc = persona.description[:200]
            persona_scope = ", ".join(persona.scope_keywords[:5]) if persona.scope_keywords else ""

classify_prompt = (
    "다음 고객 발화를 분석하세요.\n"
    ...
    f"- chitchat: {persona_name}의 업무와 무관한 잡담 (일상 감상, AI 개인 질문 등)\n"
    f"- question: {persona_name}의 업무 관련 정보 질문"
    + (f" ({persona_scope})" if persona_scope else "")
    + "\n"
    + (f"  [{persona_name} 업무 범위: {persona_desc}]\n" if persona_desc else "")
    ...
)
```

#### C. 키워드 기반 1차 분류 — 기상청 전용 키워드 제거

```python
INTENT_KEYWORDS["question"] 에서 제거:
  "날씨", "기온", "강수", "비", "눈", "태풍", "미세먼지", "황사", "기상", "예보",
  "특보", "폭염", "한파", "호우", "낙뢰", "강풍", "기상청"

유지 (도메인 무관 범용 패턴):
  "알려줘", "알려주세요", "알 수 있", "알고 싶", "궁금", "문의",
  "영업시간", "운영시간", "몇 시", "언제까지",
  "어디", "위치", "주소", "전화번호", "연락처",
  "방법", "어떻게", "얼마", "비용", "가격", "요금",
  "발급", "신청", "접수", "등록"
```

레스토랑·병원 등 기관 고유 키워드는 페르소나의 `scope_keywords`에서 런타임에 로드하여 적용:

```python
# 페르소나 scope_keywords를 question 키워드 1차 매칭에 추가
if persona and persona.scope_keywords:
    dynamic_question_kws = {kw.lower() for kw in persona.scope_keywords}
    if any(kw in query_lower for kw in dynamic_question_kws):
        return {"intent": "question", "confidence": 0.9, ...}
```

#### D. `_organization_role_question_not_help()` — 기관 유형 하드코딩 제거

```python
# 현재 (특정 기관 유형 열거)
if any(org in query_lower for org in ("기상청", "청은", "공사", "공단", "협회")):

# 개선: org_context에서 기관명 가져오기 (이미 _extract_org_name() 있음)
# 또는 페르소나 name 활용
org_name_lower = (persona.name if persona else "").lower()
if org_name_lower and org_name_lower in query_lower and (
    "어떤 일" in query_lower or "무슨 일" in query_lower
):
    return True
```

#### E. `judge_usefulness` 예시 도메인 중립화 (`llm_client.py`)

```python
# 현재 (기상청 예시)
"  - ❌ STT 원문: \"네 내일 강 원 지 역 날씨 는...\""

# 개선 (도메인 중립 예시)
"  - ❌ STT 원문: \"네 내일 오 전 에 방 문 하 시 면 됩 니 다\""
"  - ✅ 정제된 텍스트: \"내일 오전에 방문하시면 됩니다.\""
"  - ❌ STT 원문: \"영 업 시 간 은 오 전 아 홉 시 부 터 오 후 여 섯 시 까 지 입 니 다\""
"  - ✅ 정제된 텍스트: \"영업시간은 오전 9시부터 오후 6시까지입니다.\""
```

---

### 4-2. 중기 개선 (설계 변경 필요)

#### F. 페르소나 `description`을 `generate_response` system_prompt에 직접 반영

현재 `RESPONSE_SYSTEM_PROMPT`는 `org_context`를 활용하는데, `org_context`는 `OrganizationInfoManager`의 설정 파일 기반임. 페르소나 `description`(업무 범위 자연어 설명)을 system_prompt에 추가하면 LLM이 업무 범위를 더 명확히 인식:

```python
RESPONSE_SYSTEM_PROMPT = """당신은 {org_name}의 AI 통화 비서입니다.

{persona_context}   ← 신규: 페르소나 description 삽입

기관 정보:
{org_context}
...
```

```python
# generate_response_node에서
persona_desc = ""
if owner:
    persona = await persona_svc.get_persona(owner)
    if persona:
        persona_desc = f"[업무 범위]\n{persona.description}\n"

prompt = RESPONSE_SYSTEM_PROMPT.format(
    org_name=org_name,
    persona_context=persona_desc,
    org_context=org_context,
    ...
)
```

#### G. `scope_keywords` 활용 강화

현재: ChromaDB 메타데이터에 저장되지만 분류 로직에 미사용.

개선:
- 키워드 1차 분류에서 `scope_keywords`를 동적 `question` 키워드로 활용 (C안 참고)
- `route_utterance_node`의 `compute_domain_question_signal`에서 `scope_keywords` 포함 여부로 도메인 시그널 판단

---

## 5. 작업 우선순위

| 우선순위 | 항목 | 효과 | 복잡도 |
|----------|------|------|--------|
| **P1 (즉시)** | A: `_callee` 주입 버그 수정 | 페르소나 분류 활성화 (현재 비동작) | 낮음 |
| **P1 (즉시)** | C: 기상청 전용 question 키워드 제거 | 다른 테넌트 오분류 방지 | 낮음 |
| **P1 (즉시)** | E: `judge_usefulness` 예시 도메인 중립화 | 도메인 혼선 제거 | 낮음 |
| **P2 (단기)** | B: 분류 프롬프트 question 예시 동적화 | 정확도 향상 | 중간 |
| **P2 (단기)** | D: `_organization_role_question_not_help` 동적화 | 범용성 | 중간 |
| **P3 (중기)** | F: 페르소나 description → generate_response 반영 | 응답 품질 향상 | 중간 |
| **P3 (중기)** | G: scope_keywords 동적 분류 | 정확도 향상 | 높음 |

---

## 6. 현재 `generate_response` 프롬프트 평가

`RESPONSE_SYSTEM_PROMPT`는 현재 구조가 비교적 범용적:

```
당신은 {org_name}의 AI 통화 비서입니다.
기관 정보: {org_context}       ← 테넌트별 config 값
...
```

`org_context`는 `OrganizationInfoManager`에서 테넌트 config 파일 기반으로 생성되므로,
**테넌트 config가 올바르게 설정되어 있으면** generate_response 자체는 범용적으로 동작.

→ 응답 생성 프롬프트는 상대적으로 양호. **분류 프롬프트와 키워드 목록이 우선 개선 대상.**

---

## 7. 요약

현재 시스템의 도메인 하드코딩은 주로 **분류(classify) 단계**에 집중되어 있음:

1. `INTENT_KEYWORDS["question"]` — 기상청 전용 17개 키워드
2. `classify_intent` LLM 프롬프트 — 날씨/태풍 예시
3. `_organization_role_question_not_help()` — 기관 유형 열거
4. `judge_usefulness` 예시 — 기상청/강원 날씨

페르소나 인프라(ChromaDB, PersonaService, OrganizationPersona)는 이미 구축되어 있으나
**`_callee` 미주입 버그로 분류 분기가 실제 동작하지 않는 상태**가 가장 큰 문제.

→ P1 항목 3개를 먼저 적용하면 다른 테넌트에서도 즉시 올바르게 동작할 수 있음.
