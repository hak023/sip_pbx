# 📚 Documentation Quick Reference

## 어떤 문서를 읽어야 할까요?

### 🚀 처음 시작하시나요?
➡️ **[docs/QUICK_START.md](docs/QUICK_START.md)** - 5분 안에 시스템 실행하기

### 📋 전체 문서 목록이 필요하신가요?
➡️ **[docs/INDEX.md](docs/INDEX.md)** - 22개 문서의 체계적인 인덱스 ⭐

### 🏗️ 시스템 아키텍처를 이해하고 싶으신가요?
➡️ **[docs/SYSTEM_OVERVIEW.md](docs/SYSTEM_OVERVIEW.md)** - 전체 시스템 개요  
➡️ **[docs/ai-voicebot-architecture.md](docs/ai-voicebot-architecture.md)** - AI Voicebot 설계  
➡️ **[docs/frontend-architecture.md](docs/frontend-architecture.md)** - Frontend 설계

### 🔧 문제가 발생했나요?
➡️ **[docs/guides/TROUBLESHOOTING.md](docs/guides/TROUBLESHOOTING.md)** - 일반적인 10가지 문제 해결  
➡️ **[RESOLVED_START_ALL_ISSUES.md](RESOLVED_START_ALL_ISSUES.md)** - start-all.ps1 실행 문제  
➡️ **[START_ALL_GUIDE.md](START_ALL_GUIDE.md)** - 통합 실행 가이드

### 👨‍💼 운영자/사용자이신가요?
➡️ **[docs/guides/USER_MANUAL.md](docs/guides/USER_MANUAL.md)** - 사용자 매뉴얼  
➡️ **[docs/guides/OPERATOR_AWAY_MODE_QUICKSTART.md](docs/guides/OPERATOR_AWAY_MODE_QUICKSTART.md)** - 부재중 모드

### 👨‍💻 개발자이신가요?
➡️ **[docs/design/ai-implementation-guide.md](docs/design/ai-implementation-guide.md)** - 구현 가이드  
➡️ **[docs/guides/DEBUGGING.md](docs/guides/DEBUGGING.md)** - 디버깅 가이드

### ⚙️ Google API 설정이 필요하신가요?
➡️ **[docs/guides/google-api-setup.md](docs/guides/google-api-setup.md)** - Google Cloud API 설정  
➡️ **[HOW_TO_SET_API_KEY.md](HOW_TO_SET_API_KEY.md)** - API 키 설정 방법

---

## 📁 문서 구조

```
docs/
├── 📌 핵심 문서 (5개) ⭐
│   ├── INDEX.md                     - 문서 인덱스 ⭐
│   ├── QUICK_START.md              - 빠른 시작 ⭐
│   ├── SYSTEM_OVERVIEW.md          - 시스템 개요 ⭐
│   ├── ai-voicebot-architecture.md  - AI 아키텍처 ⭐
│   └── frontend-architecture.md     - Frontend 아키텍처 ⭐
│
├── 📂 guides/ (10개) - 설정 및 사용 가이드
│   ├── AI_QUICKSTART.md
│   ├── QUICK_START_FRONTEND.md
│   ├── USER_MANUAL.md               - 사용자 매뉴얼
│   ├── TROUBLESHOOTING.md           - 문제 해결
│   ├── DEBUGGING.md                 - 디버깅
│   ├── google-api-setup.md
│   ├── OPERATOR_AWAY_MODE_SETUP.md
│   ├── OPERATOR_AWAY_MODE_QUICKSTART.md
│   └── gemini-model-comparison.md
│
├── 📂 design/ (3개) - 상세 설계
│   ├── ai-implementation-guide.md
│   ├── ai-implementation-guide-part2.md
│   └── OPERATOR-AWAY-MODE-DESIGN.md
│
├── 📂 analysis/ (1개) - 성능 분석
│   └── ai-response-time-analysis.md
│
└── 📂 reports/ (5개) - 완료 보고서
    ├── B2BUA_STATUS.md              - B2BUA 구현 상태
    ├── IMPLEMENTATION_STATUS.md
    ├── AI-COMPLETION-CHECKLIST.md
    ├── WEEK2_COMPLETION_REPORT.md
    └── AI-DEVELOPMENT.md
```

---

## 🎯 상황별 추천 문서

| 상황 | 추천 문서 |
|------|----------|
| 💻 **처음 설치** | QUICK_START.md → SYSTEM_OVERVIEW.md |
| 🤖 **AI 기능 테스트** | guides/AI_QUICKSTART.md → guides/google-api-setup.md |
| 🖥️ **Frontend 실행** | guides/QUICK_START_FRONTEND.md |
| ❌ **설치 오류** | guides/TROUBLESHOOTING.md → RESOLVED_START_ALL_ISSUES.md |
| 👨‍💼 **운영자 기능** | guides/USER_MANUAL.md → guides/OPERATOR_AWAY_MODE_QUICKSTART.md |
| 🏗️ **시스템 이해** | SYSTEM_OVERVIEW.md → ai-voicebot-architecture.md |
| 🔧 **개발/디버깅** | design/ai-implementation-guide.md → guides/DEBUGGING.md |
| 📊 **성능 분석** | analysis/ai-response-time-analysis.md |

---

**전체 문서 인덱스**: [docs/INDEX.md](docs/INDEX.md)  
**최종 업데이트**: 2026-01-06

