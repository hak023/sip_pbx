# AI SIP PBX 문서 인덱스

전체 문서 구조 및 바로가기.

**최종 수정**: 2026-03-30

---

## 핵심 문서

| 문서 | 설명 |
|---|---|
| [SYSTEM_OVERVIEW.md](SYSTEM_OVERVIEW.md) | 시스템 전체 개요, 기능 상세, 유저 스토리, 아키텍처 (소개자료) |
| [QUICK_START.md](QUICK_START.md) | 설치 및 실행 가이드 |

---

## 설계서 (docs/design/)

### 아키텍처

| 문서 | 설명 |
|---|---|
| [AI_VOICEBOT_ARCHITECTURE.md](design/AI_VOICEBOT_ARCHITECTURE.md) | AI 음성봇 전체 아키텍처 (Pipecat, LangGraph, RAG, TTS, STT, HITL) |
| [FRONTEND_ARCHITECTURE.md](design/FRONTEND_ARCHITECTURE.md) | Next.js 대시보드 아키텍처 (Socket.IO, REST, UI 구조) |
| [ORCHESTRATOR_VS_PIPECAT_STRUCTURE.md](design/ORCHESTRATOR_VS_PIPECAT_STRUCTURE.md) | Orchestrator vs Pipecat 구조 비교 |

### 대화 처리

| 문서 | 설명 |
|---|---|
| [INTENT_HANDLING_DESIGN.md](design/INTENT_HANDLING_DESIGN.md) | Intent별 처리 로직 (17가지 의도, 5단계 분류, LangGraph 분기) |
| [AI_RESPONSE_HUMANLIKE_DESIGN.md](design/AI_RESPONSE_HUMANLIKE_DESIGN.md) | 자연스러운 AI 응답 설계 |
| [INTENT_TAXONOMY_RESEARCH.md](design/INTENT_TAXONOMY_RESEARCH.md) | Intent 분류 체계 연구 |

### 미디어 (RTP/TTS/STT)

| 문서 | 설명 |
|---|---|
| [TTS_RTP_AND_STT_QUEUE_DESIGN.md](design/TTS_RTP_AND_STT_QUEUE_DESIGN.md) | TTS→RTP 큐 및 STT 입력 큐 설계 (Continuous Silence, Drain) |
| [TTS_RTP_STRUCTURE_REVIEW.md](design/TTS_RTP_STRUCTURE_REVIEW.md) | TTS→큐→RTP 구조 검토 및 이슈 분석 |
| [TTS_RTP_LOSS_DEBUG_LOGGING.md](design/TTS_RTP_LOSS_DEBUG_LOGGING.md) | TTS/RTP 손실 디버그 로깅 |
| [WEBRTC_AEC_DESIGN.md](design/WEBRTC_AEC_DESIGN.md) | WebRTC AEC(음향 에코 제거) 설계 |
| [BYPASS_REALTIME_STT_AND_WS.md](design/BYPASS_REALTIME_STT_AND_WS.md) | Bypass 모드 실시간 STT 설계 |
| [USER_TO_USER_STT_REALTIME.md](design/USER_TO_USER_STT_REALTIME.md) | 사용자간 통화 실시간 STT |
| [STT_ADDITIONAL_CONSIDERATIONS.md](design/STT_ADDITIONAL_CONSIDERATIONS.md) | STT 추가 고려사항 |
| [TEMPORAL_EXPRESSION_DESIGN.md](design/TEMPORAL_EXPRESSION_DESIGN.md) | 한글 시제 표현 정규화 설계 |
| [TEMPORAL_EXPRESSION_RESEARCH.md](design/TEMPORAL_EXPRESSION_RESEARCH.md) | 시제 표현 연구 |

### HITL (Human-in-the-Loop)

| 문서 | 설명 |
|---|---|
| [HITL_OPERATOR_RESPONSE_FLOW.md](design/HITL_OPERATOR_RESPONSE_FLOW.md) | HITL 운영자 응답 흐름 |
| [HITL_DEFERRED_RESPONSE_DESIGN.md](design/HITL_DEFERRED_RESPONSE_DESIGN.md) | HITL 지연 응답 설계 |
| [HITL_CURRENT_LOGIC.md](design/HITL_CURRENT_LOGIC.md) | HITL 현재 로직 |
| [HITL_AND_FOLLOWUP_VERIFICATION.md](design/HITL_AND_FOLLOWUP_VERIFICATION.md) | HITL 및 후속 처리 검증 |
| [HITL_CALL_HISTORY_INTEGRATION.md](design/HITL_CALL_HISTORY_INTEGRATION.md) | HITL-통화이력 연동 |
| [HITL-IMPLEMENTATION-STATUS-AND-RESEARCH.md](design/HITL-IMPLEMENTATION-STATUS-AND-RESEARCH.md) | HITL 구현 상태 및 연구 |

### 지식베이스 / RAG

| 문서 | 설명 |
|---|---|
| [CHROMADB_CATEGORY_DESIGN.md](design/CHROMADB_CATEGORY_DESIGN.md) | ChromaDB 카테고리 설계 |
| [KNOWLEDGE_MANAGEMENT_DESIGN.md](design/KNOWLEDGE_MANAGEMENT_DESIGN.md) | 지식 관리 설계 |
| [KNOWLEDGE_CLASSIFICATION_AND_INCOMING_DATA.md](design/KNOWLEDGE_CLASSIFICATION_AND_INCOMING_DATA.md) | 지식 분류 및 수신 데이터 |
| [KNOWLEDGE_DOC_TYPE_DESIGN.md](design/KNOWLEDGE_DOC_TYPE_DESIGN.md) | 지식 문서 유형 설계 |
| [KNOWLEDGE_STAGE3_AND_LOGGING.md](design/KNOWLEDGE_STAGE3_AND_LOGGING.md) | 지식 추출 3단계 및 로깅 |
| [knowledge-extraction-upgrade.md](design/knowledge-extraction-upgrade.md) | 지식 추출 업그레이드 |
| [RAG_DB_LOGGING.md](design/RAG_DB_LOGGING.md) | RAG DB 로깅 |
| [UNKNOWN_ANSWER_AND_FOLLOW_UP_DESIGN.md](design/UNKNOWN_ANSWER_AND_FOLLOW_UP_DESIGN.md) | 미응답 및 후속 처리 설계 |

### 호 전환 / 운영자

| 문서 | 설명 |
|---|---|
| [AI_DYNAMIC_CALL_TRANSFER_DESIGN.md](design/AI_DYNAMIC_CALL_TRANSFER_DESIGN.md) | AI 동적 호 전환 설계 |
| [OPERATOR_TAKEOVER_DESIGN.md](design/OPERATOR_TAKEOVER_DESIGN.md) | 운영자 실시간 개입 설계 |
| [OPERATOR-AWAY-MODE-DESIGN.md](design/OPERATOR-AWAY-MODE-DESIGN.md) | 운영자 부재중 모드 설계 |
| [ai-call-transfer.md](design/ai-call-transfer.md) | AI 호 전환 |

### 통화이력 / CDR

| 문서 | 설명 |
|---|---|
| [CALL_HISTORY_AND_CONTENT_DESIGN.md](design/CALL_HISTORY_AND_CONTENT_DESIGN.md) | 통화이력 및 내용 설계 |
| [CALL_HISTORY_AND_RECORDINGS.md](design/CALL_HISTORY_AND_RECORDINGS.md) | 통화이력 및 녹음 |
| [CDR_ENHANCEMENT_DESIGN.md](design/CDR_ENHANCEMENT_DESIGN.md) | CDR 개선 설계 |

### 기타

| 문서 | 설명 |
|---|---|
| [multi-tenant-rag-and-dashboard.md](design/multi-tenant-rag-and-dashboard.md) | 멀티테넌트 RAG 및 대시보드 |
| [ai-outbound-call.md](design/ai-outbound-call.md) | AI 발신 통화 |
| [ai-greeting-and-capability-guide.md](design/ai-greeting-and-capability-guide.md) | AI 인사말 및 기능 가이드 |
| [ai-implementation-guide.md](design/ai-implementation-guide.md) | AI 구현 가이드 |
| [ai-implementation-guide-part2.md](design/ai-implementation-guide-part2.md) | AI 구현 가이드 Part 2 |
| [CALLER_MEMORY_DESIGN.md](design/CALLER_MEMORY_DESIGN.md) | 발신자 메모리 설계 |
| [CALLER_MEMORY_VERIFICATION.md](design/CALLER_MEMORY_VERIFICATION.md) | 발신자 메모리 검증 |
| [RECORDING_FLOW_CHECK.md](design/RECORDING_FLOW_CHECK.md) | 녹음 흐름 검증 |
| [PIPELINE_REPLACEMENT_VERIFICATION.md](design/PIPELINE_REPLACEMENT_VERIFICATION.md) | 파이프라인 교체 검증 |

---

## 가이드 (docs/guides/)

### 설치 / 설정

| 문서 | 설명 |
|---|---|
| [google-api-setup.md](guides/google-api-setup.md) | Google Cloud API 설정 |
| [HOW_TO_SET_API_KEY.md](guides/HOW_TO_SET_API_KEY.md) | API 키 설정 방법 |
| [GEMINI_API_KEY_ROTATION.md](guides/GEMINI_API_KEY_ROTATION.md) | Gemini API 키 로테이션 |
| [AI_QUICKSTART.md](guides/AI_QUICKSTART.md) | AI 기능 빠른 시작 |
| [QUICK_START_FRONTEND.md](guides/QUICK_START_FRONTEND.md) | Frontend 빠른 시작 |
| [START_ALL_GUIDE.md](guides/START_ALL_GUIDE.md) | 전체 시스템 실행 가이드 |
| [AI_DB_LOGGING_SETUP.md](guides/AI_DB_LOGGING_SETUP.md) | AI DB 로깅 설정 |

### 운영 / 사용

| 문서 | 설명 |
|---|---|
| [USER_MANUAL.md](guides/USER_MANUAL.md) | 사용자 매뉴얼 |
| [OPERATOR_AWAY_MODE_SETUP.md](guides/OPERATOR_AWAY_MODE_SETUP.md) | 운영자 부재중 모드 설정 |
| [OPERATOR_AWAY_MODE_QUICKSTART.md](guides/OPERATOR_AWAY_MODE_QUICKSTART.md) | 운영자 부재중 모드 빠른 시작 |
| [REALTIME_CONVERSATION.md](guides/REALTIME_CONVERSATION.md) | 실시간 대화 가이드 |
| [RAG_CHROMADB_LLM_TECHNICAL_MANUAL.md](guides/RAG_CHROMADB_LLM_TECHNICAL_MANUAL.md) | RAG/ChromaDB/LLM 기술 매뉴얼 |
| [gemini-model-comparison.md](guides/gemini-model-comparison.md) | Gemini 모델 비교 |

### 디버깅 / 문제해결

| 문서 | 설명 |
|---|---|
| [TROUBLESHOOTING.md](guides/TROUBLESHOOTING.md) | 문제 해결 가이드 |
| [DEBUGGING.md](guides/DEBUGGING.md) | 디버깅 가이드 |
| [DEBUG-CHEATSHEET.md](guides/DEBUG-CHEATSHEET.md) | 디버그 치트시트 |
| [APP_LOG_STARTUP_ERRORS.md](guides/APP_LOG_STARTUP_ERRORS.md) | 앱 로그 시작 에러 |
| [APP_LOG_ERRORS_364_425.md](guides/APP_LOG_ERRORS_364_425.md) | 앱 로그 에러 분석 |
| [TTS_NO_AUDIO_FIX.md](guides/TTS_NO_AUDIO_FIX.md) | TTS 무음 수정 |
| [TTS_RTP_AFTER_ACK_FIX.md](guides/TTS_RTP_AFTER_ACK_FIX.md) | TTS RTP ACK 후 수정 |
| [MIGRATION_KNOWLEDGE_METADATA.md](guides/MIGRATION_KNOWLEDGE_METADATA.md) | 지식 메타데이터 마이그레이션 |

---

## 리포트 (docs/reports/)

월별 분석·점검·수정 리포트. 파일명 형식: `YYYY-MM-DD_HHmm_주제.md`

| 폴더 | 내용 |
|---|---|
| [reports/2026-03/](reports/2026-03/) | 2026년 3월: RTP 오디오 품질 개선, AI 응답 시간 최적화, 호 전환 버그 수정 등 |

---

## 디렉토리 구조

```
docs/
├── INDEX.md                    ← 이 파일 (문서 인덱스)
├── SYSTEM_OVERVIEW.md          ← 시스템 전체 개요 (소개자료)
├── QUICK_START.md              ← 빠른 시작 가이드
├── design/                     ← 설계서 (~46개)
│   ├── AI_VOICEBOT_ARCHITECTURE.md
│   ├── FRONTEND_ARCHITECTURE.md
│   ├── INTENT_HANDLING_DESIGN.md
│   ├── TTS_RTP_AND_STT_QUEUE_DESIGN.md
│   ├── CHROMADB_CATEGORY_DESIGN.md
│   ├── HITL_OPERATOR_RESPONSE_FLOW.md
│   └── ...
├── guides/                     ← 가이드 (~22개)
│   ├── TROUBLESHOOTING.md
│   ├── USER_MANUAL.md
│   ├── google-api-setup.md
│   └── ...
└── reports/                    ← 월별 리포트
    └── 2026-03/                ← 2026년 3월 (~50+개)
```
