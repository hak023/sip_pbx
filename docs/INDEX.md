# 📚 Documentation Index

## 문서 구조 개요

```
docs/
├── 📌 핵심 문서 (5개) - 메인 레벨 ⭐
├── 📂 guides/ - 설정 및 사용 가이드 (10개)
├── 📂 design/ - 상세 설계 문서 (3개)
├── 📂 analysis/ - 분석 및 성능 (1개)
└── 📂 reports/ - 완료 보고서 (5개)
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

---

## 📂 analysis/ - 분석 및 성능

시스템 성능 분석 및 최적화 관련 문서

| 문서 | 설명 |
|------|------|
| [analysis/ai-response-time-analysis.md](analysis/ai-response-time-analysis.md) | AI 응답 시간 상세 분석 (STT→RAG→LLM→TTS 단계별 지연 시간) |

---

## 📂 reports/ - 완료 보고서 & 체크리스트

개발 진행 상황 및 완료 내역

| 문서 | 설명 |
|------|------|
| [reports/B2BUA_STATUS.md](reports/B2BUA_STATUS.md) | **B2BUA 구현 상태** - SIP B2BUA 지원 메서드 및 기능 상태 |
| [reports/IMPLEMENTATION_STATUS.md](reports/IMPLEMENTATION_STATUS.md) | Frontend & HITL 구현 상태 추적 |
| [reports/AI-COMPLETION-CHECKLIST.md](reports/AI-COMPLETION-CHECKLIST.md) | AI Voicebot 기능별 완료 체크리스트 |
| [reports/WEEK2_COMPLETION_REPORT.md](reports/WEEK2_COMPLETION_REPORT.md) | Week 2 완료 보고서 (실시간 모니터링 & HITL UI) |
| [reports/AI-DEVELOPMENT.md](reports/AI-DEVELOPMENT.md) | AI 개발 관련 메모 및 진행 사항 |

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

## 📝 문서 작성 규칙 (앞으로)

### 새 문서 저장 위치

| 문서 유형 | 저장 위치 | 예시 |
|----------|----------|------|
| **핵심 아키텍처/시스템 개요** | `docs/` | ai-voicebot-architecture.md, SYSTEM_OVERVIEW.md |
| **사용/설정/문제해결 가이드** | `docs/guides/` | USER_MANUAL, TROUBLESHOOTING, API 설정 |
| **상세 설계** | `docs/design/` | 구현 가이드, 워크플로우 설계 |
| **분석/성능** | `docs/analysis/` | 응답 시간, 비용 분석 |
| **완료 보고서/상태** | `docs/reports/` | 구현 상태, 체크리스트, B2BUA 상태 |

### 파일명 규칙
- 핵심 문서: `UPPERCASE.md` (예: `QUICK_START.md`)
- 일반 문서: `kebab-case.md` (예: `ai-voicebot-architecture.md`)
- 가이드: `{기능}-setup.md`, `{기능}-quickstart.md`
- 보고서: `{주제}-status.md`, `{주제}-report.md`

---

**최종 업데이트**: 2026-01-06  
**문서 개수**: 24개 (핵심 5개 + guides 10개 + design 3개 + analysis 1개 + reports 5개)

