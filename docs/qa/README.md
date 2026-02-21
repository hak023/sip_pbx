# 🧪 테스트 디렉토리 구조

## 📁 폴더 구조

```
sip-pbx/
├── tests/                          # 기존 테스트 (Unit + Integration)
│   ├── unit/                       # 단위 테스트
│   │   ├── test_sip_core/          # SIP Core 테스트
│   │   ├── test_media/             # Media Layer 테스트
│   │   ├── test_events/            # Events 테스트
│   │   ├── test_monitoring/        # Monitoring 테스트
│   │   └── test_config/            # Configuration 테스트
│   │
│   ├── integration/                # 통합 테스트
│   │   ├── test_call_manager_media_integration.py
│   │   ├── test_rtp_relay.py
│   │   ├── test_sip_server.py
│   │   └── test_webhook.py
│   │
│   ├── performance/                # 성능 테스트
│   │   └── test_media_performance.py
│   │
│   ├── conftest.py                 # Pytest 설정 및 공통 Fixtures
│   └── fixtures/                   # 테스트 데이터

├── tests_new/                      # 신규 추가 테스트 (AI & E2E)
│   ├── unit/                       # 단위 테스트 (AI Pipeline)
│   │   ├── test_ai_pipeline/
│   │   │   ├── test_text_embedder.py       ✨ 신규
│   │   │   ├── test_rag_engine.py          ✨ 신규
│   │   │   ├── test_llm_client.py          ✨ 신규
│   │   │   ├── test_vad_detector.py        ✨ 신규
│   │   │   └── test_knowledge_extractor.py ✨ 신규
│   │   │
│   │   ├── test_backend_api/
│   │   │   ├── test_call_history_api.py    ✨ 신규
│   │   │   ├── test_hitl_api.py            ✨ 신규
│   │   │   ├── test_recording_api.py       ✨ 신규
│   │   │   └── test_ai_insights_api.py     ✨ 신규
│   │   │
│   │   └── test_sip_recorder/
│   │       └── test_sip_call_recorder.py   ✨ 신규
│   │
│   ├── integration/                # 통합 테스트 (AI & Services)
│   │   ├── test_ai_orchestrator_integration.py     ✨ 신규
│   │   ├── test_hitl_service_integration.py        ✨ 신규
│   │   ├── test_recording_playback_flow.py         ✨ 신규
│   │   └── test_post_stt_integration.py            ✨ 신규
│   │
│   ├── e2e/                        # End-to-End 테스트
│   │   ├── test_e2e_standard_call.py               ✨ 신규
│   │   ├── test_e2e_ai_call.py                     ✨ 신규
│   │   ├── test_e2e_hitl_intervention.py           ✨ 신규
│   │   ├── test_e2e_knowledge_extraction.py        ✨ 신규
│   │   └── test_e2e_frontend_monitoring.py         ✨ 신규
│   │
│   ├── load/                       # 부하 테스트
│   │   ├── test_concurrent_calls.py                ✨ 신규
│   │   └── locustfile.py                           ✨ 신규
│   │
│   ├── security/                   # 보안 테스트
│   │   ├── test_api_authentication.py              ✨ 신규
│   │   ├── test_sql_injection.py                   ✨ 신규
│   │   └── test_xss_prevention.py                  ✨ 신규
│   │
│   ├── helpers/                    # 테스트 헬퍼 유틸리티
│   │   ├── sip_client.py           # SIP 클라이언트 시뮬레이터
│   │   ├── test_utils.py           # 공통 유틸리티
│   │   └── mock_factories.py       # Mock 객체 생성
│   │
│   └── conftest.py                 # 신규 테스트용 Fixtures

└── docs/qa/                        # 테스트 문서
    ├── test-strategy.md            ✨ 신규 - 테스트 전략 및 계획
    ├── test-execution-guide.md     ✨ 신규 - 테스트 실행 가이드
    └── README.md                   ✨ 이 파일
```

---

## 📊 테스트 레벨별 분류

### Unit Tests (단위 테스트)
**목적**: 개별 함수/클래스 로직 검증
**실행 빈도**: 모든 PR
**목표 커버리지**: 85% 이상

#### 기존 (tests/unit/)
- ✅ SIP Core: 완료 (~95% 커버리지)
- ✅ Media Layer: 완료 (~90% 커버리지)
- ✅ Events: 완료 (~85% 커버리지)

#### 신규 (tests_new/unit/)
- 🧪 AI Pipeline: 진행 필요
- 🧪 Backend API: 진행 필요
- 🧪 SIP Recorder: 진행 필요

### Integration Tests (통합 테스트)
**목적**: 컴포넌트 간 연동 검증
**실행 빈도**: 매일 nightly build
**목표**: 주요 통합 경로 100%

#### 기존 (tests/integration/)
- ✅ Call Manager ↔ Media: 완료
- ✅ RTP Relay: 완료
- ✅ SIP Server: 완료
- ✅ Webhook: 완료

#### 신규 (tests_new/integration/)
- 🧪 AI Orchestrator ↔ Google Cloud
- 🧪 HITL Service ↔ WebSocket
- 🧪 Recording ↔ Playback
- 🧪 Post-processing STT

### E2E Tests (End-to-End)
**목적**: 전체 시스템 시나리오 검증
**실행 빈도**: 주간 릴리스 전
**목표**: 핵심 시나리오 100%

#### 신규 (tests_new/e2e/)
- 🧪 표준 SIP 통화
- 🧪 AI 자동 응답
- 🧪 HITL 개입
- 🧪 지식 추출
- 🧪 Frontend 모니터링

### Performance Tests (성능 테스트)
**목적**: 성능 기준 충족 검증
**실행 빈도**: 주간
**목표**: 
- RTP 지연 <5ms
- AI 응답 <2초
- 100 동시 통화

### Load Tests (부하 테스트)
**목적**: 시스템 한계 측정
**실행 빈도**: 월간
**목표**: 500 Peak Load

### Security Tests (보안 테스트)
**목적**: 보안 취약점 검증
**실행 빈도**: 릴리스 전
**목표**: OWASP Top 10 준수

---

## 🚀 빠른 시작

### 1. 환경 설정

```bash
# 의존성 설치
pip install -r requirements.txt
pip install -r requirements-test.txt

# 테스트 DB 시작
docker-compose -f docker-compose.test.yml up -d
```

### 2. 전체 테스트 실행

```bash
# 모든 테스트 (기존 + 신규)
pytest

# 기존 테스트만
pytest tests/

# 신규 테스트만
pytest tests_new/
```

### 3. 레벨별 실행

```bash
# Unit Tests
pytest tests/unit tests_new/unit -v

# Integration Tests
pytest tests/integration tests_new/integration -v

# E2E Tests
pytest tests_new/e2e -v --slow
```

### 4. 커버리지 확인

```bash
# 커버리지 측정
pytest --cov=src --cov-report=html

# HTML 리포트 확인
open htmlcov/index.html
```

---

## 📝 테스트 작성 규칙

### 1. 파일명 규칙
- `test_*.py` 또는 `*_test.py`
- 테스트 대상 모듈명과 일치
- 예: `call_manager.py` → `test_call_manager.py`

### 2. 함수명 규칙
- `test_` 접두사 필수
- Given-When-Then 명확히 표현
- 예: `test_handle_incoming_invite_creates_call_session()`

### 3. 테스트 구조
```python
def test_example():
    """
    Given: 초기 조건
    When: 실행 동작
    Then: 예상 결과
    """
    # Given
    setup_code()
    
    # When
    result = action()
    
    # Then
    assert result == expected
```

### 4. Fixture 사용
- 공통 설정은 `conftest.py`에
- 테스트별 설정은 개별 fixture로
- `@pytest.fixture` 데코레이터 사용

### 5. Mock 사용
- 외부 의존성은 Mock으로 대체
- `unittest.mock.Mock`, `AsyncMock` 사용
- 실제 외부 API 호출 금지 (Unit Test)

---

## 🎯 테스트 우선순위

### 🔴 우선순위 1 (Critical)
- SIP Core 기능 (INVITE, BYE, ACK)
- RTP Relay 지연 (<5ms)
- AI 자동 응답
- HITL 개입

### 🟡 우선순위 2 (High)
- SIP 확장 기능 (PRACK, UPDATE, CANCEL)
- 녹음 및 재생
- 지식 추출
- Backend API

### 🟢 우선순위 3 (Medium)
- Frontend 통합
- 성능 최적화
- 보안 강화
- 모니터링

---

## 📊 현재 상태

### 완료된 테스트 (tests/)
| 모듈 | 테스트 수 | 커버리지 | 상태 |
|------|-----------|----------|------|
| SIP Core | 15개 | 95% | ✅ 완료 |
| Media Layer | 20개 | 90% | ✅ 완료 |
| Events | 8개 | 85% | ✅ 완료 |
| Monitoring | 3개 | 80% | ✅ 완료 |

### 신규 추가 필요 (tests_new/)
| 모듈 | 테스트 수 | 커버리지 | 상태 |
|------|-----------|----------|------|
| AI Pipeline | 0 → 15개 | 0 → 85% | 🧪 진행 필요 |
| Backend API | 0 → 12개 | 0 → 90% | 🧪 진행 필요 |
| E2E | 0 → 5개 | N/A | 🧪 진행 필요 |
| Performance | 1 → 3개 | N/A | 🧪 진행 필요 |
| Security | 0 → 3개 | N/A | 🧪 진행 필요 |

---

## 🔗 관련 문서

- **[테스트 전략](test-strategy.md)** - 전체 테스트 계획 및 전략
- **[테스트 실행 가이드](test-execution-guide.md)** - 상세 실행 방법
- **[시스템 아키텍처](../ai-voicebot-architecture.md)** - 시스템 구조 이해

---

**작성자**: Quinn (Test Architect)  
**최종 업데이트**: 2026-01-08

