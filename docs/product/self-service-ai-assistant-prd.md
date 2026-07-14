# 셀프서비스 AI 도우미 — Brownfield Enhancement PRD

**작성일**: 2026-07-14
**버전**: 0.2 (Draft — 1차 리뷰 반영: 자동설정 범위를 "설정 카탈로그" 기반 전체 프론트엔드 API 도메인 커버로 확장, 온보딩 체크리스트 Story 추가)
**상태**: 초안 — Epic/Story 확정 전
**관련 문서**:
- [self-service-ai-assistant-brief.md](self-service-ai-assistant-brief.md) — 본 PRD의 상위 Project Brief
- [prd.md](prd.md) — 마스터 PRD (승인 후 본 Epic을 Phase로 편입 예정)
- [../design/INTENT_HANDLING_DESIGN.md](../design/INTENT_HANDLING_DESIGN.md)
- [../../src/ai_voicebot/langgraph/tools/booking_tools.py](../../src/ai_voicebot/langgraph/tools/booking_tools.py)

> **범위/생성 방식 안내**: 사용자 요청에 따라 **보안 리스크(SIP 본인확인 강화 등)는 본 PRD의 스코프에서 제외**하고 **기능 구현에 집중**한다. 보안 강화는 별도 트랙(추후 PRD/Epic)으로 분리한다. 본 문서는 BMAD `brownfield-prd-tmpl.yaml` 기준 완성 초안(YOLO 모드)이다.

---

## Intro: Project Analysis and Context

### Analysis Source

IDE 기반 코드베이스 분석(document-project task 미실행) + [self-service-ai-assistant-brief.md](self-service-ai-assistant-brief.md) 리서치 결과 재사용.

### Current Project State

SmartPBX AI는 SIP B2BUA + 실시간 음성 AI(LangGraph 오케스트레이션, ChromaDB 기반 멀티테넌트 RAG, Pipecat 음성 파이프라인)를 갖춘 통합 PBX 플랫폼이다. 현재 AI는 **고객(발신자)이 테넌트(착신자)에게 문의**하는 시나리오만 처리하며, **테넌트 관리자 자신을 위한 셀프서비스 채널은 없다**.

### Available Documentation Analysis

| 문서                     | 상태                                                                       |
| ------------------------ | -------------------------------------------------------------------------- |
| Tech Stack               | ✅ (`pyproject.toml`, PRD 구현 스냅샷)                                      |
| Source Tree/Architecture | ✅ ([technical-architecture.md](../architecture/technical-architecture.md)) |
| API 명세                 | ✅ ([api-specification.md](../api/api-specification.md))                    |
| Intent 분류 설계         | ✅ ([INTENT_HANDLING_DESIGN.md](../design/INTENT_HANDLING_DESIGN.md))       |
| 코딩 표준 문서           | ⚠️ 부분적 (`.github/copilot-instructions.md`의 로깅·문서 규칙 수준)         |
| UX/UI 가이드             | ❌ 없음 — 기존 설정 페이지 컨벤션을 관찰하여 따름                           |

### Enhancement Type

☑ New Feature Addition

### Enhancement Description

테넌트 관리자가 **자기 자신의 번호로 전화/문자**를 보내면 AI가 응대하여 서비스 사용법 안내, 온보딩 체크리스트 안내, 대화를 통한 자동 설정 변경을 제공한다. **핵심 요구사항**: 프론트엔드(`sip-pbx/frontend/app/settings/*`)의 API를 통해 설정 가능한 모든 항목은 원칙적으로 AI를 통해서도 설정 가능해야 한다 — 이를 위해 "설정 카탈로그(Settings Catalog)"라는 범용 메커니즘을 도입한다. 4대 정보 소스(설정 카탈로그, 이용 매뉴얼, 온보딩 체크리스트, 이용 통계)를 RAG·Tool-calling으로 결합한다.

### Impact Assessment

☑ Significant Impact — 설정 카탈로그가 `persona`/`ai-escalation`/`call-control`/`chat-relay`/`contacts`/`general`/`integrations` **7개 기존 설정 도메인 전부**를 등록해야 하므로 단순 신규 추가보다 영향범위가 넓다. 다만 각 도메인의 기존 서비스 레이어는 그대로 재사용하므로(CR4) 실제 변경은 "등록(wiring)" 수준이며, **기존 고객 응대 경로(booking, question 등)는 변경하지 않는다.**

---

## Goals and Background Context

### Goals

- 테넌트 관리자가 별도 문서 탐색 없이 전화/문자만으로 서비스 사용법을 확인할 수 있다.
- 테넌트 관리자가 대화를 통해 자신의 설정(알림, 페르소나 응답 등)을 확인·변경할 수 있다.
- 테넌트 관리자가 자연어 질의로 자신의 이용 통계(통화량, HITL 건수 등)를 확인할 수 있다.
- 기존 고객 응대(예약, 지식 질의 등) 파이프라인은 회귀 없이 그대로 유지된다.

### Background Context

[Project Brief](self-service-ai-assistant-brief.md)에서 식별한 대로, 현재 설정 변경은 프론트엔드 대시보드 접근이 필수이며 매뉴얼은 개발/운영자 관점이라 고객 친화적이지 않다. 이 리포지토리는 이미 `booking_agent`에서 "LLM+Tool-calling으로 필수/옵션 값을 대화로 수집·확인 발화 후 실행"하는 패턴을 프로덕션 수준으로 보유하고 있으므로, 동일 아키텍처 원칙을 셀프서비스 도메인에 재사용하는 것이 핵심 전략이다.

### Change Log

| Change      | Date       | Version | Description                                                                                                                                              | Author                 |
| ----------- | ---------- | ------- | -------------------------------------------------------------------------------------------------------------------------------------------------------- | ---------------------- |
| 초안 생성   | 2026-07-14 | 0.1     | Project Brief 기반 브라운필드 PRD 최초 작성                                                                                                              | Copilot (BMAD PM 역할) |
| 범위 확장   | 2026-07-14 | 0.2     | 자동설정을 "설정 카탈로그" 기반 전체 도메인 커버로 확장, 온보딩 체크리스트 Story 추가(Story 1.4), FR/NFR 재정의                                          | Copilot (BMAD PM 역할) |
| 시퀀싱 정정 | 2026-07-14 | 0.3     | SM 리뷰에서 온보딩 Story가 미생성 카탈로그에 의존하는 순서 오류 발견 → 설정 카탈로그 구축을 Story 1.4로 앞당김, 이후 Story를 1.5~1.9로 재배치(9개 Story) | Copilot (BMAD SM 역할) |

---

## Requirements

### Functional

- **FR1**: 시스템은 SIP INVITE/MESSAGE 수신 시 발신 내선과 착신 내선이 **동일 테넌트(owner)에 매핑**되는지 판별하여 `is_self_service_session` 플래그를 세션 상태에 세팅해야 한다.
- **FR2**: `is_self_service_session=True`인 세션은 기존 고객 응대용 `classify_intent`/`route_utterance` 대신 전용 셀프서비스 페르소나·시스템 프롬프트로 라우팅되어야 한다.
- **FR3**: 시스템은 서비스 이용 매뉴얼(고객 친화적 콘텐츠, 신규 작성)을 RAG 소스로 조회하여 사용법 질의에 답변해야 한다.
- **FR4**: 시스템은 테넌트별 초기/현재 설정 완료 상태(페르소나 등록, 알림 설정, 지식베이스 업로드 등)를 점검하여 미완료 항목을 안내하는 **온보딩 체크리스트**를 제공해야 한다.
- **FR5**: 시스템은 "현재 내 설정이 어떻게 되어 있는지" 질의에 대해 **설정 카탈로그(Settings Catalog)에 등록된 모든 도메인**(`persona`, `ai-escalation`, `call-control`, `chat-relay`, `contacts`, `general`, `integrations` — 기존 프론트엔드 `settings/*` 전 영역)의 현재 값을 **읽기 전용 조회 Tool**로 답변해야 한다.
- **FR6**: 시스템은 **설정 카탈로그에 등록된 프론트엔드 API 설정 가능 항목 전체**에 대해, 각 항목의 필수/옵션 스키마를 동적으로 조회하여 확인 발화 후 실행하는 **범용 자동설정 Tool**을 제공해야 한다(패턴: `booking_agent`의 확인 절차와 동일). 되돌리기 어려운 항목(계정 삭제, 결제 변경 등)만 명시적 제외 목록으로 관리하며, 그 외 카탈로그 등록 항목은 기본적으로 자동설정 가능해야 한다.
- **FR7**: 시스템은 이번 달/이번 주 통화 수, AI 평균 confidence, HITL 발생 건수 등 정형화된 통계 질의에 **실시간 조회 Tool**로 답변해야 한다(RAG 임베딩 방식 아님).
- **FR8**: 자동설정 Tool이 값을 변경할 때마다 변경 이력(변경 필드, 이전 값, 새 값, 시각, call_id)을 로깅해야 한다.
- **FR9**: 프론트엔드에 "AI 자동설정 변경 이력"을 조회할 수 있는 신규 읽기 전용 페이지가 추가되어야 한다.
- **FR10**: 자동설정 Tool이 호출하는 로직은 프론트엔드 설정 화면이 호출하는 것과 **동일한 서비스 레이어(내부 함수/API)**를 재사용해야 한다(로직 이중 구현 금지).
- **FR11**: 설정 카탈로그는 신규 설정 페이지/필드 추가 시 **카탈로그 등록만으로 자동설정 Tool이 이를 인식**하도록 확장 가능한 구조여야 한다(도메인별 하드코딩된 개별 Tool 추가 불필요).

### Non Functional

- **NFR1**: 셀프서비스 세션의 첫 응답 지연은 기존 AI 응대 파이프라인과 동일한 수준(음성 첫 문장 ~2~3초대)을 유지해야 한다.
- **NFR2**: 신규 ChromaDB doc_type(`self_service_manual` 등)은 기존 `owner` 필터 기반 테넌트 격리 원칙을 그대로 따라야 한다.
- **NFR3**: 통계 조회 Tool은 캐시 없이 매 요청 최신값을 반영하거나, 명확한 TTL(예: 1분) 내 캐시를 사용해야 한다.
- **NFR4**: 자동설정 Tool은 **설정 카탈로그에 등록된 항목을 기본 허용**하고, **명시적 제외 목록(destructive/비가역 항목)**에 있는 항목만 변경을 거부해야 한다(허용 목록 방식이 아닌 제외 목록 방식 — 카탈로그 등록이 곧 자동설정 활성화 조건).

### Compatibility Requirements

- **CR1**: 기존 `classify_intent`/`route_utterance`/`booking_agent` 등 고객 응대 경로의 동작은 `is_self_service_session=False`일 때 **완전히 동일하게 유지**되어야 한다.
- **CR2**: 신규 ChromaDB doc_type 추가는 기존 `knowledge`/`tenant_config` doc_type의 조회·필터 로직에 영향을 주지 않아야 한다.
- **CR3**: 신규 프론트엔드 페이지는 기존 `sip-pbx/frontend/app/settings/*` 페이지의 레이아웃·컴포넌트 컨벤션(Next.js App Router, 기존 폼/테이블 패턴)을 따라야 한다.
- **CR4**: 자동설정 Tool이 호출하는 서비스 레이어는 기존 프론트엔드 설정 API와 동일해야 하며, 별도 API를 중복 구현하지 않아야 한다.

---

## Technical Constraints and Integration Requirements

### Existing Technology Stack

```
Languages:    Python 3.11+ (백엔드), TypeScript/Next.js (프론트엔드)
Frameworks:   FastAPI(REST API), LangGraph(대화 오케스트레이션), Pipecat(음성 파이프라인)
Database:     ChromaDB(Vector/RAG), SQLite(AsyncSqliteSaver 체크포인터), CDR 저장소
Infrastructure: 단일 리포지토리 배포(온프레미스), 구성 파일 기반(YAML)
External Dependencies: LLM API(Gemini 계열), STT/TTS(Google Cloud 등)
```

### Integration Approach

- **Database Integration Strategy**: 신규 ChromaDB doc_type(`self_service_manual`)을 기존 `knowledge` 컬렉션 또는 신규 컬렉션에 `owner` 필터와 함께 추가. 기존 `organization_info.py`의 `tenant_config` 로드 패턴을 재사용해 통계·설정 조회 Tool을 구성한다.
- **API Integration Strategy**: 자동설정 Tool은 신규 REST 엔드포인트를 만들지 않고, 프론트엔드가 이미 호출하는 서비스 레이어 함수를 직접 import하여 호출한다(`booking_tools.py`가 `src.services.booking_service`를 직접 호출하는 패턴과 동일).
- **Frontend Integration Strategy**: 기존 `sip-pbx/frontend/app/settings/` 하위에 신규 라우트(예: `settings/ai-assistant`) 추가, 기존 컴포넌트/폼 패턴 재사용.
- **Testing Integration Strategy**: 기존 `sip-pbx/tests/`, `tests_new/` 구조에 `test_self_service_*.py` 형태로 추가. LangGraph 노드 단위 테스트(`booking_agent` 테스트가 있다면 동일 패턴 참고).

### Code Organization and Standards

- **File Structure Approach**:
  - `src/ai_voicebot/langgraph/nodes/self_service_agent.py` (booking_agent.py와 병렬 구조)
  - `src/ai_voicebot/langgraph/tools/self_service_tools.py` (booking_tools.py와 병렬 구조, 설정 카탈로그를 조회/실행하는 범용 Tool)
  - `src/ai_voicebot/langgraph/self_service_detection.py` (셀프콜 판별 로직, SIP 레이어 훅)
  - `src/ai_voicebot/self_service/settings_catalog.py` (설정 카탈로그 레지스트리 — 도메인별 조회/변경 함수, 필수/옵션 스키마, destructive 플래그 등록)
- **Naming Conventions**: 기존 `booking_*` 네이밍 컨벤션을 `self_service_*`로 그대로 미러링.
- **Coding Standards**: `.github/copilot-instructions.md`의 로깅 원칙(추론 근거를 확인할 수 있는 로그 필수) 준수. `call_data_record`에 셀프서비스 세션 전용 이벤트 추가.
- **Documentation Standards**: 신규 기능 완료 시 `docs/reports/YYYY-MM/`에 완료 보고서, `SYSTEM_OVERVIEW.md`/`INDEX.md` 업데이트 (copilot-instructions.md 체크리스트 준수).

### Deployment and Operations

- **Build Process Integration**: 기존 배포 파이프라인 변경 없음(신규 Python 모듈·Next.js 라우트만 추가).
- **Deployment Strategy**: 기존 `start-all.ps1` 구성 변경 불필요.
- **Monitoring and Logging**: `call_data_record`에 `self_service_session_started`, `self_service_auto_config_applied` 등 신규 이벤트 추가(§근본 원인 추적 가능하도록 상세 로그 원칙 적용).
- **Configuration Management**: 자동설정 **제외 목록**(destructive/비가역 항목만 명시적으로 등록)은 YAML 설정 파일(`config/self_service_exclusions.yaml` 등)로 관리하여 코드 배포 없이 항목 추가/제거 가능하게 한다. 설정 카탈로그 자체(도메인·스키마 등록)는 코드 모듈(`settings_catalog.py`)에서 관리한다.

### Risk Assessment and Mitigation

> 사용자 지시에 따라 보안 리스크(본인확인 강화 등)는 본 PRD 범위에서 **의도적으로 제외**한다. 아래는 기능 구현 관점의 리스크만 다룬다.

- **Technical Risks**: 신규 `self_service` 레인이 기존 `classify_intent`/`route_utterance` 로직에 잘못 개입하여 일반 고객 응대 경로에 회귀를 일으킬 위험 — CR1로 완화(플래그 분기 우선 처리 후 조기 반환). 또한 **설정 카탈로그 등록 누락** 시 일부 프론트엔드 설정 항목이 AI 자동설정 대상에서 조용히 빠질 수 있음 — 신규 설정 API 추가 시 카탈로그 등록을 개발 체크리스트 항목으로 강제(FR11).
- **Integration Risks**: 자동설정 Tool이 프론트엔드와 다른 검증 로직을 사용하면 데이터 불일치 발생 — CR4/NFR4로 완화(동일 서비스 레이어·명시적 제외 목록).
- **Deployment Risks**: 낮음(신규 모듈 추가 위주, 기존 파일 수정 최소화).
- **Mitigation Strategies**: 각 Story마다 "기존 기능 회귀 없음" Integration Verification(IV) 항목을 필수로 포함(하단 Epic 참고).

---

## Epic and Story Structure

### Epic Approach

**Epic Structure Decision**: 단일 Epic(Epic 1)으로 구성한다. 이유: 이 기능은 하나의 사용자 여정(테넌트 관리자의 셀프서비스)을 완성하기 위한 연속된 단계들이며, 서로 강하게 의존적이다(감지 → 라우팅 → 정보 안내 → **설정 카탈로그 구축** → 온보딩 안내 → 설정 조회 → 통계 조회 → 자동설정(쓰기) → 가시성). 브라운필드 권장사항대로 여러 개의 작은 Epic으로 쪼개기보다 **하나의 Epic 내 9개 순차 Story**로 리스크를 점진적으로 낮추며 진행한다.

> **시퀀싱 정정(SM 리뷰 반영, 2026-07-14)**: 최초 버전은 "온보딩 체크리스트"(옛 1.4)가 "설정 카탈로그 구축"(옛 1.7)의 조회 함수에 의존하면서도 먼저 배치되어 있었다 — 나중 Story에 의존하는 순서 오류. **설정 카탈로그의 읽기 전용 등록(도메인·조회 함수·스키마)을 Story 1.4로 앞당기고, 온보딩/조회/통계를 그 위에 쌓은 뒤, 카탈로그에 쓰기(자동설정 실행)를 더하는 Story를 1.8로 분리**했다. "각 Story는 이전 Story에만 의존해야 한다"는 브라운필드 원칙을 따른 결과다.

---

## Epic 1: 셀프서비스 AI 도우미

**Epic Goal**: 테넌트 관리자가 자기 번호로 전화/문자 시 AI가 사용법 안내·온보딩 체크·설정 조회·**설정 카탈로그 기반 전체 도메인 자동설정**을 제공하며, 기존 고객 응대 파이프라인은 회귀 없이 유지된다.

**Integration Requirements**: 신규 SIP 레이어 감지 훅은 `classify_intent` 이전에 위치하며, 감지 실패 시(플래그 미설정) 항상 기존 경로로 폴백해야 한다. 모든 신규 Tool은 프론트엔드와 동일한 서비스 레이어를 재사용하며, 자동설정 대상은 **설정 카탈로그에 등록된 전체 도메인**(`persona`, `ai-escalation`, `call-control`, `chat-relay`, `contacts`, `general`, `integrations`)이다.

### Story 1.1 셀프콜/셀프문자 감지 및 세션 플래그

As a 테넌트 관리자,
I want 내 번호로 전화하거나 문자를 보내면 시스템이 이를 인식하기를,
so that 이후 셀프서비스 전용 응대를 받을 수 있다.

**Acceptance Criteria**
1: SIP INVITE/MESSAGE 수신 시 from_uri user와 to_uri user가 동일 owner에 매핑되면 `ConversationState.is_self_service_session=True`가 세팅된다.
2: 동일 owner가 아닌 일반 통화/문자는 플래그가 세팅되지 않는다.
3: 플래그 판별 로직과 판단 근거(owner 매핑 결과)가 `call_data_record`에 로깅된다.

**Integration Verification**
IV1: 기존 일반 고객 통화/문자 시나리오에서 `is_self_service_session`이 항상 `False`로 유지되고 기존 응답이 동일하게 생성됨을 회귀 테스트로 확인한다.
IV2: `classify_intent`/`route_utterance`가 플래그 유무와 무관하게 예외 없이 실행됨을 확인한다.
IV3: 플래그 판별 로직 추가로 인한 세션 시작 지연이 50ms 이내임을 측정한다.

---

### Story 1.2 셀프서비스 전용 대화 레인 및 페르소나

As a 테넌트 관리자,
I want 셀프서비스 모드에서 전용 인사말과 안내를 받기를,
so that 일반 고객 응대와 구분된 경험을 얻는다.

**Acceptance Criteria**
1: `is_self_service_session=True`이면 LangGraph 그래프가 신규 `self_service_agent` 노드로 라우팅된다(`booking_agent`와 병렬 엣지 구조).
2: 셀프서비스 진입 시 전용 시스템 프롬프트("당신은 서비스 이용을 돕는 AI입니다...")가 사용된다.
3: 셀프서비스 세션 종료(farewell) 시 기존 종료 처리 흐름(update_state → END)과 동일하게 정리된다.

**Integration Verification**
IV1: 기존 `_route_after_classify`/`_route_after_utterance` 분기가 셀프서비스 분기 추가 후에도 기존 조건에서 동일하게 동작한다.
IV2: 셀프서비스 세션의 체크포인터 스키마 버전이 `_LANGGRAPH_SCHEMA_VERSION` 증가로 기존 캐시와 충돌하지 않는다.

---

### Story 1.3 서비스 이용 매뉴얼 RAG 연동

As a 테넌트 관리자,
I want 사용법을 자연어로 질문하면 정확한 안내를 받기를,
so that 문서를 직접 찾아볼 필요가 없다.

**Acceptance Criteria**
1: 고객 친화적 매뉴얼 콘텐츠(신규 작성)가 `doc_type=self_service_manual`로 ChromaDB에 색인된다.
2: 셀프서비스 세션의 RAG 검색은 `owner` 필터 + `doc_type=self_service_manual`로 제한된다.
3: 매뉴얼에 없는 질문은 "제가 알지 못하는 내용" 안내로 폴백한다(기존 `RESPONSE_UNKNOWN_NEEDS_FOLLOWUP` 패턴 재사용 가능).

**Integration Verification**
IV1: 기존 `knowledge` doc_type 검색 결과에 `self_service_manual` 문서가 섞여 나오지 않는다(테넌트 고객용 RAG와 완전 분리).
IV2: 기존 RAG 검색 성능(지연)이 신규 doc_type 추가로 저하되지 않는다.

---

### Story 1.4 설정 카탈로그 구축 (읽기 전용 등록)

As a 테넌트 관리자,
I want (간접적으로) AI가 내 서비스의 모든 설정 항목이 무엇인지 이미 알고 있기를,
so that 이후 온보딩 안내·설정 조회·자동설정 기능이 특정 항목 몇 개에 국한되지 않는다.

**Acceptance Criteria**
1: `settings_catalog.py`에 **7개 설정 도메인**(persona, ai-escalation, call-control, chat-relay, contacts, general, integrations) 각각의 **조회 함수**·필수/옵션 스키마·destructive 여부가 등록된다(이 Story에서는 변경 함수·자동설정 실행은 다루지 않는다 — Story 1.8 범위).
2: `list_domains()`, `get_domain_schema(domain)`, `get_domain_value(domain, owner)` 3개 조회 API가 카탈로그를 통해 동작한다.
3: 카탈로그에 등록되지 않은 도메인 조회 시 명확한 오류(빈 스키마 또는 "미등록 도메인")를 반환한다.

**Integration Verification**
IV1: 카탈로그의 조회 함수는 각 도메인의 기존 서비스/라우터 함수를 오직 읽기(read-only)로만 호출하며 부작용이 없다.
IV2: 7개 도메인 각각에 대해 최소 1개 필드의 조회 테스트가 통과한다(카탈로그 커버리지 검증).

---

### Story 1.5 온보딩 체크리스트 안내

As a 테넌트 관리자,
I want 아직 설정하지 않은 항목이 있으면 AI가 먼저 알려주기를,
so that 놓친 초기 설정 없이 서비스를 온전히 활용할 수 있다.

**Acceptance Criteria**
1: `get_onboarding_checklist` Tool이 **설정 카탈로그(Story 1.4)의 조회 함수**를 사용해 미완료 항목(예: 페르소나 미등록, 지식베이스 미업로드, 알림 미설정)을 판별해 목록으로 반환한다.
2: 셀프서비스 세션 시작 시 미완료 항목이 있으면 AI가 먼저 안내하고, 사용자가 원하면 바로 해당 항목의 자동설정 Tool(Story 1.8)로 이어간다.
3: 모든 항목이 완료된 테넌트는 체크리스트 안내를 생략하고 일반 질의응답으로 진행한다.

**Integration Verification**
IV1: 체크리스트 판별 로직이 설정 카탈로그의 조회 함수만 사용하며 별도 완료 여부 저장소를 새로 만들지 않는다(단일 진실 소스 원칙).
IV2: 체크리스트 안내가 기존 셀프서비스 진입 인사말(Story 1.2) 흐름 뒤에 자연스럽게 이어지고 응답 지연을 유의미하게 늘리지 않는다.

---

### Story 1.6 설정 조회 Tool (읽기 전용, 전체 도메인)

As a 테넌트 관리자,
I want "지금 알림 설정이 어떻게 되어 있어?"처럼 물어보면 현재 값을 답변받기를,
so that 대시보드에 접속하지 않고도 현재 상태를 확인할 수 있다.

**Acceptance Criteria**
1: `get_self_service_settings(domain)` Tool이 **설정 카탈로그(Story 1.4)에 등록된 모든 도메인**의 현재 값을 조회해 구조화된 값을 반환한다(카탈로그 조회 함수를 LangGraph Tool로 노출하는 얇은 래퍼).
2: 카탈로그에 등록되지 않은 도메인/필드 조회 요청 시 "확인해드릴 수 없는 항목"으로 안내한다.
3: 조회 결과는 실제 설정값과 100% 일치한다(프론트엔드와 동일 데이터 소스 사용, FR10).

**Integration Verification**
IV1: 이 Tool이 Story 1.4의 카탈로그 조회 함수만 호출하며 별도 조회 로직을 중복 구현하지 않는다.

---

### Story 1.7 이용 통계 조회 Tool

As a 테넌트 관리자,
I want "이번 달 AI가 몇 번 응대했어?"를 물어보면 답변을 받기를,
so that 대시보드를 열지 않고도 운영 현황을 파악할 수 있다.

**Acceptance Criteria**
1: `get_self_service_stats` Tool이 기간(이번 주/이번 달)별 통화 수, 평균 confidence, HITL 발생 건수를 반환한다.
2: 응답은 `StatisticsCollector`/CDR 등 기존 통계 소스를 재사용하며 별도 집계 로직을 새로 만들지 않는다(NFR3).
3: 지원하지 않는 기간·조건 질의는 "정형화된 질의만 가능합니다" 안내로 폴백한다(MVP 범위 명시, Brief §Out of Scope 반영).

**Integration Verification**
IV1: 통계 Tool 호출이 `StatisticsCollector`의 기존 락(`_stats_lock`) 정합성을 깨지 않는다(읽기 전용 접근만 수행).

---

### Story 1.8 범용 자동설정 Tool (쓰기 + 제외 목록)

As a 테넌트 관리자,
I want 대화로 "알림 꺼줘", "페르소나 응답 문구 바꿔줘" 같은 요청을 하면 AI가 확인 후 실제로 반영해주기를,
so that 어떤 설정 화면을 열지 않고도 원하는 대로 바꿀 수 있다.

**Acceptance Criteria**
1: `settings_catalog.py`(Story 1.4에서 구축된 레지스트리)에 **변경 함수**가 도메인별로 추가 등록된다(조회 함수·스키마·destructive 플래그는 이미 Story 1.4에서 등록됨).
2: `update_self_service_setting(domain, field, value)` Tool이 카탈로그에 등록된 스키마를 동적으로 조회하여 필수/옵션 값을 확인하고, **반드시 확인 발화**를 거친 뒤 실행한다(booking_agent와 동일 원칙).
3: 카탈로그의 **명시적 제외 목록(destructive 항목)**에 있는 항목에 대한 변경 요청은 거부되고 이유가 안내된다(NFR4). 제외 목록 밖 항목은 변경 함수 등록만으로 기본 자동설정 가능하다.
4: 변경 시 변경 이력(도메인, 필드, 이전값, 새값, 시각, call_id)이 로깅된다(FR8).
5: 신규 설정 도메인이 카탈로그에 등록되면 코드 추가 변경 없이 Tool이 이를 인식해 조회·자동설정에 반영한다(FR11).

**Integration Verification**
IV1: 자동설정 Tool이 프론트엔드 설정 화면과 동일한 서비스 함수를 호출하여, 프론트엔드에서 확인 시 즉시 반영된 값이 보임을 확인한다(CR4).
IV2: 제외 목록에 있는 항목에 대한 강제 시도(프롬프트 인젝션 유사 테스트 포함)가 실제 설정 변경으로 이어지지 않음을 확인한다.
IV3: 7개 도메인 각각에 대해 최소 1개 필드의 조회·자동설정 왕복 테스트가 통과한다(카탈로그 커버리지 검증).

---

### Story 1.9 자동설정 변경 이력 프론트엔드 페이지

As a 테넌트 관리자,
I want AI가 최근에 무엇을 바꿨는지 화면에서 확인하기를,
so that 대화로 변경한 내용을 신뢰하고 검증할 수 있다.

**Acceptance Criteria**
1: `sip-pbx/frontend/app/settings/ai-assistant`(가칭) 신규 페이지에서 최근 자동설정 변경 이력이 목록으로 표시된다.
2: 각 항목은 변경 도메인·필드, 이전값→새값, 변경 시각, 관련 call_id를 표시한다.
3: 기존 설정 페이지 컴포넌트/레이아웃 컨벤션을 따른다(CR3).

**Integration Verification**
IV1: 신규 페이지 추가가 기존 `settings/*` 라우트의 네비게이션·레이아웃에 영향을 주지 않는다.

---

## Checklist Results Report

_(pm-checklist 실행 전 — 팀 리뷰 후 `execute-checklist` 태스크로 검증 예정)_

---

## Next Steps

### Architect Prompt

이 PRD([self-service-ai-assistant-prd.md](self-service-ai-assistant-prd.md))를 입력으로 `architect` 에이전트를 기동하여, brownfield 아키텍처 문서(`brownfield-architecture-tmpl.yaml`)를 생성해 주세요. 특히 §Technical Constraints의 "Integration Approach"와 **설정 카탈로그(Settings Catalog, `settings_catalog.py`)의 데이터 구조**(도메인 등록 스키마, 조회/변경 함수 시그니처, destructive 플래그)를 구체적인 클래스/함수 시그니처 수준으로 확정해야 합니다. 보안(SIP 본인확인) 설계는 이번 아키텍처 범위에서 제외하고, 추후 별도 트랙에서 다룹니다.

### UX Expert Prompt

Story 1.9(자동설정 변경 이력 페이지)에 대해서만 `front-end-spec-tmpl.yaml` 기준 최소 스펙을 작성해 주세요. 기존 `sip-pbx/frontend/app/settings/persona` 페이지의 폼·리스트 UI 패턴을 참고 기준으로 삼습니다.

---

*최종 업데이트: 2026-07-14*
