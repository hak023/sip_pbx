# SmartPBX AI

**Active RAG 기반 지능형 통화 응대 시스템**

[![Documentation](https://img.shields.io/badge/docs-7%20documents-blue)](bmad/docs/)
[![Status](https://img.shields.io/badge/status-development-yellow)]()

---

## 📖 프로젝트 개요

SmartPBX AI는 기존 SIP PBX에 **Active RAG**(Real-time Augmented Generation)와 **HITL**(Human-In-The-Loop) 시스템을 결합하여, 통화 이력을 자동으로 학습하고 운영자 피드백을 통해 지속적으로 개선되는 지능형 통화 응대 시스템입니다.

### 핵심 특징

- 🤖 **제로 구축비용 지식 관리**: 통화 데이터를 자동으로 벡터DB화하여 지식 자산 구축
- 🎯 **유연한 AI-ARS**: 고정된 Tree 구조 대신 자연어 기반 동적 응대
- 📈 **한계 비용 감소 곡선**: 시간이 지날수록 AI 정확도 상승, 운영 비용 하락

---

## 📚 Documentation

본 프로젝트의 상세 문서는 `bmad/docs/` 디렉토리에 있습니다. 아래 문서들을 참고하여 프로젝트의 전체 구조와 요구사항을 파악할 수 있습니다.

### 📋 Planning & Requirements

| 문서 | 설명 | 페이지 수 |
|------|------|-----------|
| **[Project Plan - AI PBX](bmad/docs/project-plan-ai-pbx.md)** | 시장 조사, 문제 정의, 솔루션 제안, 재무 계획 및 실행 계획을 포함한 종합 프로젝트 계획서 | ~35 pages |
| **[PRD - Detailed Phase 1-4](bmad/docs/prd-detailed-phase1-4.md)** | Phase 1-4의 상세 기능 요구사항과 User Story 정의. Active RAG, AI-ARS, HITL, Agentic AI 기능 명세 | ~60 pages |

### 🏗️ Architecture & Design

| 문서 | 설명 | 페이지 수 |
|------|------|-----------|
| **[Technical Architecture](bmad/docs/technical-architecture.md)** | 시스템 아키텍처, 컴포넌트 설계, 데이터 아키텍처, 배포 전략, 보안 및 성능 최적화 가이드 | ~85 pages |
| **[Frontend Architecture](bmad/docs/frontend-architecture.md)** | React 기반 운영자 & 상담원 대시보드 설계. 컴포넌트 구조, 상태 관리, WebSocket 통합, UI/UX 디자인 시스템 | ~70 pages |
| **[API Specification](bmad/docs/api-specification.md)** | OpenAPI 3.0 기반 완전한 API 참조 문서. REST API 및 WebSocket 엔드포인트, 인증, 요청/응답 스키마 | ~45 pages |

### 🧪 Development & Testing

| 문서 | 설명 | 페이지 수 |
|------|------|-----------|
| **[Backend Testing Strategy](bmad/docs/backend-testing-strategy.md)** | Python 백엔드용 포괄적인 테스트 프레임워크. Unit, Integration, API, WebSocket, AI/LLM 테스트 전략 및 CI/CD 통합 | ~55 pages |

### 👥 User Experience

| 문서 | 설명 | 페이지 수 |
|------|------|-----------|
| **[User Flow](bmad/docs/user-flow.md)** | 사용자 페르소나, End Customer/Operator/Agent/Admin 플로우, 주요 사용자 여정 및 에러 케이스 처리 | ~20 pages |

---

## 📊 문서 요약

| 카테고리 | 문서 수 | 총 페이지 수 |
|----------|---------|--------------|
| **Planning & Requirements** | 2 | ~95 pages |
| **Architecture & Design** | 3 | ~200 pages |
| **Development & Testing** | 1 | ~55 pages |
| **User Experience** | 1 | ~20 pages |
| **합계** | **7** | **~370 pages** |

---

## 🚀 빠른 시작

### 문서 읽기 순서 추천

1. **신규 팀원**: [Project Plan](bmad/docs/project-plan-ai-pbx.md) → [PRD](bmad/docs/prd-detailed-phase1-4.md) → [Technical Architecture](bmad/docs/technical-architecture.md)
2. **개발자**: [Technical Architecture](bmad/docs/technical-architecture.md) → [API Specification](bmad/docs/api-specification.md) → [Backend Testing Strategy](bmad/docs/backend-testing-strategy.md)
3. **프론트엔드 개발자**: [Frontend Architecture](bmad/docs/frontend-architecture.md) → [User Flow](bmad/docs/user-flow.md) → [API Specification](bmad/docs/api-specification.md)
4. **기획자/PM**: [Project Plan](bmad/docs/project-plan-ai-pbx.md) → [PRD](bmad/docs/prd-detailed-phase1-4.md) → [User Flow](bmad/docs/user-flow.md)

---

## 📁 프로젝트 구조

```
workspace_sippbx/
├── sip-pbx/              # SIP PBX 핵심 구현
│   ├── src/              # 소스 코드
│   ├── config/           # 설정 파일
│   └── tests/            # 테스트 코드
├── bmad/
│   └── docs/             # 📚 프로젝트 문서 (이 디렉토리)
│       ├── project-plan-ai-pbx.md
│       ├── prd-detailed-phase1-4.md
│       ├── technical-architecture.md
│       ├── frontend-architecture.md
│       ├── api-specification.md
│       ├── backend-testing-strategy.md
│       └── user-flow.md
└── README.md             # 이 파일
```

---

## 🔗 관련 링크

- [SIP PBX 구현 가이드](sip-pbx/README.md) - SIP PBX 핵심 기능 구현 문서
- [프로젝트 규칙](.cursorrules) - 프로젝트 특화 코딩 규칙 및 디버깅 가이드

---

## 📝 문서 업데이트

문서는 지속적으로 업데이트됩니다. 최신 버전은 각 문서의 헤더에 표시된 버전 정보를 확인하세요.

**마지막 업데이트**: 2026-02-02

---

## 📧 문의

문서에 대한 질문이나 제안사항이 있으시면 프로젝트 관리자에게 문의해주세요.
