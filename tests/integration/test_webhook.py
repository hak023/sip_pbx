"""Webhook Integration 테스트"""

import pytest
import asyncio
from aiohttp import web
import threading
from datetime import datetime

from src.events.webhook import WebhookNotifier
from src.ai.event_models import AIEvent, EventType, SeverityLevel
from src.common.logger import setup_logging


@pytest.fixture(scope="module", autouse=True)
def setup_test_logging():
    """테스트용 로깅 설정"""
    setup_logging(level="DEBUG", format_type="text")


class MockWebhookServer:
    """Mock Webhook 서버"""
    
    def __init__(self, port=18080):
        self.port = port
        self.received_events = []
        self.app = None
        self.runner = None
        self.site = None
        self.should_fail = False
        self.response_status = 200
        
    async def handle_webhook(self, request):
        """Webhook 요청 처리"""
        if self.should_fail:
            return web.Response(status=self.response_status or 500, text="Mock failure")
        
        data = await request.json()
        self.received_events.append(data)
        
        return web.Response(status=200, text="OK")
    
    async def start(self):
        """서버 시작"""
        self.app = web.Application()
        self.app.router.add_post('/webhook', self.handle_webhook)
        
        self.runner = web.AppRunner(self.app)
        await self.runner.setup()
        
        self.site = web.TCPSite(self.runner, 'localhost', self.port)
        await self.site.start()
    
    async def stop(self):
        """서버 중지"""
        if self.site:
            await self.site.stop()
        if self.runner:
            await self.runner.cleanup()
    
    def clear_events(self):
        """수신 이벤트 초기화"""
        self.received_events.clear()


@pytest.fixture
async def mock_webhook_server():
    """Mock webhook 서버 fixture"""
    server = MockWebhookServer()
    await server.start()
    
    # 서버 시작 대기
    await asyncio.sleep(0.2)
    
    yield server
    
    await server.stop()


@pytest.fixture
def webhook_notifier(mock_webhook_server):
    """Webhook notifier"""
    return WebhookNotifier(
        webhook_urls=[f"http://localhost:{mock_webhook_server.port}/webhook"],
        timeout=5.0,
        max_retries=2,
    )


@pytest.fixture
def sample_event():
    """샘플 이벤트"""
    return AIEvent(
        event_id="test-event-1",
        event_type=EventType.PROFANITY_DETECTED,
        call_id="test-call-1",
        direction="caller",
        timestamp=10.5,
        confidence=0.9,
        severity=SeverityLevel.HIGH,
        details={"text": "sample text", "keywords": ["bad"]},
    )


class TestWebhookNotifier:
    """WebhookNotifier 테스트"""
    
    def test_notifier_creation(self):
        """Notifier 생성"""
        notifier = WebhookNotifier(
            webhook_urls=["http://example.com/webhook"],
            timeout=10.0,
            max_retries=3,
        )
        
        assert len(notifier.webhook_urls) == 1
        assert notifier.timeout == 10.0
        assert notifier.max_retries == 3
    
    @pytest.mark.asyncio
    async def test_send_event_success(self, webhook_notifier, sample_event, mock_webhook_server):
        """이벤트 전송 성공"""
        mock_webhook_server.clear_events()
        
        success = await webhook_notifier.send_event(sample_event)
        
        # 전송 대기
        await asyncio.sleep(0.3)
        
        assert success is True
        assert len(mock_webhook_server.received_events) == 1
        
        # 페이로드 확인
        payload = mock_webhook_server.received_events[0]
        assert payload["event_id"] == "test-event-1"
        assert payload["call_id"] == "test-call-1"
        assert payload["event_type"] == "profanity_detected"
        assert payload["severity"] == "high"
        assert payload["confidence"] == 0.9
    
    @pytest.mark.asyncio
    async def test_send_event_with_retry(self, webhook_notifier, sample_event, mock_webhook_server):
        """재시도 후 성공"""
        mock_webhook_server.clear_events()
        
        # 처음에는 실패하도록 설정
        mock_webhook_server.should_fail = True
        mock_webhook_server.response_status = 500
        
        # 비동기 태스크로 전송 시작
        async def delayed_success():
            await asyncio.sleep(1.5)  # 첫 번째 재시도 후
            mock_webhook_server.should_fail = False
        
        asyncio.create_task(delayed_success())
        
        success = await webhook_notifier.send_event(sample_event)
        
        # 재시도가 발생했는지 확인
        assert webhook_notifier.stats["retries"] > 0
    
    @pytest.mark.asyncio
    async def test_send_event_all_retries_failed(self):
        """모든 재시도 실패"""
        notifier = WebhookNotifier(
            webhook_urls=["http://localhost:19999/nonexistent"],  # 존재하지 않는 서버
            timeout=0.5,
            max_retries=2,
            backoff_factor=1.0,  # 빠른 테스트
        )
        
        event = AIEvent(
            event_id="fail-event",
            event_type=EventType.ANGER_DETECTED,
            call_id="fail-call",
            direction="caller",
            timestamp=0.0,
            confidence=0.8,
            severity=SeverityLevel.MEDIUM,
        )
        
        success = await notifier.send_event(event)
        
        assert success is False
        assert notifier.stats["total_failed"] == 1
        assert notifier.stats["retries"] == 2
    
    @pytest.mark.asyncio
    async def test_multiple_webhooks(self, sample_event):
        """여러 webhook URL"""
        # 여러 서버 시작
        servers = []
        urls = []
        
        for i in range(3):
            port = 18081 + i
            server = MockWebhookServer(port=port)
            await server.start()
            servers.append(server)
            urls.append(f"http://localhost:{port}/webhook")
        
        await asyncio.sleep(0.3)
        
        notifier = WebhookNotifier(webhook_urls=urls, timeout=5.0)
        
        success = await notifier.send_event(sample_event)
        
        await asyncio.sleep(0.5)
        
        # 모든 서버가 받았는지 확인
        assert success is True
        
        for server in servers:
            assert len(server.received_events) == 1
        
        # 정리
        for server in servers:
            await server.stop()
    
    def test_add_remove_webhook_url(self, webhook_notifier):
        """Webhook URL 추가/제거"""
        initial_count = len(webhook_notifier.webhook_urls)
        
        # 추가
        webhook_notifier.add_webhook_url("http://example.com/new-webhook")
        assert len(webhook_notifier.webhook_urls) == initial_count + 1
        
        # 제거
        webhook_notifier.remove_webhook_url("http://example.com/new-webhook")
        assert len(webhook_notifier.webhook_urls) == initial_count
    
    def test_get_stats(self, webhook_notifier):
        """통계 조회"""
        stats = webhook_notifier.get_stats()
        
        assert "total_sent" in stats
        assert "total_success" in stats
        assert "total_failed" in stats
        assert "retries" in stats
        assert "webhook_urls_count" in stats
    
    @pytest.mark.asyncio
    async def test_no_webhook_urls(self, sample_event):
        """Webhook URL이 없는 경우"""
        notifier = WebhookNotifier(webhook_urls=[], timeout=5.0)
        
        success = await notifier.send_event(sample_event)
        
        # URL이 없으면 True 반환
        assert success is True
    
    @pytest.mark.asyncio
    async def test_payload_format(self, webhook_notifier, mock_webhook_server):
        """페이로드 포맷 검증"""
        mock_webhook_server.clear_events()
        
        event = AIEvent(
            event_id="format-test",
            event_type=EventType.THREATENING_LANGUAGE,
            call_id="format-call",
            direction="callee",
            timestamp=25.5,
            confidence=0.95,
            severity=SeverityLevel.CRITICAL,
            details={
                "text": "threatening message",
                "keywords": ["kill", "hurt"],
                "context": "full conversation",
            },
        )
        
        await webhook_notifier.send_event(event)
        await asyncio.sleep(0.3)
        
        assert len(mock_webhook_server.received_events) == 1
        
        payload = mock_webhook_server.received_events[0]
        
        # 필수 필드 확인
        assert "event_id" in payload
        assert "call_id" in payload
        assert "timestamp" in payload
        assert "event_type" in payload
        assert "severity" in payload
        assert "confidence" in payload
        assert "direction" in payload
        assert "details" in payload
        
        # 값 확인
        assert payload["event_type"] == "threatening_language"
        assert payload["severity"] == "critical"
        assert payload["details"]["keywords"] == ["kill", "hurt"]

