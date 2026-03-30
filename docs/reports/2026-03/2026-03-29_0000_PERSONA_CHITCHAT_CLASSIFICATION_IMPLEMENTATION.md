# Persona 기반 Chitchat 분류 시스템

## 개요

조직 페르소나(Organization Persona)를 ChromaDB에 저장하여, **사용자 질문이 조직 업무와 관련되면 `question` (RAG/LLM), 무관하면 `chitchat` (템플릿)** 으로 정확히 분류합니다.

## 설계 목표

### 문제
- 기존: 키워드 + LLM 분류만으로는 **업무 범위 밖 질문(예: "너도 개나리를 좋아하니?")** 을 `chitchat`으로 정확히 분류하기 어려움.
- 결과: 불필요한 RAG/HITL 실행, 응답 지연, 운영자 부담 증가.

### 해결
**"이 AI Bot은 무엇을 하는 조직인가?"** 를 페르소나로 정의하고, 질문과 페르소나의 의미적 유사도로 분류.

```
질문: "너도 개나리를 좋아하니?"
Persona: "기상청은 날씨정보와 기상특보를 안내하는 국가 공공기관입니다."
유사도: 0.25 (< 0.6 threshold)
→ chitchat (템플릿 응답: "죄송합니다. 저는 기상 관련 업무만 도와드릴 수 있어요.")
```

## 아키텍처

```
Frontend (Persona 관리 UI)
   ↓ POST /api/persona/
Backend API (persona.py)
   ↓
PersonaService (persona_service.py)
   ↓ embed(description)
ChromaDB (persona collection)
   ↓ query(user_query)
Intent Classification (classify_intent.py)
   ↓ similarity > threshold → question
   ↓ similarity < threshold → chitchat
Generate Response (generate_response.py)
   ↓ chitchat → template
   ↓ question → RAG/LLM
```

## 데이터 스키마

### OrganizationPersona (models.py)

```python
class OrganizationPersona(BaseModel):
    owner: str                          # Owner ID (착신번호, 예: "1004")
    name: str                           # 조직명 (예: "기상청")
    description: str                    # 조직 설명 및 업무 범위
    scope_keywords: List[str]           # 선택: 업무 키워드 (예: ["날씨", "예보", "특보"])
    chitchat_response_template: str     # Chitchat 시 응답 템플릿
    enabled: bool                       # 활성화 여부
    created_at: str
    updated_at: str
```

### ChromaDB Document

```json
{
  "id": "persona_1004",
  "document": "기상청은 날씨정보와 기상특보 등을 안내하는 국가 공공기관입니다.",
  "embedding": [0.12, -0.34, ...],
  "metadata": {
    "owner": "1004",
    "name": "기상청",
    "scope_keywords": "날씨,예보,특보,기상",
    "chitchat_template": "죄송합니다. 저는 기상 관련 업무만 도와드릴 수 있어요.",
    "enabled": true,
    "created_at": "2026-03-28T23:45:00",
    "updated_at": "2026-03-28T23:45:00"
  }
}
```

## API 엔드포인트

### POST /api/persona/
Persona 생성

```bash
curl -X POST http://localhost:8000/api/persona/ \
  -H "Content-Type: application/json" \
  -d '{
    "owner": "1004",
    "name": "기상청",
    "description": "기상청은 날씨정보와 기상특보 등을 안내하는 국가 공공기관입니다.",
    "scope_keywords": ["날씨", "예보", "특보", "기상"],
    "chitchat_response_template": "죄송합니다. 저는 기상 관련 업무만 도와드릴 수 있어요."
  }'
```

### GET /api/persona/{owner}
Persona 조회

```bash
curl http://localhost:8000/api/persona/1004
```

### PUT /api/persona/{owner}
Persona 수정

```bash
curl -X PUT http://localhost:8000/api/persona/1004 \
  -H "Content-Type: application/json" \
  -d '{
    "description": "기상청은 날씨정보, 기상특보, 태풍 정보를 안내합니다."
  }'
```

### DELETE /api/persona/{owner}
Persona 삭제

```bash
curl -X DELETE http://localhost:8000/api/persona/1004
```

### GET /api/persona/
모든 Persona 목록

```bash
curl http://localhost:8000/api/persona/
```

### POST /api/persona/{owner}/check-relevance
테스트용 (Query 관련성 체크)

```bash
curl -X POST http://localhost:8000/api/persona/1004/check-relevance?query=너도개나리를좋아하니
```

## 프론트엔드

### Persona 관리 UI
- URL: `http://localhost:3000/settings/persona`
- 기능:
  - Persona 생성 (Owner, Name, Description, Keywords, Template)
  - 수정 (부분 업데이트)
  - 삭제
  - 활성화/비활성화

### 대시보드 링크
- 대시보드 헤더에 **"⚙️ Persona 설정"** 링크 추가됨.

## 분류 로직

### classify_intent_node (classify_intent.py)

**1차: 키워드 매칭** (greeting, farewell, transfer 등)

**2차: Persona 기반 필터 (신규)**

```python
if owner:
    relevance = await persona_svc.check_query_relevance(query, owner, threshold=0.6)
    
    if relevance["persona_found"] and not relevance["is_relevant"]:
        # 유사도 < 0.6 → chitchat
        return {
            "intent": "chitchat",
            "_chitchat_template": relevance["chitchat_template"],
            "confidence": 1.0,
        }
    
    if relevance["persona_found"] and relevance["is_relevant"]:
        # 유사도 >= 0.6 → question
        return {"intent": "question", "confidence": 1.0}
```

**3차: LLM 기반 분류** (Persona 미설정 시)

### generate_response_node (generate_response.py)

```python
if intent == "chitchat" and state.get("_chitchat_template"):
    # Persona 템플릿 즉시 반환 (LLM 스킵)
    return {
        "response": template,
        "confidence": 1.0,
        "needs_follow_up": False,
    }
```

## 기본 동작 (Persona 미설정 시)

```python
if not persona or not persona.enabled:
    return {
        "is_relevant": True,  # 모든 질문 → question
        "persona_found": False,
    }
```

**Persona가 없으면 기존 로직 그대로 동작 (키워드 + LLM 분류).**

## 성능 최적화

### 1. 메모리 캐시 (5분 TTL)
- Persona는 자주 조회되므로 메모리 캐시 (`_cache`, `_cache_timestamps`)로 ChromaDB 쿼리 최소화.

### 2. LLM 스킵
- Chitchat 템플릿 응답 시 LLM 호출 없음 → **응답 시간 1~2초 단축**.

### 3. Embedding 재사용
- Persona description은 생성 시 한 번만 임베딩, 이후 쿼리 시 재사용.

## 테스트 시나리오

### 시나리오 1: Persona 설정 후 업무 질문

1. Persona 생성: `owner=1004, name=기상청, description=날씨정보와 기상특보를 안내하는 국가 공공기관`
2. 통화: `1004`로 전화
3. 질문: "오늘 날씨 어때요?"
4. 예상 결과:
   - Intent: `question` (유사도 > 0.6)
   - 응답: RAG/LLM 경로 (기상청 지식 검색 후 답변)

### 시나리오 2: Persona 설정 후 잡담

1. Persona 생성: 위와 동일
2. 통화: `1004`로 전화
3. 질문: "너도 개나리를 좋아하니?"
4. 예상 결과:
   - Intent: `chitchat` (유사도 < 0.6)
   - 응답: 템플릿 ("죄송합니다. 저는 기상 관련 업무만 도와드릴 수 있어요.")
   - LLM 스킵, 즉시 응답

### 시나리오 3: Persona 미설정

1. Persona 없음
2. 통화: `1004`로 전화
3. 질문: "너도 개나리를 좋아하니?"
4. 예상 결과:
   - Intent: `chitchat` (키워드 매칭 또는 LLM 분류)
   - 응답: 기존 LLM 기반 chitchat 응답

## 로그

### Persona 관련성 체크

```
persona_query_relevance_check
  owner=1004
  query_preview="너도 개나리를 좋아하니?"
  similarity=0.25
  threshold=0.6
  is_relevant=False
  persona_name="기상청"
  note="Query와 조직 페르소나 관련성 — 낮으면 chitchat"
```

### Chitchat 템플릿 응답

```
classify_intent_persona_chitchat
  intent=chitchat
  query_preview="너도 개나리를 좋아하니?"
  similarity=0.25
  threshold=0.6
  owner=1004
  note="Query가 조직 페르소나와 무관 — chitchat 템플릿 응답"

generate_response_chitchat_template
  intent=chitchat
  response_len=45
  note="Persona chitchat 템플릿 — LLM 스킵"
```

### Question 경로

```
classify_intent_persona_question
  intent=question
  query_preview="오늘 날씨 어때요?"
  similarity=0.85
  threshold=0.6
  owner=1004
  note="Query가 조직 페르소나와 관련 — question (RAG/LLM)"
```

## 파일 변경 사항

### Backend
1. **`src/config/models.py`**: `OrganizationPersona` 모델 추가
2. **`src/ai_voicebot/knowledge/persona_service.py`**: Persona CRUD 및 관련성 체크 서비스 (신규)
3. **`src/api/routers/persona.py`**: REST API 엔드포인트 (신규)
4. **`src/api/main.py`**: Persona router 등록
5. **`src/ai_voicebot/factory.py`**: PersonaService 초기화 (ChromaDB + Embedder 주입)
6. **`src/ai_voicebot/langgraph/nodes/classify_intent.py`**: Persona 기반 chitchat 필터 추가 (1.6차 분류)
7. **`src/ai_voicebot/langgraph/nodes/generate_response.py`**: Chitchat 템플릿 응답 처리

### Frontend
1. **`frontend/app/settings/persona/page.tsx`**: Persona 관리 UI (신규)
2. **`frontend/app/dashboard/page.tsx`**: 헤더에 Persona 설정 링크 추가

## 사용 방법

### 1. 서버 시작

```bash
cd sip-pbx
python src/main.py
```

### 2. Frontend 시작

```bash
cd frontend
npm run dev
```

### 3. Persona 설정

브라우저에서 `http://localhost:3000/settings/persona` 접속 후:

1. **Owner ID**: `1004` (착신번호)
2. **조직명**: `기상청`
3. **조직 설명**: `기상청은 날씨정보와 기상특보 등을 안내하는 국가 공공기관입니다.`
4. **키워드** (선택): `날씨`, `예보`, `특보`, `기상`, `태풍`, `황사`
5. **Chitchat 템플릿** (선택): `죄송합니다. 저는 기상 관련 업무만 도와드릴 수 있어요.`
6. **생성** 클릭

### 4. 통화 테스트

```bash
# 업무 질문 (question → RAG/LLM)
전화 → "오늘 날씨 어때요?"
→ Intent: question (유사도 0.85)
→ 응답: RAG 검색 + LLM 생성

# 잡담 (chitchat → 템플릿)
전화 → "너도 개나리를 좋아하니?"
→ Intent: chitchat (유사도 0.25)
→ 응답: "죄송합니다. 저는 기상 관련 업무만 도와드릴 수 있어요." (LLM 스킵)
```

## 파라미터 조정

### similarity_threshold (기본 0.6)

```python
# classify_intent.py line ~285
relevance = await persona_svc.check_query_relevance(
    query=query,
    owner=owner,
    similarity_threshold=0.6  # 높이면 chitchat 증가, 낮추면 question 증가
)
```

- **0.6 (권장)**: 중간 균형
- **0.7**: 업무 질문을 엄격히 판단 (chitchat 증가)
- **0.5**: 업무 질문을 느슨하게 판단 (question 증가)

## 장점

1. **정확한 분류**: 조직 정체성 기반 → 키워드보다 의미적으로 정확
2. **응답 시간 단축**: Chitchat 시 LLM 스킵 (1~2초 단축)
3. **운영자 부담 감소**: 불필요한 HITL 감소
4. **유연한 설정**: Owner별 독립적 페르소나 (멀티 테넌트 지원)
5. **사용자 경험 향상**: 빠르고 명확한 경계 안내

## 제한사항

1. **Embedding 품질 의존**: Persona description이 모호하면 분류 정확도 하락.
2. **Cold Start**: Persona 미설정 시 기존 로직 사용 (LLM 분류).
3. **Threshold 민감도**: 도메인별로 최적값 다를 수 있음 (튜닝 필요).

## 향후 개선

1. **Multi-Persona Support**: 하나의 Owner가 여러 Persona 관리 (부서별)
2. **Dynamic Threshold**: 통화 히스토리 기반 자동 조정
3. **A/B Testing**: Persona 유무 성능 비교
4. **Analytics Dashboard**: Chitchat vs Question 분류 통계

---

**작성일**: 2026-03-28  
**버전**: 1.0  
**상태**: 구현 완료
