# AI SIP PBX 문서 인덱스

전체 문서 구조 및 바로가기. **스택·배포의 근거**는 [architecture/technical-architecture.md](architecture/technical-architecture.md)(구현체)와 [architecture/production-deployment-architecture.md](architecture/production-deployment-architecture.md)(상용 타깃)를 우선하고, `design/`은 설계·연구·히스토리가 섞일 수 있다([design/README.md](design/README.md)).

**최종 수정**: 2026-05-08

---

## 핵심 문서

| 문서                                                                                                                                                             | 설명                                                                                                                         |
| ---------------------------------------------------------------------------------------------------------------------------------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------- |
| [README.md](README.md)                                                                                                                                           | `docs` 폴더 안내, 주요 문서 표, 읽는 순서                                                                                    |
| [SYSTEM_OVERVIEW.md](SYSTEM_OVERVIEW.md)                                                                                                                         | 시스템 전체 개요, 기능, 유저 스토리, 다이어그램 링크 (소개자료)                                                              |
| [QUICK_START.md](QUICK_START.md)                                                                                                                                 | 설치 및 실행 가이드                                                                                                          |
| [../SKILL.md](../SKILL.md) 및 [../../.github/instructions/sip-pbx-bmad-harness.instructions.md](../../.github/instructions/sip-pbx-bmad-harness.instructions.md) | **문서·BMAD 개발·테스트 하네스** — AI가 모를 때 문서 찾는 규칙, 요청→PRD→architecture→story 진행 순서, 테스트+QA 리포트 연동 |

### Canonical 아키텍처 (`docs/architecture/`)

`design/`의 동명·유사 주제와 겹칠 수 있다. **구현 스택·컴포넌트 경계**는 아래를 우선한다.

| 문서                                                                                                                | 설명                                                                                                    |
| ------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------- |
| [technical-architecture.md](architecture/technical-architecture.md)                                                 | **현재 리포** 기준 기술 아키텍처(구현·스택)                                                             |
| [coding-standards.md](architecture/coding-standards.md)                                                             | BMAD Dev 에이전트 상시 로드 문서 — 로깅/DB스키마/LLM Tool-calling 등 검증된 코드 컨벤션                 |
| [production-deployment-architecture.md](architecture/production-deployment-architecture.md)                         | **상용 통합** 목표(교환기/WTIMS/API/용량/비용/외부 연동 개발)                                           |
| [ai-voicebot-architecture.md](architecture/ai-voicebot-architecture.md)                                             | AI Voicebot 백엔드                                                                                      |
| [frontend-architecture.md](architecture/frontend-architecture.md)                                                   | Next.js 운영 콘솔                                                                                       |
| [voice-ai-conversation-engine.md](architecture/voice-ai-conversation-engine.md)                                     | Voice AI 대화 엔진                                                                                      |
| [realtime-call-dashboard-design.md](architecture/realtime-call-dashboard-design.md)                                 | 실시간 통화 대시보드 설계(문서)                                                                         |
| [realtime-call-dashboard-implementation-summary.md](architecture/realtime-call-dashboard-implementation-summary.md) | 위 항목 구현 요약                                                                                       |
| [self-service-ai-assistant-architecture.md](architecture/self-service-ai-assistant-architecture.md)                 | **Brownfield Architecture(초안)** — 셀프서비스 AI 도우미 컴포넌트·통합 지점·소스 트리                   |
| [voice-latency-turn-taking-architecture.md](architecture/voice-latency-turn-taking-architecture.md)                 | **Brownfield Architecture(초안)** — 응답 지연 계측·TTFT 전환·턴테이킹 재정비(Epic 3~5)                  |
| [gemini-genai-migration-architecture.md](architecture/gemini-genai-migration-architecture.md)                       | **Brownfield Architecture(초안)** — google-genai SDK 마이그레이션 치환 매핑·Tool-calling 재구현(Epic 6) |

**기타**: [architecture/](architecture/) 내 나머지 `.md`는 INDEX에 모두 열거하지 않는다. 폴더 목록·검색으로 보완한다.

---

## 제품·범위 (`docs/product/`)

| 문서                                                                             | 설명                                                                                                                                                                                                                       |
| -------------------------------------------------------------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| [prd.md](product/prd.md)                                                         | **마스터 PRD** (SIP Core + AI + 사업 요약 + MM); 구현 스냅샷                                                                                                                                                               |
| [prd-detailed-phase1-4.md](product/prd-detailed-phase1-4.md)                     | Phase 1–4 **부록** — 상세 FR·User Story                                                                                                                                                                                    |
| [project-plan.md](product/project-plan.md)                                       | 시장·재무·GTM **원문 보관**(기획 시점; 요약은 `prd.md`)                                                                                                                                                                    |
| [self-service-ai-assistant-brief.md](product/self-service-ai-assistant-brief.md) | **Project Brief(초안)** — 셀프서비스 AI 도우미(본인 번호 통화·문자 시 사용법·설정 안내·자동설정)                                                                                                                           |
| [self-service-ai-assistant-prd.md](product/self-service-ai-assistant-prd.md)     | **Brownfield PRD(초안)** — 셀프서비스 AI 도우미 Epic 1(Story 1.1~1.25, FR30 IntelliDecision 판단 근거 투명성 + FR31 RAG·IntelliDecision 고도화 포함) + Epic 2(설정 카탈로그/Screen Graph 동적화, Story 2.1~2.8), FR/NFR/CR |
| [self-service-manual-content.md](product/self-service-manual-content.md)         | **셀프서비스 AI RAG 지식 소스** — 관리자용 서비스 이용 매뉴얼(Q&A 형식, Story 1.3 색인 대상)                                                                                                                               |
| [voice-latency-turn-taking-brief.md](product/voice-latency-turn-taking-brief.md) | **Project Brief(초안)** — 음성 AI 응답 지연 개선(5초 SLA)·TTFT 도입·스마트 턴테이킹 재정비                                                                                                                                 |
| [voice-latency-turn-taking-prd.md](product/voice-latency-turn-taking-prd.md)     | **Brownfield PRD(초안)** — Epic 3(지연 계측·SLA 가드레일)/Epic 4(TTFT 전환)/Epic 5(턴테이킹 재정비), FR/NFR/CR                                                                                                             |
| [gemini-genai-migration-brief.md](product/gemini-genai-migration-brief.md)       | **Project Brief(초안)** — `google-generativeai`→`google-genai` SDK 마이그레이션(thinking 비활성화 근본 원인 해결)                                                                                                          |
| [gemini-genai-migration-prd.md](product/gemini-genai-migration-prd.md)           | **Brownfield PRD(초안)** — Epic A(LLMClient 전환)/B(Tool-calling 재구현)/C(주변 모듈)/D(통합 검증), FR/NFR/CR                                                                                                              |

---

## Dev Stories (`docs/stories/`) — 셀프서비스 AI 도우미 Epic 1

BMAD SM(`create-next-story`)이 생성한 개발 착수용 상세 Story. 각 파일은 Dev 에이전트가 아키텍처 문서를 다시 읽지 않아도 되도록 Dev Notes에 충분한 컨텍스트를 포함한다.

| Story | 문서                                                                                                                                           | 상태                                                                                                                                                                                |
| ----- | ---------------------------------------------------------------------------------------------------------------------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| 1.1   | [1.1.self-call-detection.story.md](stories/1.1.self-call-detection.story.md)                                                                   | Review                                                                                                                                                                              |
| 1.2   | [1.2.self-service-conversation-lane.story.md](stories/1.2.self-service-conversation-lane.story.md)                                             | Review                                                                                                                                                                              |
| 1.3   | [1.3.self-service-manual-rag.story.md](stories/1.3.self-service-manual-rag.story.md)                                                           | Review                                                                                                                                                                              |
| 1.4   | [1.4.settings-catalog-readonly.story.md](stories/1.4.settings-catalog-readonly.story.md)                                                       | Review                                                                                                                                                                              |
| 1.5   | [1.5.onboarding-checklist.story.md](stories/1.5.onboarding-checklist.story.md)                                                                 | Review                                                                                                                                                                              |
| 1.6   | [1.6.settings-query-tool.story.md](stories/1.6.settings-query-tool.story.md)                                                                   | Review                                                                                                                                                                              |
| 1.7   | [1.7.usage-stats-tool.story.md](stories/1.7.usage-stats-tool.story.md)                                                                         | Review                                                                                                                                                                              |
| 1.8   | [1.8.auto-config-write-tool.story.md](stories/1.8.auto-config-write-tool.story.md)                                                             | Review                                                                                                                                                                              |
| 1.9   | [1.9.config-change-history-page.story.md](stories/1.9.config-change-history-page.story.md)                                                     | Review                                                                                                                                                                              |
| 1.10  | [1.10.intelli-decision-intent-tier.story.md](stories/1.10.intelli-decision-intent-tier.story.md)                                               | Done                                                                                                                                                                                |
| 1.11  | [1.11.screen-graph-guided-assistance.story.md](stories/1.11.screen-graph-guided-assistance.story.md)                                           | Done                                                                                                                                                                                |
| 1.12  | [1.12.screen-graph-frontend-viewer.story.md](stories/1.12.screen-graph-frontend-viewer.story.md)                                               | Done                                                                                                                                                                                |
| 1.13  | [1.13.call-history-nlq.story.md](stories/1.13.call-history-nlq.story.md)                                                                       | Done                                                                                                                                                                                |
| 1.14  | [1.14.empty-candidate-string-field-mitigation.story.md](stories/1.14.empty-candidate-string-field-mitigation.story.md)                         | Done(근본 원인 수정 + 실서버 검증 완료, [리포트](reports/2026-07/2026-07-21_story_1.14_and_2.8_implementation.md))                                                                  |
| 1.15  | [1.15.intellidecision-help-type-capability-overview.story.md](stories/1.15.intellidecision-help-type-capability-overview.story.md)             | Done(2026-07-28 실서버 IV1/IV2 검증까지 완료, [master-qa Branch M](qa/self-service-ai-assistant-master-qa.md), [리포트](reports/2026-07/2026-07-23_intellidecision_help_type_c.md)) |
| 1.16  | [1.16.intellidecision-types-d-to-i.story.md](stories/1.16.intellidecision-types-d-to-i.story.md)                                               | Done(2026-07-28 실서버 IV3 검증까지 완료, [master-qa Branch N](qa/self-service-ai-assistant-master-qa.md), [리포트](reports/2026-07/2026-07-23_intellidecision_types_d_to_i.md))    |
| 1.17  | [1.17.capability-registry-rag-plan.story.md](stories/1.17.capability-registry-rag-plan.story.md)                                               | Done(2026-07-28 실서버 검증까지 완료, [master-qa Branch M](qa/self-service-ai-assistant-master-qa.md), [리포트](reports/2026-07/2026-07-23_capability_registry_implementation.md))  |
| 1.18  | [1.18.intellidecision-policy-registry-and-knowledge-graph.story.md](stories/1.18.intellidecision-policy-registry-and-knowledge-graph.story.md) | Done(정책 레지스트리+Screen Graph 2-hop 확장+축 C-1/C-2 시각화, 실서버 검증 완료, [리포트](reports/2026-07/2026-07-28_intellidecision_policy_registry_and_knowledge_graph.md))      |
| 1.19  | [1.19.intellidecision-prompt-auto-rendering.story.md](stories/1.19.intellidecision-prompt-auto-rendering.story.md)                             | Done(프롬프트 산문 번호 자동 렌더링, 실서버 검증 완료, [리포트](reports/2026-07/2026-07-28_intellidecision_prompt_auto_rendering.md))                                               |
| 1.20  | [1.20.intellidecision-rationale-capture-spike.story.md](stories/1.20.intellidecision-rationale-capture-spike.story.md)                         | Done(실제 API 스파이크 검증 완료 — 비동기 fire-and-forget 방식 채택, [리포트](reports/2026-07/2026-07-29_story_1.20_intellidecision_rationale_capture_spike.md))                    |
| 1.21  | [1.21.intellidecision-rationale-logging-and-api.story.md](stories/1.21.intellidecision-rationale-logging-and-api.story.md)                     | Done(코드+단위테스트 19건 통과 + 2026-07-30 실서버 검증 완료, [리포트](reports/2026-07/2026-07-30_story_1.21_implementation.md))                                                    |
| 1.22  | [1.22.intellidecision-rationale-frontend-viewer.story.md](stories/1.22.intellidecision-rationale-frontend-viewer.story.md)                     | Done(프론트엔드 구현 + 2026-07-30 실서버 브라우저 검증 완료, 오너 격리 확인됨)                                                                                                      |
| 1.23  | [1.23.knowledge-base-inventory-transparency.story.md](stories/1.23.knowledge-base-inventory-transparency.story.md)                             | Done(2026-08-03 실서버 IV 검증 완료 — owner=9003 실제 데이터 total_chunks=52로 기존 "매뉴얼 Q&A 52건" 사실과 일치 확인, FR31-A)                                                     |
| 1.24  | [1.24.intellidecision-rag-matching-policy-metadata.story.md](stories/1.24.intellidecision-rag-matching-policy-metadata.story.md)               | Done(2026-08-03 실서버 IV 검증 완료 — 유형 E에서도 RAG 검색이 실행되는 설계 한계 실측 재확인, FR31-B)                                                                               |
| 1.25  | [1.25.manual-source-adapter-generalization.story.md](stories/1.25.manual-source-adapter-generalization.story.md)                               | Review(SourceAdapter 인터페이스+MarkdownManualAdapter 이관 완료, Contextual Retrieval 스파이크는 의도적 보류, FR31-C)                                                               |
| 1.26  | [1.26.knowledge-base-document-crud-and-upload.story.md](stories/1.26.knowledge-base-document-crud-and-upload.story.md)                         | Done(지식 문서 CRUD API+업로드 프론트, PdfDocumentAdapter/OpenApiSpecAdapter 구현 완료, FR32-A, 실서버 IV 검증 완료)                                                                |
| 1.27  | [1.27.knowledge-base-response-simulator.story.md](stories/1.27.knowledge-base-response-simulator.story.md)                                     | Done(응답 시뮬레이터 API+프론트, FR32-B, 실서버 IV 검증 완료 — caller_number=owner 필수 버그를 IV에서 발견·수정)                                                                    |
| 1.28  | [1.28.knowledge-graph-n-hop-generalization.story.md](stories/1.28.knowledge-graph-n-hop-generalization.story.md)                               | Done(knowledge_graph.py 노드/엣지 타입 레지스트리+범용 traverse_graph() 일반화, FR32-C, 단위테스트로 회귀·신규 검증 완료)                                                           |
| 1.29  | [1.29.contextual-retrieval-adoption-spike.story.md](stories/1.29.contextual-retrieval-adoption-spike.story.md)                                 | Done(Contextual Retrieval 실측 스파이크, FR32-D — **결론: 미채택**, BM25는 후속 검토 권장, 결정 리포트 참고)                                                                        |
| 1.30  | [1.30.knowledge-upload-entrypoint-unification.story.md](stories/1.30.knowledge-upload-entrypoint-unification.story.md)                         | Done(지식 업로드/설정 관리 진입점 통합 + 시스템 표준 고정 콘텐츠 구분, FR33-A/C, 실서버 IV 검증 완료)                                                                               |
| 1.31  | [1.31.upload-driven-knowledge-base-auto-assembly.story.md](stories/1.31.upload-driven-knowledge-base-auto-assembly.story.md)                   | Done(업로드 데이터 기반 매뉴얼 Q&A/설정 항목 후보/화면 노드 자동 구성, FR33-B, 실서버 IV 검증 완료)                                                                                 |
| 1.32  | [1.32.intellidecision-simulator-ux-overhaul.story.md](stories/1.32.intellidecision-simulator-ux-overhaul.story.md)                             | Done(유형 A~I 하위 탭+예시별 RAG/Tool 배지+hop_path+멀티턴 시뮬레이터, FR33-D, 실서버 IV 검증 완료)                                                                                 |
| 1.33  | [1.33.type-c-hybrid-rag-strategy.story.md](stories/1.33.type-c-hybrid-rag-strategy.story.md)                                                   | Done(유형 C 카탈로그 도메인별 병렬 하이브리드 RAG, FR33-E, 실서버 IV 검증 완료 — 4개 도메인 걸친 검색 실증)                                                                         |
| 1.34  | [1.34.tool-execution-safety-design-spike.story.md](stories/1.34.tool-execution-safety-design-spike.story.md)                                   | Done(실제 Tool 실행 안전 설계 스파이크 — approved_methods+tool_execution_log 스키마+정책 모듈 구현)                                                                                 |
| 1.35  | [1.35.upload-based-dynamic-tool-execution.story.md](stories/1.35.upload-based-dynamic-tool-execution.story.md)                                 | Review(재개 — base_url/인증정보 캡처/엔드포인트 메타 영속화/build_execution_context 구현 완료, 실서버 IV 잔여)                                                                      |
| 1.36  | [1.36.frontend-ia-restructure-ai-agent-platform.story.md](stories/1.36.frontend-ia-restructure-ai-agent-platform.story.md)                     | Done(Frontend IA 재편 — AI 에이전트 독립 최상위 메뉴+3섹션 페이지, 실서버 IV 완료)                                                                                                  |
| 1.37  | [1.37.knowledge-base-tool-detail-cards-and-hop-view.story.md](stories/1.37.knowledge-base-tool-detail-cards-and-hop-view.story.md)             | Done(지식베이스 API/Tool 단위 상세 카드+hop 뷰 — 실서버 IV 완료)                                                                                                                    |
| 1.38  | [1.38.intellidecision-response-flowchart-ui.story.md](stories/1.38.intellidecision-response-flowchart-ui.story.md)                             | Done(최근 판단 이력 → 실제 대화 기반 세션 단위 순서도, FR34-F — 실서버 IV 완료)                                                                                                     |
| 1.39  | [1.39.response-simulator-integration-review.story.md](stories/1.39.response-simulator-integration-review.story.md)                             | Done(응답 시뮬레이터 폐지 + 실제 채팅 패널 신설, FR34-E — 실서버 IV 완료, SIP UA 미등록으로 AC4 최종 확인만 잔여)                                                                   |
| 1.40  | [1.40.intellidecision-knowledge-base-manual.story.md](stories/1.40.intellidecision-knowledge-base-manual.story.md)                             | Done(IntelliDecision 설명 매뉴얼 전환, FR34-D — 실서버 IV 완료, call_context 버그 발견·수정)                                                                                        |

### Epic 4 — 플랫폼 성숙화 · UX 투명성 전면 개편 (FR35, 2026-08-06 계획 수립, 코드 변경 없음)

계획 리포트: [2026-08-06_epic4_platform_maturation_and_ux_transparency_planning.md](reports/2026-08/2026-08-06_epic4_platform_maturation_and_ux_transparency_planning.md) — UI 미리보기 포함(사용자 검토 대기)

| Story | 문서                                                                                                                                                 | 상태                                                                                                           |
| ----- | ---------------------------------------------------------------------------------------------------------------------------------------------------- | -------------------------------------------------------------------------------------------------------------- |
| 1.41  | [1.41.upload-entrypoint-full-unification.story.md](stories/1.41.upload-entrypoint-full-unification.story.md)                                         | Review(업로드 진입점/폼 완전 통합, FR35-A — 코드+tsc/eslint 완료, 실서버 IV 잔여)                              |
| 1.42  | [1.42.knowledge-base-data-authoring-guide.story.md](stories/1.42.knowledge-base-data-authoring-guide.story.md)                                       | Review(데이터 작성 가이드 문서 페이지, FR35-B — 정적 페이지+예시 다운로드 구현, 실서버 IV 잔여)                                                                  |
| 1.43  | [1.43.platform-vs-tenant-data-origin-badge.story.md](stories/1.43.platform-vs-tenant-data-origin-badge.story.md)                                     | Draft(플랫폼 공통 vs 테넌트 데이터 배지 UI, FR35-C)                                                            |
| 1.44  | [1.44.intent-explorer-intellidecision-real-chat-integration.story.md](stories/1.44.intent-explorer-intellidecision-real-chat-integration.story.md)   | Review(응대 유형 탐색기 — IntelliDecision×실제채팅 연계, FR35-D — 미리보기 API+UI 구현, 실서버 IV 잔여)        |
| 1.45  | [1.45.type-c-hybrid-explorer-display-enhancement.story.md](stories/1.45.type-c-hybrid-explorer-display-enhancement.story.md)                         | Review(유형 C 하이브리드 RAG 탐색기 표시 보강, FR35-E — 도메인 그룹핑 UI 구현+tsc/eslint 완료, 실서버 IV 잔여) |
| 1.46  | [1.46.knowledge-decision-cross-navigation-and-plain-language.story.md](stories/1.46.knowledge-decision-cross-navigation-and-plain-language.story.md) | Review(지식베이스↔응대이력 교차 탐색 + 문구 번역 계층, FR35-F — 필터 API+UI+hop/턴 번역 구현, 실서버 IV 잔여)  |
| 1.47  | [1.47.reference-traceability-and-development-background.story.md](stories/1.47.reference-traceability-and-development-background.story.md)           | Draft(문서 전용, 레퍼런스 추적표 + 개발 배경 소개, FR35-H)                                                     |

리서치(미확정 Post-MVP 후보, 제안 1·2 모두 반영 완료): [2026-07-23_intellidecision_enhancement_research.md](reports/2026-07/2026-07-23_intellidecision_enhancement_research.md) — IntelliDecision 신규 유형(D~I, Story 1.16) 및 능력 레지스트리 기반 RAG 개선(Story 1.17)

결정 지원 리포트: [2026-07-23_capability_registry_decision_options.md](reports/2026-07/2026-07-23_capability_registry_decision_options.md) — Story 1.17의 5개 결정 사항별 옵션 비교 + 축소된 권장 설계(신규 5번째 탭 대신 기존 catalog/screen-graph API 재사용)

### Epic 2 — 설정 카탈로그/Screen Graph 동적화 및 IntelliDecision 신뢰성 개선 (2026-07-20 신설, 구현 진행 중)

| Story | 문서                                                                                             | 상태 |
| ----- | ------------------------------------------------------------------------------------------------ | ---- |
| 2.1   | [2.1.catalog-config-storage.story.md](stories/2.1.catalog-config-storage.story.md)               | Done |
| 2.2   | [2.2.catalog-loader-dynamic.story.md](stories/2.2.catalog-loader-dynamic.story.md)               | Done |
| 2.3   | [2.3.screen-graph-dynamic.story.md](stories/2.3.screen-graph-dynamic.story.md)                   | Done |
| 2.4   | [2.4.frontend-catalog-export.story.md](stories/2.4.frontend-catalog-export.story.md)             | Done |
| 2.5   | [2.5.frontend-catalog-import.story.md](stories/2.5.frontend-catalog-import.story.md)             | Done |
| 2.6   | [2.6.intelli-decision-hint-removal.story.md](stories/2.6.intelli-decision-hint-removal.story.md) | Done |
| 2.7   | [2.7.epic2-integration-qa.story.md](stories/2.7.epic2-integration-qa.story.md)                   | Done |
| 2.8   | [2.8.manual-domain-mapping-dynamic.story.md](stories/2.8.manual-domain-mapping-dynamic.story.md) | Done |

구현 리포트: [2026-07-21_self_service_epic2_story_2.1_to_2.5_implementation.md](reports/2026-07/2026-07-21_self_service_epic2_story_2.1_to_2.5_implementation.md), [2026-07-21_self_service_epic2_story2.5_iv2_and_story2.6_hint_removal.md](reports/2026-07/2026-07-21_self_service_epic2_story2.5_iv2_and_story2.6_hint_removal.md), [2026-07-21_self_service_epic2_completion_report.md](reports/2026-07/2026-07-21_self_service_epic2_completion_report.md), [2026-07-21_story_1.14_and_2.8_implementation.md](reports/2026-07/2026-07-21_story_1.14_and_2.8_implementation.md)(Story 2.8 구현 포함)

### Epic 3~5 — 음성 AI 응답 지연 개선 및 스마트 턴테이킹 (2026-07-24 신설, 진행 중)

PRD: [voice-latency-turn-taking-prd.md](product/voice-latency-turn-taking-prd.md) / Architecture: [voice-latency-turn-taking-architecture.md](architecture/voice-latency-turn-taking-architecture.md)

| Story | 문서                                                                                                     | 상태                                                                                                                                                |
| ----- | -------------------------------------------------------------------------------------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------- |
| 3.1   | [3.1.latency-instrumentation.story.md](stories/3.1.latency-instrumentation.story.md)                     | Done(기구현 확인+간극 보완, [리포트](reports/2026-07/2026-07-24_voice_latency_epic3_story_3.1_3.2_3.4_implementation.md))                           |
| 3.2   | [3.2.latency-sla-cause-tagging.story.md](stories/3.2.latency-sla-cause-tagging.story.md)                 | Done(코드+단위테스트, 실서버 cross-check는 다음 세션)                                                                                               |
| 3.3   | [3.3.latency-sla-response-policy.story.md](stories/3.3.latency-sla-response-policy.story.md)             | Done(2026-07-29 사용자 승인 — 대기멘트 없이 패시브 로깅만 유지, Story 3.2 구현으로 이미 충족)                                                       |
| 3.4   | [3.4.streaming-tts-processor-audit.story.md](stories/3.4.streaming-tts-processor-audit.story.md)         | Done(죽은 코드로 확정, 대안 C 미채택)                                                                                                               |
| 4.1   | [4.1.ttft-design-decision.story.md](stories/4.1.ttft-design-decision.story.md)                           | Done(대안 B 결정, QA 하네스 실측으로 안전 서브셋을 {chitchat, out_of_scope}로 재조정 — greeting은 이미 즉시응답)                                    |
| 4.2   | [4.2.ttft-safe-subset-implementation.story.md](stories/4.2.ttft-safe-subset-implementation.story.md)     | In Progress(2026-07-29, agent.py 안전 감지 계층 + 실서버 스모크 테스트 완료, rag_processor.py TTS 실연결은 barge-in 리스크 확인 후 보류)            |
| 5.1   | [5.1.turn-taking-threshold-audit.story.md](stories/5.1.turn-taking-threshold-audit.story.md)             | Done(Smart Turn/barge-in 죽은 코드로 확정, Epic 5 범위 재조정 필요)                                                                                 |
| 5.2   | [5.2.smart-turn-bargein-revival-design.story.md](stories/5.2.smart-turn-bargein-revival-design.story.md) | Done(사용자 결정: 부활 — 상세설계·권고 완료, 구현은 Story 5.4로 이관)                                                                               |
| 5.3   | [5.3.fr7-supersede-verification.story.md](stories/5.3.fr7-supersede-verification.story.md)               | In Progress(2026-07-29, FR7은 기존 코드로 충족 확인·로깅 충분성 점검 완료, 실통화 재현 테스트만 Story 4.2 Task 5와 통합 진행 예정)                  |
| 5.4   | [5.4.smart-barge-in-implementation.story.md](stories/5.4.smart-barge-in-implementation.story.md)         | In Progress(2026-07-29, `SmartBargeInUserTurnStartStrategy` 구현+단위테스트 10건 PASS, config 기본 비활성 유지, 활성화·A/B 검증은 실통화 QA로 이월) |

### Epic 7 — 지능형 발화 종료(턴 완료) 판단 고도화 (2026-07-29 신설)

PRD: [voice-latency-turn-taking-prd.md](product/voice-latency-turn-taking-prd.md#epic-7--지능형-발화-종료턴-완료-판단-고도화-2026-07-29-신설) / Architecture: [voice-latency-turn-taking-architecture.md](architecture/voice-latency-turn-taking-architecture.md) §2.4

> **🔴 핵심 발견(착수 전 사용자에게 즉시 보고)**: `pipeline_builder.py`가 pipecat의
> `UserTurnStrategies(start=[...])`를 만들 때 `stop=`을 지정하지 않아, pipecat 기본값
> (`TurnAnalyzerUserTurnStopStrategy(LocalSmartTurnAnalyzerV3())`, 즉 Smart Turn v3.2 문법/억양/
> 속도 기반 발화완료 모델)이 **이미 암묵적으로 적용 중임을 실제 실행으로 확인**(2026-07-29).
> `config.yaml`의 `smart_turn.*` 설정은 이 모델을 전혀 제어하지 않는다(orphan 설정). Epic 7은
> "신규 기능 개발"이 아니라 "이미 있는 모델의 관측성 확보 → 필요 시 튜닝/보강"이 출발점이다.

| Story | 문서                                                                                                               | 상태                                                                                                                |
| ----- | ------------------------------------------------------------------------------------------------------------------ | ------------------------------------------------------------------------------------------------------------------- |
| 7.1   | [7.1.smart-turn-stop-strategy-investigation.story.md](stories/7.1.smart-turn-stop-strategy-investigation.story.md) | Done(핵심 사실 확인·Architecture 정정·관측 로깅 구현+단위테스트 3건 PASS, 실통화 데이터 축적은 Story 7.2 착수 전제) |
| 7.2   | [7.2.turn-completion-design-decision.story.md](stories/7.2.turn-completion-design-decision.story.md)               | Draft(Story 7.1 Task 4 완료 후 착수)                                                                                |
| 7.3   | [7.3.turn-completion-implementation.story.md](stories/7.3.turn-completion-implementation.story.md)                 | Draft(Story 7.2 설계 결정 후 착수)                                                                                  |
| 7.4   | [7.4.turn-completion-ab-verification.story.md](stories/7.4.turn-completion-ab-verification.story.md)               | Draft(Story 7.3 구현 완료 후, 실통화 QA에서 Story 4.2/5.3/5.4와 통합 진행)                                          |

QA 하네스: [ai_pipeline_test.py](../src/api/routers/ai_pipeline_test.py)(`/api/ai-pipeline/test/converse`, `AI_PIPELINE_QA_TEST_MODE` 게이트) — 실서버 통화 없이 STT 직후~TTS 직전 갭을 텍스트로 재현. 실측 결과: [2026-07-24_ai_pipeline_qa_endpoint_and_latency_findings.md](reports/2026-07/2026-07-24_ai_pipeline_qa_endpoint_and_latency_findings.md)(chitchat 응답 9.6~9.75초 재현 확인, greeting은 0.02초)

✅ **(2026-07-27) Epic 6 완료 후 재측정**: [2026-07-27_post_thinking_fix_latency_remeasurement.md](reports/2026-07/2026-07-27_post_thinking_fix_latency_remeasurement.md) — chitchat 응답이 9.6~9.75초 → 1.05~3.02초(평균 약 2초)로 개선. **Epic 4 실구현은 이 결과 재판단 전까지 보류**(사용자 지시).

🔴 **근본 원인 확정(최우선 확인)**: [2026-07-24_root_cause_gemini_thinking_not_actually_disabled.md](reports/2026-07/2026-07-24_root_cause_gemini_thinking_not_actually_disabled.md) — 위 9.6초 지연이 `LLMClient`의 Gemini "thinking" 비활성화 코드(`ThinkingConfig`)가 설치된 `google-generativeai==0.8.6`(deprecated) SDK에 아예 존재하지 않아 실패가 침묵되어 왔던 것이 원인. `LLMClient`를 쓰는 모든 경로(classify_intent 3차 분류, self-service Tool-calling 등)에 영향 가능성. SDK 마이그레이션(`google-genai`) 등 조치 결정 필요.

📋 **다음 세션 시작 시 필독**: [2026-07-24_session_handover_voice_latency_and_gemini_thinking_root_cause.md](reports/2026-07/2026-07-24_session_handover_voice_latency_and_gemini_thinking_root_cause.md) — 이번 세션 전체 요약 + 착수 지점(모델 교체 시도 실패 확인 포함, `llm_client.py` 스파이크 검증부터 시작 권장) + 현재 `config.yaml` 상태.

> Epic 4(Story 4.2~4.3)의 나머지 Story는 PRD에 정의만 되어 있고, thinking 비활성화 이후 재측정 결과(위 2026-07-27 리포트)를 바탕으로 착수 여부를 사용자가 먼저 결정해야 한다. Epic 5는 Story 5.2에서 "부활"로 방향이 확정되었으므로, Story 5.3(FR7 실서버 재현, 저위험)을 먼저 착수하고 Story 5.4(부활 구현)로 이어간다(PRD/Architecture §2.3.1 참고).

### Epic 6 — Gemini SDK 마이그레이션 (`google-generativeai` → `google-genai`) (2026-07-24 신설, **완료**)

PRD: [gemini-genai-migration-prd.md](product/gemini-genai-migration-prd.md) / Architecture: [gemini-genai-migration-architecture.md](architecture/gemini-genai-migration-architecture.md) / Brief: [gemini-genai-migration-brief.md](product/gemini-genai-migration-brief.md)

| Story | 문서                                                                                                                     | 상태                                                                                                                                                                                                                     |
| ----- | ------------------------------------------------------------------------------------------------------------------------ | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| 6.1   | [6.1.llm-client-genai-adapter.story.md](stories/6.1.llm-client-genai-adapter.story.md)                                   | Done([리포트](reports/2026-07/2026-07-24_story_6.1_llm_client_genai_migration.md))                                                                                                                                       |
| 6.2   | [6.2.booking-gemini-fc-genai-migration.story.md](stories/6.2.booking-gemini-fc-genai-migration.story.md)                 | Done(실 API 2라운드 Tool-calling 검증 완료)                                                                                                                                                                              |
| 6.3   | [6.3.peripheral-modules-genai-migration.story.md](stories/6.3.peripheral-modules-genai-migration.story.md)               | Done([리포트](reports/2026-07/2026-07-27_story_6.3_peripheral_modules_genai_migration.md), gemini-2.0-flash 404 결함 발견 후 [즉시 수정 완료](reports/2026-07/2026-07-27_ringback_and_call_history_gemini_model_fix.md)) |
| 6.4   | [6.4.full-integration-verification-and-cleanup.story.md](stories/6.4.full-integration-verification-and-cleanup.story.md) | Done(google-generativeai venv 제거 + 실서버 booking/self_service/링백 cross-check 전부 통과)                                                                                                                             |

스파이크 검증(가설 확정): [2026-07-24_google_genai_thinking_off_spike_validation.md](reports/2026-07/2026-07-24_google_genai_thinking_off_spike_validation.md) — `thinking_budget=0` 실적용 시 TTFT 3.81s→0.77s(약 80%↓) 실측.

Epic 6 전체 완료 — `google-generativeai` 완전 제거(venv uninstall + requirements-ai.txt 정리), 실서버 chitchat/self_service Tool-calling/링백 가사 생성 cross-check 전부 통과.


---

## API·테스트·UX

| 문서                                                               | 설명                                      |
| ------------------------------------------------------------------ | ----------------------------------------- |
| [api-specification.md](api/api-specification.md)                   | REST·WebSocket API 참고(구현과 병행 검증) |
| [backend-testing-strategy.md](testing/backend-testing-strategy.md) | 백엔드 테스트 전략                        |
| [user-flow.md](ux/user-flow.md)                                    | 사용자·운영자·상담원 플로우               |

---

## QA (`docs/qa/`)

| 문서                                                                                                              | 설명                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                            |
| ----------------------------------------------------------------------------------------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| [README.md](qa/README.md)                                                                                         | QA 폴더 안내                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                    |
| [test-strategy.md](qa/test-strategy.md)                                                                           | 테스트 전략                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                     |
| [test-execution-guide.md](qa/test-execution-guide.md)                                                             | 실행 가이드                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                     |
| [test-results.md](qa/test-results.md)                                                                             | 결과 기록                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                       |
| [test-detailed-report.md](qa/test-detailed-report.md)                                                             | 상세 리포트                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                     |
| [self-service-ai-assistant-master-qa.md](qa/self-service-ai-assistant-master-qa.md)                               | **셀프서비스 AI 도우미 통합 QA 케이스 문서(Master, 2026-07-20, v1.4)** — Story 1.1~1.13 전체를 기능 분기(Branch A~N)별로 정리, 다중 Tool 연계 시나리오 포함, 실행 결과·발견된 결함 기록. Branch O/P(2026-07-29, 제안·미실행)로 IntelliDecision 유형 G/H/I 정적 매트릭스 + 실사용자 관점 동적 시나리오 계획 추가. §6에 고객 열람용 Flow 표현 방식 제안 포함(실제 문서는 [guides/self-service-ai-assistant-customer-facing-flow-samples.md](guides/self-service-ai-assistant-customer-facing-flow-samples.md) 참고). **신규 QA는 이 문서를 사용** |
| [self-service-ai-assistant-bmad-qa-test-plan.md](qa/self-service-ai-assistant-bmad-qa-test-plan.md)               | (이력 보존, master-qa.md로 통합됨) 셀프서비스 AI 도우미 BMAD QA 자동 테스트 항목서                                                                                                                                                                                                                                                                                                                                                                                                                                                              |
| [self-service-ai-assistant-intelli-decision-qa-plan.md](qa/self-service-ai-assistant-intelli-decision-qa-plan.md) | (이력 보존, master-qa.md Branch H로 통합됨) Story 1.10 IntelliDecision 전체 카탈로그 매트릭스                                                                                                                                                                                                                                                                                                                                                                                                                                                   |
| [self-service-ai-assistant-screen-graph-qa-plan.md](qa/self-service-ai-assistant-screen-graph-qa-plan.md)         | (이력 보존, master-qa.md Branch I로 통합됨) Story 1.11/1.12 Screen Graph QA                                                                                                                                                                                                                                                                                                                                                                                                                                                                     |
| [self-service-ai-assistant-call-history-nlq-qa-plan.md](qa/self-service-ai-assistant-call-history-nlq-qa-plan.md) | (이력 보존, master-qa.md Branch J로 통합됨) Story 1.13 통화 이력 자연어 질의 QA(실서버 검증 완료)                                                                                                                                                                                                                                                                                                                                                                                                                                               |

---

## 분석 (`docs/analysis/`)

| 문서                                                                  | 설명              |
| --------------------------------------------------------------------- | ----------------- |
| [README.md](analysis/README.md)                                       | 분석 폴더 안내    |
| [ai-response-time-analysis.md](analysis/ai-response-time-analysis.md) | AI 응답 시간 분석 |

---

## 발표·브리프 (`docs/presentation/`)

| 문서                                                                                                | 설명                                                                             |
| --------------------------------------------------------------------------------------------------- | -------------------------------------------------------------------------------- |
| [PROJECT_BRIEF.md](presentation/PROJECT_BRIEF.md)                                                   | 프로젝트 브리프(요약)                                                            |
| [self-service-ai-assistant-introduction.md](presentation/self-service-ai-assistant-introduction.md) | 셀프서비스 AI 도우미 신규 기능 소개자료 (아키텍처, RAG, IntelliDecision, 사용법) |

`images/`·Mermaid 생성 스크립트 등은 동 폴더에서 관리한다.

---

## 설계서 (`docs/design/`)

> **중복 주의**: [design/AI_VOICEBOT_ARCHITECTURE.md](design/AI_VOICEBOT_ARCHITECTURE.md), [design/FRONTEND_ARCHITECTURE.md](design/FRONTEND_ARCHITECTURE.md)는 이름이 `architecture/`과 비슷하지만, **최신 스택·경계**는 [architecture/](architecture/)의 동 역할 문서를 우선한다.

### 아키텍처

| 문서                                                                                | 설명                         |
| ----------------------------------------------------------------------------------- | ---------------------------- |
| [AI_VOICEBOT_ARCHITECTURE.md](design/AI_VOICEBOT_ARCHITECTURE.md)                   | AI 음성봇 설계 시점 아키텍처 |
| [FRONTEND_ARCHITECTURE.md](design/FRONTEND_ARCHITECTURE.md)                         | Next.js 대시보드(설계 시점)  |
| [ORCHESTRATOR_VS_PIPECAT_STRUCTURE.md](design/ORCHESTRATOR_VS_PIPECAT_STRUCTURE.md) | Orchestrator vs Pipecat      |

### 대화 처리

| 문서                                                                      | 설명               |
| ------------------------------------------------------------------------- | ------------------ |
| [INTENT_HANDLING_DESIGN.md](design/INTENT_HANDLING_DESIGN.md)             | Intent별 처리 로직 |
| [AI_RESPONSE_HUMANLIKE_DESIGN.md](design/AI_RESPONSE_HUMANLIKE_DESIGN.md) | 자연스러운 AI 응답 |
| [INTENT_TAXONOMY_RESEARCH.md](design/INTENT_TAXONOMY_RESEARCH.md)         | Intent 분류 연구   |

### 미디어 (RTP/TTS/STT)

| 문서                                                                        | 설명                 |
| --------------------------------------------------------------------------- | -------------------- |
| [TTS_RTP_AND_STT_QUEUE_DESIGN.md](design/TTS_RTP_AND_STT_QUEUE_DESIGN.md)   | TTS→RTP·STT 큐       |
| [TTS_RTP_STRUCTURE_REVIEW.md](design/TTS_RTP_STRUCTURE_REVIEW.md)           | TTS→RTP 구조 검토    |
| [TTS_RTP_LOSS_DEBUG_LOGGING.md](design/TTS_RTP_LOSS_DEBUG_LOGGING.md)       | 디버그 로깅          |
| [WEBRTC_AEC_DESIGN.md](design/WEBRTC_AEC_DESIGN.md)                         | WebRTC AEC           |
| [BYPASS_REALTIME_STT_AND_WS.md](design/BYPASS_REALTIME_STT_AND_WS.md)       | Bypass 모드 STT      |
| [USER_TO_USER_STT_REALTIME.md](design/USER_TO_USER_STT_REALTIME.md)         | 사용자 간 실시간 STT |
| [STT_ADDITIONAL_CONSIDERATIONS.md](design/STT_ADDITIONAL_CONSIDERATIONS.md) | STT 고려사항         |
| [TEMPORAL_EXPRESSION_DESIGN.md](design/TEMPORAL_EXPRESSION_DESIGN.md)       | 시제 정규화          |
| [TEMPORAL_EXPRESSION_RESEARCH.md](design/TEMPORAL_EXPRESSION_RESEARCH.md)   | 시제 연구            |

### HITL (Human-in-the-Loop)

| 문서                                                                                            | 설명             |
| ----------------------------------------------------------------------------------------------- | ---------------- |
| [HITL_OPERATOR_RESPONSE_FLOW.md](design/HITL_OPERATOR_RESPONSE_FLOW.md)                         | 운영자 응답 흐름 |
| [HITL_DEFERRED_RESPONSE_DESIGN.md](design/HITL_DEFERRED_RESPONSE_DESIGN.md)                     | 지연 응답        |
| [HITL_CURRENT_LOGIC.md](design/HITL_CURRENT_LOGIC.md)                                           | 현재 로직        |
| [HITL_AND_FOLLOWUP_VERIFICATION.md](design/HITL_AND_FOLLOWUP_VERIFICATION.md)                   | 후속 검증        |
| [HITL_CALL_HISTORY_INTEGRATION.md](design/HITL_CALL_HISTORY_INTEGRATION.md)                     | 통화이력 연동    |
| [HITL-IMPLEMENTATION-STATUS-AND-RESEARCH.md](design/HITL-IMPLEMENTATION-STATUS-AND-RESEARCH.md) | 구현 상태·연구   |

### 지식베이스 / RAG

| 문서                                                                                                                                    | 설명                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                             |
| --------------------------------------------------------------------------------------------------------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| [CHROMADB_CATEGORY_DESIGN.md](design/CHROMADB_CATEGORY_DESIGN.md)                                                                       | ChromaDB 카테고리                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                |
| [KNOWLEDGE_MANAGEMENT_DESIGN.md](design/KNOWLEDGE_MANAGEMENT_DESIGN.md)                                                                 | 지식 관리                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                        |
| [KNOWLEDGE_CLASSIFICATION_AND_INCOMING_DATA.md](design/KNOWLEDGE_CLASSIFICATION_AND_INCOMING_DATA.md)                                   | 분류·수신 데이터                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                 |
| [KNOWLEDGE_DOC_TYPE_DESIGN.md](design/KNOWLEDGE_DOC_TYPE_DESIGN.md)                                                                     | 문서 유형                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                        |
| [KNOWLEDGE_STAGE3_AND_LOGGING.md](design/KNOWLEDGE_STAGE3_AND_LOGGING.md)                                                               | 추출 3단계·로깅                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                  |
| [knowledge-extraction-upgrade.md](design/knowledge-extraction-upgrade.md)                                                               | 추출 업그레이드                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                  |
| [RAG_DB_LOGGING.md](design/RAG_DB_LOGGING.md)                                                                                           | RAG DB 로깅                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                      |
| [UNKNOWN_ANSWER_AND_FOLLOW_UP_DESIGN.md](design/UNKNOWN_ANSWER_AND_FOLLOW_UP_DESIGN.md)                                                 | 미응답·후속                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                      |
| [SELF_SERVICE_HELP_DOCS_DESIGN.md](design/SELF_SERVICE_HELP_DOCS_DESIGN.md)                                                             | 셀프서비스 도움말 Q&A ChromaDB 색인·API 설계                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                     |
| [SELF_SERVICE_SCREEN_GUIDED_GRAPHRAG_RESEARCH.md](design/SELF_SERVICE_SCREEN_GUIDED_GRAPHRAG_RESEARCH.md)                               | 화면 안내형 응대 리서치 — GraphRAG Brownfield 검토(구현 전 리서치)                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                               |
| [SELF_SERVICE_INTELLIDECISION_KNOWLEDGE_STRUCTURING_RESEARCH.md](design/SELF_SERVICE_INTELLIDECISION_KNOWLEDGE_STRUCTURING_RESEARCH.md) | **(2026-07-27)** IntelliDecision 정책 구조화·Screen Graph 다중 홉 확장·가시화 리서치(구현 전, 방향 제시)                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                         |
| [SELF_SERVICE_CORE_FEATURES_EXTERNAL_RESEARCH.md](design/SELF_SERVICE_CORE_FEATURES_EXTERNAL_RESEARCH.md)                               | **(2026-07-29)** Story 1.1~1.7 핵심 기능별 외부 레퍼런스 리서치(IntelliDecision/RAG/Tool-calling/카탈로그/온보딩/통계질의/세션감지 — 학술자료·산업사례·상용 레퍼런스·대안 비교)                                                                                                                                                                                                                                                                                                                                                                                                                                  |
| [SELF_SERVICE_RAG_INTELLIDECISION_ADVANCEMENT_RESEARCH.md](design/SELF_SERVICE_RAG_INTELLIDECISION_ADVANCEMENT_RESEARCH.md)             | **(2026-08-04 v2.3)** 도메인 비종속 지식베이스 & IntelliDecision 플랫폼 설계 — 웹 업로드·CRUD(PDF/OpenAPI 포함), n-hop 그래프 일반화, 실제 LLM 응답 기반 응답 시뮬레이터, 실사용 레퍼런스 다수(Fin/Glean/Anthropic/Alexa/Dialogflow CX/Lex/Zendesk/GraphRAG/Rasa) 비교 — PRD FR32/Story 1.26~1.29(전부 Done, FR32-D는 미채택 결론) → FR33/Story 1.30~1.33(전부 Done) 완료                                                                                                                                                                                                                                        |
| [MCP_VS_CLIENT_CENTRIC_UNIVERSAL_AGENT_MARKET_RESEARCH.md](design/MCP_VS_CLIENT_CENTRIC_UNIVERSAL_AGENT_MARKET_RESEARCH.md)             | **(2026-08-05 v1.1)** "서버 표준화(MCP)" vs "클라이언트가 API 문서만으로 임의 시스템에 적응"(사용자 아이디어) 시장·연구 조사 — OpenAI GPT Actions/ChatGPT Plugins/Zapier NLA→MCP/Composio(상용), Gorilla·GoEx/RestGPT/API-Bank(학계), GitHub "openapi to mcp" 오픈소스 생태계(437개 저장소, mcp-link/openapi-mcp-server/Twilio 공식/open-connector 등 스타 수백~4천+) 10건 이상 원문·번역·시사점 정리. 결론: 이미 있는 개념(RestGPT·GPT Actions·mcp-link 계열이 가장 근접), 우리 시스템(Story 1.26/1.31)의 차별점은 "런타임 업로드 즉시 반영", 격차는 "실제 실행"(Non-Goal로 미룸) — 코드 변경 없음, 순수 리서치 |

### 호 전환 / 운영자

| 문서                                                                            | 설명         |
| ------------------------------------------------------------------------------- | ------------ |
| [AI_DYNAMIC_CALL_TRANSFER_DESIGN.md](design/AI_DYNAMIC_CALL_TRANSFER_DESIGN.md) | 동적 호 전환 |
| [OPERATOR_TAKEOVER_DESIGN.md](design/OPERATOR_TAKEOVER_DESIGN.md)               | 운영자 개입  |
| [OPERATOR-AWAY-MODE-DESIGN.md](design/OPERATOR-AWAY-MODE-DESIGN.md)             | 부재중 모드  |
| [ai-call-transfer.md](design/ai-call-transfer.md)                               | AI 호 전환   |

### 통화이력 / CDR

| 문서                                                                            | 설명          |
| ------------------------------------------------------------------------------- | ------------- |
| [CALL_HISTORY_AND_CONTENT_DESIGN.md](design/CALL_HISTORY_AND_CONTENT_DESIGN.md) | 통화이력·내용 |
| [CALL_HISTORY_AND_RECORDINGS.md](design/CALL_HISTORY_AND_RECORDINGS.md)         | 이력·녹음     |
| [CDR_ENHANCEMENT_DESIGN.md](design/CDR_ENHANCEMENT_DESIGN.md)                   | CDR 개선      |

### 기타

| 문서                                                                                | 설명                    |
| ----------------------------------------------------------------------------------- | ----------------------- |
| [multi-tenant-rag-and-dashboard.md](design/multi-tenant-rag-and-dashboard.md)       | 멀티테넌트 RAG·대시보드 |
| [ai-outbound-call.md](design/ai-outbound-call.md)                                   | AI 발신                 |
| [ai-greeting-and-capability-guide.md](design/ai-greeting-and-capability-guide.md)   | 인사말·기능             |
| [ai-implementation-guide.md](design/ai-implementation-guide.md)                     | AI 구현 가이드 Part 1   |
| [ai-implementation-guide-part2.md](design/ai-implementation-guide-part2.md)         | Part 2                  |
| [CALLER_MEMORY_DESIGN.md](design/CALLER_MEMORY_DESIGN.md)                           | 발신자 메모리           |
| [CALLER_MEMORY_VERIFICATION.md](design/CALLER_MEMORY_VERIFICATION.md)               | 메모리 검증             |
| [RECORDING_FLOW_CHECK.md](design/RECORDING_FLOW_CHECK.md)                           | 녹음 흐름               |
| [PIPELINE_REPLACEMENT_VERIFICATION.md](design/PIPELINE_REPLACEMENT_VERIFICATION.md) | 파이프라인 교체 검증    |

전체 설계 목록·카테고리는 [design/README.md](design/README.md)를 병행한다.

---

## 가이드 (`docs/guides/`)

전체 파일(현재 22개 내외)은 [guides/README.md](guides/README.md)에서 카테고리별로 본다. INDEX에는 자주 쓰는 항목만 남긴다.

### 설치 / 설정

| 문서                                                            | 설명               |
| --------------------------------------------------------------- | ------------------ |
| [google-api-setup.md](guides/google-api-setup.md)               | Google Cloud API   |
| [HOW_TO_SET_API_KEY.md](guides/HOW_TO_SET_API_KEY.md)           | API 키             |
| [GEMINI_API_KEY_ROTATION.md](guides/GEMINI_API_KEY_ROTATION.md) | Gemini 키 로테이션 |
| [AI_QUICKSTART.md](guides/AI_QUICKSTART.md)                     | AI 빠른 시작       |
| [QUICK_START_FRONTEND.md](guides/QUICK_START_FRONTEND.md)       | Frontend 빠른 시작 |
| [START_ALL_GUIDE.md](guides/START_ALL_GUIDE.md)                 | 전체 실행          |
| [AI_DB_LOGGING_SETUP.md](guides/AI_DB_LOGGING_SETUP.md)         | AI DB 로깅         |

### 운영 / 사용

| 문서                                                                                                                          | 설명                                                                                                                                                                                                                                                             |
| ----------------------------------------------------------------------------------------------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| [USER_MANUAL.md](guides/USER_MANUAL.md)                                                                                       | 사용자 매뉴얼                                                                                                                                                                                                                                                    |
| [self-service-ai-assistant-customer-facing-flow-samples.md](guides/self-service-ai-assistant-customer-facing-flow-samples.md) | (v2.0, 2026-07-29) 셀프서비스 AI 도우미 고객 열람용 검증 Flow — IntelliDecision 9유형 상세 설명 + 2-hop 지식 연결 경로(화면·변경가능여부) 설명 + Branch A~N 전체 38건 실행 케이스를 mermaid flow로 변환(대표 샘플이 아니라 전체 반영), 내부 함수명·API 경로 생략 |
| [OPERATOR_AWAY_MODE_SETUP.md](guides/OPERATOR_AWAY_MODE_SETUP.md)                                                             | 부재중 모드 설정                                                                                                                                                                                                                                                 |
| [OPERATOR_AWAY_MODE_QUICKSTART.md](guides/OPERATOR_AWAY_MODE_QUICKSTART.md)                                                   | 부재중 빠른 시작                                                                                                                                                                                                                                                 |
| [REALTIME_CONVERSATION.md](guides/REALTIME_CONVERSATION.md)                                                                   | 실시간 대화                                                                                                                                                                                                                                                      |
| [RAG_CHROMADB_LLM_TECHNICAL_MANUAL.md](guides/RAG_CHROMADB_LLM_TECHNICAL_MANUAL.md)                                           | RAG/ChromaDB/LLM                                                                                                                                                                                                                                                 |
| [gemini-model-comparison.md](guides/gemini-model-comparison.md)                                                               | Gemini 모델 비교                                                                                                                                                                                                                                                 |

### 디버깅 / 문제해결

| 문서                                                                      | 설명                   |
| ------------------------------------------------------------------------- | ---------------------- |
| [TROUBLESHOOTING.md](guides/TROUBLESHOOTING.md)                           | 문제 해결              |
| [DEBUGGING.md](guides/DEBUGGING.md)                                       | 디버깅                 |
| [DEBUG-CHEATSHEET.md](guides/DEBUG-CHEATSHEET.md)                         | 치트시트               |
| [APP_LOG_STARTUP_ERRORS.md](guides/APP_LOG_STARTUP_ERRORS.md)             | 시작 에러              |
| [APP_LOG_ERRORS_364_425.md](guides/APP_LOG_ERRORS_364_425.md)             | 특정 에러 분석         |
| [TTS_NO_AUDIO_FIX.md](guides/TTS_NO_AUDIO_FIX.md)                         | TTS 무음               |
| [TTS_RTP_AFTER_ACK_FIX.md](guides/TTS_RTP_AFTER_ACK_FIX.md)               | TTS RTP ACK 후 이슈    |
| [MIGRATION_KNOWLEDGE_METADATA.md](guides/MIGRATION_KNOWLEDGE_METADATA.md) | 지식 메타 마이그레이션 |

---

## 리포트 (`docs/reports/`)

월별 분석·점검·구현 기록. 요약·주제별 대표: **[reports/README.md](reports/README.md)**.

| 폴더                                 | 비고                                       |
| ------------------------------------ | ------------------------------------------ |
| [reports/2025-10/](reports/2025-10/) | 소량 (예: B2BUA 상태)                      |
| [reports/2026-01/](reports/2026-01/) | Phase3·VectorDB·통화이력·프론트 등 (~44편) |
| [reports/2026-02/](reports/2026-02/) | 성능·로그 등 (~16편)                       |
| [reports/2026-03/](reports/2026-03/) | RTP/TTS/HITL/대시보드 등 (~218+편)         |
| [reports/2026-04/](reports/2026-04/) | 이슈·구현 기록 (~200+편)                   |

---

## 디렉토리 구조 (요약)

```
docs/
├── INDEX.md                 ← 이 파일
├── README.md
├── SYSTEM_OVERVIEW.md
├── QUICK_START.md
├── architecture/
├── product/
├── api/
├── testing/
├── ux/
├── guides/
├── design/
├── reports/YYYY-MM/
├── presentation/
├── diagrams/
├── qa/
└── analysis/
```

---

## 링크 문서 현행화 계획 (로드맵)

INDEX 및 상위 문서(`README.md`, `SYSTEM_OVERVIEW.md`)에서 링크된 문서를 **살아 있는 참조**로 유지하기 위한 절차다. 한 번에 전부 고치지 않고, **계층 순서 + 리스크**로 나눈다.

> **진행 현황 (2026-05-08)**: 1·2단계(근거 문서·API/테스트/UX/QA 링크) 및 **3~5단계**(`design/` 클러스터 안내 헤더, [`guides/README.md`](guides/README.md) 동기화, [`presentation/PROJECT_BRIEF.md`](presentation/PROJECT_BRIEF.md) Canonical 아키텍처 정렬) 반영 완료. 이후에는 아래 **지속 점검**만 주기적으로 수행한다.

### 1단계 — 근거 문서 (우선)

| 대상                                                                                                     | 점검 내용                                                       |
| -------------------------------------------------------------------------------------------------------- | --------------------------------------------------------------- |
| [architecture/technical-architecture.md](architecture/technical-architecture.md)                         | 스택 표·다이어그램 링크·내부 상호 링크                          |
| [architecture/production-deployment-architecture.md](architecture/production-deployment-architecture.md) | §11 비용·외부 연동 표, Mermaid, `technical`과 용어 충돌 시 각주 |
| [product/prd.md](product/prd.md) · [prd-detailed-phase1-4.md](product/prd-detailed-phase1-4.md)          | 마스터 PRD·부록 상세 FR과 코드/리포트 불일치 목록화             |

**산출**: 상위 문서 하단 "관련 문서" 표가 1단계만으로 닫히는지 확인.

### 2단계 — API·테스트·UX·QA

| 대상                                                                       | 점검 내용                           |
| -------------------------------------------------------------------------- | ----------------------------------- |
| [api/api-specification.md](api/api-specification.md)                       | 실제 라우트·WS 이벤트명과 diff 목록 |
| [testing/backend-testing-strategy.md](testing/backend-testing-strategy.md) | CI·디렉터리 구조와 일치             |
| [ux/user-flow.md](ux/user-flow.md)                                         | 프론트 화면·역할과 일치             |
| [qa/*.md](qa/)                                                             | 최신 실행 결과 날짜·링크            |

### 3단계 — `design/` 대량 문서

- **방법**: 파일 단위가 아니라 **주제 클러스터**(HITL, RTP, 지식, 호전환)별로 1개 대표 문서를 정해, 나머지에 "대표 문서 참조" 헤더를 추가하거나 obsolete 표시.
- **중복**: `design/AI_VOICEBOT_ARCHITECTURE.md` ↔ [architecture/ai-voicebot-architecture.md](architecture/ai-voicebot-architecture.md) — 한쪽에 "Canonical은 architecture/" 한 줄 삽입.

### 4단계 — `guides/` · 루트 인접 문서

- [guides/README.md](guides/README.md)와 INDEX의 "자주 쓰는 링크" 동기화.
- [QUICK_START.md](QUICK_START.md)·[SYSTEM_OVERVIEW.md](SYSTEM_OVERVIEW.md) 내 **상대 링크 일괄 검사**(스크립트 또는 `rg`로 깨진 경로 검색).

### 5단계 — 리포트·발표 자료

- [reports/README.md](reports/README.md) 큐레이션만 유지·월 폴더 증가 시 테이블 행 추가.
- [presentation/PROJECT_BRIEF.md](presentation/PROJECT_BRIEF.md)가 제품·아키텍처와 어긋나면 1단계 문서 기준으로 한 번만 맞춤.

### 지속 점검 (가벼운 자동화)

- PR 또는 월 1회: `docs/` 내 마크다운에서 `(](...)` 패턴으로 **존재하지 않는 상대 경로** 검색.
- 원칙: **단일 소스**는 `architecture/technical-architecture.md`(구현) / `production-deployment-architecture.md`(상용)이며, 나머지는 이 둘을 가리키도록 정리한다.
