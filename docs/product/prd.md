# SmartPBX AI - Product Requirements Document (PRD)
## 통합 PRD: SIP PBX Core + AI 기능

**문서 버전**: v3.4  
**작성일**: 2026-02-02  
**최종 갱신**: 2026-05-11  
**작성자**: Product Team  
**상태**: Current (AI 범위는 [구현 스냅샷](#ai-기능-구현-스냅샷-2026-05) 기준)

---

## 📋 목차

1. [문서 개요](#문서-개요)
2. [SIP PBX Core 요구사항](#sip-pbx-core-요구사항)
3. [AI 기능 요구사항 (Phase 1-4)](#ai-기능-요구사항-phase-1-4)
4. [Cross-cutting Concerns](#cross-cutting-concerns)
5. [Success Metrics](#success-metrics)
6. [사업 맥락 및 프로젝트 계획 (요약)](#사업-맥락-및-프로젝트-계획-요약)
7. [개발 공수 (MM)](#개발-공수-mm)

---

## 문서 개요

### 목적 · 문서 구조 (통합 PRD)

본 저장소의 제품 요구는 **두 개의 마크다운 파일**로 나뉜다.

| 파일 | 역할 |
|------|------|
| **본 문서 (`prd.md`)** | **마스터 PRD**: SIP Core + AI Phase 개요, Cross-cutting, 지표, **사업·프로젝트 요약**, **AI Call Agent MM(서버 역할·Epic Phase, 합계 동일 65.0)** |
| **[prd-detailed-phase1-4.md](./prd-detailed-phase1-4.md)** | **부록 — 상세 요구사항**: Phase 1~4 **FR·User Story·Acceptance** (검수 시 본 부록과 코드·리포트를 병행) |

- **Part 1**: SIP PBX Core 기능 (구현 완료)
- **Part 2**: AI 기능 (Phase 1-4) — 개요·목표는 본문, **상세 FR은 부록** [prd-detailed-phase1-4.md](./prd-detailed-phase1-4.md), **구현 수준**은 아래 스냅샷·[docs/reports/README.md](../reports/README.md)를 병행한다.
- **사업·시장·재무·GTM 상세(기획 시점 원문)** 는 [project-plan.md](./project-plan.md)에 보관하며, **요약만** 본문 [사업 맥락 및 프로젝트 계획 (요약)](#사업-맥락-및-프로젝트-계획-요약)에 옮겼다.

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
- **v3.4** (2026-05-11): MM를 **65.0**으로 상향 — STT/TTS/LLM **품질·모델별 개런티(~1.5× 가중)**, **AI Runtime** 복잡도 가산, **시뮬레이터·연동 후 전구간** 다단계 검증 반영.
- **v3.3** (2026-05-11): **MM 산정 범위 점검표** 추가 — 기존 노드(§11.3) vs AI 구역(MM 총액), 부하·검증시험 포함 수준 명시.
- **v3.2** (2026-05-11): Epic·Phase MM을 **온프레미스·연동·부하 검증** 포함 상용 전제로 재산정하여 **서버별 합계와 동일 44.0 MM**으로 정렬.
- **v3.1** (2026-05-11): [production-deployment-architecture.md](../architecture/production-deployment-architecture.md) 기준 **AI Call Agent 서버별 MM** 재산정; Epic 단위 표는 참고로 유지.
- **v3.0** (2026-05-11): 기존 `prd.md` · `project-plan` 요약 · MM 표를 **마스터 PRD 단일 파일**로 통합; 상세 FR은 부록 파일로 유지. 별도 실행 요약 파일(`prd-executive-summary.md`)은 폐기하고 본문 §개발 공수로 이관.
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

## 사업 맥락 및 프로젝트 계획 (요약)

아래는 [project-plan.md](./project-plan.md) 기획 시점 본문을 **요약**한 것이다. 시장 수치·재무·채널별 예산 등 **장문·표 전체**는 원문 파일을 본다.

### 제품·가치

| 항목 | 내용 |
|------|------|
| 제품명 | SmartPBX AI |
| 한 줄 | 기존 SIP PBX 위에 **Active RAG**·**동적 응대**·**HITL**·**Agentic**을 결합한 지능형 통화 응대 |
| 차별점 | 통화 기반 자동 지식 축적, 고정 ARS 탈피, 운영 피드백 학습, (로드맵) 멀티 에이전트 |

### 시장·기회 (요약)

| 구분 | 참고치 (기획 시점) |
|------|---------------------|
| 글로벌 클라우드 PBX | 성장률 등 거시 지표는 project-plan §시장 조사 |
| 초기 타깃 | 한국 중소기업 콜센터·고객센터 등 (페르소나·Pain은 project-plan §고객 분석) |

### 재무 하이라이트 (Year 1, 기획 시점)

| 지표 | 목표 (예시) |
|------|-------------|
| ARR | $420K |
| 유료 고객 수 | 175 |
| Seed 등 조달 전제 | project-plan §Funding |

### 실행 로드맵 (기획 시점 분기)

| 분기 | 초점 |
|------|------|
| Q2 | Active RAG·지식 파이프라인·Beta |
| Q3 | NL IV·Intent·Tool·AI-ARS 출시 준비 |
| Q4 | HITL·Shadowing·고객 확대 |

### 리스크·대응 (사업 관점)

AI 정확도·규제·경쟁 등 **상세 매트릭스**는 [project-plan.md](./project-plan.md) §리스크 관리 및 본문 [Risks and Mitigation](#risks-and-mitigation)을 함께 본다.

---

## 개발 공수 (MM)

**정의**

- **1 MM** = 1인·1개월 **개발 인월**(설계·구현·단위·통합 테스트 포함).
- **미포함**: PM 전담, 별도 QA 조직, UAT, **운영비(Opex)** — Opex는 [production-deployment-architecture.md](../architecture/production-deployment-architecture.md) §11.6 등에서 AI Call Agent 범위로 정리한다.

### 산정 전제 (Epic·서버 합계 일치)

이전 **Epic만 합산한 34 MM**은 온프레미스 전용 **STT/TTS/LLM** 추론 스택, **PostgreSQL·Qdrant** 운영 반영, **코어(WT·바이토·유엔젤) 연동 검증**, **250 세션·2.1 CPS** 부하 리허설 등을 충분히 넣지 않은 값이었다. **v3.2~v3.3**에서 이를 **44.0 MM**으로 정렬했으나, 검토 결과 **추론 품질 보증·런타임 복잡도·다층 검증**을 상용 **품질 개런티** 수준에 두면 ROM이 부족하다는 판단이 있었다. **v3.4**에서는 아래 **가산 근거**를 반영하여 **합계 65.0 MM**으로 상향한다. **Epic 표**와 **서버 역할 표**는 동일 전제에서 **분해만 다르다**.

| 관점 | 상용([production-deployment-architecture.md](../architecture/production-deployment-architecture.md)) 반영 시 MM에 포함할 일 |
|------|--------------------------------------------------------------------------------------------------------------------------|
| SIP·RTP·프론트 | 코어·바이토·WTIMS는 **연동·규약 검증** — 미디어 RTP는 GW 비경유, 통합 시그널만 GW·Runtime 경로 |
| STT·TTS·LLM | **온프레미스 전용 노드**(GPU, vLLM/TGI, gRPC 스트리밍, §5 모델·용량) 구축·튜닝·검증 **+ 목표 품질 대비 측정·회귀·모델/버전별 튜닝**(약 **1.5×** 상당 가산 — 아래 **가산 근거**) |
| DB·벡터 | **PostgreSQL HA** + **Qdrant** 노드 기준 스키마·HA·검색 부하 |
| AI Runtime | 세션 오케스트레이션 **복잡도·경계 조건·복구**에 대한 추가 개런티 공수 |
| 검증·공통 | **시뮬레이터·목업** 기반 구성요소 검증 → **기존 노드 연동 스테이징** 재검증 → **전구간 E2E·부하·품질 게이트**; 부하 리허설(§6.4), 관측·보안·문서화 |

#### MM 가산 근거 (v3.4, 요약)

| 구분 | 내용 |
|------|------|
| **STT·TTS·LLM** | “코드 완료”만이 아니라 **WER/지연/합성 품질·환각 완화** 등 **목표 품질**을 맞추기 위한 **벤치·현장 시나리오·회귀**, **모델·프롬프트·추론 설정별** 반복 수정을 **기존 산정 대비 약 1.5배 수준**(해당 노드 MM 가중)으로 반영한다. |
| **AI Runtime** | Intent·RAG·HITL·도구·WT 재생 시그널이 얽인 **상태 기계**, 장애·타임아웃·재시도 등 **운영 경계**를 포함해 **추가 개런티** 공수를 반영한다. |
| **검증** | AI Call Agent를 **시뮬레이터로 단위·서브시스템 검증**한 뒤, **기존 노드와 연동한 스테이징**에서 **재통합 검증**, 이후 **Fully E2E**(품질·부하·회귀)까지 이르는 **다단계 시험**을 **공통·통합·검증** 및 **Cross-cutting**에 명시적으로 가산한다. §11.3 **코어 측 제품 개발** 자체는 여전히 **별도 MM**(이중 계상 금지). |

### AI Call Agent 서버별 MM (배포 역할 축, 합계 65.0 MM)

근거 역할: `production-deployment-architecture.md` **§5** · **§6** (AIR GW, API/Realtime, AI Runtime, STT, TTS, LLM, PostgreSQL, Qdrant).  
**한 줄 요약**: 코어·EMS는 제외하고, **AI Call Agent 시스템 16노드 구성**에 대응하는 **소프트웨어 개발·연동·품질 개런티·다단계 검증** 공수다 (HW 조달·상면은 미포함).

| 서버(역할) | 개발·연동 범위 (MM 산정 시 포함) | MM |
|------------|----------------------------------|-----|
| **AIR 연동 접점 GW** | WT→GW→Active AIR **통합 시그널**, gRPC/HTTP 게이트웨이, VIP·A/S 페일오버, 백프레셔·헬스 | **2.0** |
| **API/Realtime** | 유엔젤·바이토 **단일 VIP**, REST/WSS, 인증·레이트리밋, AIR↔API, **운영 UI는 연동·스펙 정합**(신규 풀스택 단독 가정 아님) | **5.0** |
| **AI Runtime** | 세션 오케스트레이션, Intent·RAG·HITL, STT/TTS/LLM **클라이언트**, 정책·도구 호출, WT 재생 시그널, DB 접근 **+ 복잡 경로·복구·운영 경계 개런티** | **15.0** |
| **STT Server** | 온프레미스 ASR(§5.1), GPU 추론 서비스, **RTP mirror↔STT** 계약, gRPC 스트리밍, 풀·SLO **+ 품질(WER·지연)·모델별 튜닝·회귀** | **9.0** |
| **TTS Server** | 온프레미스 합성(§5.2), 스트리밍·캐시, AIR↔TTS·WT 재생 경로 정합 **+ 음질·지연·모델별 검증·수정** | **6.0** |
| **LLM Server** | vLLM/TGI, fp8·멀티 GPU(§5.3), OpenAI 호환 API, **2노드 추론 풀**, RAG·발화율 가정(§5.3)과 정합 **+ 환각·지연·토큰 정책·모델별 SLA 근접 검증** | **11.0** |
| **PostgreSQL HA** | 트랜잭션 스키마, 세션·정책·이력, HA(Patroni 등)·풀러, 백업·전환 시나리오 | **2.5** |
| **Qdrant(VectorDB)** | 컬렉션·차원, 임베딩 반입 파이프, 검색·업서트 부하(§7.2), 운영 규칙 | **2.5** |
| **공통·통합·검증** | OTel 등 관측 훅, 보안·비밀 관리, **시뮬레이터·목업** 기반 구성요소 시험, **연동 스테이징 재검증**, **전구간 E2E·품질 회귀**, **250 세션·2.1 CPS** 부하 리허설(§6.4), 인수인계 문서 | **12.0** |
| **합계 (AI Call Agent 소프트웨어)** | | **65.0** |

- **잔여 구현**이 [구현 스냅샷](#ai-기능-구현-스냅샷-2026-05) 대비 많을수록 양 표 모두 **비율로 줄여** 재계산한다.
- **기존 코어 연동 개발**(WTIMS↔GW, CM↔WT, 유엔젤·바이토↔API 등)은 `production-deployment-architecture.md` **§11.3** 범주이며, 위 표·Epic 표 **합계와 이중 계상**하지 않도록 과제를 나눈다.

### 기능(Epic·Phase)별 MM (기능 축, 합계 65.0 MM · 서버 표와 동일 총액)

온프레미스 추론·DB·연동·**품질 개런티·시뮬레이터·다단계 검증·부하**를 Epic 줄에 흡수한 값이다. **부록** [prd-detailed-phase1-4.md](./prd-detailed-phase1-4.md) Epic 번호와 매핑해 요구 추적에 쓴다.

| 기능 영역 | 포함 (부록 Epic 대응) | MM |
|-----------|------------------------|-----|
| 실시간 STT·트랜스크립트·Diarization·통화 메타 (온프레미스 ASR·RTP mirror 경로 포함, **품질·모델별 검증·회귀**) | Epic 1.1 | **6.5** |
| VectorDB·임베딩·지식 저장 파이프라인 (운영 스택·Qdrant 정합) | Epic 1.2 | **4.0** |
| RAG Retrieval·추론 런타임 연동 (온프레미스 LLM 경로·토큰 가정 정합, **환각·지연 개런티**) | Epic 1.3 | **5.0** |
| 지식 적재·문서 업로드·운영 UI | Phase 1 연계 | **1.5** |
| 부재중 AI 응대·설정·API | Phase 1 부록 | **2.0** |
| **소계 Phase 1** | | **19.0** |
| Intent·NL IV·대화 상태·오케스트레이션 (**런타임 복잡도·경계 조건**) | Epic 2.1 | **6.0** |
| Tool Calling·외부 연동 프레임워크 | Epic 2.1 | **4.0** |
| 운영 대시보드·ARS/플로우 관리 (API/Realtime·바이토 연동 정합) | Epic 2.2 | **3.5** |
| **소계 Phase 2** | | **13.5** |
| HITL 실시간 피드백·WS·Confidence·알림 | Epic 3.1 | **5.0** |
| 사후 리뷰·라벨링·통화이력 연계 | Epic 3.1 | **3.0** |
| Shadowing(실시간 가이드) | Epic 3.2 | **2.5** |
| **소계 Phase 3** | | **10.5** |
| Tool-calling Agent·권한·감사 로그 | Epic 4.1 | **4.5** |
| Multi-Agent 협업·라우팅 | Epic 4.2 | **4.0** |
| **소계 Phase 4** | | **8.5** |
| 공통: 보안·관측·**시뮬레이터·단계별 검증·연동 후 Fully E2E**·온프레미스 부하 검증(§6.4)·통합 테스트·문서 | Cross-cutting | **13.5** |
| **합계 (Epic·Phase, 상용 전제)** | | **65.0** |

**Epic 합계 = 서버 역할 합계 = 65.0 MM** — 하나는 **기능·Phase** 축, 하나는 **배포 노드** 축일 뿐이다.

### MM 산정 범위 점검 (기존 노드 연동 · 검증·부하 시험)

아래는 [production-deployment-architecture.md](../architecture/production-deployment-architecture.md) **§11.3**(기존 노드 연동 개발) 및 **§6.2·§6.4**(목표 용량·환산)와 맞춰 본 **포함/제외**이다.

| 구분 | 세부 | 65.0 MM에 포함되는가 |
|------|------|----------------------|
| **AI Call Agent 측 연동** | AIR GW가 받는 **통합 시그널** 처리, Runtime의 WT 재생·세션 연계, API/Realtime의 **유엔젤·바이토 단일 VIP** 계약·클라이언트, STT/TTS의 **RTP mirror·재생 경로**와의 프로토콜 정합 | **예** — 해당 노드·Epic 줄에 분배됨 |
| **기존 코어·외부 서버의 제품 개발** | 통화매니저 AS↔WTIMS **호 세션 릴레이**, WTIMS의 통합 시그널 발신·**RTP 미러**, 유엔젤·바이토 서버의 **AI 호출·조회 REST** 추가 등 — 문서상 **AI Call Agent 제외** 연동 과제 | **아니오** — 상용 문서 **§11.3**에서 별도 공수·금액 산정. 본 **65 MM**과 **이중 계상 금지**(본문 위 bullet과 동일) |
| **시뮬레이터·구성요소 단위·서브시스템 검증** | 목업/시뮬레이터로 STT·TTS·LLM·Runtime·API를 **독립·조합** 검증, 회귀 시나리오 | **예** — Cross-cutting·공통·통합·검증에 **명시 가산**(v3.4) |
| **연동 스테이징 후 재검증·Fully E2E** | 기존 노드와 붙인 뒤 **재통합 시험**, 품질·지연·실패 모드 **전구간** 검증 | **예** — 상동 (**AI 측 시험 공수** 기준). 코어 **제품 코드 개발**은 §11.3 |
| **스테이징 검증·통합 시험** | 모듈·API 단위 테스트, AI 구역 내부 통합, 코어와의 **인터페이스 단** 통합 | **예** |
| **Production 목표 부하 리허설** | 문서 목표 **약 250 동시 세션·약 2.1 CPS·120초** 등 **부하 시험 설계·실행·조치**(§6.2·§6.4) | **예** — 서버 표「공통·통합·검증」**12.0** 및 Epic「Cross-cutting」**13.5**에 반영 |
| **전 구간 E2E·장기 Soak·코어 단독 부하** | 교환기~WT **코어 전용** 성능 시험, 다일간 soak **전담 인력** | **부분·별도** — AI 구역 E2E는 위에 포함; **코어 단독·전사 전담 Soak**은 §11.3 또는 운영 과제로 **추가 MM** 검토 |

**정리**

- **기존 노드와의 연동**: **AI 측에서 구현·검증하는 범위**는 본 MM에 들어 있으나, **CM·WT·유엔젤·바이토 제품 코드 변경**은 §11.3 **별도 MM**이다. 상용 전체 일정은 **65 MM + §11.3 연동 MM**으로 보는 것이 맞다.
- **검증·부하**: **시뮬레이터·단계별 검증·연동 후 Fully E2E·목표 부하 리허설**을 v3.4에서 **가산**했다. 그래도 **전사 단독 QA 조직·수 주 Soak·코어 대역 단독 부하**를 전부 넣으면 **추가 MM**을 별도 과제로 둔다.

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
- **[PRD Detailed Phase 1-4](./prd-detailed-phase1-4.md)**: AI 기능 상세 요구사항 (부록 — FR·User Story)
- **[Project Plan](./project-plan.md)**: 시장·재무·GTM **상세**(기획 시점 원문; 요약은 본문 §사업 맥락)
- **[Reports index](../reports/README.md)**: 월별 구현·분석 리포트 요약

---

**문서 완료일**: 2026-02-02  
**최종 갱신**: 2026-05-11
