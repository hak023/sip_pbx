# SIP PBX Product Requirements Document (PRD)

## Goals and Background Context

### Goals

- **SIP B2BUA 구현**: 표준 SIP B2BUA로 동작하는 통화 제어 시스템
- **효율적인 미디어 처리**: RTP bypass 모드를 통한 저지연 미디어 relay
- **확장 가능한 포트 풀 관리**: 동시 다중 호 처리를 위한 효율적인 미디어 포트 리소스 관리
- **표준 SIP 프로토콜 준수**: 기본 SIP 메서드 및 REGISTER 지원으로 기존 인프라와 통합
- **관찰성**: 메트릭, 로깅, CDR을 통한 시스템 모니터링

### Background Context

SIP(Session Initiation Protocol)는 VoIP 통신의 표준 프로토콜입니다. 본 프로젝트는 B2BUA(Back-to-Back User Agent) 아키텍처를 채택하여 SIP 시그널링과 미디어 스트림 모두를 제어할 수 있는 PBX를 구축합니다.

B2BUA는 두 개의 독립적인 SIP leg을 생성하여 각각을 완전히 제어할 수 있으며, 이를 통해 유연한 통화 제어와 미디어 처리가 가능합니다.

### Change Log

| Date | Version | Description | Author |
|------|---------|-------------|--------|
| 2025-10-27 | v1.0 | Initial PRD creation | BMad Master |
| 2025-01-05 | v1.1 | AI 기능 제거, 현재 구현 상태 반영 | BMad Master |

## Requirements

### Functional

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

### Non-Functional

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

## Technical Assumptions

### Language and Framework
- **언어**: Python 3.11+
- **비동기 처리**: asyncio 기반
- **HTTP 프레임워크**: aiohttp

### Architecture
- **스타일**: 모듈러 모놀리스
- **리포지토리**: Monorepo
- **배포**: 컨테이너화 (Docker), Kubernetes StatefulSet

### Infrastructure
- **OS**: Linux (Ubuntu 20.04+) 또는 Windows
- **메모리**: 최소 2GB, 권장 4GB
- **디스크**: 최소 1GB
- **네트워크**: UDP 5060 (SIP), UDP 10000-20000 (RTP), TCP 8080 (HTTP), TCP 9090 (Prometheus)

### Third-party Services
- **모니터링**: Prometheus
- **로깅**: structlog
- **설정**: YAML

## Out of Scope

다음 기능들은 현재 버전의 범위를 벗어납니다:

- SIP TLS/SRTP 암호화
- SIP 인증 (Digest Authentication)
- 통화 녹음
- 음성 분석 (STT, 감정 분석 등)
- GUI 관리 인터페이스
- 데이터베이스 통합
- 실시간 통화 품질 모니터링 (MOS 점수 등)

## Success Metrics

### 기술 메트릭
- 100개 동시 통화 처리 성공률 > 99%
- SIP 응답 시간 < 100ms
- RTP relay 지연 < 5ms
- 메모리 사용량 < 4GB (100개 동시 통화)
- CPU 사용률 < 70% (100개 동시 통화)

### 운영 메트릭
- 시스템 가동률 (Uptime) > 99.9%
- 평균 통화 설정 시간 < 1초
- CDR 생성 성공률 100%
- Webhook 전달 성공률 > 95%

## Timeline

### Phase 1: Core SIP B2BUA (완료)
- SIP 서버 기본 구조
- INVITE/BYE 처리
- REGISTER 지원
- 기본 포트 풀

### Phase 2: 미디어 처리 (완료)
- RTP Relay
- SDP 파싱 및 조작
- 코덱 지원

### Phase 3: 관찰성 (완료)
- Prometheus 메트릭
- CDR 생성
- Structured logging

### Phase 4: 안정화 (진행 중)
- 에러 처리 강화
- 성능 최적화
- 문서화 완료

## Risks and Mitigation

| 위험 | 영향 | 완화 방안 |
|------|------|-----------|
| 포트 고갈 | 높음 | 포트 풀 크기 모니터링, 동적 확장 |
| 메모리 누수 | 중간 | 정기적인 메모리 프로파일링, 세션 타임아웃 |
| SIP 호환성 | 중간 | 다양한 SIP 클라이언트로 테스트 |
| 네트워크 지연 | 낮음 | 저지연 알고리즘, 성능 테스트 |

## Stakeholders

- **개발팀**: 시스템 구현 및 유지보수
- **운영팀**: 배포 및 모니터링
- **QA팀**: 테스트 및 품질 보증

