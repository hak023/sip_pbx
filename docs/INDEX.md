# AI SIP PBX 문서 인덱스

전체 문서 구조 및 바로가기. **스택·배포의 근거**는 [architecture/technical-architecture.md](architecture/technical-architecture.md)(구현체)와 [architecture/production-deployment-architecture.md](architecture/production-deployment-architecture.md)(상용 타깃)를 우선하고, `design/`은 설계·연구·히스토리가 섞일 수 있다([design/README.md](design/README.md)).

**최종 수정**: 2026-05-08

---

## 핵심 문서

| 문서                                     | 설명                                                            |
| ---------------------------------------- | --------------------------------------------------------------- |
| [README.md](README.md)                   | `docs` 폴더 안내, 주요 문서 표, 읽는 순서                       |
| [SYSTEM_OVERVIEW.md](SYSTEM_OVERVIEW.md) | 시스템 전체 개요, 기능, 유저 스토리, 다이어그램 링크 (소개자료) |
| [QUICK_START.md](QUICK_START.md)         | 설치 및 실행 가이드                                             |

### Canonical 아키텍처 (`docs/architecture/`)

`design/`의 동명·유사 주제와 겹칠 수 있다. **구현 스택·컴포넌트 경계**는 아래를 우선한다.

| 문서                                                                                                                | 설명                                                                                  |
| ------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------- |
| [technical-architecture.md](architecture/technical-architecture.md)                                                 | **현재 리포** 기준 기술 아키텍처(구현·스택)                                           |
| [production-deployment-architecture.md](architecture/production-deployment-architecture.md)                         | **상용 통합** 목표(교환기/WTIMS/API/용량/비용/외부 연동 개발)                         |
| [ai-voicebot-architecture.md](architecture/ai-voicebot-architecture.md)                                             | AI Voicebot 백엔드                                                                    |
| [frontend-architecture.md](architecture/frontend-architecture.md)                                                   | Next.js 운영 콘솔                                                                     |
| [voice-ai-conversation-engine.md](architecture/voice-ai-conversation-engine.md)                                     | Voice AI 대화 엔진                                                                    |
| [realtime-call-dashboard-design.md](architecture/realtime-call-dashboard-design.md)                                 | 실시간 통화 대시보드 설계(문서)                                                       |
| [realtime-call-dashboard-implementation-summary.md](architecture/realtime-call-dashboard-implementation-summary.md) | 위 항목 구현 요약                                                                     |
| [self-service-ai-assistant-architecture.md](architecture/self-service-ai-assistant-architecture.md)                 | **Brownfield Architecture(초안)** — 셀프서비스 AI 도우미 컴포넌트·통합 지점·소스 트리 |

**기타**: [architecture/](architecture/) 내 나머지 `.md`는 INDEX에 모두 열거하지 않는다. 폴더 목록·검색으로 보완한다.

---

## 제품·범위 (`docs/product/`)

| 문서                                                                             | 설명                                                                                             |
| -------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------ |
| [prd.md](product/prd.md)                                                         | **마스터 PRD** (SIP Core + AI + 사업 요약 + MM); 구현 스냅샷                                     |
| [prd-detailed-phase1-4.md](product/prd-detailed-phase1-4.md)                     | Phase 1–4 **부록** — 상세 FR·User Story                                                          |
| [project-plan.md](product/project-plan.md)                                       | 시장·재무·GTM **원문 보관**(기획 시점; 요약은 `prd.md`)                                          |
| [self-service-ai-assistant-brief.md](product/self-service-ai-assistant-brief.md) | **Project Brief(초안)** — 셀프서비스 AI 도우미(본인 번호 통화·문자 시 사용법·설정 안내·자동설정) |
| [self-service-ai-assistant-prd.md](product/self-service-ai-assistant-prd.md)     | **Brownfield PRD(초안)** — 셀프서비스 AI 도우미 Epic 1·Story 1.1~1.9, FR/NFR/CR                  |

---

## Dev Stories (`docs/stories/`) — 셀프서비스 AI 도우미 Epic 1

BMAD SM(`create-next-story`)이 생성한 개발 착수용 상세 Story. 각 파일은 Dev 에이전트가 아키텍처 문서를 다시 읽지 않아도 되도록 Dev Notes에 충분한 컨텍스트를 포함한다.

| Story | 문서 | 상태 |
|---|---|---|
| 1.1 | [1.1.self-call-detection.story.md](stories/1.1.self-call-detection.story.md) | Draft |
| 1.2 | [1.2.self-service-conversation-lane.story.md](stories/1.2.self-service-conversation-lane.story.md) | Draft |
| 1.3 | [1.3.self-service-manual-rag.story.md](stories/1.3.self-service-manual-rag.story.md) | Draft |
| 1.4 | [1.4.settings-catalog-readonly.story.md](stories/1.4.settings-catalog-readonly.story.md) | Draft |
| 1.5 | [1.5.onboarding-checklist.story.md](stories/1.5.onboarding-checklist.story.md) | Draft |
| 1.6 | [1.6.settings-query-tool.story.md](stories/1.6.settings-query-tool.story.md) | Draft |
| 1.7 | [1.7.usage-stats-tool.story.md](stories/1.7.usage-stats-tool.story.md) | Draft |
| 1.8 | [1.8.auto-config-write-tool.story.md](stories/1.8.auto-config-write-tool.story.md) | Draft |
| 1.9 | [1.9.config-change-history-page.story.md](stories/1.9.config-change-history-page.story.md) | Draft |

---

## API·테스트·UX

| 문서                                                               | 설명                                      |
| ------------------------------------------------------------------ | ----------------------------------------- |
| [api-specification.md](api/api-specification.md)                   | REST·WebSocket API 참고(구현과 병행 검증) |
| [backend-testing-strategy.md](testing/backend-testing-strategy.md) | 백엔드 테스트 전략                        |
| [user-flow.md](ux/user-flow.md)                                    | 사용자·운영자·상담원 플로우               |

---

## QA (`docs/qa/`)

| 문서                                                  | 설명         |
| ----------------------------------------------------- | ------------ |
| [README.md](qa/README.md)                             | QA 폴더 안내 |
| [test-strategy.md](qa/test-strategy.md)               | 테스트 전략  |
| [test-execution-guide.md](qa/test-execution-guide.md) | 실행 가이드  |
| [test-results.md](qa/test-results.md)                 | 결과 기록    |
| [test-detailed-report.md](qa/test-detailed-report.md) | 상세 리포트  |

---

## 분석 (`docs/analysis/`)

| 문서                                                                  | 설명              |
| --------------------------------------------------------------------- | ----------------- |
| [README.md](analysis/README.md)                                       | 분석 폴더 안내    |
| [ai-response-time-analysis.md](analysis/ai-response-time-analysis.md) | AI 응답 시간 분석 |

---

## 발표·브리프 (`docs/presentation/`)

| 문서                                              | 설명                  |
| ------------------------------------------------- | --------------------- |
| [PROJECT_BRIEF.md](presentation/PROJECT_BRIEF.md) | 프로젝트 브리프(요약) |

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

| 문서                                                                                                  | 설명              |
| ----------------------------------------------------------------------------------------------------- | ----------------- |
| [CHROMADB_CATEGORY_DESIGN.md](design/CHROMADB_CATEGORY_DESIGN.md)                                     | ChromaDB 카테고리 |
| [KNOWLEDGE_MANAGEMENT_DESIGN.md](design/KNOWLEDGE_MANAGEMENT_DESIGN.md)                               | 지식 관리         |
| [KNOWLEDGE_CLASSIFICATION_AND_INCOMING_DATA.md](design/KNOWLEDGE_CLASSIFICATION_AND_INCOMING_DATA.md) | 분류·수신 데이터  |
| [KNOWLEDGE_DOC_TYPE_DESIGN.md](design/KNOWLEDGE_DOC_TYPE_DESIGN.md)                                   | 문서 유형         |
| [KNOWLEDGE_STAGE3_AND_LOGGING.md](design/KNOWLEDGE_STAGE3_AND_LOGGING.md)                             | 추출 3단계·로깅   |
| [knowledge-extraction-upgrade.md](design/knowledge-extraction-upgrade.md)                             | 추출 업그레이드   |
| [RAG_DB_LOGGING.md](design/RAG_DB_LOGGING.md)                                                         | RAG DB 로깅       |
| [UNKNOWN_ANSWER_AND_FOLLOW_UP_DESIGN.md](design/UNKNOWN_ANSWER_AND_FOLLOW_UP_DESIGN.md)               | 미응답·후속       |

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

| 문서                                                                                | 설명             |
| ----------------------------------------------------------------------------------- | ---------------- |
| [USER_MANUAL.md](guides/USER_MANUAL.md)                                             | 사용자 매뉴얼    |
| [OPERATOR_AWAY_MODE_SETUP.md](guides/OPERATOR_AWAY_MODE_SETUP.md)                   | 부재중 모드 설정 |
| [OPERATOR_AWAY_MODE_QUICKSTART.md](guides/OPERATOR_AWAY_MODE_QUICKSTART.md)         | 부재중 빠른 시작 |
| [REALTIME_CONVERSATION.md](guides/REALTIME_CONVERSATION.md)                         | 실시간 대화      |
| [RAG_CHROMADB_LLM_TECHNICAL_MANUAL.md](guides/RAG_CHROMADB_LLM_TECHNICAL_MANUAL.md) | RAG/ChromaDB/LLM |
| [gemini-model-comparison.md](guides/gemini-model-comparison.md)                     | Gemini 모델 비교 |

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
