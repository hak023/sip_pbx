# 📚 Documentation Index

## 문서 구조 개요

```
docs/
├── 📌 핵심 문서 (5개) - 메인 레벨 ⭐
├── 📂 guides/ - 설정 및 사용 가이드 (10개)
├── 📂 design/ - 상세 설계 문서 (5개)
├── 📂 analysis/ - 분석 및 성능 (1개)
└── 📂 reports/ - 완료 보고서 & 분석 (25개)
```

---

## 📌 핵심 문서 (메인) - 최상위 5개만!

**시스템의 핵심 아키텍처 및 개요 문서**

| 문서 | 설명 |
|------|------|
| [INDEX.md](INDEX.md) | **📚 문서 인덱스** - 모든 문서의 체계적인 분류 및 링크 ⭐ |
| [QUICK_START.md](QUICK_START.md) | **🚀 5분 빠른 시작** - 전체 시스템 설치 및 실행 가이드 |
| [SYSTEM_OVERVIEW.md](SYSTEM_OVERVIEW.md) | **🌐 시스템 전체 개요** - 아키텍처 맵, 데이터 플로우, 성능 지표 |
| [ai-voicebot-architecture.md](ai-voicebot-architecture.md) | **🤖 AI Voicebot 아키텍처** - STT/TTS/LLM/RAG/HITL 전체 설계 (2,679 lines) |
| [frontend-architecture.md](frontend-architecture.md) | **🖥️ Frontend 아키텍처** - Next.js 기반 Control Center 설계 (2,535 lines) |

---

## 📂 guides/ - 설정 및 사용 가이드

특정 기능 설정 및 사용을 위한 단계별 가이드

### 🚀 빠른 시작 가이드

| 문서 | 설명 |
|------|------|
| [guides/AI_QUICKSTART.md](guides/AI_QUICKSTART.md) | AI Voicebot 기능만 빠르게 시작하기 |
| [guides/QUICK_START_FRONTEND.md](guides/QUICK_START_FRONTEND.md) | Frontend Control Center 시작 가이드 |

### 📖 사용자 가이드

| 문서 | 설명 |
|------|------|
| [guides/USER_MANUAL.md](guides/USER_MANUAL.md) | **사용자 매뉴얼** - 기능별 상세 사용법 |
| [guides/TROUBLESHOOTING.md](guides/TROUBLESHOOTING.md) | **문제 해결** - 10가지 일반적인 문제 및 해결 방법 |
| [guides/DEBUGGING.md](guides/DEBUGGING.md) | **디버깅** - 로그 분석, 성능 프로파일링 |

### ⚙️ 설정 가이드

| 문서 | 설명 |
|------|------|
| [guides/google-api-setup.md](guides/google-api-setup.md) | Google Cloud API 설정 (STT/TTS/Gemini) |
| [guides/OPERATOR_AWAY_MODE_SETUP.md](guides/OPERATOR_AWAY_MODE_SETUP.md) | 운영자 부재중 모드 설정 (DB 마이그레이션 포함) |
| [guides/OPERATOR_AWAY_MODE_QUICKSTART.md](guides/OPERATOR_AWAY_MODE_QUICKSTART.md) | 부재중 모드 빠른 시작 |

### 📊 비교 및 선택

| 문서 | 설명 |
|------|------|
| [guides/gemini-model-comparison.md](guides/gemini-model-comparison.md) | Gemini Flash vs Pro 모델 비교 (성능/비용/품질) |

---

## 📂 design/ - 상세 설계 문서

개발자를 위한 구현 수준의 상세 설계

| 문서 | 설명 |
|------|------|
| [design/ai-implementation-guide.md](design/ai-implementation-guide.md) | AI 컴포넌트 구현 가이드 Part 1 (8개 컴포넌트) |
| [design/ai-implementation-guide-part2.md](design/ai-implementation-guide-part2.md) | AI 컴포넌트 구현 가이드 Part 2 (추가 7개 컴포넌트) |
| [design/OPERATOR-AWAY-MODE-DESIGN.md](design/OPERATOR-AWAY-MODE-DESIGN.md) | 운영자 부재중 모드 상세 설계 (워크플로우/API/DB 스키마) |
| [design/OPERATOR_TAKEOVER_DESIGN.md](design/OPERATOR_TAKEOVER_DESIGN.md) | **상담원 실시간 개입 설계** - AI 통화 중 원클릭 개입 ⭐ |
| [design/TEMPORAL_EXPRESSION_DESIGN.md](design/TEMPORAL_EXPRESSION_DESIGN.md) | **시제 표현 정규화 설계** - 한글 상대적 시간 처리 ⭐ |
| [design/AI_DYNAMIC_CALL_TRANSFER_DESIGN.md](design/AI_DYNAMIC_CALL_TRANSFER_DESIGN.md) | **AI 동적 호 전환 설계** - 지식베이스 기반 자동 호 전환 ⭐ NEW |

---

## 📂 analysis/ - 분석 및 성능

시스템 성능 분석 및 최적화 관련 문서

| 문서 | 설명 |
|------|------|
| [analysis/ai-response-time-analysis.md](analysis/ai-response-time-analysis.md) | AI 응답 시간 상세 분석 (STT→RAG→LLM→TTS 단계별 지연 시간) |

---

## 📂 reports/ - 완료 보고서 & 분석 보고서

개발 진행 상황, 완료 내역 및 에러/성능 분석 보고서

### 📋 완료 보고서 & 체크리스트

| 문서 | 설명 |
|------|------|
| [reports/B2BUA_STATUS.md](reports/B2BUA_STATUS.md) | **B2BUA 구현 상태** - SIP B2BUA 지원 메서드 및 기능 상태 |
| [reports/IMPLEMENTATION_STATUS.md](reports/IMPLEMENTATION_STATUS.md) | Frontend & HITL 구현 상태 추적 |
| [reports/AI-COMPLETION-CHECKLIST.md](reports/AI-COMPLETION-CHECKLIST.md) | AI Voicebot 기능별 완료 체크리스트 |
| [reports/KNOWLEDGE_BASE_ARCHITECTURE_REVIEW.md](reports/KNOWLEDGE_BASE_ARCHITECTURE_REVIEW.md) | **지식베이스 설계 점검** - RAG 기반 테넌트별 지식 관리 검증 ⭐ NEW |
| [reports/WEEK2_COMPLETION_REPORT.md](reports/WEEK2_COMPLETION_REPORT.md) | Week 2 완료 보고서 (실시간 모니터링 & HITL UI) |
| [reports/AI-DEVELOPMENT.md](reports/AI-DEVELOPMENT.md) | AI 개발 관련 메모 및 진행 사항 |

### 🔍 에러 & 성능 분석 보고서

| 문서 | 설명 |
|------|------|
| [reports/GET_VECTOR_DB_IMPORT_FIX.md](reports/GET_VECTOR_DB_IMPORT_FIX.md) | **🔧 get_vector_db Import 에러 수정** - ChromaDB Client 및 Embedder 모듈 생성 ⭐ NEW |
| [reports/RTP_CONNECTION_LOST_ROOT_CAUSE_FINAL.md](reports/RTP_CONNECTION_LOST_ROOT_CAUSE_FINAL.md) | **🔴 RTP Connection Lost 근본 원인** - AI Takeover 시 Callee Transport 문제 완전 해결 ⭐ NEW |
| [reports/APP_LOG_ERROR_FIX_20260311.md](reports/APP_LOG_ERROR_FIX_20260311.md) | **app.log 에러 수정** - rag_processor.py 인덴트 에러, tenants API 404 분석 ⭐ |
| [reports/TENANTS_AUTH_API_IMPLEMENTATION.md](reports/TENANTS_AUTH_API_IMPLEMENTATION.md) | **Frontend 로그인용 Tenants & Auth API 구현 완료** ⭐ |
| [reports/MISSING_API_ENDPOINTS.md](reports/MISSING_API_ENDPOINTS.md) | **누락된 API 엔드포인트 구현** - Metrics, Operator, Follow-ups API ⭐ |
| [reports/AI_ORCHESTRATOR_NULL_ROOT_CAUSE.md](reports/AI_ORCHESTRATOR_NULL_ROOT_CAUSE.md) | **🔴 AI Orchestrator NULL 근본 원인** - CallManager 생성 시 파라미터 누락 ⭐ |
| [reports/THREE_ISSUES_COMPREHENSIVE_ANALYSIS.md](reports/THREE_ISSUES_COMPREHENSIVE_ANALYSIS.md) | **🔴 세 가지 재발 문제 완전 분석** - NULL 바이트, Deprecation, AI 타이밍 ⭐ NEW |
| [reports/GIANT_WHITESPACE_LOG_BUG.md](reports/GIANT_WHITESPACE_LOG_BUG.md) | **700KB NULL 바이트 로그 버그 분석** - 버퍼 초기화 실패 ⭐ |
| [reports/RTP_RELAY_INVALID_REMOTE_ANALYSIS.md](reports/RTP_RELAY_INVALID_REMOTE_ANALYSIS.md) | **RTP Relay Invalid Remote 경고 분석** - AI Orchestrator 연결 문제 ⭐ |
| [reports/RECURRING_ISSUES_COMPREHENSIVE_FIX.md](reports/RECURRING_ISSUES_COMPREHENSIVE_FIX.md) | **🔴 재발 문제 종합 분석** - Active API/RTP/NULL 로깅 통합 해결 방안 ⭐ |
| [reports/ROOT_CAUSE_FINAL_FIX.md](reports/ROOT_CAUSE_FINAL_FIX.md) | **🎯 근본 원인 완전 분석** - AI Orchestrator global 키워드 / loguru 충돌 ⭐ NEW |
| [reports/ERROR_LOG_ANALYSIS.md](reports/ERROR_LOG_ANALYSIS.md) | **에러 로그 점검** - AI Orchestrator & RTP Relay 이슈 분석 |
| [reports/LOG_REVIEW_ACTION_ITEMS.md](reports/LOG_REVIEW_ACTION_ITEMS.md) | 로그 검토 액션 아이템 |
| [reports/AUDIO_SEND_ERROR_FIX.md](reports/AUDIO_SEND_ERROR_FIX.md) | 오디오 전송 에러 수정 보고서 |
| [reports/APP_LOG_AI_CALL_ANALYSIS.md](reports/APP_LOG_AI_CALL_ANALYSIS.md) | AI 통화 로그 분석 (TTS/STT/RTP 이슈) |
| [reports/STT_PIPELINE_DEBUG.md](reports/STT_PIPELINE_DEBUG.md) | STT 파이프라인 디버깅 보고서 |
| [reports/RTP_AUDIO_ISSUES_REPORT.md](reports/RTP_AUDIO_ISSUES_REPORT.md) | RTP 오디오 이슈 분석 |

### 🚀 구현 완료 보고서

| 문서 | 설명 |
|------|------|
| [reports/AI_DYNAMIC_CALL_TRANSFER_FINAL_IMPLEMENTATION.md](reports/AI_DYNAMIC_CALL_TRANSFER_FINAL_IMPLEMENTATION.md) | **AI 동적 호 전환 최종 구현** - Phase 1-6 완전 구현 (TransferManager 활용) ⭐ NEW |
| [reports/AI_DYNAMIC_CALL_TRANSFER_IMPLEMENTATION_PHASE6.md](reports/AI_DYNAMIC_CALL_TRANSFER_IMPLEMENTATION_PHASE6.md) | **AI 동적 호 전환 Phase 6** - Knowledge Base CRUD Frontend/Backend 구현 |
| [reports/AI_DYNAMIC_CALL_TRANSFER_IMPLEMENTATION_PHASE1-5.md](reports/AI_DYNAMIC_CALL_TRANSFER_IMPLEMENTATION_PHASE1-5.md) | **AI 동적 호 전환 Phase 1-5** - Intent, RAG, Call Manager, WebSocket 구현 |

### 📚 문서 관리

| 문서 | 설명 |
|------|------|
| [reports/DOCUMENTATION_MANAGEMENT_RULES.md](reports/DOCUMENTATION_MANAGEMENT_RULES.md) | **문서 관리 규칙** - 문서 위치, 네이밍, 업데이트 규칙 ⭐ |

---

## 🗂️ 문서 선택 가이드

### 처음 시작하는 경우
1. [QUICK_START.md](QUICK_START.md) - 5분 설치 및 실행
2. [SYSTEM_OVERVIEW.md](SYSTEM_OVERVIEW.md) - 전체 시스템 이해
3. [guides/AI_QUICKSTART.md](guides/AI_QUICKSTART.md) - AI 기능 테스트

### 운영자/사용자
1. [guides/USER_MANUAL.md](guides/USER_MANUAL.md) - 사용법
2. [guides/TROUBLESHOOTING.md](guides/TROUBLESHOOTING.md) - 문제 해결
3. [guides/OPERATOR_AWAY_MODE_QUICKSTART.md](guides/OPERATOR_AWAY_MODE_QUICKSTART.md) - 부재중 모드

### 개발자
1. [ai-voicebot-architecture.md](ai-voicebot-architecture.md) - AI 아키텍처
2. [frontend-architecture.md](frontend-architecture.md) - Frontend 아키텍처
3. [design/ai-implementation-guide.md](design/ai-implementation-guide.md) - 구현 가이드

### 시스템 관리자
1. [guides/google-api-setup.md](guides/google-api-setup.md) - API 설정
2. [guides/DEBUGGING.md](guides/DEBUGGING.md) - 디버깅
3. [analysis/ai-response-time-analysis.md](analysis/ai-response-time-analysis.md) - 성능 분석

---

## 📝 문서 작성 규칙 (.cursorrules 적용)

### 🚨 중요: 문서 위치 규칙

**✅ 반드시 준수**:
- 모든 분석, 에러 점검, 완료 보고서는 `docs/reports/`에 생성
- ❌ **금지**: `logs/` 디렉토리에 `.md` 파일 생성
- ✅ **허용**: `logs/` 디렉토리는 `.log` 파일만

### 새 문서 저장 위치

| 문서 유형 | 저장 위치 | 예시 |
|----------|----------|------|
| **핵심 아키텍처/시스템 개요** | `docs/` | ai-voicebot-architecture.md, SYSTEM_OVERVIEW.md |
| **사용/설정/문제해결 가이드** | `docs/guides/` | USER_MANUAL, TROUBLESHOOTING, API 설정 |
| **상세 설계** | `docs/design/` | 구현 가이드, 워크플로우 설계 |
| **분석/성능** | `docs/analysis/` | 응답 시간, 비용 분석 |
| **완료 보고서/상태** | `docs/reports/` | 구현 상태, 체크리스트, B2BUA 상태 |
| **에러 분석/로그 점검** | `docs/reports/` | ERROR_LOG_ANALYSIS.md (NOT in logs/) |

### 필수 업데이트 대상 문서 (새 기능 추가 시)

**Priority: HIGH** - 반드시 함께 업데이트:
1. `docs/SYSTEM_OVERVIEW.md` - 시스템 전체 개요
   - 새 기능 → Layer 2/3에 추가
   - 새 시나리오 추가
   - 관련 문서 링크 추가

2. `docs/INDEX.md` - 문서 인덱스 (이 파일)
   - 새 문서 링크 추가
   - 문서 개수 업데이트

3. `README.md` - 프로젝트 루트
   - 주요 기능 변경 → Features 섹션 업데이트
   - 새 가이드 → Quick Links 업데이트

**Priority: MEDIUM** - 해당 시:
- `docs/ai-voicebot-architecture.md` (AI 관련 기능 변경 시)
- `docs/frontend-architecture.md` (Frontend 컴포넌트 추가 시)
- 관련 설계 문서에 상호 참조 추가

### 파일명 규칙
- 핵심 문서: `UPPERCASE.md` (예: `QUICK_START.md`)
- 일반 문서: `kebab-case.md` (예: `ai-voicebot-architecture.md`)
- 가이드: `{기능}-setup.md`, `{기능}-quickstart.md`
- 보고서: `{주제}_REPORT.md`, `{기능}_COMPLETE.md`

### 필수 메타데이터 (문서 상단)
```markdown
# 문서 제목

**작성일**: YYYY-MM-DD
**버전**: X.Y
**상태**: 설계 완료 / 구현 중 / 완료
**관련 문서**: 
- [링크1](경로1)
- [링크2](경로2)
```

### 문서 생성 워크플로우 체크리스트
```markdown
## 문서 업데이트 체크리스트

- [ ] `SYSTEM_OVERVIEW.md` - 기능 목록 및 시나리오 추가
- [ ] `INDEX.md` - 새 문서 링크 추가, 문서 개수 업데이트
- [ ] `README.md` - Features 또는 Quick Links 업데이트 (필요시)
- [ ] 관련 아키텍처 문서 업데이트 (해당시)
- [ ] 관련 설계 문서에 상호 참조 추가 (해당시)
```

**참고**: 상세 규칙은 [reports/DOCUMENTATION_MANAGEMENT_RULES.md](reports/DOCUMENTATION_MANAGEMENT_RULES.md) 참조

---

**최종 업데이트**: 2026-03-11  
**문서 개수**: 37개 (핵심 5개 + guides 10개 + design 6개 + analysis 1개 + reports 15개)

