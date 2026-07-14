# Project Brief: 셀프서비스 AI 도우미 (Self-Service AI Assistant)

**작성일**: 2026-07-14
**버전**: 0.1 (Draft — YOLO 모드 생성, 팀 리뷰 필요)
**상태**: 초안 (Draft) — PRD 작성 전 단계
**관련 문서**:
- [prd.md](prd.md) — 마스터 PRD (본 브리프의 상위 문서, 승인 후 PRD 섹션으로 반영 예정)
- [../design/INTENT_HANDLING_DESIGN.md](../design/INTENT_HANDLING_DESIGN.md) — Intent 분류 파이프라인 (본 기능의 `self_service` 인텐트 추가 지점)
- [../design/KNOWLEDGE_MANAGEMENT_DESIGN.md](../design/KNOWLEDGE_MANAGEMENT_DESIGN.md) — RAG·테넌트 격리 구조 (본 기능의 KB 재사용 대상)
- [../../src/ai_voicebot/langgraph/tools/booking_tools.py](../../src/ai_voicebot/langgraph/tools/booking_tools.py) — Tool-calling 기반 자동설정 참조 구현체
- [../api/api-specification.md](../api/api-specification.md) — 프론트엔드 API 명세 (RAG 소스 1)
- [../guides/USER_MANUAL.md](../guides/USER_MANUAL.md) — 기존 사용 매뉴얼 (RAG 소스 2, 고객 관점 재작성 필요)

> **생성 방식 안내**: 본 문서는 BMAD `analyst` 에이전트의 `project-brief-tmpl.yaml`을 기준으로, 코드베이스 리서치(기존 `booking_agent`/`persona_service`/`tenant_config`/`statistics` 구조 분석)를 반영한 **완성 초안(YOLO 모드)**입니다. 대화형 elicitation(섹션별 1-9 옵션 확인) 없이 일괄 작성했으므로, 각 섹션의 가정·트레이드오프를 팀에서 검토 후 확정해야 합니다.

---

## Executive Summary

**제품 개념**: 고객(테넌트 관리자)이 **자기 자신의 번호로 전화 또는 문자(SIP MESSAGE)를 보내면**, 기존 AI 응대 파이프라인이 이를 감지하여 "셀프서비스 도우미" 모드로 전환하고, 서비스 사용법 안내·설정 방법 안내·AI를 통한 자동 설정 변경을 대화형으로 제공한다.

**핵심 문제**: 현재 SmartPBX AI의 설정(페르소나, 예약 정책, 착신 전환, 알림 등)은 프론트엔드 대시보드를 직접 조작해야 하며, 신규/비기술 관리자에게는 진입장벽이 있다. 사용 매뉴얼(`USER_MANUAL.md`)도 개발/운영자 관점으로 작성되어 있어 고객 관점 안내 자료가 부재하다.

**타깃 시장**: 이미 SmartPBX AI를 사용 중인 테넌트(매장·기관) 관리자 — 별도 온보딩 콜센터 없이 셀프서비스로 문제를 해결하고자 하는 소상공인/소규모 조직.

**핵심 가치 제안**: "설정 화면을 뒤질 필요 없이, 내 번호로 전화 한 통이면 AI가 사용법을 알려주고 원하는 대로 설정까지 바꿔준다." — 기존에 구축된 RAG·LangGraph·Tool-calling(예: `booking_agent`) 인프라를 그대로 재사용하여 **신규 인프라 투자 없이** 구현 가능하다는 점이 기술적 강점.

---

## Problem Statement

### 현재 상태 및 문제점

- **설정 채널의 단절**: 관리자는 프론트엔드(`sip-pbx/frontend/app/settings/*`)에 진입해야만 페르소나, 착신전환, 알림, 예약 정책 등을 변경할 수 있다. 통화 중이거나 이동 중에는 접근이 어렵다.
- **매뉴얼과 사용자 경험의 불일치**: `docs/guides/USER_MANUAL.md`는 설치·배포·트러블슈팅 위주로 작성되어 있어(§시스템 요구사항, §API 엔드포인트 등) **엔드 테넌트 관리자가 읽기엔 기술적으로 과도**하다. 고객 친화적 사용 안내 자료가 사실상 없다.
- **통계 확인의 진입장벽**: `GET /api/v1/agent/confidence-stats`, CDR, HITL 통계 등은 존재하지만 대시보드 UI 탐색이 필요하며, "지난주 AI가 몇 건이나 응대했는지", "확인 안 된 HITL이 몇 건인지" 같은 질문에 즉답을 얻을 채널이 없다.
- **신규 설정 항목 발견 어려움**: 새 기능(예: 도메인 추가 필드, 아웃바운드 캠페인)이 추가되어도 관리자가 이를 인지하지 못하면 활용도가 낮아진다.

### 문제의 영향

- 초기 온보딩 실패율 증가 → 이탈(churn) 위험.
- 지원 문의(전화/이메일)가 반복적 FAQ성 질문에 집중되어 CS 리소스 낭비.
- 신기능 activation 저조 → 프로덕트 투자 대비 사용률 저하.

### 왜 지금 해결해야 하는가

- 이미 이 리포지토리는 예약(booking) 도메인에서 **"LLM + Tool-calling으로 설정값을 대화로 수집·반영"** 하는 패턴(`booking_agent.py`, `booking_tools.py`)을 프로덕션 수준으로 보유하고 있다. 동일 패턴을 "서비스 자체 설정"에 적용하는 것은 **한계비용이 낮고 재사용성이 높다** — Active RAG·멀티테넌트 격리 철학(PRD Phase 1-4)과도 정합된다.

---

## Proposed Solution

### 핵심 개념

1. **자기 자신에게 연락 = 셀프서비스 모드 트리거**
   - 판별 조건: 발신번호(caller)와 착신번호(callee)가 **동일 테넌트로 매핑**될 때(정확히는 to_uri의 user와 from_uri의 user가 동일 owner로 등록된 내선일 때). 단순 문자열 일치(`from_uri == to_uri`)는 SIP 헤더 스푸핑에 취약하므로 **등록(REGISTER) 정보 기반 검증**을 병행한다 (§Technical Considerations §Security 참고).
   - 진입점: 기존 `classify_intent` 파이프라인 이전 단계(또는 `route_utterance`)에서 `is_self_service_session` 플래그를 세팅 → 전용 페르소나·시스템 프롬프트·Tool 세트로 전환.

2. **3대 RAG 소스 + Tool-calling 하이브리드**
   - 순수 질의응답(RAG)과 실제 값 변경(Tool-calling)을 분리한다 — `booking_agent`가 "정보 안내"와 "예약 생성"을 분리하는 것과 동일한 설계 원칙.

   | #   | 소스                                     | 형태                                                           | 처리 방식                                                |
   | --- | ---------------------------------------- | -------------------------------------------------------------- | -------------------------------------------------------- |
   | 1   | **설정 스키마(API 설계 문서)**           | 프론트 설정 메뉴가 호출하는 REST API의 필수/옵션 파라미터 정의 | RAG(설명) + **Tool-calling(자동설정 실행)**              |
   | 2   | **서비스 이용 매뉴얼**                   | 사용법·FAQ·설정 방법                                           | RAG(순수 질의응답)                                       |
   | 3   | **이용 통계/모니터링**                   | 테넌트별 통화량, AI confidence, HITL 발생 건수 등              | **읽기 전용 Tool** (실시간 조회, RAG 아님 — 최신값 필요) |
   | 4   | *(리서치로 보강, 하단 §Appendix A 참고)* | 온보딩 체크리스트, 알림 설정, 계정/보안, 요금제 안내 등        | 항목별 RAG/Tool 혼합                                     |

3. **프론트엔드 설정 메뉴와 데이터 소스 공유**
   - "frontend의 설정 메뉴에서 특정 페이지를 통해 확인 가능"이라는 요구사항을 반영하여, AI가 참조하는 스키마·매뉴얼·통계는 **프론트엔드가 렌더링하는 것과 동일한 API·데이터 소스**를 가리키도록 설계한다(이중 관리 방지). 신규 프론트엔드 페이지(가칭 `settings/ai-assistant` 또는 `settings/help`)에서 "AI가 무엇을 알고 있는지" 및 "최근 AI 자동설정 변경 이력"을 사람이 확인할 수 있게 한다.

### 차별점 및 성공 가능성

- 별도 챗봇/IVR 트리를 새로 만드는 대신, **기존 LangGraph 대화 엔진·페르소나·테넌트 격리 구조를 그대로 재사용** → 개발 리스크와 유지보수 이중화를 최소화.
- Tool-calling 기반 자동설정은 `booking_tools.py`에서 이미 "필수/옵션 필드 확인 → 실행 전 confirmaiton 발화 → 실행" 패턴이 검증되어 있어 동일 원칙을 적용 가능.

---

## Target Users

### Primary User Segment: 테넌트 관리자(매장/기관 운영자)

- **프로필**: SmartPBX AI를 이미 도입한 소상공인·소규모 기관의 실무 운영자. 기술 배경이 얕을 수 있음.
- **현재 행동**: 문제가 생기면 지인·벤더 지원팀에 전화하거나, 대시보드를 이리저리 눌러본다.
- **니즈/불편**: "이 기능 어떻게 켜요?", "이번 달에 AI가 응대 몇 건 했어요?" 같은 즉답 니즈. 문서 탐색에 대한 피로감.
- **목표**: 설정을 빠르게 마치고 본업(매장 운영)에 집중.

### Secondary User Segment: 신규 온보딩 담당자(벤더 측 CS/운영)

- **프로필**: 신규 테넌트 온보딩을 지원하는 내부 담당자.
- **니즈**: 반복 FAQ 응대를 AI에 위임하여 온보딩 처리량 확대.
- **목표**: CS 문의량 감소, 온보딩 완료 시간 단축.

---

## Goals & Success Metrics

### Business Objectives

- 신규 테넌트의 **초기 설정 완료율**을 온보딩 후 7일 이내 기준 X%p 향상 (베이스라인은 기존 온보딩 데이터 확보 후 확정 — Open Question 참고).
- 반복 FAQ성 CS 문의 건수를 셀프서비스 도우미 도입 후 분기 대비 감소.

### User Success Metrics

- 셀프서비스 세션에서 **첫 응답까지 걸리는 시간** (기존 AI 응대 SLA와 동일 수준 유지).
- 셀프서비스 세션 내 **자동설정 성공률**(사용자가 요청한 설정이 확인 발화 후 실제 반영된 비율).
- 세션 종료 후 HITL(사람 개입) 전환율 — 낮을수록 AI가 자기완결적으로 처리했다는 의미.

### Key Performance Indicators (KPIs)

- **KPI1 셀프서비스 세션 수**: 월간 self-service 세션 트리거 횟수.
- **KPI2 자동설정 성공률**: (성공적으로 반영된 설정 변경) / (설정 변경 시도).
- **KPI3 정보 안내 정확도**: RAG 응답에 대한 HITL 전환율 또는 사용자 재질문율.
- **KPI4 CS 문의 절감률**: 도입 전후 반복 FAQ 문의 비교.

---

## MVP Scope

### Core Features (Must Have)

- **셀프콜 감지 및 세션 전환**: SIP INVITE/MESSAGE 처리 경로에서 발신=착신(동일 테넌트) 여부를 판별하고, 전용 페르소나·시스템 프롬프트로 전환한다.
- **정보 안내 RAG (읽기 전용)**: 서비스 이용 매뉴얼(신규 고객 친화적으로 재작성) 기반 질의응답.
- **설정값 조회 Tool**: "현재 내 설정이 어떻게 되어 있나요?" — 현재 tenant_config/페르소나/예약 정책 등을 읽어 안내(변경 없음).
- **필수/옵션 항목 확인 후 자동설정 Tool (1~2개 파일럿 도메인)**: 예) 페르소나 chitchat 응답 템플릿 변경, 착신 알림 on/off 등 **되돌리기 쉬운 설정**부터 시작.
- **변경 이력 로깅 및 확인 발화**: `booking_agent`의 "실행 전 확인 발화" 원칙을 그대로 적용 — 자동설정 실행 전 반드시 사용자 확인.
- **프론트엔드 확인 페이지(최소)**: 최근 AI 자동설정 변경 이력을 보여주는 읽기 전용 페이지 1개.

### Out of Scope for MVP

- 통계/모니터링 정보의 완전한 자연어 질의응답(복잡한 기간·조건 필터링) — 우선 "이번 달 통화 수", "이번 주 HITL 건수" 등 정형화된 질의만 지원.
- 결제/요금제 변경, 계정 탈퇴 등 **되돌리기 어려운(destructive) 설정**의 자동화.
- 다국어 지원.
- 문자(SIP MESSAGE) 경로와 음성 경로의 UX 완전 동등화(음성 우선, 문자는 후속).

### MVP Success Criteria

파일럿 테넌트 3~5곳을 대상으로 4주 운영 시, 자동설정 성공률 90% 이상 + 오설정으로 인한 롤백 요청 0건을 만족하면 정식 확대.

---

## Post-MVP Vision

### Phase 2 Features

- 자동설정 대상 도메인 확대(예약 정책 전체, 착신전환 규칙, 알림 세분화).
- 통계 질의 고도화(기간·조건별 자연어 질의, 그래프성 요약 음성 안내).
- 온보딩 체크리스트 대화형 마법사(§Appendix A 참고).

### Long-term Vision

- "설정 화면이 없어도 되는 PBX" — 신규 기능 출시 시 대시보드 UI 없이 AI 안내만으로 우선 노출(다크런치) 가능한 구조로 발전.

### Expansion Opportunities

- 벤더 CS팀용 "테넌트 대리 진단" 모드(테넌트 관리자 동의 하에 CS가 동일 봇을 통해 원격 점검).
- 다른 채널(카카오톡 비즈니스, 슬랙 등)로 셀프서비스 도우미 확장.

---

## Technical Considerations

### Platform Requirements

- **대상 채널**: SIP 음성 통화, SIP MESSAGE(텍스트). 기존 `sip_endpoint.py`/`call_manager.py` 처리 경로 재사용.
- **성능 요구사항**: 기존 AI 응대 파이프라인과 동일한 응답 지연 목표(음성 첫 문장 ~2~3초대, 기존 `llm_first_sentence_ready` 로그 기준과 동일 수준 유지).

### Technology Preferences

- **오케스트레이션**: 기존 LangGraph `ConversationState` 그래프에 `self_service` 레인 추가(신규 엔진 도입 없음).
- **Tool-calling**: `booking_tools.py`와 동일한 `_make_tool` 패턴 재사용 — 신규 `self_service_tools.py` 모듈 신설 제안.
- **RAG/KB**: 기존 ChromaDB 컬렉션 구조에 `doc_type=self_service_manual` 등 신규 doc_type 추가(테넌트 격리는 기존 `owner` 필터 그대로 사용).
- **프론트엔드**: 기존 Next.js 설정 메뉴(`sip-pbx/frontend/app/settings/*`) 컨벤션을 따르는 신규 페이지 추가.

### Architecture Considerations

- **Repository Structure**: 기존 `sip-pbx/src/ai_voicebot/langgraph/` 트리 내에 `nodes/self_service_agent.py`, `tools/self_service_tools.py` 형태로 booking 도메인과 병렬 구조 유지.
- **Service Architecture**: `classify_intent`가 아닌 **세션 진입 시점(SIP 레이어)**에서 self-service 여부를 판별해야 한다 — intent 분류보다 선행하는 게이트이므로 `route_utterance` 이전 단계에 훅 추가 필요.
- **Integration Requirements**: 프론트엔드 API(설정 CRUD 엔드포인트)를 Tool 함수가 직접 호출(내부 서비스 레이어 재사용)하도록 하여 **프론트엔드와 AI가 동일 비즈니스 로직·검증 규칙을 공유**해야 한다(로직 이중 구현 방지).
- **Security/Compliance**: 아래 §Risks 참고 — **가장 중요한 기술 리스크**.

---

## Constraints & Assumptions

### Constraints

- **Budget**: 별도 명시 없음 — 기존 인프라(LLM API, ChromaDB, LangGraph) 재사용을 전제로 추가 인프라 비용 최소화가 암묵적 제약.
- **Timeline**: 명시 없음 — MVP 파일럿 4주 운영을 가정.
- **Resources**: 기존 booking 도메인 개발 인력·패턴 재사용 가능 전제.
- **Technical**: 기존 멀티테넌트 격리(owner 필터) 원칙을 반드시 준수해야 하며, 새 기능이 이를 우회해서는 안 됨.

### Key Assumptions

- 테넌트는 SIP 내선 등록 시 자기 번호(본인 계정)임이 시스템에 의해 이미 검증되어 있다(REGISTER 인증 로직 확인 필요 — 현재 코드베이스 확인 결과 REGISTER는 "항상 200 OK, 인증 없이 모든 등록 허용"(PRD FR3)로 되어 있어 **이 가정은 현재 코드 기준 성립하지 않음** — Open Question/Risk로 승격).
- 프론트엔드 설정 메뉴와 AI가 참조하는 데이터가 항상 동일 소스(API)를 바라본다.
- 통계 정보는 실시간에 가까운 최신값이어야 하므로 RAG 임베딩 방식이 아닌 **직접 조회 Tool**로 구현한다(설계 결정, MVP 범위에 이미 반영).

---

## Risks & Open Questions

### Key Risks

- **[치명적] SIP 헤더 스푸핑을 통한 미인가 자동설정 변경**: PRD FR3에 따르면 현재 REGISTER는 무인증으로 모두 허용된다. From/To URI만으로 "본인 확인"을 하면 공격자가 From 헤더를 위조해 타 테넌트의 설정을 변경할 수 있다(OWASP A01 Broken Access Control 성격). **자동설정을 실행하는 Tool은 반드시 별도의 강한 신원 확인(예: 등록된 Contact/디바이스 매핑, 또는 통화 채널 자체의 회선 인증)을 거쳐야 하며, 이 문제가 해결되기 전에는 "조회/안내"만 허용하고 "쓰기(자동설정)" 기능은 보류하는 단계적 출시를 권장한다.**
- **RAG 환각으로 인한 잘못된 설정 안내**: 매뉴얼 RAG가 오래된/부정확한 절차를 안내할 경우 사용자가 잘못 설정할 위험. → 자동설정 Tool은 항상 최신 스키마(API 자체)에서 필수/옵션을 직접 조회하고, RAG 텍스트는 설명용으로만 사용.
- **통계 데이터 소스 이원화**: 프론트엔드 대시보드와 AI가 서로 다른 집계 로직을 사용하면 숫자 불일치로 신뢰도 저하. → 동일 서비스 레이어 재사용 원칙 필수.
- **문자(SIP MESSAGE) 채널의 응답 길이 제약**: 음성 대비 텍스트는 더 상세한 설명이 가능하지만, SMS/MESSAGE 특성상 과도하게 긴 응답은 UX 저하.

### Open Questions

- "자기 자신에게 전화/문자"의 정확한 판별 기준은? (내선 간 동일 owner 매핑 vs 정확히 동일 번호)
- 자동설정이 허용되는 항목의 화이트리스트는 누가 정의·승인하는가?
- 온보딩 완료율 베이스라인 데이터가 현재 존재하는가? (KPI 목표 수치 확정에 필요)
- 통계 조회 시 기간·요약 단위(일/주/월)는 어디까지 자연어로 지원할 것인가?

### Areas Needing Further Research

- REGISTER 인증 강화 방안(현재 무인증 구조와 self-service 자동설정 기능 간의 정합성).
- 고객 친화적 매뉴얼 콘텐츠 신규 작성 범위와 소유권(프로덕트/CS팀).
- 화이트리스트 기반 자동설정 항목 선정 기준(되돌리기 쉬운 정도, 영향 범위).

---

## Appendices

### A. 리서치 요약 — "4) 또 어떤 정보가 있으면 좋을지" 제안

요청하신 3가지(API 설정 스키마, 이용 매뉴얼, 통계/모니터링) 외에, 일반적인 SaaS 셀프서비스 어시스턴트(예: 대시보드 내 AI 헬프데스크, 통신사 자가진단 ARS) 사례와 본 리포지토리의 기존 자산을 참고하여 아래 항목을 보강 후보로 제안합니다.

| #   | 제안 항목                               | 근거/재사용 자산                                                                                                                                                             | 우선순위 제안          |
| --- | --------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ---------------------- |
| 5   | **온보딩 체크리스트 안내**              | 신규 테넌트가 놓치기 쉬운 초기 설정(페르소나 등록, 지식베이스 업로드 등) 단계별 안내                                                                                         | MVP 이후               |
| 6   | **트러블슈팅 자동 안내**                | 기존 [KNOWLEDGE_404_TROUBLESHOOTING.md](../KNOWLEDGE_404_TROUBLESHOOTING.md), [TROUBLESHOOTING.md](../guides/TROUBLESHOOTING.md) 콘텐츠를 RAG 소스로 재사용                  | MVP 후보               |
| 7   | **알림/알림채널 설정 안내 및 자동변경** | Webhook(FR16), SMS 알림 등 on/off                                                                                                                                            | MVP 파일럿 도메인 후보 |
| 8   | **HITL/부재중 모드 현황 안내**          | [HITL_CURRENT_LOGIC.md](../design/HITL_CURRENT_LOGIC.md), [OPERATOR-AWAY-MODE-DESIGN.md](../design/OPERATOR-AWAY-MODE-DESIGN.md) — "지금 부재중 모드 켜져 있나요?" 같은 질의 | MVP 이후               |
| 9   | **계정/보안 안내(비밀번호, API 키 등)** | 자동설정 대상에서는 제외(치명적 리스크와 동일 사유)하되 안내(RAG)는 가능                                                                                                     | 조회만 허용            |
| 10  | **최근 변경 이력 안내**                 | "지난주에 뭐 바꿨는지" — 프론트엔드 신규 확인 페이지와 동일 데이터 재사용                                                                                                    | MVP 포함               |

### B. 이해관계자 의견

_(수집 필요 — 본 초안은 사용자 1인의 최초 아이디어를 기반으로 작성됨. 프로덕트/CS/보안 담당자 리뷰 후 보강 예정)_

### C. 참고 자료

- [prd.md](prd.md) — AI 기능 Phase 1-4 구현 스냅샷
- [../../src/ai_voicebot/langgraph/nodes/booking_agent.py](../../src/ai_voicebot/langgraph/nodes/booking_agent.py) — Tool-calling 자동설정 참조 구현
- [../../src/ai_voicebot/langgraph/tools/booking_tools.py](../../src/ai_voicebot/langgraph/tools/booking_tools.py) — `get_booking_settings`(필수/옵션 스키마 조회) 패턴
- [../../src/ai_voicebot/knowledge/organization_info.py](../../src/ai_voicebot/knowledge/organization_info.py) — 테넌트 설정(tenant_config) 로드 구조
- [../../src/events/statistics.py](../../src/events/statistics.py) — 실시간 통계 수집기
- [../api/api-specification.md](../api/api-specification.md) §3 AI Agent, §confidence-stats — 통계 API 참고 필드

---

## Next Steps

### Immediate Actions

1. **보안 리스크 확정**: REGISTER 무인증 구조와 self-service 자동설정 기능의 충돌 여부를 보안 담당자와 확정 — 자동설정(쓰기) 기능의 출시 게이팅 조건 수립.
2. **자동설정 화이트리스트 초안 확정**: MVP 파일럿 대상 1~2개 도메인(예: 알림 on/off, 페르소나 응답 템플릿) 선정.
3. **고객 친화적 매뉴얼 콘텐츠 작성**: 기존 `USER_MANUAL.md`와 별도로 RAG 소스용 고객 관점 콘텐츠 작성(소유권: 프로덕트/CS팀).
4. **PRD 섹션화**: 본 브리프를 `docs/product/prd.md`의 신규 Phase 또는 Epic으로 편입(§PM Handoff 참고).
5. **프론트엔드 확인 페이지 와이어프레임**: "AI 자동설정 변경 이력" 페이지 최소 스펙 정의.

### PM Handoff

본 Project Brief는 **셀프서비스 AI 도우미** 기능의 전체 컨텍스트를 제공합니다. 다음 단계로 'PRD Generation Mode'로 진입하여, 본 브리프를 섹션별로 검토하며 [prd-tmpl.yaml](../../bmad/.bmad-core/templates/prd-tmpl.yaml) 기준 PRD를 함께 작성해 주세요. 특히 §Risks의 "REGISTER 무인증 구조" 이슈는 PRD의 NFR(보안 요구사항)로 반드시 승격되어야 합니다.

---

*최종 업데이트: 2026-07-14*
