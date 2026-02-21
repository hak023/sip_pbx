# SmartPBX AI - Documentation

**최종 업데이트**: 2026-02-02  
**문서 통합 완료**: bmad/docs → sip-pbx/docs

---

## 📋 문서 구조

```
sip-pbx/docs/
├── README.md (이 문서)
│
├── architecture/          # 아키텍처 문서
│   ├── technical-architecture.md      # 전체 기술 아키텍처 (최신, 상세)
│   ├── ai-voicebot-architecture.md   # AI Voicebot 아키텍처 (기존)
│   └── frontend-architecture.md      # 프론트엔드 아키텍처 (최신)
│
├── product/              # 제품 요구사항 문서
│   ├── prd.md                        # 통합 PRD (SIP PBX Core + AI)
│   ├── prd-detailed-phase1-4.md     # AI 기능 상세 PRD (Phase 1-4)
│   └── project-plan.md              # 프로젝트 계획서
│
├── api/                  # API 문서
│   └── api-specification.md         # OpenAPI 3.0 명세서
│
├── testing/              # 테스트 문서
│   └── backend-testing-strategy.md  # 백엔드 테스트 전략
│
├── ux/                   # UX/사용자 플로우 문서
│   └── user-flow.md                 # 사용자 여정 및 플로우
│
├── guides/               # 설정 및 사용 가이드 (기존 유지)
│   ├── AI_QUICKSTART.md
│   ├── USER_MANUAL.md
│   ├── TROUBLESHOOTING.md
│   └── ...
│
├── reports/              # 완료 보고서 (기존 유지)
│   ├── B2BUA_STATUS.md
│   ├── IMPLEMENTATION_STATUS.md
│   └── ...
│
├── qa/                   # QA 문서 (기존 유지)
│   └── ...
│
├── analysis/             # 분석 문서 (기존 유지)
│   └── ...
│
└── design/               # 설계 문서 (기존 유지)
    └── ...
```

---

## 📚 주요 문서

### 아키텍처 문서

| 문서 | 설명 | 페이지 수 | 상태 |
|------|------|----------|------|
| **[technical-architecture.md](./architecture/technical-architecture.md)** | 전체 기술 아키텍처 (SIP PBX + AI Layer) | ~2,800줄 | ✅ 최신 |
| **[ai-voicebot-architecture.md](./architecture/ai-voicebot-architecture.md)** | AI Voicebot Backend 아키텍처 | ~1,765줄 | ✅ 기존 유지 |
| **[frontend-architecture.md](./architecture/frontend-architecture.md)** | React 기반 운영자 대시보드 | ~2,300줄 | ✅ 최신 |

### 제품 문서

| 문서 | 설명 | 페이지 수 | 상태 |
|------|------|----------|------|
| **[prd.md](./product/prd.md)** | 통합 PRD (SIP PBX Core + AI 기능) | ~300줄 | ✅ 통합 완료 |
| **[prd-detailed-phase1-4.md](./product/prd-detailed-phase1-4.md)** | AI 기능 상세 요구사항 (Phase 1-4) | ~2,000줄 | ✅ 최신 |
| **[project-plan.md](./product/project-plan.md)** | 프로젝트 계획서 (시장 분석, 재무 계획) | ~1,300줄 | ✅ 최신 |

### API 문서

| 문서 | 설명 | 페이지 수 | 상태 |
|------|------|----------|------|
| **[api-specification.md](./api/api-specification.md)** | OpenAPI 3.0 명세서 (REST + WebSocket) | ~1,400줄 | ✅ 최신 |

### 테스트 문서

| 문서 | 설명 | 페이지 수 | 상태 |
|------|------|----------|------|
| **[backend-testing-strategy.md](./testing/backend-testing-strategy.md)** | 백엔드 테스트 전략 (Pytest, Integration, Load) | ~1,700줄 | ✅ 최신 |

### UX 문서

| 문서 | 설명 | 페이지 수 | 상태 |
|------|------|----------|------|
| **[user-flow.md](./ux/user-flow.md)** | 사용자 여정 및 플로우 (고객/운영자/상담원) | ~850줄 | ✅ 최신 |

---

## 🎯 빠른 시작 가이드

### 처음 시작하는 경우
1. **[QUICK_START.md](./QUICK_START.md)** - 5분 설치 및 실행
2. **[SYSTEM_OVERVIEW.md](./SYSTEM_OVERVIEW.md)** - 전체 시스템 이해
3. **[architecture/technical-architecture.md](./architecture/technical-architecture.md)** - 기술 아키텍처 상세

### 개발자
1. **[architecture/technical-architecture.md](./architecture/technical-architecture.md)** - 전체 기술 아키텍처
2. **[architecture/frontend-architecture.md](./architecture/frontend-architecture.md)** - 프론트엔드 아키텍처
3. **[api/api-specification.md](./api/api-specification.md)** - API 명세서
4. **[testing/backend-testing-strategy.md](./testing/backend-testing-strategy.md)** - 테스트 전략

### 제품 관리자
1. **[product/prd.md](./product/prd.md)** - 통합 제품 요구사항
2. **[product/prd-detailed-phase1-4.md](./product/prd-detailed-phase1-4.md)** - AI 기능 상세 요구사항
3. **[product/project-plan.md](./product/project-plan.md)** - 프로젝트 계획서
4. **[ux/user-flow.md](./ux/user-flow.md)** - 사용자 플로우

### 운영자/사용자
1. **[guides/USER_MANUAL.md](./guides/USER_MANUAL.md)** - 사용자 매뉴얼
2. **[guides/TROUBLESHOOTING.md](./guides/TROUBLESHOOTING.md)** - 문제 해결
3. **[guides/OPERATOR_AWAY_MODE_QUICKSTART.md](./guides/OPERATOR_AWAY_MODE_QUICKSTART.md)** - 부재중 모드

---

## 📊 문서 통합 요약

### 통합된 문서

#### Architecture 문서
- ✅ **technical-architecture.md**: `bmad/docs/technical-architecture.md` → `sip-pbx/docs/architecture/` (최신, 상세)
- ✅ **frontend-architecture.md**: `bmad/docs/frontend-architecture.md` → `sip-pbx/docs/architecture/` (최신)
- ✅ **ai-voicebot-architecture.md**: `sip-pbx/docs/ai-voicebot-architecture.md` → `sip-pbx/docs/architecture/` (기존 유지)

#### Product 문서
- ✅ **prd.md**: `bmad/docs/prd.md` + `bmad/docs/prd-detailed-phase1-4.md` 통합 → `sip-pbx/docs/product/prd.md`
- ✅ **prd-detailed-phase1-4.md**: `bmad/docs/prd-detailed-phase1-4.md` → `sip-pbx/docs/product/` (상세 PRD)
- ✅ **project-plan.md**: `bmad/docs/project-plan-ai-pbx.md` → `sip-pbx/docs/product/project-plan.md`

#### API 문서
- ✅ **api-specification.md**: `bmad/docs/api-specification.md` → `sip-pbx/docs/api/` (OpenAPI 3.0)

#### Testing 문서
- ✅ **backend-testing-strategy.md**: `bmad/docs/backend-testing-strategy.md` → `sip-pbx/docs/testing/`

#### UX 문서
- ✅ **user-flow.md**: `bmad/docs/user-flow.md` → `sip-pbx/docs/ux/`

### 제거된 중복 문서
- ❌ `sip-pbx/docs/frontend-architecture.md` (중복, architecture/로 이동)
- ❌ `sip-pbx/docs/ai-voicebot-architecture.md` (중복, architecture/로 이동)

---

## 📁 카테고리별 문서 목록

### Architecture (3개)
- [technical-architecture.md](./architecture/technical-architecture.md) - 전체 기술 아키텍처
- [ai-voicebot-architecture.md](./architecture/ai-voicebot-architecture.md) - AI Voicebot 아키텍처
- [frontend-architecture.md](./architecture/frontend-architecture.md) - 프론트엔드 아키텍처

### Product (3개)
- [prd.md](./product/prd.md) - 통합 PRD
- [prd-detailed-phase1-4.md](./product/prd-detailed-phase1-4.md) - AI 기능 상세 PRD
- [project-plan.md](./product/project-plan.md) - 프로젝트 계획서

### API (1개)
- [api-specification.md](./api/api-specification.md) - API 명세서

### Testing (1개)
- [backend-testing-strategy.md](./testing/backend-testing-strategy.md) - 백엔드 테스트 전략

### UX (1개)
- [user-flow.md](./ux/user-flow.md) - 사용자 플로우

### Guides (10개) - 기존 유지
- [AI_QUICKSTART.md](./guides/AI_QUICKSTART.md)
- [USER_MANUAL.md](./guides/USER_MANUAL.md)
- [TROUBLESHOOTING.md](./guides/TROUBLESHOOTING.md)
- [DEBUGGING.md](./guides/DEBUGGING.md)
- [google-api-setup.md](./guides/google-api-setup.md)
- [OPERATOR_AWAY_MODE_SETUP.md](./guides/OPERATOR_AWAY_MODE_SETUP.md)
- [OPERATOR_AWAY_MODE_QUICKSTART.md](./guides/OPERATOR_AWAY_MODE_QUICKSTART.md)
- [gemini-model-comparison.md](./guides/gemini-model-comparison.md)
- [QUICK_START_FRONTEND.md](./guides/QUICK_START_FRONTEND.md)
- [START_ALL_GUIDE.md](./guides/START_ALL_GUIDE.md)

### Reports (30+개) - 기존 유지
- [B2BUA_STATUS.md](./reports/B2BUA_STATUS.md)
- [IMPLEMENTATION_STATUS.md](./reports/IMPLEMENTATION_STATUS.md)
- [AI-COMPLETION-CHECKLIST.md](./reports/AI-COMPLETION-CHECKLIST.md)
- ... (기타 완료 보고서)

### QA (5개) - 기존 유지
- [test-strategy.md](./qa/test-strategy.md)
- [test-execution-guide.md](./qa/test-execution-guide.md)
- ... (기타 QA 문서)

### Analysis (1개) - 기존 유지
- [ai-response-time-analysis.md](./analysis/ai-response-time-analysis.md)

### Design (4개) - 기존 유지
- [ai-implementation-guide.md](./design/ai-implementation-guide.md)
- [ai-implementation-guide-part2.md](./design/ai-implementation-guide-part2.md)
- [OPERATOR-AWAY-MODE-DESIGN.md](./design/OPERATOR-AWAY-MODE-DESIGN.md)

---

## 🔗 관련 문서 링크

### 핵심 문서
- [INDEX.md](./INDEX.md) - 전체 문서 인덱스
- [QUICK_START.md](./QUICK_START.md) - 빠른 시작 가이드
- [SYSTEM_OVERVIEW.md](./SYSTEM_OVERVIEW.md) - 시스템 개요

### 아키텍처
- [Technical Architecture](./architecture/technical-architecture.md) ⭐ 최신
- [Frontend Architecture](./architecture/frontend-architecture.md) ⭐ 최신
- [AI Voicebot Architecture](./architecture/ai-voicebot-architecture.md)

### 제품
- [PRD (통합)](./product/prd.md) ⭐ 통합 완료
- [PRD Detailed Phase 1-4](./product/prd-detailed-phase1-4.md)
- [Project Plan](./product/project-plan.md)

---

## 📝 문서 작성 가이드

### 새 문서 저장 위치

| 문서 유형 | 저장 위치 | 예시 |
|----------|----------|------|
| **아키텍처** | `docs/architecture/` | technical-architecture.md |
| **제품 요구사항** | `docs/product/` | prd.md, project-plan.md |
| **API 명세** | `docs/api/` | api-specification.md |
| **테스트 전략** | `docs/testing/` | backend-testing-strategy.md |
| **UX/사용자 플로우** | `docs/ux/` | user-flow.md |
| **사용 가이드** | `docs/guides/` | USER_MANUAL.md |
| **완료 보고서** | `docs/reports/` | IMPLEMENTATION_STATUS.md |
| **설계 문서** | `docs/design/` | ai-implementation-guide.md |

### 파일명 규칙
- 핵심 문서: `kebab-case.md` (예: `technical-architecture.md`)
- 가이드: `UPPERCASE.md` 또는 `kebab-case.md` (예: `USER_MANUAL.md`, `google-api-setup.md`)
- 보고서: `UPPERCASE.md` (예: `B2BUA_STATUS.md`)

---

## 📈 문서 통계

### 통합된 문서 (bmad/docs → sip-pbx/docs)
- **총 9개 문서** 통합 완료
- **Architecture**: 3개
- **Product**: 3개
- **API**: 1개
- **Testing**: 1개
- **UX**: 1개

### 문서 크기
- **technical-architecture.md**: ~2,800줄 (최대)
- **prd-detailed-phase1-4.md**: ~2,000줄
- **frontend-architecture.md**: ~2,300줄
- **api-specification.md**: ~1,400줄
- **backend-testing-strategy.md**: ~1,700줄

---

## ✅ 통합 완료 상태

- ✅ 새 폴더 구조 생성 (architecture/, product/, api/, testing/, ux/)
- ✅ bmad/docs/ 문서 복사 및 이동
- ✅ 중복 문서 제거
- ✅ PRD 문서 통합 (prd.md)
- ✅ README.md 업데이트

---

**문서 통합 완료일**: 2026-02-02  
**다음 리뷰**: 2026-02-15
