# SmartPBX AI - Backend Testing Strategy
## Comprehensive Testing Framework for Python Backend

**문서 버전**: v1.1  
**작성일**: 2026-01-30  
**최종 갱신**: 2026-05-08  
**작성자**: QA Team  
**상태**: Implementation Ready

**정합**: 테스트 피라미드·도구는 본 문서를 표준으로 하되, **실행 결과·커버리지**는 [`docs/qa/`](../qa/) 및 월별 [`docs/reports/`](../reports/README.md) 리포트와 함께 본다.

---

## 📋 목차

1. [Testing Philosophy](#testing-philosophy)
2. [Test Pyramid](#test-pyramid)
3. [Testing Framework Setup](#testing-framework-setup)
4. [Unit Testing](#unit-testing)
5. [Integration Testing](#integration-testing)
6. [API Testing](#api-testing)
7. [WebSocket Testing](#websocket-testing)
8. [Database Testing](#database-testing)
9. [AI/LLM Testing](#aillm-testing)
10. [Load Testing](#load-testing)
11. [Security Testing](#security-testing)
12. [Test Coverage](#test-coverage)
13. [CI/CD Integration](#cicd-integration)
14. [Test Data Management](#test-data-management)

---

## Testing Philosophy

### Core Principles

1. **Fast Feedback**: 테스트는 빠르게 실행되어야 함 (Unit < 1s, Integration < 10s)
2. **Isolated**: 각 테스트는 독립적이며 순서에 의존하지 않음
3. **Repeatable**: 동일한 입력에 대해 항상 동일한 결과
4. **Meaningful**: 테스트 이름만으로도 의도 파악 가능
5. **Maintainable**: 코드 변경 시 테스트 수정 최소화

### Testing Objectives

| Objective | Target | Measurement |
|-----------|--------|-------------|
| **Code Coverage** | >80% | Line coverage |
| **Unit Test Speed** | <5 minutes | Total execution time |
| **Integration Test Speed** | <15 minutes | Total execution time |
| **Bug Detection** | >95% | Pre-production bug catch rate |
| **Regression Prevention** | 100% | Critical path coverage |

---

## Test Pyramid

```
        /\
       /  \
      / E2E\        ~ 10% (Slow, Expensive)
     /______\
    /        \
   /Integration\   ~ 30% (Medium Speed)
  /____________\
 /              \
/  Unit Tests    \ ~ 60% (Fast, Cheap)
/__________________\
```

### Distribution Strategy

**Unit Tests (60%)**:
- Pure function tests
- Class method tests
- Business logic tests
- Utility function tests

**Integration Tests (30%)**:
- Database operations
- External API calls
- Message queue interactions
- File I/O operations

**End-to-End Tests (10%)**:
- Full user workflows
- Critical business processes
- Cross-service interactions

---

## Testing Framework Setup

### Dependencies

```toml
# pyproject.toml

[project.optional-dependencies]
test = [
    "pytest>=7.4.0",
    "pytest-asyncio>=0.21.0",
    "pytest-cov>=4.1.0",
    "pytest-mock>=3.11.0",
    "pytest-xdist>=3.3.0",          # Parallel execution
    "pytest-timeout>=2.1.0",         # Timeout control
    "pytest-randomly>=3.13.0",       # Random test order
    "httpx>=0.24.0",                 # Async HTTP client
    "respx>=0.20.0",                 # HTTP mock
    "freezegun>=1.2.0",              # Time mocking
    "faker>=19.0.0",                 # Test data generation
    "factory-boy>=3.3.0",            # Model factories
    "locust>=2.15.0",                # Load testing
]
```

### Pytest Configuration

```ini
# pytest.ini

[pytest]
# Test discovery
testpaths = tests
python_files = test_*.py
python_classes = Test*
python_functions = test_*

# Async support
asyncio_mode = auto

# Markers
markers =
    unit: Unit tests (fast)
    integration: Integration tests (medium)
    e2e: End-to-end tests (slow)
    smoke: Smoke tests (critical path)
    ai: Tests involving AI/LLM
    db: Tests requiring database
    ws: WebSocket tests
    slow: Tests that take >1 second

# Coverage
addopts =
    --strict-markers
    --strict-config
    --cov=src
    --cov-report=html
    --cov-report=term-missing
    --cov-fail-under=80
    --maxfail=5
    --timeout=300

# Parallel execution
# Run with: pytest -n auto
```

### Directory Structure

```
tests/
├── conftest.py                    # Global fixtures
│
├── unit/                          # Unit tests (60%)
│   ├── test_sip_message.py
│   ├── test_rtp_parser.py
│   ├── test_config_loader.py
│   ├── test_rag_engine.py
│   └── test_dialog_manager.py
│
├── integration/                   # Integration tests (30%)
│   ├── test_sip_endpoint.py
│   ├── test_database.py
│   ├── test_vector_db.py
│   ├── test_google_cloud.py
│   └── test_event_bus.py
│
├── e2e/                          # End-to-end tests (10%)
│   ├── test_call_flow.py
│   ├── test_hitl_workflow.py
│   └── test_knowledge_extraction.py
│
├── load/                         # Load tests
│   ├── locustfile.py
│   └── scenarios/
│
├── fixtures/                     # Test fixtures & data
│   ├── __init__.py
│   ├── call_fixtures.py
│   ├── knowledge_fixtures.py
│   └── factories.py
│
└── mocks/                        # Mock objects
    ├── mock_llm.py
    ├── mock_stt.py
    └── mock_vector_db.py
```

---

## Unit Testing

### Basic Test Structure

```python
# tests/unit/test_sip_message.py

import pytest
from src.sip_core.sip_message import SIPMessage, SIPMethod

class TestSIPMessage:
    """SIP Message parsing and generation tests"""
    
    def test_parse_invite_request(self):
        """INVITE 요청 파싱이 정확해야 함"""
        # Given
        raw_message = """INVITE sip:1004@10.153.195.83 SIP/2.0
Via: SIP/2.0/UDP 10.153.195.11:5060;branch=z9hG4bK-abc123
From: "1003" <sip:1003@10.153.195.11>;tag=abc123
To: <sip:1004@10.153.195.83>
Call-ID: xyz789@10.153.195.11
CSeq: 1 INVITE
Contact: <sip:1003@10.153.195.11:5060>
Content-Type: application/sdp
Content-Length: 200

v=0
o=- 123456 654321 IN IP4 10.153.195.11
s=-
c=IN IP4 10.153.195.11
t=0 0
m=audio 10000 RTP/AVP 0
a=rtpmap:0 PCMU/8000"""

        # When
        message = SIPMessage.parse(raw_message)

        # Then
        assert message.method == SIPMethod.INVITE
        assert message.uri == "sip:1004@10.153.195.83"
        assert message.headers["Call-ID"] == "xyz789@10.153.195.11"
        assert message.headers["From"].startswith('"1003"')
        assert message.body is not None
        assert "m=audio 10000" in message.body

    def test_generate_200_ok_response(self):
        """200 OK 응답 생성이 정확해야 함"""
        # Given
        invite = SIPMessage.parse_invite(sample_invite_message)
        contact = "sip:1004@10.153.195.83:5060"
        
        # When
        response = SIPMessage.create_response(
            request=invite,
            status_code=200,
            reason_phrase="OK",
            contact=contact
        )

        # Then
        assert response.status_code == 200
        assert response.reason_phrase == "OK"
        assert response.headers["Contact"] == f"<{contact}>"
        assert response.headers["Call-ID"] == invite.headers["Call-ID"]

    @pytest.mark.parametrize("method,uri,expected", [
        (SIPMethod.INVITE, "sip:1004@example.com", True),
        (SIPMethod.BYE, "sip:1004@example.com", True),
        (SIPMethod.CANCEL, "sip:1004@example.com", True),
        (None, "sip:1004@example.com", False),
        (SIPMethod.INVITE, "", False),
    ])
    def test_message_validation(self, method, uri, expected):
        """SIP 메시지 유효성 검증"""
        message = SIPMessage(method=method, uri=uri)
        assert message.is_valid() == expected
```

---

### Testing RTP Parser

```python
# tests/unit/test_rtp_parser.py

import pytest
from src.media.rtp_parser import RTPParser, RTPPacket

class TestRTPParser:
    """RTP packet parsing tests"""
    
    def test_parse_rtp_packet(self):
        """RTP 패킷 파싱이 정확해야 함"""
        # Given: RTP header (12 bytes) + payload
        rtp_data = bytes([
            0x80,  # Version=2, Padding=0, Extension=0, CSRC=0
            0x00,  # Marker=0, Payload Type=0 (PCMU)
            0x12, 0x34,  # Sequence number
            0x00, 0x00, 0x00, 0x01,  # Timestamp
            0xAA, 0xBB, 0xCC, 0xDD,  # SSRC
        ]) + b'\x00' * 160  # 160 bytes of audio payload

        # When
        packet = RTPParser.parse(rtp_data)

        # Then
        assert packet.version == 2
        assert packet.payload_type == 0
        assert packet.sequence_number == 0x1234
        assert packet.timestamp == 1
        assert packet.ssrc == 0xAABBCCDD
        assert len(packet.payload) == 160

    def test_parse_invalid_packet(self):
        """잘못된 RTP 패킷은 예외 발생"""
        # Given: Too short packet
        invalid_data = b'\x80\x00\x12'

        # When/Then
        with pytest.raises(ValueError, match="RTP packet too short"):
            RTPParser.parse(invalid_data)

    def test_strip_rtp_header(self):
        """RTP 헤더 제거 후 payload만 추출"""
        # Given
        rtp_data = b'\x80\x00' + b'\x00' * 10 + b'PAYLOAD'

        # When
        payload = RTPParser.strip_header(rtp_data)

        # Then
        assert payload == b'PAYLOAD'
        assert len(payload) == 7
```

---

### Testing RAG Engine

```python
# tests/unit/test_rag_engine.py

import pytest
from unittest.mock import AsyncMock, MagicMock
from src.ai.rag_engine import RAGEngine

class TestRAGEngine:
    """RAG 검색 엔진 테스트"""
    
    @pytest.fixture
    def mock_vector_db(self):
        """Mock Qdrant client"""
        mock = MagicMock()
        mock.search.return_value = [
            MagicMock(
                id="qa_001",
                score=0.95,
                payload={
                    "question": "배송은 언제 도착하나요?",
                    "answer": "2-3일 소요됩니다",
                    "category": "배송"
                }
            ),
            MagicMock(
                id="qa_002",
                score=0.85,
                payload={
                    "question": "배송 조회 방법",
                    "answer": "주문번호로 조회 가능합니다",
                    "category": "배송"
                }
            ),
        ]
        return mock

    @pytest.fixture
    def mock_embeddings(self):
        """Mock OpenAI embeddings"""
        mock = AsyncMock()
        mock.aembed_query.return_value = [0.1] * 3072  # Fake embedding
        return mock

    @pytest.fixture
    def rag_engine(self, mock_vector_db, mock_embeddings):
        """RAG Engine with mocked dependencies"""
        engine = RAGEngine()
        engine.vector_db = mock_vector_db
        engine.embeddings = mock_embeddings
        return engine

    @pytest.mark.asyncio
    async def test_search_returns_top_results(self, rag_engine):
        """검색 시 Top-K 결과 반환"""
        # When
        results = await rag_engine.search("배송 조회", top_k=2)

        # Then
        assert len(results) == 2
        assert results[0]["id"] == "qa_001"
        assert results[0]["similarity"] == 0.95
        assert "배송" in results[0]["answer"]

    @pytest.mark.asyncio
    async def test_search_filters_by_threshold(self, rag_engine):
        """Threshold 이하 결과는 필터링"""
        # Given
        rag_engine.vector_db.search.return_value = [
            MagicMock(id="qa_001", score=0.95, payload={"question": "A", "answer": "A"}),
            MagicMock(id="qa_002", score=0.50, payload={"question": "B", "answer": "B"}),
        ]

        # When
        results = await rag_engine.search("test", threshold=0.7)

        # Then
        assert len(results) == 1
        assert results[0]["id"] == "qa_001"

    @pytest.mark.asyncio
    async def test_upsert_knowledge(self, rag_engine, mock_embeddings):
        """Knowledge 저장 시 Embedding 생성 및 Vector DB 저장"""
        # Given
        qa_pair = {
            "id": "qa_new",
            "question": "신제품 있나요?",
            "answer": "아이폰 16 Pro 있습니다",
            "category": "상품문의"
        }

        # When
        await rag_engine.upsert(qa_pair)

        # Then
        mock_embeddings.aembed_query.assert_called_once()
        rag_engine.vector_db.upsert.assert_called_once()
```

---

## Integration Testing

### Database Testing

```python
# tests/integration/test_database.py

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from src.database.models import Base, Call, Transcript
from datetime import datetime

@pytest.fixture(scope="function")
def test_db():
    """Test database fixture (SQLite in-memory)"""
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    
    Session = sessionmaker(bind=engine)
    session = Session()
    
    yield session
    
    session.close()
    Base.metadata.drop_all(engine)

class TestCallModel:
    """Call 모델 DB 연동 테스트"""
    
    def test_create_call(self, test_db):
        """통화 생성 및 저장"""
        # Given
        call = Call(
            caller="1003",
            callee="1004",
            start_time=datetime.now(),
            status="active",
            call_type="sip_call"
        )

        # When
        test_db.add(call)
        test_db.commit()

        # Then
        saved_call = test_db.query(Call).filter_by(caller="1003").first()
        assert saved_call is not None
        assert saved_call.callee == "1004"
        assert saved_call.status == "active"

    def test_call_with_transcript(self, test_db):
        """통화와 Transcript 관계"""
        # Given
        call = Call(
            caller="1003",
            callee="1004",
            start_time=datetime.now(),
            status="completed"
        )
        test_db.add(call)
        test_db.commit()

        transcript = Transcript(
            call_id=call.call_id,
            content="발신자: 안녕하세요\n수신자: 네, 안녕하세요",
            quality_score=0.95,
            word_count=10
        )
        test_db.add(transcript)
        test_db.commit()

        # When
        saved_call = test_db.query(Call).filter_by(call_id=call.call_id).first()

        # Then
        assert saved_call.transcript is not None
        assert saved_call.transcript.quality_score == 0.95

    def test_query_calls_by_date_range(self, test_db):
        """날짜 범위로 통화 조회"""
        # Given: 3개 통화 생성
        for i in range(3):
            call = Call(
                caller=f"100{i}",
                callee="1004",
                start_time=datetime(2026, 1, 30, 10, i, 0),
                status="completed"
            )
            test_db.add(call)
        test_db.commit()

        # When
        date_from = datetime(2026, 1, 30, 10, 1, 0)
        date_to = datetime(2026, 1, 30, 10, 2, 0)
        calls = test_db.query(Call).filter(
            Call.start_time >= date_from,
            Call.start_time <= date_to
        ).all()

        # Then
        assert len(calls) == 2
```

---

### External API Testing (Google Cloud)

```python
# tests/integration/test_google_cloud.py

import pytest
from unittest.mock import AsyncMock, patch
from src.integrations.google_cloud import GoogleCloudIntegration

@pytest.fixture
def mock_stt_client():
    """Mock Google STT client"""
    with patch('google.cloud.speech_v2.SpeechAsyncClient') as mock:
        client = AsyncMock()
        mock.return_value = client
        
        # Mock response
        client.recognize.return_value = AsyncMock(
            results=[
                AsyncMock(
                    alternatives=[
                        AsyncMock(
                            transcript="안녕하세요, 주문 조회하려고 합니다",
                            confidence=0.95
                        )
                    ]
                )
            ]
        )
        
        yield client

@pytest.mark.integration
@pytest.mark.asyncio
async def test_transcribe_audio(mock_stt_client):
    """STT API 호출 및 응답 파싱"""
    # Given
    integration = GoogleCloudIntegration(credentials_path="test-key.json")
    audio_content = b'\x00' * 1000  # Fake audio data

    # When
    result = await integration.transcribe_audio(
        audio_content=audio_content,
        sample_rate=8000,
        language_code="ko-KR"
    )

    # Then
    assert result["transcript"] == "안녕하세요, 주문 조회하려고 합니다"
    assert result["confidence"] == 0.95
    mock_stt_client.recognize.assert_called_once()
```

---

## API Testing

### FastAPI Testing

```python
# tests/integration/test_api_calls.py

import pytest
from httpx import AsyncClient
from src.api.main import app

@pytest.fixture
async def client():
    """Async HTTP client for API testing"""
    async with AsyncClient(app=app, base_url="http://test") as client:
        yield client

@pytest.fixture
def auth_headers(auth_token):
    """Authorization headers"""
    return {"Authorization": f"Bearer {auth_token}"}

@pytest.mark.asyncio
async def test_list_calls(client, auth_headers):
    """GET /api/v1/calls - 통화 목록 조회"""
    # When
    response = await client.get(
        "/api/v1/calls",
        headers=auth_headers,
        params={"limit": 10}
    )

    # Then
    assert response.status_code == 200
    data = response.json()
    assert "total" in data
    assert "data" in data
    assert isinstance(data["data"], list)

@pytest.mark.asyncio
async def test_get_call_detail(client, auth_headers, sample_call_id):
    """GET /api/v1/calls/{call_id} - 통화 상세 조회"""
    # When
    response = await client.get(
        f"/api/v1/calls/{sample_call_id}",
        headers=auth_headers
    )

    # Then
    assert response.status_code == 200
    data = response.json()
    assert data["call_id"] == sample_call_id
    assert "caller" in data
    assert "callee" in data

@pytest.mark.asyncio
async def test_get_call_not_found(client, auth_headers):
    """GET /api/v1/calls/{call_id} - 존재하지 않는 통화"""
    # When
    response = await client.get(
        "/api/v1/calls/nonexistent-id",
        headers=auth_headers
    )

    # Then
    assert response.status_code == 404

@pytest.mark.asyncio
async def test_create_knowledge(client, auth_headers):
    """POST /api/v1/knowledge - Knowledge 생성"""
    # Given
    payload = {
        "question": "신제품 있나요?",
        "answer": "아이폰 16 Pro 있습니다",
        "category": "상품문의"
    }

    # When
    response = await client.post(
        "/api/v1/knowledge",
        headers=auth_headers,
        json=payload
    )

    # Then
    assert response.status_code == 201
    data = response.json()
    assert data["question"] == payload["question"]
    assert data["answer"] == payload["answer"]
    assert "id" in data

@pytest.mark.asyncio
async def test_create_knowledge_validation_error(client, auth_headers):
    """POST /api/v1/knowledge - 유효성 검증 실패"""
    # Given: question too short
    payload = {
        "question": "짧음",
        "answer": "답변",
        "category": "기타"
    }

    # When
    response = await client.post(
        "/api/v1/knowledge",
        headers=auth_headers,
        json=payload
    )

    # Then
    assert response.status_code == 400

@pytest.mark.asyncio
async def test_unauthorized_request(client):
    """인증 없이 API 호출 시 401"""
    # When
    response = await client.get("/api/v1/calls")

    # Then
    assert response.status_code == 401
```

---

## WebSocket Testing

```python
# tests/integration/test_websocket.py

import pytest
import asyncio
from websockets import connect
from src.api.websocket import ConnectionManager

@pytest.mark.ws
@pytest.mark.asyncio
async def test_websocket_connection():
    """WebSocket 연결 및 메시지 송수신"""
    uri = "ws://localhost:8000/ws/operator/op001?token=test-token"
    
    async with connect(uri) as websocket:
        # Given: Connected
        
        # When: Send ping
        await websocket.send('{"type": "ping"}')
        
        # Then: Receive pong
        response = await websocket.recv()
        data = json.loads(response)
        assert data["type"] == "pong"

@pytest.mark.ws
@pytest.mark.asyncio
async def test_hitl_alert_broadcast():
    """HITL 알림 브로드캐스트"""
    # Given: 2 operators connected
    manager = ConnectionManager()
    
    mock_ws1 = AsyncMock()
    mock_ws2 = AsyncMock()
    
    await manager.connect("op001", mock_ws1)
    await manager.connect("op002", mock_ws2)
    
    # When: Broadcast HITL alert
    alert = {
        "type": "hitl_alert",
        "alert_id": "alert_001",
        "question": "신제품 있나요?",
        "confidence": 0.25
    }
    await manager.broadcast(alert)
    
    # Then: Both operators received
    mock_ws1.send_json.assert_called_once_with(alert)
    mock_ws2.send_json.assert_called_once_with(alert)

@pytest.mark.ws
@pytest.mark.asyncio
async def test_websocket_reconnection():
    """WebSocket 재연결 처리"""
    uri = "ws://localhost:8000/ws/operator/op001?token=test-token"
    
    async with connect(uri) as websocket:
        # Given: Initial connection
        assert websocket.open
        
        # When: Force disconnect
        await websocket.close()
        
        # Then: Reconnect
        async with connect(uri) as new_websocket:
            assert new_websocket.open
            
            # Verify can still send/receive
            await new_websocket.send('{"type": "ping"}')
            response = await new_websocket.recv()
            assert json.loads(response)["type"] == "pong"
```

---

## AI/LLM Testing

### Mocking LLM Responses

```python
# tests/mocks/mock_llm.py

from unittest.mock import AsyncMock

class MockLLM:
    """Mock LLM for testing"""
    
    def __init__(self, responses=None):
        self.responses = responses or {}
        self.call_count = 0
    
    async def ainvoke(self, prompt: str):
        """Mock LLM invocation"""
        self.call_count += 1
        
        # Return predefined response or default
        for keyword, response in self.responses.items():
            if keyword in prompt:
                return AsyncMock(content=response)
        
        return AsyncMock(content="Default response")
    
    def reset(self):
        """Reset call count"""
        self.call_count = 0
```

### AI Agent Testing

```python
# tests/unit/test_ai_agent.py

import pytest
from unittest.mock import AsyncMock, MagicMock
from src.ai.agent_service import AIAgentService
from tests.mocks.mock_llm import MockLLM

@pytest.fixture
def mock_llm():
    """Mock LLM with predefined responses"""
    return MockLLM(responses={
        "배송": "주문번호를 알려주시겠어요?",
        "환불": "환불 사유를 말씀해주세요",
        "상품": "어떤 상품이 궁금하신가요?"
    })

@pytest.fixture
def mock_rag_engine():
    """Mock RAG engine"""
    mock = AsyncMock()
    mock.search.return_value = [
        {
            "question": "배송 조회",
            "answer": "주문번호로 조회 가능",
            "similarity": 0.92
        }
    ]
    return mock

@pytest.fixture
def agent_service(mock_llm, mock_rag_engine):
    """AI Agent with mocked dependencies"""
    service = AIAgentService()
    service.llm = mock_llm
    service.rag_engine = mock_rag_engine
    return service

@pytest.mark.ai
@pytest.mark.asyncio
async def test_process_query_with_high_confidence(agent_service):
    """High confidence 쿼리 처리"""
    # When
    result = await agent_service.process_query(
        query="배송 조회하고 싶어요",
        session_id="session_123"
    )

    # Then
    assert result["response"] == "주문번호를 알려주시겠어요?"
    assert result["confidence"] > 0.6
    assert result["intent"] == "delivery_tracking"

@pytest.mark.ai
@pytest.mark.asyncio
async def test_process_query_triggers_hitl(agent_service, mock_rag_engine):
    """Low confidence 시 HITL 트리거"""
    # Given: Low similarity RAG results
    mock_rag_engine.search.return_value = [
        {"question": "무관한 질문", "answer": "무관한 답변", "similarity": 0.30}
    ]

    # When
    result = await agent_service.process_query(
        query="완전히 새로운 질문",
        session_id="session_123"
    )

    # Then
    assert result["confidence"] < 0.6
    assert result["hitl_triggered"] is True

@pytest.mark.ai
@pytest.mark.asyncio
async def test_intent_classification(agent_service):
    """Intent 분류 정확도"""
    test_cases = [
        ("배송 조회", "delivery_tracking"),
        ("환불 하고 싶어요", "refund"),
        ("상품 재고 확인", "product_inquiry"),
    ]

    for query, expected_intent in test_cases:
        result = await agent_service.process_query(query, "session_test")
        assert result["intent"] == expected_intent
```

---

## Load Testing

### Locust Configuration

```python
# tests/load/locustfile.py

from locust import HttpUser, task, between, events
import json
import random

class SmartPBXUser(HttpUser):
    """사용자 시뮬레이션"""
    
    wait_time = between(1, 5)  # 1-5초 간격
    
    def on_start(self):
        """사용자 시작 시 로그인"""
        response = self.client.post("/api/v1/auth/login", json={
            "email": f"test{random.randint(1, 100)}@example.com",
            "password": "testpass"
        })
        
        if response.status_code == 200:
            self.token = response.json()["access_token"]
        else:
            self.token = None
    
    @task(3)
    def list_calls(self):
        """통화 목록 조회 (빈도: 높음)"""
        if not self.token:
            return
        
        self.client.get(
            "/api/v1/calls",
            headers={"Authorization": f"Bearer {self.token}"},
            params={"limit": 20},
            name="/api/v1/calls"
        )
    
    @task(2)
    def search_knowledge(self):
        """Knowledge 검색 (빈도: 중간)"""
        if not self.token:
            return
        
        queries = ["배송", "환불", "교환", "상품", "결제"]
        query = random.choice(queries)
        
        self.client.get(
            "/api/v1/knowledge",
            headers={"Authorization": f"Bearer {self.token}"},
            params={"query": query, "top_k": 5},
            name="/api/v1/knowledge/search"
        )
    
    @task(1)
    def agent_query(self):
        """AI Agent 쿼리 (빈도: 낮음, 비용 높음)"""
        if not self.token:
            return
        
        queries = [
            "배송 조회하고 싶어요",
            "환불 가능한가요?",
            "상품 재고 있나요?"
        ]
        
        self.client.post(
            "/api/v1/agent/query",
            headers={"Authorization": f"Bearer {self.token}"},
            json={
                "query": random.choice(queries),
                "session_id": f"session_{random.randint(1, 1000)}"
            },
            name="/api/v1/agent/query"
        )
    
    @task(1)
    def get_metrics(self):
        """메트릭 조회"""
        if not self.token:
            return
        
        self.client.get(
            "/api/v1/metrics/performance",
            headers={"Authorization": f"Bearer {self.token}"},
            params={"period": "1h"},
            name="/api/v1/metrics/performance"
        )

# Custom events for reporting
@events.test_start.add_listener
def on_test_start(environment, **kwargs):
    print(f"Load test starting with {environment.runner.user_count} users")

@events.test_stop.add_listener
def on_test_stop(environment, **kwargs):
    print(f"Load test completed")
    print(f"Total requests: {environment.stats.total.num_requests}")
    print(f"Total failures: {environment.stats.total.num_failures}")
    print(f"Average response time: {environment.stats.total.avg_response_time:.2f}ms")
```

### Load Test Scenarios

```python
# tests/load/scenarios/peak_load.py

from locust import HttpUser, task, between, LoadTestShape

class PeakLoadShape(LoadTestShape):
    """
    점진적 부하 증가 시나리오
    
    1분: 10 users
    2분: 50 users
    3분: 100 users (피크)
    4분: 50 users
    5분: 10 users
    """
    
    stages = [
        {"duration": 60, "users": 10, "spawn_rate": 1},
        {"duration": 120, "users": 50, "spawn_rate": 5},
        {"duration": 180, "users": 100, "spawn_rate": 10},
        {"duration": 240, "users": 50, "spawn_rate": 5},
        {"duration": 300, "users": 10, "spawn_rate": 2},
    ]
    
    def tick(self):
        run_time = self.get_run_time()
        
        for stage in self.stages:
            if run_time < stage["duration"]:
                return (stage["users"], stage["spawn_rate"])
        
        return None
```

**Run Commands**:
```bash
# Basic load test (10 users, 1 minute)
locust -f tests/load/locustfile.py --host=http://localhost:8000 \
       --users 10 --spawn-rate 1 --run-time 1m --headless

# Peak load test (100 users, 5 minutes)
locust -f tests/load/locustfile.py --host=http://localhost:8000 \
       --users 100 --spawn-rate 10 --run-time 5m --headless

# Custom shape
locust -f tests/load/scenarios/peak_load.py --host=http://localhost:8000 \
       --headless

# With web UI
locust -f tests/load/locustfile.py --host=http://localhost:8000
# Open http://localhost:8089
```

---

## Security Testing

### Authentication Testing

```python
# tests/integration/test_security.py

import pytest
from httpx import AsyncClient

@pytest.mark.asyncio
async def test_jwt_token_validation(client):
    """JWT 토큰 유효성 검증"""
    # Given: Invalid token
    headers = {"Authorization": "Bearer invalid-token"}

    # When
    response = await client.get("/api/v1/calls", headers=headers)

    # Then
    assert response.status_code == 401

@pytest.mark.asyncio
async def test_expired_token(client, expired_token):
    """만료된 토큰 거부"""
    # Given
    headers = {"Authorization": f"Bearer {expired_token}"}

    # When
    response = await client.get("/api/v1/calls", headers=headers)

    # Then
    assert response.status_code == 401

@pytest.mark.asyncio
async def test_rbac_permission_denied(client, viewer_token):
    """권한 없는 작업 거부 (RBAC)"""
    # Given: Viewer trying to delete knowledge
    headers = {"Authorization": f"Bearer {viewer_token}"}

    # When
    response = await client.delete(
        "/api/v1/knowledge/qa_001",
        headers=headers
    )

    # Then
    assert response.status_code == 403
```

### SQL Injection Testing

```python
@pytest.mark.asyncio
async def test_sql_injection_protection(client, auth_headers):
    """SQL Injection 방어"""
    # Given: SQL injection attempt
    malicious_input = "1' OR '1'='1"

    # When
    response = await client.get(
        f"/api/v1/calls/{malicious_input}",
        headers=auth_headers
    )

    # Then: Should return 404, not 200 (not vulnerable)
    assert response.status_code == 404
```

### XSS Testing

```python
@pytest.mark.asyncio
async def test_xss_protection(client, auth_headers):
    """XSS 공격 방어"""
    # Given: XSS payload
    payload = {
        "question": "<script>alert('xss')</script>",
        "answer": "Test answer",
        "category": "test"
    }

    # When
    response = await client.post(
        "/api/v1/knowledge",
        headers=auth_headers,
        json=payload
    )

    # Then: Should sanitize input
    assert response.status_code == 201
    data = response.json()
    assert "<script>" not in data["question"]
```

---

## Test Coverage

### Coverage Configuration

```ini
# .coveragerc

[run]
source = src
omit =
    */tests/*
    */venv/*
    */__pycache__/*
    */migrations/*

[report]
precision = 2
exclude_lines =
    pragma: no cover
    def __repr__
    raise AssertionError
    raise NotImplementedError
    if __name__ == .__main__.:
    if TYPE_CHECKING:
    @abstractmethod

[html]
directory = htmlcov
```

### Coverage Commands

```bash
# Run tests with coverage
pytest --cov=src --cov-report=html --cov-report=term-missing

# Coverage report
coverage report

# HTML report (open htmlcov/index.html)
coverage html

# Fail if coverage < 80%
pytest --cov=src --cov-fail-under=80
```

### Coverage Targets

| Module | Target | Current | Status |
|--------|--------|---------|--------|
| **sip_core/** | 85% | 92% | ✅ |
| **media/** | 80% | 88% | ✅ |
| **ai/** | 75% | 82% | ✅ |
| **api/** | 85% | 90% | ✅ |
| **database/** | 90% | 95% | ✅ |
| **integrations/** | 70% | 78% | ✅ |
| **Overall** | 80% | 87% | ✅ |

---

## CI/CD Integration

### GitHub Actions Workflow

```yaml
# .github/workflows/test.yml

name: Tests

on:
  push:
    branches: [main, develop]
  pull_request:
    branches: [main, develop]

jobs:
  test:
    runs-on: ubuntu-latest
    
    services:
      postgres:
        image: postgres:15
        env:
          POSTGRES_DB: smartpbx_test
          POSTGRES_USER: test
          POSTGRES_PASSWORD: test
        ports:
          - 5432:5432
        options: >-
          --health-cmd pg_isready
          --health-interval 10s
          --health-timeout 5s
          --health-retries 5
      
      redis:
        image: redis:7-alpine
        ports:
          - 6379:6379
        options: >-
          --health-cmd "redis-cli ping"
          --health-interval 10s
          --health-timeout 5s
          --health-retries 5
      
      qdrant:
        image: qdrant/qdrant:v1.7.0
        ports:
          - 6333:6333

    steps:
      - uses: actions/checkout@v3
      
      - name: Set up Python
        uses: actions/setup-python@v4
        with:
          python-version: '3.11'
      
      - name: Cache dependencies
        uses: actions/cache@v3
        with:
          path: ~/.cache/pip
          key: ${{ runner.os }}-pip-${{ hashFiles('**/pyproject.toml') }}
          restore-keys: |
            ${{ runner.os }}-pip-
      
      - name: Install dependencies
        run: |
          python -m pip install --upgrade pip
          pip install -e ".[test]"
      
      - name: Run linting
        run: |
          pip install ruff
          ruff check src tests
      
      - name: Run type checking
        run: |
          pip install mypy
          mypy src
      
      - name: Run unit tests
        run: |
          pytest tests/unit -v --cov=src --cov-report=xml
        env:
          DATABASE_URL: postgresql://test:test@localhost:5432/smartpbx_test
          REDIS_URL: redis://localhost:6379
      
      - name: Run integration tests
        run: |
          pytest tests/integration -v --cov=src --cov-append --cov-report=xml
        env:
          DATABASE_URL: postgresql://test:test@localhost:5432/smartpbx_test
          REDIS_URL: redis://localhost:6379
          QDRANT_URL: http://localhost:6333
      
      - name: Upload coverage to Codecov
        uses: codecov/codecov-action@v3
        with:
          file: ./coverage.xml
          flags: unittests
          name: codecov-umbrella
      
      - name: Check coverage threshold
        run: |
          pytest --cov=src --cov-fail-under=80 --cov-report=term-missing
      
      - name: Run security checks
        run: |
          pip install safety bandit
          safety check
          bandit -r src -ll

  load-test:
    runs-on: ubuntu-latest
    if: github.event_name == 'pull_request'
    
    steps:
      - uses: actions/checkout@v3
      
      - name: Set up Python
        uses: actions/setup-python@v4
        with:
          python-version: '3.11'
      
      - name: Install Locust
        run: pip install locust
      
      - name: Run load tests
        run: |
          locust -f tests/load/locustfile.py \
                 --host=http://staging.smartpbx.ai \
                 --users 50 \
                 --spawn-rate 5 \
                 --run-time 2m \
                 --headless \
                 --html=load_test_report.html
      
      - name: Upload load test report
        uses: actions/upload-artifact@v3
        with:
          name: load-test-report
          path: load_test_report.html
```

---

## Test Data Management

### Factories (Factory Boy)

```python
# tests/fixtures/factories.py

import factory
from factory.fuzzy import FuzzyChoice, FuzzyDateTime
from datetime import datetime, timedelta
from src.database.models import Call, Transcript, Knowledge

class CallFactory(factory.Factory):
    """Call model factory"""
    
    class Meta:
        model = Call
    
    call_id = factory.Faker('uuid4')
    caller = factory.Sequence(lambda n: f"100{n}")
    callee = factory.Sequence(lambda n: f"200{n}")
    start_time = FuzzyDateTime(
        datetime.now() - timedelta(days=30),
        datetime.now()
    )
    duration = factory.Faker('random_int', min=10, max=600)
    status = FuzzyChoice(['active', 'completed', 'failed'])
    call_type = 'sip_call'

class TranscriptFactory(factory.Factory):
    """Transcript model factory"""
    
    class Meta:
        model = Transcript
    
    id = factory.Faker('uuid4')
    call_id = factory.LazyAttribute(lambda _: CallFactory().call_id)
    content = factory.Faker('text', max_nb_chars=500)
    quality_score = factory.Faker('pyfloat', min_value=0.7, max_value=1.0)
    word_count = factory.Faker('random_int', min=50, max=300)

class KnowledgeFactory(factory.Factory):
    """Knowledge model factory"""
    
    class Meta:
        model = Knowledge
    
    id = factory.Faker('uuid4')
    question = factory.Faker('sentence', nb_words=8)
    answer = factory.Faker('text', max_nb_chars=200)
    category = FuzzyChoice(['배송', '환불', '교환', '상품문의', '기타'])
    source = FuzzyChoice(['auto', 'operator_correction', 'manual'])

# Usage in tests
def test_with_factory(test_db):
    # Create 10 calls
    calls = [CallFactory() for _ in range(10)]
    test_db.add_all(calls)
    test_db.commit()
    
    assert test_db.query(Call).count() == 10
```

---

### Fixtures

```python
# tests/conftest.py

import pytest
import asyncio
from datetime import datetime, timedelta
from jose import jwt

@pytest.fixture(scope="session")
def event_loop():
    """Create event loop for async tests"""
    loop = asyncio.get_event_loop_policy().new_event_loop()
    yield loop
    loop.close()

@pytest.fixture
def sample_call_id():
    """Sample call ID for testing"""
    return "abc123-def456-ghi789"

@pytest.fixture
def auth_token():
    """Valid JWT token for testing"""
    SECRET_KEY = "test-secret-key"
    payload = {
        "sub": "user123",
        "email": "test@example.com",
        "role": "operator",
        "exp": datetime.utcnow() + timedelta(hours=1)
    }
    return jwt.encode(payload, SECRET_KEY, algorithm="HS256")

@pytest.fixture
def expired_token():
    """Expired JWT token"""
    SECRET_KEY = "test-secret-key"
    payload = {
        "sub": "user123",
        "exp": datetime.utcnow() - timedelta(hours=1)
    }
    return jwt.encode(payload, SECRET_KEY, algorithm="HS256")

@pytest.fixture
def viewer_token():
    """Token for viewer role (limited permissions)"""
    SECRET_KEY = "test-secret-key"
    payload = {
        "sub": "viewer123",
        "email": "viewer@example.com",
        "role": "viewer",
        "exp": datetime.utcnow() + timedelta(hours=1)
    }
    return jwt.encode(payload, SECRET_KEY, algorithm="HS256")

@pytest.fixture
def sample_audio_data():
    """Sample audio data (G.711 μ-law)"""
    # 160 bytes = 20ms of audio at 8000Hz
    return b'\xFF' * 160

@pytest.fixture
def sample_rtp_packet():
    """Sample RTP packet"""
    header = bytes([
        0x80, 0x00,  # Version, PT
        0x12, 0x34,  # Sequence
        0x00, 0x00, 0x00, 0x01,  # Timestamp
        0xAA, 0xBB, 0xCC, 0xDD,  # SSRC
    ])
    payload = b'\xFF' * 160
    return header + payload
```

---

## Best Practices Summary

### ✅ DO

1. **테스트 이름을 명확하게**
   ```python
   # Good
   def test_parse_invite_request_with_sdp()
   
   # Bad
   def test_parse()
   ```

2. **AAA 패턴 사용** (Arrange, Act, Assert)
   ```python
   def test_example():
       # Arrange (Given)
       data = create_test_data()
       
       # Act (When)
       result = process(data)
       
       # Assert (Then)
       assert result == expected
   ```

3. **Fixtures로 중복 제거**
   ```python
   @pytest.fixture
   def client():
       return create_test_client()
   
   def test_a(client):
       ...
   
   def test_b(client):
       ...
   ```

4. **Parametrize로 여러 케이스 테스트**
   ```python
   @pytest.mark.parametrize("input,expected", [
       ("hello", "HELLO"),
       ("world", "WORLD"),
   ])
   def test_uppercase(input, expected):
       assert input.upper() == expected
   ```

5. **Mock 사용으로 의존성 격리**
   ```python
   @patch('src.external.api_call')
   def test_with_mock(mock_api):
       mock_api.return_value = "mocked"
       result = my_function()
       assert result == "processed: mocked"
   ```

---

### ❌ DON'T

1. **테스트 간 의존성**
   ```python
   # Bad
   def test_create():
       global user_id
       user_id = create_user()
   
   def test_update():
       update_user(user_id)  # Depends on test_create
   ```

2. **실제 외부 API 호출**
   ```python
   # Bad
   def test_stt():
       result = google_stt_api.transcribe(audio)  # Real API call
   
   # Good
   @patch('google_stt_api.transcribe')
   def test_stt(mock_stt):
       mock_stt.return_value = "mocked transcript"
   ```

3. **하드코딩된 타임스탬프**
   ```python
   # Bad
   assert result.created_at == "2026-01-30 10:00:00"
   
   # Good
   from freezegun import freeze_time
   
   @freeze_time("2026-01-30 10:00:00")
   def test_with_time():
       ...
   ```

---

## Test Execution

### Run All Tests
```bash
pytest
```

### Run Specific Test Types
```bash
# Unit tests only (fast)
pytest tests/unit -v

# Integration tests only
pytest tests/integration -v

# Tests with specific marker
pytest -m unit
pytest -m "not slow"
pytest -m "ai and not slow"
```

### Parallel Execution
```bash
# Auto-detect CPU cores
pytest -n auto

# Use 4 processes
pytest -n 4
```

### Watch Mode (pytest-watch)
```bash
pip install pytest-watch
ptw -- -v
```

### Coverage Report
```bash
pytest --cov=src --cov-report=html
open htmlcov/index.html
```

---

## Summary

이 Backend Testing Strategy 문서는:

✅ **Testing Philosophy**: Fast, Isolated, Repeatable  
✅ **Test Pyramid**: 60% Unit, 30% Integration, 10% E2E  
✅ **Framework**: Pytest + pytest-asyncio + pytest-cov  
✅ **Unit Testing**: SIP, RTP, RAG Engine, Dialog Manager  
✅ **Integration Testing**: Database, External APIs, Event Bus  
✅ **API Testing**: FastAPI endpoints with httpx  
✅ **WebSocket Testing**: Real-time communication  
✅ **AI/LLM Testing**: Mock LLM, Confidence validation  
✅ **Load Testing**: Locust scenarios (10-100 users)  
✅ **Security Testing**: Auth, RBAC, SQL Injection, XSS  
✅ **Coverage**: >80% target, HTML reports  
✅ **CI/CD**: GitHub Actions with Codecov  
✅ **Test Data**: Factory Boy, Fixtures, Faker  

**Target Metrics**:
- Unit tests: <5 minutes
- Integration tests: <15 minutes
- Coverage: >80%
- Load test: 100 concurrent users @ <2s latency

---

**완료된 문서**:
1. ✅ Technical Architecture
2. ✅ API Specification
3. ✅ Frontend Architecture
4. ✅ **Backend Testing Strategy**

**다음 작업**: Database Migration Scripts, CI/CD Pipeline, Deployment Runbook 중 선택! 🚀
