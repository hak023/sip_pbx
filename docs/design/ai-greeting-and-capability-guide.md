# AI 인사말 + 서비스 가이드 멘트 기획서
> **클러스터 안내**: 세부·히스토리 설계 문서입니다. 통합 관점·경계는 아래 대표 문서를 우선 참고하세요.
> 
> **대표 문서**: [`multi-tenant-rag-and-dashboard.md`](multi-tenant-rag-and-dashboard.md)
>
---


> **작성일**: 2026-01-29  
> **상태**: 기획 완료, 구현 대기  
> **범위**: VectorDB 스키마 확장 → Backend API → Frontend UI → AI Orchestrator

---

## 1. 개요

### 1.1 현재 문제

| 항목 | 현재 상태 | 문제 |
|------|-----------|------|
| AI 인사말 | `organization_info.json`의 고정 템플릿 4개 중 랜덤 | `config.yaml`의 `greeting_message` 미사용, 일관성 부족 |
| 서비스 가이드 | 없음 | 사용자가 뭘 요청할 수 있는지 모름 |
| capabilities | `organization_info.json`에 문자열 배열 | VectorDB와 분리되어 있어 동적 관리 불가 |
| 서비스별 동작 구분 | 없음 | 정보 안내 / API 호출 / 상담원 연결을 구분하지 못함 |

### 1.2 목표

1. **Phase 1 (고정 인사말)**: `config.yaml`에서 읽은 인사말을 즉시 TTS 발화
2. **Phase 2 (가이드 멘트)**: VectorDB에서 활성 서비스 목록을 조회 → LLM이 자연어 한 문장으로 요약 → TTS 발화
3. **후속 대화**: 사용자 요청 시 `response_type`에 따라 정보 안내 / API 호출 / 호 전환 등 분기

### 1.3 업계 벤치마크

| 시스템 | 인사말 | 가이드 |
|--------|--------|--------|
| Ada.cx Voice | 고정 Greeting Builder + "AI임을 밝힘" | open-ended 질문 유도 |
| Google Business Messages | 고정 Welcome + Conversation Starters (버튼 3~5개) | 자주 묻는 질문 카드 |
| Dialogflow CX | 고정 Welcome Intent | Route별 capabilities |
| VoiceBooker (Multi-stage) | Stage 1: 고정 Welcome | Stage 2: 동적 task-specific |
| AURA (2025 논문) | — | function-calling으로 calendar, email, search 등 tool 호출 |

**공통 패턴**: 2-Phase Greeting (고정 인사 → 동적 가이드)

---

## 2. 2-Phase Greeting 아키텍처

```
┌─────────────────────────────────────────────────────┐
│  Phase 1: 고정 인사말 (config.yaml)                  │
│                                                       │
│  "안녕하세요, ○○○의 AI 비서입니다."                   │
│                                                       │
│  • 즉시 TTS 발화 (지연 0초)                           │
│  • config.yaml → greeting_message 값 사용             │
│  • Barge-in 비활성화                                  │
└──────────────────┬──────────────────────────────────┘
                   │
                   ▼  (Phase 1 발화 중 Phase 2 병렬 생성)
┌─────────────────────────────────────────────────────┐
│  Phase 2: 가이드 멘트 (VectorDB → LLM 요약)          │
│                                                       │
│  "저는 오시는길 안내, 주차 안내, 영업시간 안내,        │
│   메뉴 안내, 상담원 연결을 도와드릴 수 있어요.        │
│   어떤 것이 궁금하신가요?"                             │
│                                                       │
│  • VectorDB에서 doc_type=capability 조회              │
│  • LLM이 display_name 목록 → 자연어 한 문장           │
│  • 결과 캐싱 (owner별, TTL 기반)                      │
│  • Barge-in 활성화 (중간에 끊고 말할 수 있음)          │
└──────────────────┬──────────────────────────────────┘
                   │
                   ▼
          [LISTENING 상태 진입]
```

### 타이밍 예산

| 단계 | 소요 시간 | 비고 |
|------|-----------|------|
| Phase 1 TTS 합성 | ~0.5초 | 짧은 문장, Google Neural TTS |
| Phase 1 발화 | ~2초 | "안녕하세요. 기상청 AI 비서입니다." |
| Phase 2 생성 (캐시 히트) | 0ms | 메모리에서 즉시 |
| Phase 2 생성 (캐시 미스) | ~1.5초 | LLM 호출, Phase 1 발화 중 병렬 |
| Phase 2 발화 | ~4초 | 가이드 멘트 전체 |
| **총 체감** | **~6초** | 사용자는 0.5초 후부터 AI 목소리를 들음 |

---

## 3. VectorDB 스키마 설계

### 3.1 현재 스키마

```
Collection: "knowledge_base"
Document metadata:
  - category    : str   ("faq", "policy", "support", "product", "manual")
  - keywords    : str   (쉼표 구분)
  - created_at  : str
  - source      : str   ("manual", "hitl", "extracted")
  - usageCount  : str
  - addedBy     : str
```

### 3.2 확장 스키마

기존 필드를 유지하면서 `doc_type` + `response_type` 등을 추가합니다.
기존 문서는 `doc_type=knowledge`로 간주합니다 (하위 호환).

```
Collection: "knowledge_base" (단일 컬렉션 유지)

═══ 공통 메타데이터 (모든 doc_type) ═══
  doc_type      : str    "capability" | "faq" | "knowledge"
                         (기존 문서는 미설정 → "knowledge"로 취급)
  category      : str    카테고리 slug
  keywords      : str    쉼표 구분 키워드
  created_at    : str    ISO 8601
  updated_at    : str    ISO 8601
  source        : str    "manual" | "hitl" | "extracted" | "seed"
  owner         : str    소유자 ID (멀티테넌트)
  is_active     : bool   활성화 여부 (기본 true)

═══ capability 전용 메타데이터 ═══
  display_name  : str    가이드 멘트 표시명 ("매장 주차 안내")
  response_type : str    "info" | "api_call" | "transfer" | "collect"
  priority      : int    가이드 멘트 노출 순서 (낮을수록 우선)
  api_endpoint  : str    response_type=api_call 시 호출 URL
  api_method    : str    "GET" | "POST"
  api_params    : str    JSON string, API 파라미터 정의
  transfer_to   : str    response_type=transfer 시 연결 대상 (SIP URI/번호)
  collect_fields: str    response_type=collect 시 수집 항목 JSON
```

### 3.3 response_type 분류

| response_type | 설명 | AI 동작 | 예시 |
|---------------|------|---------|------|
| `info` | 정보 안내 | VectorDB 문서 내용으로 TTS 응답 | 영업시간, 주소, 메뉴 |
| `api_call` | 외부 API 호출 | API 호출 → 결과 가공 → TTS | 실시간 날씨, 예약 확인 |
| `transfer` | 상담원/부서 연결 | SIP 호 전환 실행 | "담당자 연결" |
| `collect` | 정보 수집 필요 | 멀티턴 질문 → 수집 → 처리 | 예약 접수 (이름/날짜/인원) |

### 3.4 데이터 예시

```json
[
  {
    "id": "cap_directions",
    "document": "서울시 강남구 테헤란로 123. 지하철 2호선 강남역 3번 출구에서 도보 5분.",
    "metadata": {
      "doc_type": "capability",
      "category": "location",
      "display_name": "오시는길 안내",
      "response_type": "info",
      "priority": 1,
      "is_active": true,
      "owner": "store_gangnam",
      "keywords": "오시는길,위치,주소,찾아오는방법",
      "source": "seed",
      "created_at": "2026-01-29T00:00:00"
    }
  },
  {
    "id": "cap_transfer",
    "document": "담당 상담원에게 전화를 연결해 드립니다.",
    "metadata": {
      "doc_type": "capability",
      "category": "transfer",
      "display_name": "상담원 연결",
      "response_type": "transfer",
      "transfer_to": "sip:operator@pbx.local",
      "priority": 99,
      "is_active": true,
      "owner": "store_gangnam",
      "keywords": "상담원,담당자,사람,연결",
      "source": "seed",
      "created_at": "2026-01-29T00:00:00"
    }
  },
  {
    "id": "cap_weather",
    "document": "기상청 API를 통해 실시간 날씨 정보를 조회합니다.",
    "metadata": {
      "doc_type": "capability",
      "category": "weather",
      "display_name": "실시간 날씨 조회",
      "response_type": "api_call",
      "api_endpoint": "https://apis.data.go.kr/1360000/VilageFcstInfoService_2.0/getUltraSrtNcst",
      "api_method": "GET",
      "api_params": "{\"serviceKey\": \"...\", \"numOfRows\": 10}",
      "priority": 5,
      "is_active": true,
      "owner": "store_gangnam",
      "keywords": "날씨,기온,비,눈",
      "source": "seed",
      "created_at": "2026-01-29T00:00:00"
    }
  }
]
```

### 3.5 초기 시딩 정책

| 시점 | 동작 |
|------|------|
| 최초 서버 시작 | `doc_type=capability` 문서 수 확인 → 0개면 시드 데이터 투입 |
| 이후 서버 재시작 | VectorDB는 PersistentClient → 스킵 |
| 운영 중 | Frontend UI 또는 API로 CRUD → VectorDB가 정본(source of truth) |

---

## 4. Backend API 변경

### 4.1 현재 API 구조

```
GET    /api/knowledge/          → 전체 조회 (category 필터)
POST   /api/knowledge/          → 추가
PUT    /api/knowledge/{id}      → 수정
DELETE /api/knowledge/{id}      → 삭제
```

현재 Pydantic 모델:
```python
class KnowledgeEntryCreate(BaseModel):
    text: str
    category: str
    keywords: List[str]
    metadata: Optional[Dict[str, Any]] = {}
```

### 4.2 확장: Capability 전용 API

기존 knowledge API에 `doc_type` 필터를 추가하고, capability 전용 편의 엔드포인트를 신설합니다.

```
# ═══ 기존 knowledge API (doc_type 필터 추가) ═══
GET    /api/knowledge/?doc_type=capability    → capability만 조회
GET    /api/knowledge/?doc_type=faq           → FAQ만 조회
GET    /api/knowledge/?doc_type=knowledge     → 일반 지식만 조회

# ═══ 신규: Capability 전용 편의 API ═══
GET    /api/capabilities/                     → 활성 capability 목록 (is_active=true, priority 정렬)
POST   /api/capabilities/                     → capability 추가 (doc_type 자동 설정)
PUT    /api/capabilities/{id}                 → capability 수정
DELETE /api/capabilities/{id}                 → capability 삭제
PATCH  /api/capabilities/{id}/toggle          → 활성화/비활성화 토글
PUT    /api/capabilities/reorder              → 우선순위 일괄 변경

# ═══ 신규: 가이드 멘트 API (AI Orchestrator가 호출) ═══
GET    /api/capabilities/guide-text?owner={owner_id}
                                              → 캐싱된 가이드 멘트 텍스트 반환
POST   /api/capabilities/guide-text/refresh   → 캐시 무효화 + 재생성
```

### 4.3 Pydantic 모델 확장

```python
# ═══ 신규 모델 ═══

class CapabilityCreate(BaseModel):
    """서비스(Capability) 생성"""
    display_name: str                                    # "매장 주차 안내"
    text: str                                            # 상세 안내 내용
    category: str                                        # "parking"
    response_type: Literal["info", "api_call", "transfer", "collect"] = "info"
    keywords: List[str] = []
    priority: int = 50                                   # 1~99
    is_active: bool = True
    owner: Optional[str] = None

    # response_type별 선택 필드
    api_endpoint: Optional[str] = None                   # api_call용
    api_method: Optional[Literal["GET", "POST"]] = None
    api_params: Optional[Dict[str, Any]] = None
    transfer_to: Optional[str] = None                    # transfer용
    collect_fields: Optional[List[Dict]] = None          # collect용


class CapabilityEntry(BaseModel):
    """서비스(Capability) 응답"""
    id: str
    display_name: str
    text: str
    category: str
    response_type: str
    keywords: List[str]
    priority: int
    is_active: bool
    owner: Optional[str] = None
    api_endpoint: Optional[str] = None
    api_method: Optional[str] = None
    api_params: Optional[Dict[str, Any]] = None
    transfer_to: Optional[str] = None
    collect_fields: Optional[List[Dict]] = None
    created_at: str
    updated_at: Optional[str] = None


class CapabilityListResponse(BaseModel):
    """서비스 목록 응답"""
    items: List[CapabilityEntry]
    total: int


class GuideTextResponse(BaseModel):
    """가이드 멘트 응답"""
    text: str
    capability_count: int
    cached: bool
    generated_at: str
```

---

## 5. Frontend UI 변경

### 5.1 현재 Frontend 구조

```
/knowledge          → 지식 관리 (list, 탭: faq/support/product/policy/hitl)
/knowledge/add      → 지식 추가 (text, category, keywords)
/knowledge/[id]/edit→ 지식 수정
/dashboard          → 운영 대시보드
```

### 5.2 신규 페이지: `/capabilities` (서비스 관리)

Knowledge 페이지와 별도로 **서비스(Capability) 전용 관리 페이지**를 신설합니다.

```
/capabilities               → 서비스 관리 메인
/capabilities/add           → 서비스 추가
/capabilities/[id]/edit     → 서비스 수정
```

### 5.3 서비스 관리 메인 (`/capabilities`)

```
┌─────────────────────────────────────────────────────────────┐
│  🤖 AI 서비스 관리                              [+ 서비스 추가] │
├─────────────────────────────────────────────────────────────┤
│                                                               │
│  📋 가이드 멘트 미리보기                          [🔄 새로고침]  │
│  ┌─────────────────────────────────────────────────────────┐ │
│  │ "저는 오시는길 안내, 주차 안내, 영업시간 안내,          │ │
│  │  메뉴 안내, 상담원 연결을 도와드릴 수 있어요.           │ │
│  │  어떤 것이 궁금하신가요?"                               │ │
│  └─────────────────────────────────────────────────────────┘ │
│                                                               │
│  ─────────────────────────────────────────────────────────── │
│                                                               │
│  [전체] [정보안내] [API연동] [상담원연결] [정보수집]           │
│                                                               │
│  순서  활성  서비스명         유형        카테고리    동작      │
│  ───────────────────────────────────────────────────────────  │
│  ⠿ 1  🟢  오시는길 안내     📄 정보안내  location   [편집][삭제]│
│  ⠿ 2  🟢  매장 주차 안내    📄 정보안내  parking    [편집][삭제]│
│  ⠿ 3  🟢  영업시간 안내     📄 정보안내  hours      [편집][삭제]│
│  ⠿ 4  🟢  판매 메뉴 안내    📄 정보안내  menu       [편집][삭제]│
│  ⠿ 5  🟢  실시간 날씨 조회  🔗 API연동   weather    [편집][삭제]│
│  ⠿ 99 🟢  상담원 연결       📞 상담원    transfer   [편집][삭제]│
│  ── ─  🔴  이벤트 안내       📄 정보안내  event      [편집][삭제]│
│                                                               │
│  ⠿ = 드래그로 순서 변경, 🟢/🔴 = 활성/비활성 토글             │
│                                                               │
└─────────────────────────────────────────────────────────────┘
```

**핵심 기능:**

| 기능 | 설명 |
|------|------|
| 가이드 멘트 미리보기 | VectorDB의 활성 capability → LLM 요약 결과를 실시간 미리보기 |
| 드래그 정렬 | priority 값을 드래그&드롭으로 변경 → `PUT /api/capabilities/reorder` |
| 활성/비활성 토글 | 스위치 클릭 → `PATCH /api/capabilities/{id}/toggle` |
| 탭 필터 | response_type별 필터 (전체, 정보안내, API연동, 상담원연결, 정보수집) |
| 추가/편집/삭제 | 표준 CRUD |

### 5.4 서비스 추가/편집 폼 (`/capabilities/add`, `/capabilities/[id]/edit`)

```
┌─────────────────────────────────────────────────────────────┐
│  ➕ 새 서비스 추가                                           │
├─────────────────────────────────────────────────────────────┤
│                                                               │
│  서비스명 *                                                    │
│  ┌─────────────────────────────────────────────────────────┐ │
│  │ 매장 주차 안내                                          │ │
│  └─────────────────────────────────────────────────────────┘ │
│                                                               │
│  카테고리 *           응답 유형 *                              │
│  ┌──────────────┐    ┌──────────────────────┐                │
│  │ parking    ▼ │    │ 📄 정보 안내       ▼ │                │
│  └──────────────┘    └──────────────────────┘                │
│                                                               │
│  안내 내용 *                                                   │
│  ┌─────────────────────────────────────────────────────────┐ │
│  │ 지하 1~3층에 고객 전용 주차장이 있으며, 2시간 무료      │ │
│  │ 주차가 가능합니다. 이후 30분당 1,000원이 부과됩니다.    │ │
│  │ 5만원 이상 구매 시 추가 1시간 무료입니다.               │ │
│  └─────────────────────────────────────────────────────────┘ │
│                                                               │
│  키워드 (쉼표 구분)                                           │
│  ┌─────────────────────────────────────────────────────────┐ │
│  │ 주차, 주차장, 주차비, 무료주차, 발렛                    │ │
│  └─────────────────────────────────────────────────────────┘ │
│                                                               │
│  ┌─── 응답 유형별 추가 설정 ──────────────────────────────┐  │
│  │                                                         │  │
│  │  (response_type = "info" 일 때)                         │  │
│  │  → 추가 설정 없음                                       │  │
│  │                                                         │  │
│  │  (response_type = "api_call" 일 때)                     │  │
│  │  API URL *      [https://api.example.com/weather     ]  │  │
│  │  HTTP 메서드    [GET ▼]                                 │  │
│  │  파라미터 (JSON) [{...}                              ]  │  │
│  │                                                         │  │
│  │  (response_type = "transfer" 일 때)                     │  │
│  │  연결 대상 *    [sip:operator@pbx.local              ]  │  │
│  │                                                         │  │
│  │  (response_type = "collect" 일 때)                      │  │
│  │  수집 항목:                                              │  │
│  │    [+ 항목 추가]                                        │  │
│  │    1. 이름  (필수) [텍스트]                              │  │
│  │    2. 날짜  (필수) [날짜]                                │  │
│  │    3. 인원  (필수) [숫자]                                │  │
│  └─────────────────────────────────────────────────────────┘ │
│                                                               │
│  우선순위        활성화                                        │
│  ┌────────┐    ┌────────────┐                                │
│  │ 2      │    │ 🟢 ON      │                                │
│  └────────┘    └────────────┘                                │
│                                                               │
│              [취소]  [저장]                                    │
└─────────────────────────────────────────────────────────────┘
```

### 5.5 기존 Knowledge 페이지 변경

기존 `/knowledge` 페이지는 **일반 지식/FAQ 관리** 용도로 유지하되, 탭 구성을 조정합니다.

```
변경 전 탭: [FAQ] [고객지원] [제품정보] [정책] [HITL저장]
변경 후 탭: [FAQ] [고객지원] [제품정보] [정책] [HITL저장] [통화추출]

* "서비스(Capability)" 항목은 /capabilities 페이지로 분리
* knowledge 페이지에서는 doc_type=knowledge, faq만 표시
```

### 5.6 사이드바 네비게이션 추가

```
현재:                          변경 후:
├── 🏠 대시보드                ├── 🏠 대시보드
├── 📞 통화 이력               ├── 📞 통화 이력
├── 📚 지식 관리               ├── 📚 지식 관리
└── ...                        ├── 🤖 서비스 관리  ← 신규
                               └── ...
```

### 5.7 대시보드 위젯 추가

대시보드에 서비스 상태 요약 카드를 추가합니다.

```
┌──────────────────────┐
│  🤖 AI 서비스 현황    │
│                       │
│  활성 서비스: 6개      │
│  비활성: 1개           │
│                       │
│  유형별:               │
│  📄 정보안내: 4        │
│  🔗 API연동: 1         │
│  📞 상담원연결: 1      │
│                       │
│  [서비스 관리 →]       │
└──────────────────────┘
```

---

## 6. AI Orchestrator 변경

### 6.1 play_greeting() 개편

```python
async def play_greeting(self):
    """2-Phase Greeting"""

    # ═══ Phase 1: 고정 인사말 (config.yaml) ═══
    fixed_greeting = self.config.get('greeting_message',
                                      '안녕하세요. AI 비서입니다.')
    await self.barge_in_controller.on_tts_start()

    # Phase 2를 Phase 1 발화 중 병렬 생성
    guide_task = asyncio.create_task(self._generate_capability_guide())

    await self.speak(fixed_greeting)

    # ═══ Phase 2: 가이드 멘트 (VectorDB 기반) ═══
    guide_text = await guide_task  # 이미 완료되었을 가능성 높음
    if guide_text:
        await self.barge_in_controller.on_tts_end()
        await self.speak(guide_text)
    else:
        await self.barge_in_controller.on_tts_end()
```

### 6.2 _generate_capability_guide()

```python
async def _generate_capability_guide(self) -> Optional[str]:
    """VectorDB에서 활성 서비스 목록 → LLM 자연어 요약"""

    # 1. 캐시 확인 (owner별, TTL 기반)
    cached = self._capability_guide_cache.get(self.callee)
    if cached and not cached.is_expired():
        return cached.text

    # 2. VectorDB에서 capability 목록 조회
    capabilities = await self.rag.vector_db.search_by_metadata(
        where={
            "doc_type": "capability",
            "is_active": True,
            "owner": self.callee
        },
        sort_by="priority"
    )

    if not capabilities:
        return None

    # 3. display_name 추출 (priority 순)
    display_names = [cap.metadata["display_name"] for cap in capabilities]
    max_items = self.config.get('capability_guide', {}).get('max_items', 5)
    display_names = display_names[:max_items]

    # 4. LLM으로 자연어 요약
    items_text = ", ".join(display_names)
    prompt = f"다음 항목을 자연어 한 문장으로 안내하세요: {items_text}"
    guide_text = await self.llm.generate_response(
        user_text=prompt,
        context_docs=[],
        call_id=self.call_id,
        system_prompt="전화 상담 안내 멘트를 간결하게 생성하세요. "
                      "형식: '저는 A, B, C를 안내해 드릴 수 있어요. "
                      "어떤 것이 궁금하신가요?'"
    )

    # 5. 캐시 저장
    self._capability_guide_cache.set(self.callee, guide_text, ttl=3600)

    return guide_text
```

### 6.3 후속 대화에서 response_type 분기

```python
async def generate_and_speak_response(self, user_text: str):
    """RAG 검색 → response_type별 분기"""

    # 1. RAG 검색
    documents = await self.rag.search(query=user_text, owner_filter=self.callee)

    if not documents:
        await self.speak("죄송합니다. 관련 정보를 찾지 못했습니다.")
        return

    top_doc = documents[0]
    response_type = top_doc.metadata.get("response_type", "info")

    # 2. response_type별 분기
    if response_type == "info":
        # 정보 안내: LLM이 문서 내용 기반 답변 생성
        response = await self.llm.generate_response(
            user_text=user_text,
            context_docs=[doc.text for doc in documents],
            call_id=self.call_id
        )
        await self.speak(response)

    elif response_type == "transfer":
        # 상담원 연결
        transfer_to = top_doc.metadata.get("transfer_to")
        await self.speak("네, 담당자에게 연결해 드리겠습니다. 잠시만 기다려 주세요.")
        # SIP PBX 호 전환 트리거
        await self._trigger_call_transfer(transfer_to)

    elif response_type == "api_call":
        # 외부 API 호출
        api_result = await self._call_external_api(top_doc.metadata)
        response = await self.llm.generate_response(
            user_text=user_text,
            context_docs=[api_result],
            call_id=self.call_id
        )
        await self.speak(response)

    elif response_type == "collect":
        # 정보 수집 (멀티턴)
        collect_fields = json.loads(top_doc.metadata.get("collect_fields", "[]"))
        await self._start_collection_flow(collect_fields)
```

---

## 7. 전체 시스템 다이어그램

```
┌──────────────────────────────────────────────────────────────────┐
│  Frontend (Next.js)                                               │
│                                                                    │
│  ┌────────────┐  ┌────────────────┐  ┌──────────────────────┐    │
│  │ /dashboard │  │ /knowledge     │  │ /capabilities        │    │
│  │ (대시보드)  │  │ (지식 관리)     │  │ (서비스 관리) ← 신규  │    │
│  │            │  │ doc_type:      │  │ doc_type:            │    │
│  │ 서비스현황  │  │ knowledge,faq  │  │ capability           │    │
│  │ 위젯      │  │               │  │                      │    │
│  │            │  │ CRUD          │  │ CRUD + 순서변경       │    │
│  │            │  │               │  │ + 활성토글           │    │
│  │            │  │               │  │ + 가이드멘트 미리보기 │    │
│  └─────┬──────┘  └───────┬───────┘  └──────────┬───────────┘    │
│        │                 │                      │                 │
└────────┼─────────────────┼──────────────────────┼─────────────────┘
         │                 │                      │
         ▼                 ▼                      ▼
┌──────────────────────────────────────────────────────────────────┐
│  Backend (FastAPI)                                                │
│                                                                    │
│  GET /api/knowledge/          ← doc_type 필터 추가                │
│  POST/PUT/DELETE /api/knowledge/*                                 │
│                                                                    │
│  GET /api/capabilities/       ← 신규 (활성 목록, priority 정렬)   │
│  POST/PUT/DELETE /api/capabilities/*                              │
│  PATCH /api/capabilities/{id}/toggle                              │
│  PUT /api/capabilities/reorder                                    │
│  GET /api/capabilities/guide-text                                 │
│                                                                    │
│  ┌─────────────────────┐                                         │
│  │ KnowledgeService    │                                         │
│  │ (확장: doc_type 지원)│                                         │
│  └──────────┬──────────┘                                         │
└─────────────┼────────────────────────────────────────────────────┘
              │
              ▼
┌──────────────────────────────────────────────────────────────────┐
│  ChromaDB (knowledge_base collection)                             │
│                                                                    │
│  ┌──────────────┐  ┌──────────────┐  ┌───────────────────────┐   │
│  │ doc_type=    │  │ doc_type=    │  │ doc_type=             │   │
│  │ capability   │  │ faq          │  │ knowledge             │   │
│  │              │  │              │  │                       │   │
│  │ response_type│  │ category     │  │ (통화 추출 지식)       │   │
│  │ display_name │  │ question     │  │                       │   │
│  │ priority     │  │ answer       │  │                       │   │
│  │ is_active    │  │              │  │                       │   │
│  └──────┬───────┘  └──────────────┘  └───────────────────────┘   │
└─────────┼────────────────────────────────────────────────────────┘
          │
          ▼
┌──────────────────────────────────────────────────────────────────┐
│  AI Orchestrator (SIP PBX 프로세스)                               │
│                                                                    │
│  play_greeting()                                                  │
│   ├─ Phase 1: config.yaml → greeting_message → TTS               │
│   └─ Phase 2: VectorDB(capability) → LLM 요약 → TTS              │
│                                                                    │
│  generate_and_speak_response()                                    │
│   ├─ RAG 검색 → response_type 확인                                │
│   ├─ info      → LLM 답변 생성 → TTS                              │
│   ├─ api_call  → 외부 API 호출 → LLM 가공 → TTS                   │
│   ├─ transfer  → TTS 안내 → SIP 호 전환                           │
│   └─ collect   → 멀티턴 정보 수집                                  │
└──────────────────────────────────────────────────────────────────┘
```

---

## 8. 구현 로드맵

| Phase | 내용 | 범위 | 난이도 |
|-------|------|------|--------|
| **Phase 1** | VectorDB 스키마 확장 + 시딩 로직 + `play_greeting()` 2-Phase 구현 | Backend + AI | 중 |
| **Phase 2** | Capability 전용 Backend API (`/api/capabilities/*`) | Backend | 중 |
| **Phase 3** | Frontend `/capabilities` 서비스 관리 페이지 (CRUD + 순서 + 토글) | Frontend | 중 |
| **Phase 4** | 가이드 멘트 미리보기 + 대시보드 위젯 | Frontend | 소 |
| **Phase 5** | `response_type=transfer` → SIP 호 전환 연동 | Backend + SIP | 중 |
| **Phase 6** | `response_type=api_call` → 외부 API 호출 프레임워크 | Backend | 상 |
| **Phase 7** | `response_type=collect` → 멀티턴 정보 수집 대화 | AI | 상 |

---

## 9. 기술 참고

### 9.1 업계 레퍼런스
- **Ada.cx Voice**: Greeting Builder + Transfer Call Block + End Call Block
- **Rasa Knowledge Base Actions**: object_type + attributes 스키마, `ActionQueryKnowledgeBase`
- **AURA (2025)**: 음성 에이전트 + function-calling (calendar, email, search)
- **Stream RAG (2025)**: 음성 중 tool 사용 예측 → 지연 20% 감소

### 9.2 ChromaDB 쿼리 패턴
- metadata pre-filter (`where` 절) → vector search 순서가 최적
- `where={"doc_type": "capability", "is_active": True}` → HNSW 검색 범위 축소
- ChromaDB metadata는 string, int, float, bool만 지원 (list/dict 불가 → JSON string으로 저장)
