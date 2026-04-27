# Agentic AI 통화비서 × MCP 기능 확장 기획

- **작성일**: 2026-04-13
- **상태**: 기획/제안
- **분류**: 기능 로드맵
- **관련 도메인**: AI Orchestrator / MCP 연동 전략

---

## 개요

현재 시스템은 **LLM(Google Gemini) + RAG(ChromaDB) + HITL(Human-in-the-Loop)** 구조로 구성된 AI 통화비서다.
MCP(Model Context Protocol)를 도입하면 LLM이 통화 중 실시간으로 외부 서비스에 접근하여
단순 응대를 넘어 **예약·결제·CRM·알림 등 실제 업무 처리**까지 수행할 수 있게 된다.

현재 `LangGraph → generate_response_node` 단계에서 MCP 툴 호출을 삽입하는 방식으로 확장 가능하다.

---

## 현재 아키텍처 요약

```
[전화 수신]
  ↓
[SIP B2BUA] → [RTP 스트림]
  ↓
[VAD] → [Google STT]
  ↓
[RAG Engine (ChromaDB)] + [LLM Client (Gemini)]
  ↓
[LangGraph Orchestrator]
  ├── generate_response_node
  ├── classify_intent
  └── HITL (운영자 개입)
  ↓
[TTS] → [RTP 전송]
```

**현재 한계**: LLM이 알고 있는 정보(RAG 지식베이스)만 답변 가능.
외부 시스템(예약, 재고, CRM 등)에 실시간 접근 불가.

---

## MCP 도입 시 확장 아키텍처

```
[LangGraph Orchestrator]
  ├── generate_response_node
  ├── classify_intent
  ├── [MCP Tool Router] ← 신규
  │     ├── MCP Server A (캘린더/예약)
  │     ├── MCP Server B (CRM/고객정보)
  │     ├── MCP Server C (결제)
  │     ├── MCP Server D (재고/상품)
  │     ├── MCP Server E (알림/SMS)
  │     └── MCP Server N (확장 가능)
  └── HITL (운영자 개입 - 줄어듦)
```

LangGraph의 `MultiServerMCPClient`를 사용해 통화 컨텍스트 내에서 동적으로 툴 호출.

---

## 카테고리별 MCP 기능 제안

### 1. 예약·일정 관리 (Scheduling)

| 기능 | MCP 서버 | 레퍼런스 |
|------|----------|----------|
| Google 캘린더 예약 조회/생성/수정 | `google-calendar-mcp` | github.com/nspady/google-calendar-mcp ⭐1K |
| 자체 예약 시스템 연동 | 커스텀 MCP 서버 | 현재 DB 래핑 |
| 네이버 예약 (파트너 계약 후) | 커스텀 MCP 서버 | 전 리포트 참조 |

**통화 시나리오**:
> "다음 주 화요일 오후 3시에 예약해 드릴게요. 확인해볼게요."
> → MCP 툴: `list_events(date=...)` → `create_event(...)` → "확인됐습니다, 예약 완료했습니다."

---

### 2. 고객 정보 조회 (CRM)

| 기능 | MCP 서버 | 레퍼런스 |
|------|----------|----------|
| HubSpot 고객 조회/메모 추가 | `mcp-hubspot` | github.com/peakmojo/mcp-hubspot ⭐120 |
| Salesforce 리드·케이스 관리 | `MCP-Salesforce` | github.com/smn2gnt/MCP-Salesforce ⭐172 |
| 자체 PostgreSQL 고객 DB | `postgres-mcp` | github.com/crystaldba/postgres-mcp ⭐2.5K |

**통화 시나리오**:
> 발신자 번호(010-XXXX) → CRM에서 자동 조회 → "김철수 고객님, 지난번 주문 건 관련해서 연락 주셨군요."
> → 통화 종료 후 자동 메모 저장

---

### 3. 알림·메시지 발송 (Notification)

| 기능 | MCP 서버 | 레퍼런스 |
|------|----------|----------|
| 이메일 발송 (Gmail/Mailgun) | `mailgun-mcp-server` / Gmail MCP | 공식 지원 |
| Slack 팀 채널 알림 | `slack-mcp-server` | ⭐1.5K, 공식 지원 |
| SMS/카카오 알림톡 발송 | 커스텀 MCP (Solapi/CoolSMS) | 국내 서비스 |
| 카카오톡 채널 메시지 | 커스텀 MCP | 카카오비즈메시지 API |

**통화 시나리오**:
> "방금 안내드린 내용을 문자로 보내드릴까요?" → MCP 툴: `send_sms(to=..., message=...)` → "발송 완료했습니다."
> 통화 종료 후 → Slack `#운영팀` 채널에 통화 요약 자동 전송

---

### 4. 상품·재고 조회 (Commerce)

| 기능 | MCP 서버 | 레퍼런스 |
|------|----------|----------|
| Shopify 상품/주문 조회 | `shopify-mcp` | github.com/GeLi2001/shopify-mcp ⭐188 |
| 자체 상품 DB (PostgreSQL) | `postgres-mcp` | 커스텀 쿼리 |
| 재고 실시간 조회 | 커스텀 MCP | ERP/WMS 연동 |

**통화 시나리오**:
> "XX 제품 재고 있나요?" → MCP 툴: `query_inventory(product=...)` → "현재 15개 재고 있습니다."
> "주문하시겠어요?" → `create_order(...)` → 주문 번호 안내

---

### 5. 결제 처리 (Payment)

| 기능 | MCP 서버 | 레퍼런스 |
|------|----------|----------|
| 네이버페이 결제 예약 | 커스텀 MCP (N Pay API) | 공식 API 존재 |
| 카카오페이 | 커스텀 MCP | 카카오페이 API |
| Stripe (글로벌) | 공식 Stripe MCP | Stripe 공식 제공 |
| 주문/결제 내역 조회 | `postgres-mcp` | 자체 DB |

**통화 시나리오**:
> "전화로 결제 도와드릴까요?" → 결제 링크 SMS 발송 → 결제 확인 → "결제가 완료되었습니다."
> ※ 전화상 카드번호 수집 없이 결제 링크 방식으로 PCI DSS 준수

---

### 6. 지식 검색 강화 (Enhanced RAG)

| 기능 | MCP 서버 | 레퍼런스 |
|------|----------|----------|
| 네이버 검색/뉴스 | `naver-search-mcp` | github.com/isnow890/naver-search-mcp ⭐59 |
| 웹 실시간 검색 | `fetch` MCP (공식) | 공식 레퍼런스 서버 |
| 파일/문서 검색 | `filesystem` MCP (공식) | 공식 레퍼런스 서버 |
| Notion 지식베이스 | 공식 Notion MCP | 공식 지원 |
| Google Drive 문서 | `google-drive` MCP | 공식 지원 |

**통화 시나리오**:
> RAG 지식베이스에 없는 최신 정보 질문 → 네이버 검색 MCP 호출 → 실시간 답변
> "공지사항 최신 내용은요?" → Notion/Drive MCP → 최신 문서 참조

---

### 7. 운영 자동화 (Operations)

| 기능 | MCP 서버 | 레퍼런스 |
|------|----------|----------|
| 통화 후 티켓 생성 (Jira/Linear) | Linear MCP, Jira MCP | 공식 지원 |
| Zapier/n8n 워크플로우 트리거 | Zapier MCP | 공식 지원 |
| Google Sheets 데이터 기록 | Google Sheets MCP | 커뮤니티 지원 |
| 지식베이스 자동 업데이트 | 커스텀 MCP (ChromaDB) | 자체 개발 |

**통화 시나리오**:
> 통화 종료 → 자동으로 Jira 티켓 생성 ("주문 문의, 김철수, 010-XXXX")
> → 담당자에게 Slack DM → Google Sheets에 통화 이력 기록

---

### 8. 실시간 분석·모니터링 (Analytics)

| 기능 | MCP 서버 | 레퍼런스 |
|------|----------|----------|
| 통화 감성 분석 결과 저장 | 커스텀 MCP | LangGraph 노드 확장 |
| 대시보드 지표 업데이트 | `postgres-mcp` | 자체 metrics DB |
| 이상 패턴 감지 → 알림 | 커스텀 MCP | 룰 기반 + LLM |

---

## 우선순위 로드맵

### Phase 1 — 즉시 도입 가능 (공개 MCP, 2~4주)

| 순위 | 기능 | MCP 서버 | 임팩트 | 난이도 |
|------|------|----------|--------|--------|
| 1 | **Google 캘린더 예약** | `google-calendar-mcp` | ★★★★★ | 낮음 |
| 2 | **Slack 운영팀 알림** | `slack-mcp-server` | ★★★★☆ | 낮음 |
| 3 | **PostgreSQL 고객 DB 조회** | `postgres-mcp` | ★★★★★ | 낮음 |
| 4 | **SMS 발송 (Solapi)** | 커스텀 MCP | ★★★★☆ | 중간 |
| 5 | **네이버 검색 (실시간 정보)** | `naver-search-mcp` | ★★★☆☆ | 낮음 |

### Phase 2 — 커스텀 MCP 개발 (4~8주)

| 순위 | 기능 | 비고 |
|------|------|------|
| 1 | **자체 예약 시스템 MCP 서버화** | 현재 DB → MCP 툴로 노출 |
| 2 | **CRM MCP (HubSpot or 자체)** | 발신자 자동 식별 |
| 3 | **카카오 알림톡 MCP** | SMS 대체, 비용 절감 |
| 4 | **통화 후 티켓/리포트 자동화** | Jira 또는 자체 이슈 트래커 |

### Phase 3 — 고도화 (2~3개월)

| 기능 | 비고 |
|------|------|
| 결제 링크 발송 (네이버페이/카카오페이) | 전화 주문 처리 |
| 멀티 MCP 동시 호출 최적화 | 응답 속도 <500ms 유지 |
| MCP 툴 결과 기반 HITL 감소 | 자동화율 목표 90% |
| LangGraph ↔ MCP 관찰가능성 | LangSmith 연동 |

---

## 기술 구현 방향

### LangGraph + MultiServerMCPClient 통합

```python
# src/ai_voicebot/ai_pipeline/mcp_tool_manager.py (신규)
from langchain_mcp_adapters.client import MultiServerMCPClient

async def get_mcp_client(config: dict) -> MultiServerMCPClient:
    return MultiServerMCPClient({
        "google-calendar": {
            "command": "npx",
            "args": ["@cocal/google-calendar-mcp"],
            "transport": "stdio",
        },
        "postgres-crm": {
            "url": config["mcp"]["postgres_crm_url"],
            "transport": "streamable_http",
        },
        "slack-notify": {
            "url": config["mcp"]["slack_mcp_url"],
            "transport": "streamable_http",
        },
        "naver-search": {
            "command": "npx",
            "args": ["@isnow890/naver-search-mcp"],
            "transport": "stdio",
        }
    })
```

### LangGraph 노드 확장 (generate_response_node)

```python
# 기존 generate_response_node에 MCP 툴 주입
async def generate_response_node(state, config):
    # 1. 기존 RAG 검색
    rag_results = await rag_engine.search(state["user_text"])
    
    # 2. MCP 툴로 ReAct 에이전트 실행
    mcp_client = await get_mcp_client(config)
    async with mcp_client:
        tools = await mcp_client.get_tools()
        agent = create_react_agent(llm, tools)
        response = await agent.ainvoke({
            "messages": [("user", state["user_text"])],
            "context": rag_results,
            "caller_info": state["caller"]
        })
    
    return {"response": response["messages"][-1].content}
```

### 응답 지연 관리

통화 특성상 **응답 지연 < 1.5초** 유지가 핵심.

| 전략 | 방법 |
|------|------|
| MCP 툴 사전 필터링 | intent 분류 후 필요한 툴만 로드 |
| 스트리밍 응답 | LLM 스트리밍 + TTS 청크 동기화 |
| 툴 결과 캐싱 | 동일 고객 재문의 시 Redis 캐시 활용 |
| 타임아웃 설정 | MCP 툴 최대 2초, 초과 시 HITL 또는 폴백 |

---

## 주요 결정 사항

| 결정 | 이유 |
|------|------|
| `MultiServerMCPClient` 사용 | LangGraph 공식 지원, 동적 툴 디스커버리 |
| stdio transport 우선 | 로컬 MCP 서버는 stdio가 안정적 |
| 공개 MCP 서버 우선 채택 | 개발 속도 최대화, 직접 구현 최소화 |
| 응답 지연 관리 필수 | 전화 UX는 1.5초 초과 시 불편함 |
| HITL 트리거 조건 유지 | MCP 툴 실패 또는 신뢰도 < 0.6 시 운영자 개입 |

---

## 기대 효과

| 지표 | 현재 | MCP 도입 후 (예상) |
|------|------|-------------------|
| AI 자동 처리율 | ~60% | ~85% |
| HITL 개입 비율 | ~40% | ~15% |
| 통화당 처리 업무 범위 | 답변만 | 답변 + 예약 + 조회 + 알림 |
| 운영자 부하 | 높음 | 낮음 (예외 케이스만) |

---

## 잔여 과제

1. **Phase 1 MCP 서버 선정 및 PoC** (구글 캘린더 + PostgreSQL 우선)
2. **LangGraph `generate_response_node`에 MCP 툴 주입 코드 작성**
3. **응답 지연 측정 및 타임아웃 정책 수립**
4. **통화 중 MCP 툴 호출 로그 구조 설계** (디버깅·감사용)
5. **HITL 조건 재정의** (MCP 툴 실패 케이스 추가)
6. **보안 검토**: MCP 툴을 통한 DB 접근 권한 최소화 원칙 적용
