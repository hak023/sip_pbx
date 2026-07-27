# 셀프서비스 AI 도우미 — Brownfield Enhancement PRD

**작성일**: 2026-07-14
**버전**: 0.8 (2026-07-23 갱신 — 능력 레지스트리 기반 유형 C 동적화(FR27, Story 1.17))
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

| Change                        | Date       | Version | Description                                                                                                                                                                                                                    | Author                 |
| ----------------------------- | ---------- | ------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ | ---------------------- |
| 초안 생성                     | 2026-07-14 | 0.1     | Project Brief 기반 브라운필드 PRD 최초 작성                                                                                                                                                                                    | Copilot (BMAD PM 역할) |
| 범위 확장                     | 2026-07-14 | 0.2     | 자동설정을 "설정 카탈로그" 기반 전체 도메인 커버로 확장, 온보딩 체크리스트 Story 추가(Story 1.4), FR/NFR 재정의                                                                                                                | Copilot (BMAD PM 역할) |
| 시퀀싱 정정                   | 2026-07-14 | 0.3     | SM 리뷰에서 온보딩 Story가 미생성 카탈로그에 의존하는 순서 오류 발견 → 설정 카탈로그 구축을 Story 1.4로 앞당김, 이후 Story를 1.5~1.9로 재배치(9개 Story)                                                                       | Copilot (BMAD SM 역할) |
| 범위 추가                     | 2026-07-20 | 0.4     | 통화 이력 자연어 질의(Call History NLQ) 기능을 Post-MVP에서 MVP로 승격 — FR15/NFR5 신설, Story 1.13 추가(총 13개 Story)                                                                                                        | Copilot (BMAD PM 역할) |
| Epic 2 신설                   | 2026-07-20 | 0.5     | 설정 카탈로그/Screen Graph 하드코딩 의존도 개선 + IntelliDecision 키워드 힌트 제거를 위한 Epic 2 신설(FR16-24, NFR6-8, CR5-6, Story 2.1~2.8)                                                                                   | Copilot (BMAD PM 역할) |
| IntelliDecision 유형 C 추가   | 2026-07-23 | 0.6     | 포괄적 도움 요청("뭘 할 수 있어?") 응대를 위한 유형 C 신설(FR25, Story 1.15) — 기존 유형 A/B는 특정 기능 전제 발화만 다루던 공백 해소                                                                                          | Copilot (BMAD PM 역할) |
| IntelliDecision 유형 D~I 추가 | 2026-07-23 | 0.7     | 대화 수리·복구 패턴(정정/실행취소/모호성해소/일괄처리/범위외설명/반복요청) 6종 신설(FR26, Story 1.16) — 리서치 보고서 제안 1 채택, undo용 Tool 2개 신규 추가                                                                   | Copilot (BMAD PM 역할) |
| 능력 레지스트리 구현          | 2026-07-23 | 0.8     | 유형 C 응답을 하드코딩 대신 `settings_catalog` 실시간 데이터+Tool 정적 매핑으로 동적 생성(FR27, Story 1.17) — 제안 2 축소 권장안 채택(신규 레지스트리 모듈/API/5번째 탭 대신 기존 API·페이지 재사용), 매뉴얼 §9 축소(버전 1.3) | Copilot (BMAD PM 역할) |

---

## Post-MVP 후보 (리서치, 2026-07-23 — 제안 1·2 모두 반영 완료)

IntelliDecision·지식베이스 고도화 리서치
([리포트](../reports/2026-07/2026-07-23_intellidecision_enhancement_research.md)) 결과 중 **제안 1(유형 D~I)은 FR26/Story 1.16**, **제안 2(능력 레지스트리)는 축소된 권장안([결정 지원 리포트](../reports/2026-07/2026-07-23_capability_registry_decision_options.md))으로 FR27/Story 1.17에 반영 완료되었다**. 남은 작업은 실서버 A/B 검증(하드코딩 대비 동적 버전 응답 품질)뿐이다.

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
- **FR12 (IntelliDecision)**: 시스템은 설정 변경 관련 발화를 **"탐색성(궁금해서 물어봄)"** 과 **"실행성(명확히 변경을 요청)"** 두 유형으로 구분하여 응대해야 한다.
  - 탐색성 발화(예: "~해줄 수 있어?", "그런 기능 있어?")에는 매뉴얼 참고 정보를 바탕으로 기능·사전 준비사항을 설명하고 "필요하면 말씀해 주세요"처럼 다음 행동을 제안만 하며, 이 단계에서 자동설정 Tool을 호출하지 않는다.
  - 실행성 발화(예: "~설정해줘", "~꺼줘")에는 변경 대상(도메인/필드/값)이 이미 분명하므로 "[항목]을 [값]으로 설정할까요?" 형태로 즉시 확인 발화를 하되, 매뉴얼에 해당 변경의 부작용이 있으면 함께 안내한다.
  - 두 유형의 최종 판단은 키워드 매칭이 아닌 LLM 판단을 우선하며(기존 의도 분류 원칙과 동일), 발화 패턴 기반 힌트는 참고용 신호로만 프롬프트에 제공한다.
- **FR13 (화면 안내형 응대 — Screen Graph)**: 시스템은 탐색성 발화(기능 설명·설정 방법 질문)에 답할 때, 매뉴얼 텍스트 설명에 더해 **해당 설정을 실제로 변경할 수 있는 프론트엔드 화면(라우트·화면 내 UI 요소)** 을 함께 안내해야 한다(예: "설정 > AI 에스컬레이션 화면에서 라디오 버튼 3개 중 하나를 선택하시면 됩니다").
  - 이를 위해 **설정 카탈로그 도메인 ↔ 프론트엔드 화면(라우트) ↔ 화면 내 UI 요소**를 연결하는 경량 지식 그래프(Screen Graph)를 신규로 구축해야 한다.
  - 화면 정보가 없는 도메인(프론트엔드 전용 폼이 없는 경우)은 화면 안내를 생략하고 기존 텍스트 설명만 제공해야 한다(존재하지 않는 화면을 안내하지 않음).
  - Screen Graph는 매뉴얼 Q&A의 기존 `related_domain` 태그를 그대로 재사용해 연결하며, 별도 그래프 데이터베이스 없이 `settings_catalog.py`와 동일한 정적 레지스트리 패턴으로 구현한다(Full GraphRAG 프레임워크 도입은 본 코드베이스 규모에 부적합 — [SELF_SERVICE_SCREEN_GUIDED_GRAPHRAG_RESEARCH.md](../design/SELF_SERVICE_SCREEN_GUIDED_GRAPHRAG_RESEARCH.md) 리서치 결론 참고).
- **FR14 (Screen Graph 프론트엔드 열람)**: 프론트엔드에 Screen Graph(도메인별 화면 라우트·UI 요소 연결 정보)를 **읽기 전용으로 열람**할 수 있는 화면이 추가되어야 한다(기존 `settings/ai-assistant/docs` 도움말 페이지의 신규 탭으로 통합). 이를 통해 관리자가 AI 도우미가 어떤 화면을 안내할 수 있는지 직접 확인할 수 있다.
- **FR15 (통화 이력 자연어 질의, Call History NLQ — 2026-07-20 범위 추가)**: 시스템은 테넌트 관리자가 자기 번호(owner)의 통화 이력을 자연어로 질의하면 다음 3가지 유형에 응답하는 Tool을 제공해야 한다.
  1. **키워드 검색**: "~라고 얘기한 통화 찾아줘"처럼 특정 키워드가 포함된 통화(`call_records.call_summary` 기준)를 검색해 발신번호·통화시각·요약을 안내한다.
  2. **기간별 최다 발신 번호 집계**: "한 달 내에 제일 많이 전화한 번호 찾아줘"처럼 기간(오늘/이번 주/이번 달) 내 발신 번호별 통화 건수를 집계해 상위 번호를 안내한다.
  3. **오늘자 미응답(수신 못한) 번호 조회**: "오늘 수신받지 못한 번호를 알려줘"처럼 오늘 걸려왔지만 응답(AI/사람 모두)되지 않은 통화의 발신번호를 조회해 안내한다.

  이 Tool은 새로운 벡터 임베딩 인덱스를 구축하지 않고, 기존 `call-history` API가 사용하는 `call_records`(SQLite) 데이터를 owner로 필터링한 뒤 구조화 검색·집계하는 방식으로 구현한다(설계 결정 근거는 NFR5 참고).
- **FR25 (IntelliDecision 유형 C — 포괄적 도움 요청, 2026-07-23 범위 추가, Story 1.15)**: 시스템은 FR12의 탐색성/실행성 두 유형에 더해, 사용자가 특정 기능을 지정하지 않고 포괄적으로 "뭘 할 수 있어?", "어떤 도움을 줄 수 있어?"처럼 묻는 발화를 **유형 C(도움 요청)** 로 구분해야 한다.
  - 유형 C 응답은 실제로 구현된 능력(설정 조회/자동설정/통계 조회/통화 이력 NLQ/온보딩 안내/매뉴얼 Q&A) 중 최소 3개 카테고리를 **구체적 예시 발화와 함께** 안내해야 하며, 존재하지 않는 기능을 언급하지 않아야 한다.
  - 유형 C는 Tool 호출이 필요 없는 순수 안내이므로, Tool 바인딩 성공 여부와 무관하게 항상 적용되어야 한다(기본 시스템 프롬프트에 직접 포함, bind_tools/Gemini FC/프롬프트 폴백 3개 경로 모두 적용).
  - 유형 A/B와 마찬가지로 최종 판단은 키워드 매칭이 아닌 LLM 판단을 우선한다(FR12/Story 2.6과 일관된 원칙, 별도 분류 LLM 호출 추가 없음 — NFR1 지연 예산 보호).
- **FR26 (IntelliDecision 유형 D~I — 대화 수리·복구 패턴, 2026-07-23 범위 추가, Story 1.16)**: 시스템은 유형 A/B/C에 더해 아래 6가지 대화 제어·복구 상황을 명시적으로 처리해야 한다(근거: `docs/reports/2026-07/2026-07-23_intellidecision_enhancement_research.md` 리서치, Rasa conversation repair/ISO 24617-2/Alexa 패턴 참고).
  - **유형 D(정정)**: 유형 B 확인 발화 중 사용자가 다른 대상으로 정정하면 단순 취소가 아니라 새 대상으로 다시 확인 발화를 이어간다.
  - **유형 E(실행 취소/Undo)**: 가장 최근 변경 1건을 확인 후 이전 값으로 되돌리는 전용 Tool(2개)을 제공한다 — 기존 변경 이력 테이블(Story 1.9)을 그대로 재사용하며, 되돌리기도 유형 B와 동일한 확인 후 실행 원칙을 따른다.
  - **유형 F(모호성 해소)**: 대상 도메인·필드가 불명확한 발화(예: "그거 설정 좀 바꿔줘")에는 짐작으로 진행하지 않고 먼저 되묻는다.
  - **유형 G(일괄 처리)**: 한 발화에 여러 설정 변경이 섞여 있으면 항목별로 따로따로 묻지 않고 한 번에 묶어서 확인한다.
  - **유형 H(범위 외 이유 설명)**: 제외 목록 항목 거부 시 Tool이 반환한 구체적 사유를 그대로 인용해 설명하고, 뭉뚱그려 "정책상 제한"으로만 안내하지 않는다.
  - **유형 I(반복 요청)**: 음성 채널에서 "다시 말해줘" 류 발화에 직전 AI 발화를 간결하게 요약해 다시 안내한다.
  - 유형 D/F/G/H/I는 별도 분류 LLM 호출 추가 없이 기존 메인 LLM 호출의 프롬프트 규칙만으로 구현하며(NFR1 지연 예산 보호), 유형 E만 신규 Tool 2개가 필요하다.
- **FR27 (능력 레지스트리 기반 유형 C 동적화, 2026-07-23 범위 추가, Story 1.17)**: 유형 C(FR25)의 능력 안내 목록은 하드코딩된 정적 문구가 아니라 **설정 카탈로그에서 실시간으로 생성**되어야 한다.
  - 설정 조회/변경 가능 도메인 목록은 `settings_catalog`를 그대로 재사용해야 하며(Epic 2 핫 리로드 적용 시 서버 재시작 없이 즉시 반영), Tool 기반 능력(통계·통화이력·온보딩·실행취소)은 정적 매핑으로 관리해야 한다.
  - 새 캐시 계층을 두지 않아야 한다(이미 Epic 2 캐시 위의 순수 인메모리 연산이라 추가 캐시가 무효화 버그 리스크만 늘림).
  - 생성 실패·빈 결과 시 Story 1.15의 정적 문구로 즉시 폴백해야 한다(회귀 방지).
  - 프론트엔드 도움말 페이지에 Tool 기반 능력을 안내해야 하나, 이를 위해 신규 API·신규 탭을 만들 필요는 없다(기존 페이지에 정적 안내만 추가).

### Non Functional

- **NFR1**: 셀프서비스 세션의 첫 응답 지연은 기존 AI 응대 파이프라인과 동일한 수준(음성 첫 문장 ~2~3초대)을 유지해야 한다.
- **NFR2**: 신규 ChromaDB doc_type(`self_service_manual` 등)은 기존 `owner` 필터 기반 테넌트 격리 원칙을 그대로 따라야 한다.
- **NFR3**: 통계 조회 Tool은 캐시 없이 매 요청 최신값을 반영하거나, 명확한 TTL(예: 1분) 내 캐시를 사용해야 한다.
- **NFR4**: 자동설정 Tool은 **설정 카탈로그에 등록된 항목을 기본 허용**하고, **명시적 제외 목록(destructive/비가역 항목)**에 있는 항목만 변경을 거부해야 한다(허용 목록 방식이 아닌 제외 목록 방식 — 카탈로그 등록이 곧 자동설정 활성화 조건).
- **NFR5 (Call History NLQ 구현 방식)**: FR15는 "개념적으로는 RAG(자연어 질의 → 지식 소스 검색 → 응답 생성)"이지만, 통화 이력은 이미 구조화된 SQLite(`call_records`)에 요약 텍스트(`call_summary`)까지 포함해 저장되어 있으므로, Story 1.11(Screen Graph)이 Full GraphRAG 대신 경량 정적 레지스트리를 택한 것과 동일한 원칙으로 **신규 벡터 임베딩 파이프라인을 구축하지 않는다**. 키워드 검색은 `call_summary` 텍스트 매칭으로, 집계·미응답 조회는 SQL 필터/카운트로 처리하고 LLM은 결과를 자연어로 요약하는 역할만 수행한다.

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

**Epic Structure Decision**: 단일 Epic(Epic 1)으로 구성한다. 이유: 이 기능은 하나의 사용자 여정(테넌트 관리자의 셀프서비스)을 완성하기 위한 연속된 단계들이며, 서로 강하게 의존적이다(감지 → 라우팅 → 정보 안내 → **설정 카탈로그 구축** → 온보딩 안내 → 설정 조회 → 통계 조회 → 자동설정(쓰기) → 가시성 → **탐색성/실행성 발화 구분(IntelliDecision)** → **화면 안내형 응대(Screen Graph)** → **Screen Graph 프론트엔드 열람** → **통화 이력 자연어 질의(Call History NLQ)**). 브라운필드 권장사항대로 여러 개의 작은 Epic으로 쪼개기보다 **하나의 Epic 내 13개 순차 Story**로 리스크를 점진적으로 낮추며 진행한다.

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

### Story 1.10 IntelliDecision (탐색성/실행성 발화 구분 응대)

As a 테넌트 관리자,
I want 내가 기능을 잘 몰라서 물어보는 것인지, 이미 명확히 바꿔달라고 요청하는 것인지에 따라 AI가 다르게 응대하기를,
so that 잘 모를 땐 충분한 설명과 함께 다음 행동을 제안받고, 확실히 원할 땐 불필요한 왕복 없이 빠르게 확인 후 실행되기를 바란다.

**Acceptance Criteria**
1: 탐색성 발화(예: "AI가 모르는 질문 받으면 나한테 전화하게 해줄 수 있어?")에는 매뉴얼 참고 정보 기반 설명 + 사전 준비사항 + "필요하면 말씀해 주세요"류 제안으로 응답하고, 이 턴에서 `update_self_service_setting` Tool을 호출하지 않는다.
2: 실행성 발화(예: "AI가 에스컬레이션 안 하도록 설정해줘")에는 "[항목]을 [값]으로 설정할까요?" 형태로 즉시 확인 발화를 하며, 매뉴얼에 부작용 정보가 있으면 함께 안내한다. 사용자가 긍정하면 그때 Tool을 호출한다.
3: 두 유형 판단은 LLM이 최종 결정하며, 발화 패턴 기반 힌트(예: 종결 어미)는 시스템 프롬프트에 참고 신호로만 제공되고 강제 게이트로 사용되지 않는다.
4: 판단 근거를 사후 확인할 수 있도록 힌트 값과 실제 Tool 호출 여부가 `call_data_record`에 로깅된다(§로깅 원칙).

**Integration Verification**
IV1: 기존 Story 1.8 확인 발화 흐름(2턴: 확인→긍정→실행)이 회귀 없이 그대로 동작한다.
IV2: 힌트 로직이 예외를 던지거나 값을 못 구해도 전체 응답 흐름이 중단되지 않는다(힌트는 best-effort 참고용).

---

### Story 1.11 Screen Graph 구축 및 화면 안내형 응대

As a 테넌트 관리자,
I want 설정 기능이나 방법을 물을 때 AI가 실제 프론트엔드 화면을 설명하면서 안내해주기를,
so that 설정화면을 직접 열어보지 않아도 어디를 어떻게 클릭해야 하는지 대화만으로 파악할 수 있다.

**Acceptance Criteria**
1: 설정 카탈로그 도메인(persona/ai-escalation/call-control/chat-relay/contacts/general/integrations)을 프론트엔드 라우트·화면 내 UI 요소와 연결하는 **경량 지식 그래프(Screen Graph)**가 신규 구축된다(별도 그래프 DB 없이 `settings_catalog.py`와 동일한 정적 레지스트리 패턴).
2: 프론트엔드 전용 화면이 없는 도메인(예: persona)은 화면 정보 없이 등록되어(존재하지 않는 화면을 안내하지 않음).
3: `self_service_agent_node`가 RAG 검색 결과의 `related_domain`으로 Screen Graph를 조회해 화면 안내 정보를 시스템 프롬프트에 주입한다(GraphRAG의 Local Search 패턴 재현 — 매뉴얼 RAG → 도메인 → 화면 1-hop 확장).
4: 화면 정보가 있는 경우 탐색성(IntelliDecision 유형 A) 응답에 화면 안내가 포함되고, 없는 경우 기존처럼 매뉴얼 텍스트 설명만 제공된다.

**Integration Verification**
IV1: Screen Graph 조회 실패/예외가 전체 응답 흐름을 중단시키지 않는다(best-effort, IntelliDecision 힌트와 동일한 안전 원칙).
IV2: 실행성(Story 1.8/1.10 유형 B) 응답 흐름은 화면 안내 주입과 무관하게 회귀 없이 동작한다.

---

### Story 1.12 Screen Graph 프론트엔드 열람

As a 테넌트 관리자,
I want AI 도우미가 어떤 화면을 안내할 수 있는지 프론트엔드에서 직접 확인하기를,
so that AI가 설명하는 내용이 실제 화면과 일치하는지 신뢰할 수 있다.

**Acceptance Criteria**
1: `sip-pbx/frontend/app/settings/ai-assistant/docs`(Story 1.9에서 만든 도움말 페이지)에 **신규 탭 "화면 안내"**가 추가되어 Screen Graph 데이터(도메인별 라우트·설명·UI 요소)를 읽기 전용으로 표시한다.
2: 화면 정보가 있는 도메인은 실제 라우트 링크(클릭 시 해당 설정 화면으로 이동)를 함께 제공한다.
3: 기존 설정 페이지 컴포넌트/레이아웃 컨벤션을 따른다(CR3).

**Integration Verification**
IV1: 신규 탭 추가가 기존 "이용 매뉴얼 Q&A"/"AI 변경 가능 설정" 탭의 동작에 영향을 주지 않는다.

---

### Story 1.13 통화 이력 자연어 질의(Call History NLQ)

As a 테넌트 관리자,
I want 내 번호로 걸려오거나 내가 건 통화 이력을 자연어로 물어보기를,
so that 통화 이력 화면을 직접 뒤지지 않아도 원하는 통화를 바로 찾거나 통계를 알 수 있다.

**Acceptance Criteria**
1: `search_call_history_by_keyword(owner, keyword)` Tool이 owner 소유 통화 중 `call_summary`에 키워드가 포함된 통화를 찾아 발신번호·통화시각·요약을 반환한다(FR15-1).
2: `get_top_caller(owner, period)` Tool이 기간("today"|"week"|"month") 내 발신번호별 통화 건수를 집계해 상위 번호(들)를 반환한다(FR15-2). 미지원 기간은 명확한 폴백 메시지를 반환한다.
3: `get_missed_calls_today(owner)` Tool이 오늘 걸려온 통화 중 응답(AI/사람 모두)되지 않은 것으로 판정된 통화의 발신번호·시각 목록을 반환한다(FR15-3). "미응답" 판정 기준은 Task 0 조사로 확정한다(현재 코드 조사 결과: `has_recording=False AND is_ai_handled=False`가 유력 후보 — 실제 통화 데이터로 재검증 필요).
4: 3개 Tool 모두 새로운 벡터 임베딩 파이프라인 없이 기존 `call_record_db.get_call_records_page(owner=...)`만 재사용한다(NFR5, Story 1.7과 동일 원칙).
5: `self_service_agent_node`의 Tool 목록에 3개가 추가되고, 시스템 프롬프트에 사용 안내가 포함된다.

**Integration Verification**
IV1: 기존 `get_self_service_stats`(Story 1.7) 응답 스키마·동작에 영향을 주지 않는다(신규 Tool 3개는 별도 함수로 추가).
IV2: `call_record_db.get_call_records_page`에 새 파라미터를 추가하지 않고 기존 시그니처(owner/since/direction/limit/offset)만으로 구현 가능함을 확인한다(추가 DB 스키마 변경 없음).
IV3: 3개 Tool 모두 owner 스코프를 벗어난 통화(다른 테넌트)를 반환하지 않는다(기존 owner 강제 오버라이드 패턴 재사용, PO/QA 리뷰에서 발견된 owner 강제 치환 원칙과 동일).

---

## Epic 2: 설정 카탈로그/Screen Graph 동적화 및 IntelliDecision 신뢰성 개선

**작성 배경(2026-07-20)**: Epic 1 운영 중 발견된 3가지 구조적 한계를 해소하기 위한 신규 Epic.
① `settings_catalog.py`/`screen_graph.py`가 순수 Python 하드코딩 레지스트리라 신규 설정 필드·화면이
생길 때마다 백엔드 코드 배포가 필요하다. ② IntelliDecision(Story 1.10)의 탐색성/실행성 힌트가
정규식 키워드 매칭(`intent_tier.py`)에 의존해, STT 오인식·구어체 표현에 취약해 잘못된 참고
신호를 LLM에 줄 위험이 있다. ③ 위 카탈로그·Screen Graph·매뉴얼-도메인 매핑이 실제로 "동적
구성"이라 부를 수 있는 저장소(DB/지식베이스)에 있지 않고 Python 모듈 상수로만 존재해, 실제
무중단 재구성이 가능한지 검증되지 않았다.

### Goals

- 설정 카탈로그·Screen Graph의 **메타데이터**(스키마, writable_fields, 허용값, 화면 정보, 안내
  문구)를 코드가 아닌 DB에서 로드하고, 프론트엔드에서 다운로드(내보내기)·업로드(가져오기)할 수
  있게 한다.
- IntelliDecision이 정규식 키워드 힌트 없이도 LLM 판단만으로 동일하거나 더 나은 정확도를 유지함을
  검증하고, 키워드 힌트 의존을 제거한다.
- 카탈로그/Screen Graph 변경이 **서버 재시작 없이** 즉시 반영됨을 실증한다(진짜 "동적"인지 기능
  체크).

### Non-Goals(명시적 범위 제외)

- **완전 노코드 신규 도메인 생성은 범위 밖이다.** `get_fn`/`update_fn`이 호출하는 실제 서비스
  로직(예: `persona_service.save_persona`)은 여전히 Python 코드로 존재해야 한다. 동적화 대상은
  "이미 코드로 등록된 함수를 참조하는 메타데이터"(필드명, 라벨, 허용값, 화면 안내 문구, writable
  여부)이지, 임의의 새 비즈니스 로직을 데이터만으로 생성하는 것이 아니다(보안·환각 방지 원칙).
- IntelliDecision을 위한 별도의 전용 분류 LLM 호출 추가는 기본적으로 채택하지 않는다(NFR1 지연
  예산 보호) — 기존 메인 LLM 호출 한 번 안에서 few-shot 지시로 판단하는 현재 구조를 유지하되,
  정규식 힌트만 제거한다(§FR23 근거 참고).

### Functional

- **FR16 (카탈로그 메타데이터 DB화)**: 시스템은 설정 카탈로그 도메인별 스키마(필수/옵션 필드),
  `writable_fields`, `field_allowed_values`, `destructive` 여부, 사람이 읽는 라벨/설명을 Python
  코드 상수가 아닌 **DB 테이블**에서 로드해야 한다. `get_fn`/`update_fn` 자체는 코드에 남되,
  코드에는 "함수 이름 → 실제 콜러블" 매핑만 두고(안전한 화이트리스트 방식), 그 외 서술적
  메타데이터는 전부 DB로 이전한다.
- **FR17 (Screen Graph 메타데이터 DB화)**: Screen Graph(`route`, `title`, `description`,
  `nav_hint`, UI 필드 목록)도 FR16과 동일한 원칙으로 DB에서 로드해야 한다.
- **FR18 (프론트엔드 다운로드)**: `설정 > AI 도우미` 화면(또는 하위 신규 화면)에서 현재 적용
  중인 카탈로그·Screen Graph 설정을 JSON/YAML로 다운로드(내보내기)할 수 있어야 한다.
- **FR19 (프론트엔드 업로드)**: 동일 화면에서 편집한 설정 파일을 업로드해 반영할 수 있어야
  하며, 적용 전 반드시 스키마 검증(필수 키 존재, 타입, 참조하는 함수명이 코드의 화이트리스트에
  실제로 등록되어 있는지)을 통과해야 한다. 검증 실패 시 기존 설정은 변경되지 않는다(원자적 적용).
- **FR20 (핫 리로드)**: 업로드가 성공하면 **서버 재시작 없이** 즉시 반영되어야 한다(in-memory
  캐시 무효화).
- **FR21 (버전 이력·롤백)**: 업로드마다 버전이 기록되며, 관리자는 이전 버전으로 되돌릴 수
  있어야 한다.
- **FR22 (신규 도메인 제약 문서화)**: 완전히 새로운 조회/변경 로직이 필요한 도메인은 메타데이터
  업로드만으로 지원되지 않는다는 제약을, 업로드 화면과 개발 문서 양쪽에 명확히 안내해야 한다
  (§Non-Goals 참고 — 오해로 인한 "왜 반영이 안 되냐"는 혼란 방지).
- **FR23 (IntelliDecision 키워드 힌트 제거)**: 탐색성/실행성 판별에 정규식 키워드 힌트
  (`intent_tier.py::classify_intent_tier_hint`)를 더 이상 사용하지 않는다. 시스템 프롬프트의
  few-shot 지시만으로 LLM이 최종 판단하도록 하고, 프롬프트에 삽입되던 "[발화 유형 참고 신호]"
  섹션을 제거한다.
- **FR24 (매뉴얼-도메인 매핑 동적화, 우선순위 낮음)**: `manual_indexer.py::_SECTION_TO_DOMAIN`의
  하드코딩된 섹션 제목 키워드 매칭 리스트를, 매뉴얼 문서 자체에 명시적 메타데이터(예: 섹션
  제목 옆 `{domain: call-control}` 태그)로 선언하는 방식으로 전환한다(선택 사항 — Story 2.8).

### Non Functional

- **NFR6**: 카탈로그/Screen Graph 설정은 in-memory 캐시로 서빙하며, 매 Tool 호출마다 DB를
  조회하지 않아야 한다(NFR1 응답 지연 유지).
- **NFR7**: 업로드 API는 검증 실패 시 명확한 오류 메시지를 반환하고 기존 활성 설정을 그대로
  유지해야 한다(부분 적용 금지).
- **NFR8**: 카탈로그/Screen Graph 업로드 권한은 관리자 역할로 제한되어야 한다(임의 사용자가
  자동설정 대상 필드 범위를 확장하는 것을 방지 — 보안 원칙).

### Compatibility Requirements

- **CR5**: 기존 `get_fn(owner)`/`update_fn(owner, field, value)` 시그니처는 변경하지 않는다 —
  이번 Epic은 "무엇을 어떤 라벨로 노출할지"의 메타데이터만 동적화하며, 함수 자체의 호출 규약은
  Epic 1과 동일하게 유지한다.
- **CR6**: `config/self_service_exclusions.yaml`(제외 목록)과의 관계를 Story 2.1에서 확정한다 —
  동일한 동적 구성 저장소로 통합할지, 별도 파일로 유지할지는 구현 착수 시점에 결정한다(현재는
  파일 기반으로 이미 "설정 배포 없이 편집 가능"하다는 점에서 동적화 원칙에 부분적으로 부합하므로,
  통합 여부는 리스크 대비 이득을 따져 판단).

---

## Epic 2 Story 목록

### Story 2.1 카탈로그/Screen Graph 설정 저장소 설계 및 구현

As a 개발자,
I want 설정 카탈로그·Screen Graph의 메타데이터를 저장할 DB 스키마와 안전한 함수 참조 방식을,
so that 이후 Story들이 이 저장소를 기반으로 동적 로딩·업로드 기능을 구현할 수 있다.

**Acceptance Criteria**
1: 신규 SQLite 테이블(`self_service_catalog_config`, `self_service_screen_graph_config` 또는
   통합 테이블 1개)이 `src/booking/database.py`의 `_DDL` 관례에 따라 추가된다(기존
   `self_service_config_changes`와 동일 파일 공유, 신규 DB 엔진 도입 없음).
2: 각 레코드는 버전 번호·활성 여부(`is_active`)·업로드 시각·업로드 주체를 포함해, 버전 이력
   조회와 롤백(이전 버전 재활성화)이 가능한 구조여야 한다.
3: `get_fn`/`update_fn`은 여전히 Python 코드에 정의하되, **함수명 문자열 → 콜러블** 화이트리스트
   레지스트리(예: `_FUNCTION_REGISTRY: Dict[str, Callable]`)로 별도 분리한다. DB 설정은 이
   화이트리스트에 있는 이름만 참조할 수 있으며, 등록되지 않은 이름을 참조하면 검증 실패로
   거부된다(임의 코드 실행 방지 — 보안 핵심 설계).
4: 기존 `_CATALOG`/`_SCREEN_REGISTRY`의 현재 값을 1회성 마이그레이션 스크립트로 신규 테이블에
   시드(seed)한다 — 이관 직후에는 기존과 동일한 동작을 보장해야 한다(IV1).

**Integration Verification**
IV1: 마이그레이션 직후 기존 `test_self_service_settings_tool.py`/`test_self_service_screen_graph.py`
전체가 회귀 없이 통과한다(값이 이관되었을 뿐 동작은 동일해야 함).
IV2: 화이트리스트에 없는 함수명을 참조하는 설정을 강제로 넣으면 로딩이 거부되고 명확한 오류가
남는다(보안 검증 케이스).

---

### Story 2.2 카탈로그 로더 동적화 (settings_catalog.py 리팩터링)

As a 개발자,
I want `settings_catalog.py`가 하드코딩 딕셔너리 대신 Story 2.1의 DB 저장소를 조회하도록,
so that 카탈로그 메타데이터를 코드 배포 없이 바꿀 수 있다.

**Acceptance Criteria**
1: `list_domains()`/`get_domain_schema()`/`get_domain_value()`/`domain_writable_fields()`/
   `get_field_allowed_values()`의 **외부 시그니처는 변경 없이** 내부 구현만 DB 조회 기반으로
   전환된다(CR5, 호출부인 `tools.py`/`onboarding.py` 등 수정 불필요).
2: in-memory 캐시를 두어 매 호출마다 DB를 조회하지 않는다(NFR6). 캐시는 Story 2.1의 활성 버전이
   바뀌면 무효화된다(신규 `invalidate_catalog_cache()` 함수).
3: DB 조회 실패 시(테이블 없음 등) 안전하게 폴백하거나 명확한 오류를 반환하고, 최소한 서버
   기동 자체는 실패하지 않아야 한다.

**Integration Verification**
IV1: Epic 1 전체 self_service 테스트 스위트가 리팩터링 후에도 회귀 없이 통과한다(가장 중요한
검증 — 순수 내부 구현 교체이므로 외부 동작은 1바이트도 달라지면 안 됨).

---

### Story 2.3 Screen Graph 동적화

As a 개발자,
I want `screen_graph.py`도 Story 2.2와 동일한 패턴으로 DB 기반으로 전환하기를,
so that 화면 안내 정보도 코드 배포 없이 갱신할 수 있다.

**Acceptance Criteria**
1: `get_screen_for_domain()`/`list_all_screens()`/`describe_screen_for_conversation()` 시그니처는
   변경 없이 내부 구현만 DB 조회로 전환된다.
2: 캐시·무효화 메커니즘은 Story 2.2와 동일 원칙을 재사용한다(중복 구현 지양, 공통 헬퍼 고려).

**Integration Verification**
IV1: `self_service_screen_graph_hit` 이벤트·화면 안내 문구가 리팩터링 전후 동일하게 생성됨을
회귀 테스트로 확인한다.

---

### Story 2.4 프론트엔드 설정 다운로드(내보내기)

As a 관리자,
I want AI 도우미 설정(카탈로그·Screen Graph)을 파일로 다운로드하기를,
so that 현재 구성을 검토하거나 백업·버전 관리할 수 있다.

**Acceptance Criteria**
1: `설정 > AI 도우미` 화면(또는 도움말 화면 내 신규 탭)에 "설정 다운로드" 버튼이 추가되어,
   현재 활성 버전의 카탈로그+Screen Graph 설정을 JSON(또는 YAML) 파일로 다운로드할 수 있다.
2: 다운로드 파일에는 함수 화이트리스트 이름(문자열)만 포함되고, 실제 Python 콜러블 참조나
   민감 정보는 포함되지 않는다(보안 — 파일이 유출되어도 코드 실행 경로가 노출되지 않아야 함).
3: 신규 REST 엔드포인트(`GET /api/settings/ai-assistant/catalog-config/export`)를 추가한다(본
   Epic에서 신규 엔드포인트가 필요한 지점 — 기존 `/catalog`, `/screen-graph` 조회 API와 병행
   유지, export는 원본 그대로의 편집 가능한 형식을 반환한다는 점에서 다름).

**Integration Verification**
IV1: 기존 `/api/settings/ai-assistant/catalog`, `/screen-graph` 조회 API 동작에 영향 없음.

---

### Story 2.5 프론트엔드 설정 업로드(검증·적용·롤백)

As a 관리자,
I want 편집한 설정 파일을 업로드해 반영하고, 문제가 있으면 이전 버전으로 되돌리기를,
so that 코드 배포 없이 안전하게 설정을 조정할 수 있다.

**Acceptance Criteria**
1: 업로드 UI에서 파일 선택 → 서버 검증(FR19) → 미리보기(diff: 무엇이 바뀌는지) → 확정 적용의
   흐름을 제공한다.
2: 검증 실패(필수 키 누락, 미등록 함수명 참조, 타입 오류 등) 시 구체적 오류 메시지를 보여주고
   기존 설정은 변경되지 않는다(NFR7).
3: 적용 성공 시 즉시 반영되며(FR20), 화면에서 "현재 적용 버전"과 "이전 버전 목록"을 볼 수 있고
   과거 버전으로 롤백하는 버튼을 제공한다(FR21).
4: 업로드·롤백 이벤트는 감사 로그(누가/언제/어떤 버전)로 남는다.

**Integration Verification**
IV1: 검증 실패 케이스(의도적으로 잘못된 함수명 참조)를 업로드해도 실제 카탈로그 동작이 전혀
바뀌지 않음을 확인한다(원자성 검증, 보안 핵심 시나리오).
IV2: 업로드 직후 재시작 없이 대화 테스트(`/api/self-service/test/converse`)로 변경된 라벨/화면
안내가 즉시 반영됨을 확인한다(FR20 실증 — "진짜 동적"인지 기능 체크, 사용자 요청 §3 대응).

---

### Story 2.6 IntelliDecision 키워드 힌트 제거

As a 개발자,
I want 탐색성/실행성 판별에서 정규식 키워드 힌트를 제거하고 LLM 판단만 남기기를,
so that STT 오인식·구어체 표현에도 안정적으로 동작하고 잘못된 힌트가 LLM을 오도할 위험을
없앨 수 있다.

**Acceptance Criteria**
1: `self_service_agent.py`의 시스템 프롬프트에서 `[발화 유형 참고 신호]` 섹션과
   `classify_intent_tier_hint()` 호출이 제거된다.
2: `self_service_intent_tier_hint` 로깅 이벤트도 제거하거나(또는 사후 분석용으로 남기고 싶다면
   힌트 자체가 아니라 "LLM 최종 판단"만 로깅하도록 대체) — 최종 결정은 Story 착수 시 확정.
3: [self-service-ai-assistant-intelli-decision-qa-plan.md](../qa/self-service-ai-assistant-intelli-decision-qa-plan.md)의
   전체 카탈로그 매트릭스(Case 1/2, 11건)를 힌트 제거 후 재실행해 회귀 없음을 확인한다(제거로
   인한 정확도 저하가 없어야 승인 가능).
4: `intent_tier.py` 모듈 자체는 삭제하거나(사용처가 완전히 없어지면) `deprecated` 표시로 남긴다
   (팀 결정 — 삭제 시 `docs/stories/1.10.*.story.md`에 이력 기록 필요).

**Integration Verification**
IV1: 힌트 제거 전후로 Case 1(실행성) 6건·Case 2(탐색성) 5건의 응답 패턴(확인 발화 vs 설명+제안)이
동일하게 유지됨을 회귀 테스트로 증명한다 — 만약 정확도가 떨어지면 이 Story는 보류하고 대안
(경량 LLM 분류 등)을 재검토해야 한다(§Non-Goals 참고).

---

### Story 2.7 통합 QA 및 무중단 반영 검증

As a QA 담당자,
I want Epic 2로 도입된 동적 구성이 실제로 서버 재시작 없이 반영되고 기존 기능을 깨지 않는지,
so that 안전하게 프로덕션에 반영할 수 있다.

**Acceptance Criteria**
1: [self-service-ai-assistant-master-qa.md](../qa/self-service-ai-assistant-master-qa.md)에 신규
   Branch L(동적 설정)을 추가한다 — 케이스: (a) 카탈로그 라벨 업로드 변경 → 재시작 없이 대화
   응답에 반영, (b) Screen Graph nav_hint 업로드 변경 → 재시작 없이 반영, (c) 잘못된 함수명
   참조 업로드 → 거부·기존 설정 유지, (d) 롤백 → 이전 라벨로 복원.
2: Epic 1 전체 회귀(단위 테스트 + 대표 대화 시나리오)가 Epic 2 반영 후에도 PASS.
3: IntelliDecision 힌트 제거(Story 2.6) 이후 전체 카탈로그 매트릭스 재실행 결과가 기존과 동등
   이상임을 확인한다.

**Integration Verification**
IV1: 모든 케이스가 원시 로그(`call_data_record`)로 교차검증된다(기존 QA 원칙 재사용).

---

### Story 2.8 매뉴얼-도메인 매핑 동적화 (선택, 낮은 우선순위)

As a 개발자,
I want `manual_indexer.py`의 하드코딩된 섹션 키워드 매칭 리스트를 매뉴얼 문서 자체의 명시적
태그로 대체하기를,
so that 매뉴얼 작성자가 코드를 몰라도 정확한 도메인 연결을 보장할 수 있다.

**Acceptance Criteria**
1: `self-service-manual-content.md`의 각 섹션 제목에 명시적 도메인 태그(예:
   `## 3. AI 에스컬레이션 설정 {domain: ai-escalation}`)를 추가하는 컨벤션을 정의한다.
2: `manual_indexer.py`가 이 태그를 우선 사용하고, 태그가 없으면 기존 키워드 매칭으로 폴백한다
   (점진적 마이그레이션 허용, 매뉴얼 전체를 한 번에 바꾸지 않아도 됨).

**Integration Verification**
IV1: 태그 도입 후 기존 매뉴얼 색인·RAG 검색 결과(Story 1.3 QA 케이스)가 회귀 없이 동일하다.

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
