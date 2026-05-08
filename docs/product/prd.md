# SmartPBX AI - Product Requirements Document (PRD)
## 통합 PRD: SIP PBX Core + AI 기능

**문서 버전**: v2.2  
**작성일**: 2026-02-02  
**최종 갱신**: 2026-05-08  
**작성자**: Product Team  
**상태**: Current (AI 범위는 [구현 스냅샷](#ai-기능-구현-스냅샷-2026-05) 기준)

---

## 📋 목차

1. [문서 개요](#문서-개요)
2. [SIP PBX Core 요구사항](#sip-pbx-core-요구사항)
3. [AI 기능 요구사항 (Phase 1-4)](#ai-기능-요구사항-phase-1-4)
4. [Cross-cutting Concerns](#cross-cutting-concerns)
5. [Success Metrics](#success-metrics)

---

## 문서 개요

### 목적
본 문서는 SmartPBX AI의 전체 제품 요구사항을 정의합니다:
- **Part 1**: SIP PBX Core 기능 (구현 완료)
- **Part 2**: AI 기능 (Phase 1-4) — **세부·검수는** [prd-detailed-phase1-4.md](./prd-detailed-phase1-4.md), **구현 수준은** 아래 스냅샷·[docs/reports/README.md](../reports/README.md)를 병행한다.

### AI 기능 구현 스냅샷 (2026-05)

단일 리포지토리 기준 요약이다. 상용 타깃 배포·외부 코어 연동은 [production-deployment-architecture.md](../architecture/production-deployment-architecture.md)와 별개 과제다.

| Phase | 계획 요약 | 구현 상태 (개략) |
|-------|-----------|------------------|
| **Phase 1** | Active RAG, 실시간 STT/TTS, 지식 적재, 부재중 AI 응대 | **대부분 구현**. 근거 예: `reports/2026-01/`의 VectorDB·Phase3·지식 UI 관련 리포트 |
| **Phase 2** | Dynamic ARS·Intent 기반 대화 | **부분 구현** — Intent·오케스트레이션 경로는 코드·설계 문서와 함께 지속 확장 |
| **Phase 3** | HITL·운영자 개입·품질 고도화 | **구현됨** — HITL·부재중 모드·통화이력 연계 등 (예: `reports/2026-03/` HITL·대시보드 다수) |
| **Phase 4** | Agentic·멀티 에이전트 | **부분·실험적** — 도구 호출·에이전트 범위는 제품 로드맵에 따라 확대 |

**데이터 저장소 표기**: 코드 경로에서는 Vector DB로 **ChromaDB** 등을 사용할 수 있다. PRD 본문의 Qdrant/Pinecone 표기는 **상용 확장 옵션**이며, 타깻 스택은 배포 설계서와 정렬한다.

### 문서 통합 이력
- **v2.2** (2026-05-08): AI Phase 구현 스냅샷·관련 문서 링크 반영 (리포트·상용 배포 문서와 정합)
- **v2.1** (2026-02-02): SIP PBX Core PRD와 AI PRD 통합
- **v2.0** (2026-01-30): Phase 1-4 상세 요구사항 작성
- **v1.1** (2025-01-05): 기본 SIP PBX PRD (AI 기능 제거)
- **v1.0** (2025-10-27): 초기 PRD 생성

---

## SIP PBX Core 요구사항

### Goals and Background Context

#### Goals
- **SIP B2BUA 구현**: 표준 SIP B2BUA로 동작하는 통화 제어 시스템
- **효율적인 미디어 처리**: RTP bypass 모드를 통한 저지연 미디어 relay
- **확장 가능한 포트 풀 관리**: 동시 다중 호 처리를 위한 효율적인 미디어 포트 리소스 관리
- **표준 SIP 프로토콜 준수**: 기본 SIP 메서드 및 REGISTER 지원으로 기존 인프라와 통합
- **관찰성**: 메트릭, 로깅, CDR을 통한 시스템 모니터링

#### Background Context
SIP(Session Initiation Protocol)는 VoIP 통신의 표준 프로토콜입니다. 본 프로젝트는 B2BUA(Back-to-Back User Agent) 아키텍처를 채택하여 SIP 시그널링과 미디어 스트림 모두를 제어할 수 있는 PBX를 구축합니다.

B2BUA는 두 개의 독립적인 SIP leg을 생성하여 각각을 완전히 제어할 수 있으며, 이를 통해 유연한 통화 제어와 미디어 처리가 가능합니다.

### Functional Requirements

**Core SIP B2BUA 기능**

- **FR1**: 시스템은 B2BUA(Back-to-Back User Agent)로 동작하여 양쪽 SIP leg을 독립적으로 제어해야 함
- **FR2**: 기본 SIP 메서드 지원: INVITE, UPDATE, BYE, ACK, PRACK
- **FR3**: REGISTER 요청에 대해 항상 200 OK 응답 (인증 없이 모든 등록 허용)
- **FR4**: SIP 트랜잭션 관리: INVITE/non-INVITE 트랜잭션 타이머 및 재전송 처리
- **FR5**: Call-ID 매핑 및 추적: 양쪽 leg의 Call-ID를 매핑하여 세션 추적
- **FR6**: OPTIONS 메서드 지원: Keep-alive 및 endpoint 헬스 체크
- **FR7**: CANCEL 메서드 지원: 진행 중인 INVITE 요청 취소

**미디어 처리 및 포트 관리**

- **FR8**: Bypass 모드: SDP의 미디어 IP/Port만 변경하고 코덱 및 속성은 그대로 전달
- **FR9**: 미디어 포트 풀 관리: 동적 포트 할당 및 반환 메커니즘
- **FR10**: 호당 포트 할당: 각 통화당 양쪽 방향 각 4개씩 총 8개 포트 할당 (RTP/RTCP 각 방향 2개씩)
- **FR11**: 포트 풀 설정: 시작/종료 포트 범위를 설정 파일로 구성
- **FR12**: 포트 고갈 처리: 사용 가능한 포트가 없을 경우 적절한 SIP 오류 응답 (503 Service Unavailable)
- **FR13**: 코덱 디코딩 지원: 최소한 G.711 (A-law/μ-law), Opus 지원

**알림 및 이벤트**

- **FR14**: 통화 이벤트 생성: 통화 시작, 종료 시 이벤트 발생
- **FR15**: 통화 메타데이터: 각 이벤트에 Call-ID, 타임스탬프, 참여자 정보 포함
- **FR16**: Webhook 지원: 외부 시스템으로 이벤트 전송 (HTTP POST)
- **FR17**: 이벤트 로깅: 모든 이벤트를 구조화된 로그로 저장

**설정 및 관리**

- **FR18**: 설정 파일 기반 구성: YAML 포맷 설정 파일
- **FR19**: 포트 풀 설정: 미디어 포트 범위, 최대 동시 호 수 설정
- **FR20**: 로깅 수준 설정: DEBUG, INFO, WARNING, ERROR 레벨 선택

**모니터링 및 통계**

- **FR21**: 활성 세션 모니터링: 현재 진행 중인 통화 수 및 상태
- **FR22**: 포트 사용률: 할당된 포트 수 / 전체 포트 풀
- **FR23**: CDR (Call Detail Record): 각 통화의 시작/종료 시간, 길이

### Non-Functional Requirements

**성능**
- **NFR1**: 동시 호 용량: 최소 100개 동시 통화 지원
- **NFR2**: SIP 응답 시간: INVITE 요청 수신 후 100ms 이내 1xx 응답 전송
- **NFR3**: 미디어 지연: Bypass 모드에서 추가 미디어 지연 5ms 이하
- **NFR4**: 메모리 사용: 통화당 최대 10MB 메모리 사용

**확장성**
- **NFR5**: 수평 확장: 여러 인스턴스 배포 시 로드 밸런서 지원
- **NFR6**: 포트 풀 확장: 설정 변경만으로 포트 범위 확장 가능

**신뢰성**
- **NFR7**: 고가용성: 단일 인스턴스 장애 시 기존 호 최소 영향 (graceful shutdown)
- **NFR8**: 리소스 보호: 포트 고갈, 메모리 부족 시 새 호 거부 및 기존 호 유지
- **NFR9**: 로그 무결성: 모든 중요 이벤트 및 오류를 손실 없이 기록

**보안**
- **NFR10**: 접근 제어: 관리 API에 대한 인증 및 권한 관리
- **NFR11**: Rate Limiting: 단일 IP에서 초당 최대 10 INVITE 제한 (DoS 방어)
- **NFR12**: 입력 검증: 모든 SIP 메시지 파싱 시 malformed 메시지 필터링

**운영성**
- **NFR13**: 컨테이너 배포: Docker 이미지 제공 및 Kubernetes 지원
- **NFR14**: 헬스체크: HTTP /health endpoint로 liveness/readiness 체크
- **NFR15**: 메트릭 노출: Prometheus 호환 메트릭 endpoint (/metrics)
- **NFR16**: 로그 포맷: JSON structured logging으로 중앙 로그 수집 용이

**개발 및 테스트**
- **NFR17**: 코드 커버리지: 단위 테스트 커버리지 80% 이상
- **NFR18**: 통합 테스트: SIP 시나리오 기반 자동화 테스트
- **NFR19**: 성능 테스트: 목표 동시 호 수에 대한 부하 테스트 통과
- **NFR20**: 문서화: API, 설정, 배포 가이드 문서 제공

### Technical Assumptions

#### Language and Framework
- **언어**: Python 3.11+
- **비동기 처리**: asyncio 기반
- **HTTP 프레임워크**: aiohttp

#### Architecture
- **스타일**: 모듈러 모놀리스
- **리포지토리**: Monorepo
- **배포**: 컨테이너화 (Docker), Kubernetes StatefulSet

#### Infrastructure
- **OS**: Linux (Ubuntu 20.04+) 또는 Windows
- **메모리**: 최소 2GB, 권장 4GB
- **디스크**: 최소 1GB
- **네트워크**: UDP 5060 (SIP), UDP 10000-20000 (RTP), TCP 8080 (HTTP), TCP 9090 (Prometheus)

#### Third-party Services
- **모니터링**: Prometheus
- **로깅**: structlog
- **설정**: YAML

### SIP PBX Implementation Status

#### Phase 1: Core SIP B2BUA (✅ 완료)
- SIP 서버 기본 구조
- INVITE/BYE 처리
- REGISTER 지원
- 기본 포트 풀

#### Phase 2: 미디어 처리 (✅ 완료)
- RTP Relay
- SDP 파싱 및 조작
- 코덱 지원

#### Phase 3: 관찰성 (✅ 완료)
- Prometheus 메트릭
- CDR 생성
- Structured logging

#### Phase 4: 안정화 (🔄 지속)
- 에러 처리·성능·문서 및 회귀 테스트 (종료 일정 없음 — 운영 피드백 반영)

---

## AI 기능 요구사항 (Phase 1-4)

> **참고**: 상세한 AI 기능 요구사항은 [prd-detailed-phase1-4.md](./prd-detailed-phase1-4.md) 문서를 참조하세요.

### Phase 1: Active RAG 기반 지식 자동 구축

**핵심 기능**:
- 통화 Transcript 실시간 생성 (STT + Diarization)
- Transcript → Knowledge Extraction (Q&A 쌍 자동 추출)
- Vector Database 저장 (런타임: ChromaDB 등 / 상용 목표 스택은 [production-deployment-architecture.md](../architecture/production-deployment-architecture.md) 참고)
- RAG Retrieval 엔진
- **AI 응대 모드 (AI Attendant Mode)**: 착신자 부재중 시 AI 자동 응답

**목표**: 제로 구축비용으로 지식 베이스 자동 구축, 부재중 시 AI 자동 응대

### Phase 2: AI 기반 Dynamic ARS

**핵심 기능**:
- Natural Language IVR (고정 ARS Tree 구조 탈피)
- Intent Classification
- Context-aware Dialog Management
- Tool Calling Integration (CRM/ERP API)

**목표**: 비개발자도 ARS Flow 수정 가능, 유연한 대화형 응대

### Phase 3: HITL + Shadowing Mode

**핵심 기능**:
- Confidence Monitoring (AI 답변 신뢰도 실시간 계산)
- Real-time Operator Intervention (통화 중 피드백)
- Post-call Review & Labeling
- Shadowing Mode (신입 상담원 실시간 가이드)

**목표**: AI 품질 지속적 개선, 운영자 개입률 30% → 5% 감소

### Phase 4: Agentic AI + Multi-Agent

**핵심 기능**:
- Tool-calling Agent (자율적 시스템 조작)
- Multi-Agent Collaboration (복잡한 요청 해결)

**목표**: 완전 자동화 가능한 업무 80%까지 확대

---

## Cross-cutting Concerns

### 성능 (Performance)

| Metric | Target | Measurement Method |
|--------|--------|-------------------|
| STT Latency | <500ms | RTP packet → Text 시간 |
| RAG Retrieval | <100ms | Query → Top-K results |
| LLM Response | <1s | Query → Generated response |
| End-to-End | <2s | 고객 질문 → AI 답변 (TTS 포함) |
| Throughput | 100 concurrent calls | Load test |
| Uptime | 99.9% | Prometheus monitoring |

### 보안 (Security)

| Requirement | Implementation |
|-------------|----------------|
| 통화 데이터 암호화 | AES-256 at rest, TLS 1.3 in transit |
| PII 마스킹 | 이름, 전화번호, 주소 자동 마스킹 |
| 접근 제어 | RBAC (Role-Based Access Control) |
| Audit Log | 모든 Tool 실행, Operator 개입 기록 |
| GDPR 준수 | Right to be forgotten (데이터 삭제 요청) |

### 확장성 (Scalability)

| Component | Scaling Strategy |
|-----------|------------------|
| SIP PBX | Horizontal (K8s StatefulSet, replicas: 3+) |
| Vector DB | Sharding by date (월별 분리) |
| LLM | Rate limiting + Caching (Redis) |
| WebSocket | Load balancer (sticky sessions) |
| Storage | S3 for recordings, RDS for metadata |

---

## Success Metrics

### 기술 메트릭

**SIP PBX Core**:
- 100개 동시 통화 처리 성공률 > 99%
- SIP 응답 시간 < 100ms
- RTP relay 지연 < 5ms
- 메모리 사용량 < 4GB (100개 동시 통화)
- CPU 사용률 < 70% (100개 동시 통화)

**AI 기능**:
- AI Accuracy: 85%+ (RAG Retrieval Score)
- AI Resolution Rate: 70%+ (운영자 연결 없이 해결된 비율)
- Average Latency: <2초 (고객 질문 → AI 답변 시간)
- CSAT: 4.2/5 (통화 후 만족도 조사)
- Knowledge Base Size: 5,000+ items (VectorDB에 저장된 지식 수)
- **AI 응대 모드 활성화율**: 80%+ (부재중 통화 중 AI 응대 성공률)
- **AI 응대 모드 평균 응답 시간**: <1초 (타이머 타임아웃 또는 부재중 설정 후)
- **AI 응대 모드 CSAT**: 4.0/5 (AI 응대 통화 만족도)

### 운영 메트릭

- 시스템 가동률 (Uptime) > 99.9%
- 평균 통화 설정 시간 < 1초
- CDR 생성 성공률 100%
- Webhook 전달 성공률 > 95%
- HITL Intervention Rate: <10% (3개월 후)

### 비즈니스 메트릭

- ARR: $420K (Year 1 목표)
- Customers: 175개 (Year 1 목표)
- MRR Growth: 15%+ (Month-over-Month)
- Churn Rate: <5%/월
- CAC Payback: <12개월

---

## Out of Scope

다음 기능들은 현재 버전의 범위를 벗어납니다:

- SIP TLS/SRTP 암호화 (Phase 5+)
- SIP 인증 (Digest Authentication) (Phase 5+)
- 실시간 통화 품질 모니터링 (MOS 점수 등) (Phase 5+)
- Omnichannel 지원 (전화 + 채팅 + 이메일) (Phase 5+)

---

## Risks and Mitigation

| 위험 | 영향 | 완화 방안 |
|------|------|-----------|
| 포트 고갈 | 높음 | 포트 풀 크기 모니터링, 동적 확장 |
| 메모리 누수 | 중간 | 정기적인 메모리 프로파일링, 세션 타임아웃 |
| SIP 호환성 | 중간 | 다양한 SIP 클라이언트로 테스트 |
| AI 정확도 목표 미달 | 높음 | 단계적 출시, Confidence Threshold 설정, HITL 활용 |
| 네트워크 지연 | 낮음 | 저지연 알고리즘, 성능 테스트 |

---

## Stakeholders

- **개발팀**: 시스템 구현 및 유지보수
- **운영팀**: 배포 및 모니터링
- **QA팀**: 테스트 및 품질 보증
- **Product Team**: 요구사항 정의 및 우선순위 관리

---

## 관련 문서

- **[Technical Architecture](../architecture/technical-architecture.md)**: 전체 기술 아키텍처 (구현체 기준)
- **[Production Deployment](../architecture/production-deployment-architecture.md)**: 상용 통합·용량·비용
- **[Frontend Architecture](../architecture/frontend-architecture.md)**: 프론트엔드 아키텍처
- **[API Specification](../api/api-specification.md)**: API 명세서
- **[PRD Detailed Phase 1-4](./prd-detailed-phase1-4.md)**: AI 기능 상세 요구사항
- **[Project Plan](./project-plan.md)**: 프로젝트 계획서
- **[Reports index](../reports/README.md)**: 월별 구현·분석 리포트 요약

---

**문서 완료일**: 2026-02-02  
**최종 갱신**: 2026-05-08
