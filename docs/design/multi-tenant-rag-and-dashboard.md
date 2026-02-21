# 멀티테넌트 RAG 및 대시보드 실제 구현 설계

> **상태**: 구현 완료  
> **최종 업데이트**: 2026-02-13  
> **관련 문서**: [ai-greeting-and-capability-guide.md](ai-greeting-and-capability-guide.md), [ai-implementation-guide-part2.md](ai-implementation-guide-part2.md)

---

## 1. 개요

### 1.1 배경

현재 시스템은 단일 테넌트(기상청) 기반으로 동작하며, 기관 정보가 `data/organization_info.json` 파일에 하드코딩되어 있다. 착신번호에 따라 서로 다른 AI 비서 인격과 지식을 제공하려면 **착신번호(callee) 기반 멀티테넌트** 구조가 필요하다.

### 1.2 목표

| # | 목표 | 설명 |
|---|------|------|
| 1 | **VectorDB 단일 소스** | 모든 기관/테넌트 정보를 VectorDB(ChromaDB)에서만 관리 |
| 2 | **착신번호 기반 격리** | `owner` 필드로 착신번호별 RAG 데이터 분리 |
| 3 | **초기 데이터 시드** | 1003(이탈리안 비스트로), 1004(기상청) 시드 데이터 자동 투입 |
| 4 | **대시보드 로그인** | 착신번호(1003/1004) 선택으로 로그인, 패스워드 불필요 |
| 5 | **프론트엔드 실제 구현** | 현재 mockup된 대시보드 메트릭, 지식관리 등 API 연동 |
| 6 | **대화 기반 지식 축적** | LLM 판단으로 대화에서 유용한 정보를 VectorDB에 자동 저장 |

### 1.3 현재 문제점

```
현재 구조:
  organization_info.json ──→ greeting, capabilities, system_prompt
  ChromaDB (knowledge_base) ──→ RAG 검색

문제:
  1. organization_info.json과 ChromaDB의 capabilities가 이중 관리됨
  2. organization_info.json은 단일 기관만 지원
  3. 대시보드 메트릭이 하드코딩 (Mock)
  4. 로그인이 Mock (아무 이메일/패스워드로 통과)
  5. LangGraph adaptive_rag_node에 owner_filter 미전달
```

---

## 2. 아키텍처

### 2.1 데이터 모델 변경

#### 2.1.1 테넌트 정보 (VectorDB에 `doc_type=tenant_config` 저장)

기존 `organization_info.json` 역할을 VectorDB로 이전한다.

```
doc_type: "tenant_config"
owner: "1004"              # 착신번호 = 테넌트 ID
metadata:
  tenant_name: "기상청"
  tenant_name_en: "Korea Meteorological Administration"
  tenant_type: "government_agency"
  description: "대한민국의 기상 및 기후 정보를 제공하는 정부 기관"
  service_description: "날씨 예보 및 기상 정보 안내"
  main_phone: "131"
  website: "www.kma.go.kr"
  business_hours: "평일 09:00-18:00"
  system_prompt_template: "당신은 {tenant_name}의 친절한 AI 통화 비서입니다..."
  greeting_templates: '["안녕하세요. 기상청 AI 비서입니다...", ...]'  # JSON 문자열
```

#### 2.1.2 기존 doc_type (변경 없음, owner 필수화)

| doc_type | 용도 | owner 필수 |
|----------|------|-----------|
| `tenant_config` | 테넌트 설정 (NEW) | YES |
| `capability` | AI 서비스/기능 | YES |
| `knowledge` | 일반 지식 | YES |
| `qa_pair` | Q&A 쌍 (추출) | YES |
| `entity` | 엔티티 (추출) | YES |
| `faq` | FAQ (NEW) | YES |

> **핵심 원칙**: `owner` 필드 없는 문서는 존재하지 않는다. 모든 문서는 반드시 `owner`(착신번호)를 가진다.

### 2.2 데이터 흐름

```
┌──────────────────────────────────────────────────────────┐
│                    ChromaDB (knowledge_base)              │
│                                                          │
│  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐      │
│  │ owner=1003  │  │ owner=1004  │  │ owner=1005  │ ...  │
│  │             │  │             │  │ (future)    │      │
│  │ tenant_cfg  │  │ tenant_cfg  │  │             │      │
│  │ capabilities│  │ capabilities│  │             │      │
│  │ knowledge   │  │ knowledge   │  │             │      │
│  │ faq         │  │ faq         │  │             │      │
│  └─────────────┘  └─────────────┘  └─────────────┘      │
└──────────────────────┬───────────────────────────────────┘
                       │
       ┌───────────────┼───────────────┐
       ▼               ▼               ▼
  SIP Call          Web Dashboard    대화 기반 저장
  (callee=1004)    (login=1004)     (LLM → VectorDB)
       │               │               │
       ▼               ▼               ▼
  RAG Engine       REST API        Knowledge Extractor
  (owner_filter    (owner header    (owner from callee)
   =callee)        from login)
```

### 2.3 SIP 착신 → AI 파이프라인 흐름

```
1. SIP INVITE 수신 → callee = "1004"
2. AI Pipeline 생성 시 callee 전달
3. OrganizationInfoManager → VectorDB에서 tenant_config 로드 (owner=1004)
4. Greeting Phase 1: tenant_config의 greeting_templates에서 랜덤 선택
5. Greeting Phase 2: capabilities (owner=1004) 조회 → 안내문 생성
6. 대화 중 RAG 검색: owner_filter=1004
7. 지식 추출: 새 지식 저장 시 owner=1004
```

---

## 3. 백엔드 변경 사항

### 3.1 OrganizationInfoManager 개편

**파일**: `src/ai_voicebot/knowledge/organization_info.py`

```python
class OrganizationInfoManager:
    """착신번호(owner) 기반 테넌트 정보 관리자
    
    기존: data/organization_info.json에서 단일 기관 정보 로드
    변경: ChromaDB에서 owner별 tenant_config 로드
    """
    
    def __init__(self, owner: str, knowledge_service=None):
        """
        Args:
            owner: 착신번호 (예: "1004")
            knowledge_service: KnowledgeService 인스턴스
        """
        self.owner = owner
        self.knowledge_service = knowledge_service
        self.tenant_config = None  # VectorDB에서 로드
        self._cache = {}           # 캐시
    
    async def load(self) -> None:
        """VectorDB에서 tenant_config 로드"""
        # ChromaDB: where={"$and": [{"doc_type": "tenant_config"}, {"owner": self.owner}]}
        ...
    
    def get_organization_name(self) -> str:
        return self.tenant_config.get("tenant_name", "AI 비서")
    
    def get_greeting_templates(self) -> List[str]:
        templates_json = self.tenant_config.get("greeting_templates", "[]")
        return json.loads(templates_json)
    
    def get_system_prompt(self) -> str:
        template = self.tenant_config.get("system_prompt_template", DEFAULT_PROMPT)
        return template.format(
            tenant_name=self.get_organization_name(),
            capabilities=await self.get_capabilities_text()
        )
    
    async def get_capabilities(self) -> List[str]:
        """VectorDB에서 owner의 활성 capabilities 조회"""
        caps = await self.knowledge_service.get_all_capabilities(
            owner=self.owner, active_only=True
        )
        return [c["display_name"] for c in caps]
```

### 3.2 LangGraph adaptive_rag_node에 owner_filter 추가

**파일**: `src/ai_voicebot/langgraph/nodes/adaptive_rag.py`

```python
async def adaptive_rag_node(state: ConversationState) -> dict:
    query = state.get("rewritten_query") or state.get("user_query", "")
    rag_engine = state.get("_rag_engine")
    owner = state.get("_owner")  # ← 추가: 착신번호
    
    if not rag_engine or not query:
        return {"rag_results": [], "confidence": 0.0}
    
    # owner_filter 전달하여 테넌트 격리된 검색
    search_results = await rag_engine.search(
        query, 
        owner_filter=owner,  # ← 추가
        top_k_override=SENTENCE_TOP_K
    )
    ...
```

### 3.3 Knowledge API에 owner 필터 추가

**파일**: `src/api/routers/knowledge.py`

모든 Knowledge API에 `owner` 파라미터를 추가한다. 프론트엔드에서 로그인된 착신번호를 `X-Owner` 헤더 또는 쿼리 파라미터로 전달한다.

```python
@router.get("/", response_model=KnowledgeListResponse)
async def list_knowledge(
    page: int = 1,
    limit: int = 50,
    category: Optional[str] = None,
    search: Optional[str] = None,
    owner: Optional[str] = None,  # ← 추가
):
    """지식 베이스 목록 조회 (owner별 격리)"""
    ...

@router.post("/", response_model=KnowledgeEntry)
async def create_knowledge(
    entry: KnowledgeEntryCreate,
    owner: Optional[str] = None,  # ← 추가
):
    """새 지식 항목 추가 (owner 자동 설정)"""
    ...
```

### 3.4 Tenant Config API (신규)

**파일**: `src/api/routers/tenants.py` (신규)

```python
router = APIRouter()

@router.get("/")
async def list_tenants():
    """등록된 테넌트(착신번호) 목록 조회
    
    Returns: [
        {"owner": "1003", "name": "이탈리안 비스트로", "type": "restaurant"},
        {"owner": "1004", "name": "기상청", "type": "government_agency"}
    ]
    """
    ...

@router.get("/{owner}")
async def get_tenant(owner: str):
    """특정 테넌트 정보 조회"""
    ...

@router.put("/{owner}")
async def update_tenant(owner: str, config: TenantConfigUpdate):
    """테넌트 설정 수정"""
    ...
```

### 3.5 Auth API 변경

**파일**: `src/api/routers/auth.py`

```python
@router.post("/login")
async def login(request: LoginRequest):
    """착신번호 기반 로그인 (패스워드 불필요)
    
    Request: { "extension": "1004" }
    Response: {
        "access_token": "jwt_or_simple_token",
        "tenant": { "owner": "1004", "name": "기상청", ... }
    }
    """
    # 1. VectorDB에서 tenant_config 조회
    # 2. 존재하면 토큰 발급 (단순 JWT 또는 세션)
    # 3. 미등록 착신번호면 403
    ...
```

### 3.6 Dashboard Metrics API (실제 구현)

**파일**: `src/api/routers/metrics.py`

```python
@router.get("/dashboard")
async def get_dashboard_metrics(owner: Optional[str] = None):
    """대시보드 메트릭 조회
    
    Response: {
        "active_calls": 2,           # 현재 진행 중인 통화 수
        "hitl_queue_size": 1,        # HITL 대기 건수
        "avg_ai_confidence": 0.85,   # 평균 AI 신뢰도
        "today_calls_count": 15,     # 오늘 총 통화 수
        "avg_response_time": 1.2,    # 평균 응답 시간 (초)
        "knowledge_base_size": 42,   # 지식 베이스 문서 수
        "capabilities_count": 5,     # 활성 capability 수
    }
    """
    # owner가 주어지면 해당 테넌트의 메트릭만 반환
    ...
```

---

## 4. 초기 시드 데이터

### 4.1 시드 데이터 로더

**파일**: `src/services/seed_data.py` (신규)

서버 시작 시 VectorDB에 초기 데이터가 없으면 자동으로 시드 데이터를 투입한다.
기존 `knowledge.py`의 `init_sample_data()`를 이 모듈로 이전하고, 기존 샘플 데이터는 삭제한다.

```python
async def seed_initial_data(knowledge_service):
    """서버 시작 시 초기 데이터 투입
    
    1. tenant_config가 없으면 1003, 1004 테넌트 생성
    2. 각 테넌트별 capabilities 생성
    3. 각 테넌트별 FAQ/knowledge 생성
    """
    ...
```

### 4.2 1003 - 이탈리안 비스트로 (Italian Bistro)

#### tenant_config
```json
{
  "doc_type": "tenant_config",
  "owner": "1003",
  "tenant_name": "이탈리안 비스트로",
  "tenant_name_en": "Italian Bistro",
  "tenant_type": "restaurant",
  "description": "정통 이탈리아 요리를 선보이는 캐주얼 다이닝 레스토랑",
  "service_description": "메뉴 안내, 예약, 영업시간 문의",
  "main_phone": "02-1234-5678",
  "website": "www.italian-bistro.kr",
  "business_hours": "매일 11:30-22:00 (브레이크타임 15:00-17:00)",
  "greeting_templates": [
    "안녕하세요! 이탈리안 비스트로입니다. 무엇을 도와드릴까요?",
    "이탈리안 비스트로에 전화 주셔서 감사합니다. AI 비서가 안내해 드리겠습니다.",
    "안녕하세요. 이탈리안 비스트로 AI 상담원입니다. 어떤 것이 궁금하신가요?"
  ],
  "system_prompt_template": "당신은 {tenant_name}의 친절한 AI 전화 비서입니다.\n\n## 역할\n- 고객의 메뉴, 예약, 영업시간 등 문의에 친절하게 답변\n- 간결하고 명확하게 1-2문장으로 답변\n- 예약은 날짜, 시간, 인원을 확인\n\n## 제공 가능한 서비스\n{capabilities}\n\n## 제약 사항\n- 레스토랑과 관련 없는 주제는 정중히 거절\n- 실제 결제나 주문 처리는 불가 (안내만 가능)"
}
```

#### capabilities (owner=1003)

| # | display_name | category | response_type | text |
|---|---|---|---|---|
| 1 | 메뉴 안내 | menu | info | 파스타, 피자, 리조또, 스테이크 등 이탈리안 정통 메뉴를 안내합니다. |
| 2 | 예약 안내 | reservation | collect | 날짜, 시간, 인원수를 확인하여 예약을 도와드립니다. |
| 3 | 영업시간 안내 | hours | info | 영업시간, 브레이크타임, 라스트오더 시간을 안내합니다. |
| 4 | 오시는 길 안내 | location | info | 매장 위치와 주차 정보를 안내합니다. |
| 5 | 상담원 연결 | transfer | transfer | 더 자세한 상담이 필요한 경우 직원에게 연결합니다. |

#### knowledge (owner=1003)

| # | category | text |
|---|----------|------|
| 1 | menu | **파스타 메뉴**: 까르보나라 16,000원, 알리오올리오 14,000원, 봉골레 17,000원, 아마트리치아나 15,000원, 트러플 크림 파스타 22,000원 |
| 2 | menu | **피자 메뉴**: 마르게리타 15,000원, 페퍼로니 17,000원, 콰트로 포르마지 19,000원, 프로슈토 루콜라 21,000원 |
| 3 | menu | **메인 요리**: 안심 스테이크 35,000원, 오소부코 28,000원, 해산물 리조또 22,000원, 밀라노식 커틀릿 24,000원 |
| 4 | menu | **런치 세트**: 평일 11:30-14:30, 파스타/피자 + 샐러드 + 음료 = 15,000원. 주말 런치 세트는 운영하지 않습니다. |
| 5 | hours | 영업시간은 매일 11:30~22:00이며, 브레이크타임은 15:00~17:00입니다. 라스트오더는 21:00입니다. 매주 월요일은 정기 휴무입니다. |
| 6 | location | 서울시 강남구 테헤란로 123 비스트로빌딩 1층에 위치합니다. 지하철 2호선 강남역 3번 출구에서 도보 5분 거리입니다. |
| 7 | parking | 건물 지하 주차장 이용 가능합니다. 식사 고객에게 2시간 무료 주차를 제공합니다. 주차 공간이 한정되어 있어 대중교통 이용을 권장합니다. |
| 8 | reservation | 예약은 전화 또는 네이버 예약으로 가능합니다. 2인~8인 테이블 예약 가능하며, 10인 이상 단체 예약은 별도 문의 바랍니다. 당일 예약은 17시 이전 가능합니다. |
| 9 | policy | 노쇼(No-show) 방지를 위해 예약 시간 15분 초과 시 자동 취소될 수 있습니다. 예약 변경/취소는 방문 2시간 전까지 가능합니다. |
| 10 | event | 매월 첫째 주 수요일은 와인 데이로 하우스 와인 50% 할인입니다. 생일 고객에게는 디저트 서비스를 제공합니다 (사전 예약 필요). |

#### FAQ (owner=1003, doc_type=faq)

| question | answer |
|----------|--------|
| 주차 가능한가요? | 네, 건물 지하 주차장을 이용하실 수 있으며 식사 고객에게 2시간 무료 주차를 제공합니다. |
| 예약 가능한가요? | 네, 전화 또는 네이버 예약으로 가능합니다. 2인~8인 테이블 예약 가능합니다. |
| 런치 세트 있나요? | 네, 평일 11:30~14:30에 파스타/피자 + 샐러드 + 음료 = 15,000원 런치 세트를 운영합니다. |
| 영업시간이 어떻게 되나요? | 매일 11:30~22:00이며, 브레이크타임은 15:00~17:00입니다. 매주 월요일은 정기 휴무입니다. |
| 단체 예약 가능한가요? | 10인 이상 단체 예약은 별도 문의 부탁드립니다. 전화로 연락 주시면 안내해 드리겠습니다. |

---

### 4.3 1004 - 기상청

#### tenant_config
```json
{
  "doc_type": "tenant_config",
  "owner": "1004",
  "tenant_name": "기상청",
  "tenant_name_en": "Korea Meteorological Administration",
  "tenant_type": "government_agency",
  "description": "대한민국의 기상 및 기후 정보를 제공하는 정부 기관",
  "service_description": "날씨 예보 및 기상 정보 안내",
  "main_phone": "131",
  "website": "www.kma.go.kr",
  "business_hours": "평일 09:00-18:00",
  "greeting_templates": [
    "안녕하세요. 기상청 AI 통화 비서입니다. 무엇을 도와드릴까요?",
    "안녕하세요. 기상청 AI 상담원입니다. 어떤 도움이 필요하신가요?",
    "기상청에 전화해 주셔서 감사합니다. AI 비서가 도와드리겠습니다.",
    "안녕하세요. 기상청입니다. 날씨와 관련된 문의를 도와드리겠습니다."
  ],
  "system_prompt_template": "당신은 {tenant_name}의 친절하고 전문적인 AI 통화 비서입니다.\n\n## 역할과 책임\n- 발신자의 질문에 정확하고 친절하게 답변\n- {tenant_name}의 서비스와 정보를 명확하게 안내\n- 필요시 적절한 부서나 담당자에게 연결 제안\n\n## 제공 가능한 서비스\n{capabilities}\n\n## 대화 원칙\n1. 간결하고 명확하게 답변 (1-2문장)\n2. 전문 용어는 쉽게 풀어서 설명\n3. 모르는 것은 솔직히 인정하고 대안 제시\n\n## 제약 사항\n- {tenant_name}과 관련 없는 주제는 정중히 거절\n- 실시간 날씨 정보는 기상청 웹사이트나 담당자 연결을 안내"
}
```

#### capabilities (owner=1004)

| # | display_name | category | response_type | text |
|---|---|---|---|---|
| 1 | 날씨 예보 조회 | weather_forecast | info | 오늘, 내일, 주간 날씨 예보 정보를 안내합니다. 실시간 정보는 기상청 웹사이트를 안내합니다. |
| 2 | 기상 특보 안내 | weather_warning | info | 현재 발효 중인 기상 특보(호우, 태풍, 폭설 등)를 안내합니다. |
| 3 | 과거 기상 데이터 제공 | historical_data | info | 과거 기상 관측 데이터 조회 및 자료 신청 방법을 안내합니다. |
| 4 | 기상청 담당자 연결 | transfer | transfer | 전문 상담이 필요한 경우 담당 부서로 연결합니다. |
| 5 | 일반 기상 상식 안내 | weather_knowledge | info | 기상 용어, 날씨 현상, 기후 변화 등 일반적인 기상 상식을 안내합니다. |

#### knowledge (owner=1004)

| # | category | text |
|---|----------|------|
| 1 | weather_forecast | 날씨 예보는 기상청 홈페이지(www.kma.go.kr), 날씨누리 앱, 또는 131번 자동응답전화에서 확인할 수 있습니다. 동네예보는 읍면동 단위로 제공됩니다. |
| 2 | weather_warning | 기상 특보는 주의보와 경보로 나뉩니다. 호우, 대설, 한파, 폭염, 태풍, 강풍, 건조 등의 특보가 있으며, 재난문자로도 안내됩니다. |
| 3 | weather_warning | 태풍 정보는 기상청 홈페이지 '태풍정보' 메뉴에서 실시간 확인 가능합니다. 진로 예측, 강도, 예상 영향 지역을 상세히 안내합니다. |
| 4 | historical_data | 과거 기상 데이터는 기상자료개방포털(data.kma.go.kr)에서 무료로 조회하실 수 있습니다. 기온, 강수량, 풍속 등 관측 자료를 제공합니다. |
| 5 | service_info | 기상청 고객센터 전화번호는 131입니다. 운영시간은 평일 09:00~18:00이며, 긴급 기상 상황 시에는 24시간 운영합니다. |
| 6 | weather_knowledge | 장마는 보통 6월 중순~7월 중순에 시작되며, 약 한 달간 지속됩니다. 장마 기간 중 강수량은 연간 강수량의 약 30%를 차지합니다. |
| 7 | weather_knowledge | 미세먼지 정보는 에어코리아(airkorea.or.kr)에서 실시간 확인 가능합니다. 기상청은 황사 관측 및 예보를 담당합니다. |
| 8 | application | 기상감정서 발급은 기상청 홈페이지에서 온라인 신청 가능합니다. 신청 후 약 7~14일 소요되며, 수수료가 발생합니다. |

#### FAQ (owner=1004, doc_type=faq)

| question | answer |
|----------|--------|
| 내일 날씨 어떤가요? | 실시간 날씨 정보는 기상청 홈페이지(www.kma.go.kr)나 날씨누리 앱에서 확인하실 수 있습니다. 담당자에게 연결해 드릴까요? |
| 태풍 정보는 어떻게 확인하나요? | 기상청 홈페이지의 '태풍정보' 메뉴에서 실시간으로 확인 가능합니다. 진로와 강도, 예상 영향 지역을 안내합니다. |
| 과거 날씨 데이터는 어떻게 받나요? | 기상자료개방포털(data.kma.go.kr)에서 무료로 조회 가능합니다. 자세한 절차는 담당자에게 연결해 드릴까요? |
| 기상감정서 발급은 어떻게 하나요? | 기상청 홈페이지에서 온라인으로 신청 가능하며, 약 7~14일 소요됩니다. |
| 담당자와 통화하고 싶어요 | 알겠습니다. 담당 부서로 연결해 드리겠습니다. 잠시만 기다려 주세요. |

---

## 5. 프론트엔드 변경 사항

### 5.1 로그인 페이지 개편

**파일**: `frontend/app/login/page.tsx`

현재 이메일/패스워드 Mock 로그인을 **착신번호 선택** 방식으로 변경한다.

```
┌─────────────────────────────────────────┐
│                                         │
│        🤖 AI Voicebot                   │
│        Control Center                   │
│                                         │
│   ┌─────────────────────────────────┐   │
│   │  착신번호를 선택하세요          │   │
│   │                                 │   │
│   │  ┌──────────────────────────┐   │   │
│   │  │  📞 1003                 │   │   │
│   │  │  이탈리안 비스트로       │   │   │
│   │  │  restaurant              │   │   │
│   │  └──────────────────────────┘   │   │
│   │                                 │   │
│   │  ┌──────────────────────────┐   │   │
│   │  │  📞 1004                 │   │   │
│   │  │  기상청                  │   │   │
│   │  │  government_agency       │   │   │
│   │  └──────────────────────────┘   │   │
│   │                                 │   │
│   └─────────────────────────────────┘   │
│                                         │
└─────────────────────────────────────────┘
```

**동작**:
1. 페이지 로드 시 `GET /api/tenants` 호출 → 등록된 테넌트 목록 표시
2. 테넌트 카드 클릭 → `POST /api/auth/login` (`{ extension: "1004" }`)
3. 응답의 `access_token`을 `localStorage`에 저장
4. `/dashboard`로 리다이렉트

**localStorage 구조**:
```javascript
{
  "access_token": "token_1004_...",
  "tenant": {
    "owner": "1004",
    "name": "기상청",
    "type": "government_agency"
  }
}
```

### 5.2 대시보드 레이아웃 변경

**파일**: `frontend/app/layout.tsx`, `frontend/app/dashboard/page.tsx`

#### 헤더에 테넌트 정보 표시

```
┌────────────────────────────────────────────────────────────────┐
│ 🤖 AI Voicebot │ 기상청 (1004) │ 대시보드 │ ... │ 로그아웃    │
└────────────────────────────────────────────────────────────────┘
```

#### 대시보드 메트릭 실제 API 연동

| 현재 (Mock) | 변경 (API) | API |
|---|---|---|
| `activeCalls: 3` (하드코딩) | 실시간 활성 통화 수 | `GET /api/calls/active?owner={owner}` |
| `todayCallsCount: 42` (하드코딩) | CDR 기반 오늘 통화 수 | `GET /api/metrics/dashboard?owner={owner}` |
| `avgAIConfidence: 85` (하드코딩) | 실제 평균 신뢰도 | `GET /api/metrics/dashboard?owner={owner}` |
| `knowledgeBaseSize: 156` (하드코딩) | VectorDB 문서 수 | `GET /api/metrics/dashboard?owner={owner}` |
| `avgResponseTime: 0.9` (하드코딩) | 실제 평균 응답 시간 | `GET /api/metrics/dashboard?owner={owner}` |

### 5.3 지식 관리 페이지 (Knowledge)

**현재 상태**: API 연동 완료 (CRUD)
**변경 필요**: owner 필터 추가

```
모든 API 호출에 owner 파라미터 추가:
  GET /api/knowledge?owner=1004
  POST /api/knowledge (body에 owner 포함)
  PUT /api/knowledge/{id} (body에 owner 포함)
  DELETE /api/knowledge/{id}
```

### 5.4 AI 서비스(Capabilities) 페이지

**현재 상태**: API 연동 완료
**변경 필요**: owner 필터 추가

```
  GET /api/capabilities?owner=1004
  POST /api/capabilities (body에 owner 포함)
```

### 5.5 통화 이력 페이지 (Call History)

**현재 상태**: API 연동 완료
**변경 필요**: owner(착신번호) 필터 추가

```
  GET /api/call-history?callee=1004
```

### 5.6 지식 추출 페이지 (Extractions)

**현재 상태**: API 연동 완료
**변경 필요**: owner 필터 추가

```
  GET /api/extractions?owner=1004
```

### 5.7 Mock → 실제 구현 매핑 요약

| 페이지 | 현재 상태 | 필요 작업 |
|--------|----------|-----------|
| 로그인 | Mock (아무 이메일 가능) | 착신번호 선택 방식으로 교체 |
| 대시보드 메트릭 | Mock (하드코딩) | `GET /api/metrics/dashboard` 연동 |
| 대시보드 활성통화 | Mock (빈 리스트) | `GET /api/calls/active` + WebSocket 연동 |
| 지식 관리 | API 연동 완료 | owner 필터 추가 |
| AI 서비스 | API 연동 완료 | owner 필터 추가 |
| 통화 이력 | API 연동 완료 | owner(callee) 필터 추가 |
| 통화 상세 | API 연동 완료 | 변경 없음 |
| 지식 추출 | API 연동 완료 | owner 필터 추가 |
| 호 전환 | API 연동 완료 | 변경 없음 |
| AI 발신 | API 연동 완료 | 변경 없음 |

---

## 6. 대화 기반 지식 축적

### 6.1 흐름

```
사용자 발화 → STT → LLM 대화 처리 → 응답 생성
                                      │
                                      ├─ Knowledge Extractor (통화 종료 후)
                                      │   └─ LLM이 유용한 정보 판단
                                      │       └─ VectorDB 저장 (owner=callee)
                                      │
                                      └─ 실시간 학습 (대화 중)
                                          └─ LLM이 "이건 기억할 만하다" 판단
                                              └─ extraction_source="conversation"
                                                  review_status="pending"
                                                  owner=callee
```

### 6.2 자동 저장 기준

LLM이 대화 중 또는 통화 종료 후 다음 기준으로 지식 저장을 판단:

| 기준 | 예시 |
|------|------|
| **새로운 FAQ** | "주차요금이 바뀌었나요?" → 기존 DB에 없는 새 정보 |
| **정보 업데이트** | "이번 달부터 브레이크타임이 없어졌어요" → 기존 정보 갱신 |
| **고객 피드백** | "지난번 방문 때 서비스가 좋았어요" → 서비스 피드백 |
| **빈출 질문** | 같은 유형의 질문이 반복됨 → FAQ 후보 |

### 6.3 운영자 검토 흐름

```
자동 추출 (pending) → 프론트엔드 "지식 추출" 페이지
                        │
                        ├─ 승인 (approved) → VectorDB에 확정
                        ├─ 수정 후 승인 (edited) → 수정된 내용으로 VectorDB 저장
                        └─ 거절 (rejected) → 삭제 또는 비활성
```

---

## 7. 삭제/정리 대상

### 7.1 `data/organization_info.json`

VectorDB로 이전 후 삭제한다. `OrganizationInfoManager`는 VectorDB 기반으로 완전 교체한다.

**마이그레이션 순서**:
1. VectorDB에 시드 데이터 투입 (tenant_config + capabilities + faq + knowledge)
2. `OrganizationInfoManager`를 VectorDB 기반으로 리팩토링
3. 기존 코드에서 `organization_info.json` 참조 제거
4. `organization_info.json` 파일 삭제

### 7.2 기존 샘플 데이터

`knowledge.py`의 `init_sample_data()`에 있는 "영업시간은 평일 오전 9시..." 등 기존 generic 샘플 데이터를 삭제한다. 이를 `seed_data.py`로 이전한다.

### 7.3 기존 ChromaDB 데이터

현재 ChromaDB에 있는 owner 없는 기존 데이터(capability 5건, manual 3건)를 정리한다.

---

## 8. 구현 순서 (Phase)

### Phase 1: 기반 구조 (Backend)
1. `seed_data.py` 작성 (1003, 1004 시드 데이터)
2. `OrganizationInfoManager` VectorDB 기반으로 리팩토링
3. Knowledge API에 owner 필터 추가 (`GET /{id}` 포함)
4. Capabilities API에 owner 필터 확인
5. Tenant Config API 추가 (`/api/tenants`)
6. Auth API 변경 (착신번호 기반 로그인)
7. Dashboard Metrics API 실제 구현
8. LangGraph adaptive_rag_node에 owner_filter 추가
9. 기존 ChromaDB 데이터 정리 + 시드 데이터 투입
10. `organization_info.json` 삭제

### Phase 2: 프론트엔드
1. 로그인 페이지 교체 (착신번호 선택)
2. 레이아웃에 테넌트 정보 표시
3. 전역 owner 컨텍스트 (React Context 또는 Zustand)
4. 대시보드 메트릭 API 연동
5. 모든 페이지에 owner 필터 적용
6. 지식 관리 페이지 수정 (owner 포함 CRUD)
7. AI 서비스 페이지 수정 (owner 포함 CRUD)

### Phase 3: 검증 및 최적화
1. 1003 착신 → 이탈리안 비스트로 AI 응대 테스트
2. 1004 착신 → 기상청 AI 응대 테스트
3. 프론트엔드 1003 로그인 → 비스트로 데이터만 표시 확인
4. 프론트엔드 1004 로그인 → 기상청 데이터만 표시 확인
5. 대화 기반 지식 추출 → owner 자동 설정 확인

---

## 9. API 명세 요약

### 9.1 신규 API

| Method | Path | 설명 |
|--------|------|------|
| GET | `/api/tenants` | 등록된 테넌트 목록 |
| GET | `/api/tenants/{owner}` | 테넌트 상세 정보 |
| PUT | `/api/tenants/{owner}` | 테넌트 설정 수정 |
| POST | `/api/auth/login` | 착신번호 기반 로그인 |
| GET | `/api/metrics/dashboard?owner=` | 대시보드 메트릭 (실제) |

### 9.2 변경 API (owner 필터 추가)

| Method | Path | 변경 내용 |
|--------|------|-----------|
| GET | `/api/knowledge?owner=` | owner 쿼리 파라미터 추가 |
| POST | `/api/knowledge` | body에 owner 필드 추가 |
| GET | `/api/capabilities?owner=` | owner 쿼리 파라미터 추가 |
| POST | `/api/capabilities` | body에 owner 필드 추가 |
| GET | `/api/call-history?callee=` | callee 쿼리 파라미터 추가 |
| GET | `/api/extractions?owner=` | owner 쿼리 파라미터 추가 |

---

## 10. 데이터 무결성 규칙

1. **owner 필수**: 모든 VectorDB 문서에 owner 필수. owner가 없는 문서는 생성/조회 불가.
2. **테넌트 격리**: API 호출 시 owner가 다른 데이터에 접근 불가.
3. **시드 데이터 보호**: 시드 데이터는 `source: "seed"`로 표시. 웹에서 수정/삭제 가능하지만 경고 표시.
4. **중복 방지**: 동일 텍스트 + 동일 owner는 upsert로 처리.
