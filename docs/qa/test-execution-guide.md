# 🧪 테스트 실행 가이드

## 📋 문서 정보

| 항목 | 내용 |
|------|------|
| **작성일** | 2026-01-08 |
| **작성자** | Quinn (Test Architect) |
| **버전** | v1.1 |

---

## 1. 테스트 환경 설정

### 1.1 사전 요구사항

```bash
# Python 3.11+
python --version

# 의존성 설치
pip install -r requirements.txt
pip install -r requirements-test.txt

# Docker
docker --version
docker-compose --version
```

### 1.2 환경 변수 설정

```bash
# .env.test 파일 생성
cp .env.example .env.test

# 테스트용 환경 변수
export TEST_ENV=true
export DATABASE_URL=postgresql://test:test@localhost:5432/test_db
export REDIS_URL=redis://localhost:6379/1
export GOOGLE_APPLICATION_CREDENTIALS=./config/gcp-key-test.json
```

### 1.3 테스트 데이터베이스 준비

```bash
# PostgreSQL 컨테이너 시작
docker-compose -f docker-compose.test.yml up -d postgres redis

# 마이그레이션 실행
python -m alembic upgrade head

# 테스트 데이터 로드
python scripts/load_test_data.py
```

---

## 2. 테스트 실행

### 2.1 전체 테스트 실행

```bash
# 모든 테스트 실행
pytest

# 상세 로그 출력
pytest -v

# 실패 시 즉시 중단
pytest -x

# 병렬 실행 (8 workers)
pytest -n 8
```

### 2.2 특정 레벨 테스트 실행

```bash
# Unit Tests만 실행
pytest tests/unit -v

# Integration Tests만 실행
pytest tests/integration -v

# E2E Tests만 실행
pytest tests/e2e -v

# 새로 작성한 테스트만 실행
pytest tests_new/ -v
```

### 2.3 특정 모듈 테스트 실행

```bash
# SIP Core 테스트
pytest tests/unit/test_sip_core -v

# AI Pipeline 테스트
pytest tests_new/unit/test_ai_pipeline -v

# Media Layer 테스트
pytest tests/unit/test_media -v

# API 테스트
pytest tests/integration/test_api -v
```

### 2.4 특정 테스트 케이스 실행

```bash
# 테스트 함수명으로 실행
pytest tests/unit/test_call_manager.py::test_handle_incoming_invite -v

# 테스트 클래스로 실행
pytest tests/unit/test_call_manager.py::TestCallManager -v

# 키워드로 실행
pytest -k "test_standard_call" -v
```

### 2.5 마커를 사용한 실행

```bash
# E2E 테스트만
pytest -m e2e -v

# Unit + Integration만
pytest -m "unit or integration" -v

# AI Pipeline 테스트만
pytest -m "ai_pipeline" -v
```

---

## 3. 테스트 디버깅

### 3.1 실패한 테스트 재실행

```bash
# 마지막 실패 테스트만 재실행
pytest --lf

# 마지막 실패부터 순서대로 실행
pytest --ff

# 실패 시 pdb 디버거 진입
pytest --pdb
```

### 3.2 로그 출력

```bash
# 모든 로그 출력
pytest -v --log-cli-level=DEBUG

# 파일로 저장
pytest -v --log-file=test.log --log-file-level=DEBUG
```

### 3.3 상세 정보 출력

```bash
# 캡처 비활성화 (print 출력)
pytest -v -s

# 전체 traceback 출력
pytest -v --tb=long

# 실패 시 local 변수 출력
pytest -v --showlocals
```

---

## 4. CI/CD 통합

### 4.1 GitHub Actions

`.github/workflows/test.yml`:

```yaml
name: Test Suite

on: [push, pull_request]

jobs:
  test:
    runs-on: ubuntu-latest
    
    services:
      postgres:
        image: postgres:14
        env:
          POSTGRES_PASSWORD: test
      
      redis:
        image: redis:7
    
    steps:
      - uses: actions/checkout@v3
      
      - name: Set up Python
        uses: actions/setup-python@v4
        with:
          python-version: '3.11'
      
      - name: Install dependencies
        run: |
          pip install -r requirements.txt
          pip install -r requirements-test.txt
      
      - name: Run unit tests
        run: pytest tests/unit -v
      
      - name: Run integration tests
        run: pytest tests/integration -v
```

### 4.2 Pre-commit Hooks

`.pre-commit-config.yaml`:

```yaml
repos:
  - repo: local
    hooks:
      - id: pytest-unit
        name: Unit Tests
        entry: pytest tests/unit -x
        language: system
        pass_filenames: false
        stages: [commit]
```

설치:

```bash
pip install pre-commit
pre-commit install
```

---

## 5. 테스트 작성 가이드

### 5.1 Given-When-Then 패턴

```python
def test_example():
    """
    Given: 초기 조건 설명
    When: 실행할 동작
    Then: 예상 결과
    """
    # Given
    initial_state = setup_initial_state()
    
    # When
    result = perform_action(initial_state)
    
    # Then
    assert result == expected_output
```

### 5.2 Fixture 사용

```python
@pytest.fixture
def call_manager():
    """CallManager 인스턴스 생성"""
    manager = CallManager(
        call_repository=Mock(),
        media_session_manager=Mock()
    )
    yield manager
    manager.cleanup()

def test_with_fixture(call_manager):
    # call_manager 사용
    pass
```

### 5.3 Mock 사용

```python
from unittest.mock import Mock, patch, AsyncMock

def test_with_mock():
    # Mock 객체 생성
    mock_service = Mock()
    mock_service.get_data.return_value = {"key": "value"}
    
    # 함수 패치
    with patch('module.function', return_value="mocked"):
        result = call_function_using_mocked()
    
    # 비동기 Mock
    mock_async = AsyncMock(return_value="async result")
```

---

## 6. 문제 해결

### 6.1 일반적인 오류

#### 오류: `ImportError: No module named 'src'`

```bash
# PYTHONPATH 설정
export PYTHONPATH="${PYTHONPATH}:$(pwd)"

# 또는 pytest 실행 시
pytest --import-mode=importlib
```

#### 오류: `DatabaseError: connection refused`

```bash
# 테스트 DB 컨테이너 확인
docker-compose -f docker-compose.test.yml ps

# 재시작
docker-compose -f docker-compose.test.yml restart postgres
```

#### 오류: `TimeoutError in async tests`

```bash
# 타임아웃 증가
pytest --timeout=30

# 또는 테스트에서
@pytest.mark.timeout(60)
async def test_slow_operation():
    pass
```

### 6.2 테스트 속도 개선

```bash
# 병렬 실행
pytest -n auto

# 느린 테스트 식별
pytest --durations=10  # 가장 느린 10개 표시
```

---

## 7. 테스트 마커 정의

`pytest.ini`:

```ini
[pytest]
markers =
    unit: Unit tests
    integration: Integration tests
    e2e: End-to-end tests
    ai_pipeline: AI Pipeline related tests
    sip_core: SIP Core related tests
```

사용:

```python
@pytest.mark.unit
def test_unit():
    pass

@pytest.mark.integration
async def test_integration():
    pass
```

---

## 8. 참고 자료

- **pytest 공식 문서**: https://docs.pytest.org
- **pytest-asyncio**: https://pytest-asyncio.readthedocs.io

---

**작성자**: Quinn (Test Architect)  
**최종 업데이트**: 2026-01-08
