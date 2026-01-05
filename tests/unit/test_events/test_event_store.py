"""Event Store 테스트"""

import pytest
from datetime import datetime, timedelta
import time

from src.events.event_store import EventStore
from src.ai.event_models import AIEvent, EventType, SeverityLevel
from src.common.logger import setup_logging


@pytest.fixture(scope="module", autouse=True)
def setup_test_logging():
    """테스트용 로깅 설정"""
    setup_logging(level="DEBUG", format_type="text")


@pytest.fixture
def event_store():
    """이벤트 저장소"""
    return EventStore(retention_hours=24)


@pytest.fixture
def sample_event():
    """샘플 이벤트"""
    return AIEvent(
        event_id="event-1",
        event_type=EventType.PROFANITY_DETECTED,
        call_id="call-1",
        direction="caller",
        timestamp=10.5,
        confidence=0.9,
        severity=SeverityLevel.HIGH,
        details={"text": "sample text"},
    )


class TestEventStore:
    """EventStore 테스트"""
    
    def test_store_creation(self):
        """저장소 생성"""
        store = EventStore(retention_hours=48)
        
        assert store.retention_hours == 48
        assert store.get_event_count() == 0
    
    def test_add_event(self, event_store, sample_event):
        """이벤트 추가"""
        success = event_store.add_event(sample_event)
        
        assert success is True
        assert event_store.get_event_count() == 1
    
    def test_add_duplicate_event(self, event_store, sample_event):
        """중복 이벤트 추가"""
        event_store.add_event(sample_event)
        
        # 같은 event_id로 다시 추가 시도
        success = event_store.add_event(sample_event)
        
        assert success is False
        assert event_store.get_event_count() == 1
    
    def test_get_event(self, event_store, sample_event):
        """이벤트 조회"""
        event_store.add_event(sample_event)
        
        retrieved = event_store.get_event("event-1")
        
        assert retrieved is not None
        assert retrieved.event_id == "event-1"
        assert retrieved.call_id == "call-1"
    
    def test_get_nonexistent_event(self, event_store):
        """존재하지 않는 이벤트 조회"""
        retrieved = event_store.get_event("nonexistent")
        
        assert retrieved is None
    
    def test_get_events_by_call(self, event_store):
        """Call-ID별 이벤트 조회"""
        # 여러 이벤트 추가
        for i in range(3):
            event = AIEvent(
                event_id=f"event-{i}",
                event_type=EventType.ANGER_DETECTED,
                call_id="call-multi",
                direction="caller",
                timestamp=float(i),
                confidence=0.8,
                severity=SeverityLevel.MEDIUM,
            )
            event_store.add_event(event)
        
        # 다른 call_id로 이벤트 추가
        other_event = AIEvent(
            event_id="event-other",
            event_type=EventType.PROFANITY_DETECTED,
            call_id="call-other",
            direction="callee",
            timestamp=0.0,
            confidence=0.7,
            severity=SeverityLevel.LOW,
        )
        event_store.add_event(other_event)
        
        # 특정 call_id로 조회
        events = event_store.get_events_by_call("call-multi")
        
        assert len(events) == 3
        assert all(e.call_id == "call-multi" for e in events)
        
        # 시간 순 정렬 확인
        assert events[0].timestamp < events[1].timestamp < events[2].timestamp
    
    def test_get_events_by_type(self, event_store):
        """이벤트 타입별 조회"""
        # 다양한 타입의 이벤트 추가
        events_to_add = [
            AIEvent(
                event_id="anger-1",
                event_type=EventType.ANGER_DETECTED,
                call_id="call-1",
                direction="caller",
                timestamp=0.0,
                confidence=0.8,
                severity=SeverityLevel.HIGH,
            ),
            AIEvent(
                event_id="anger-2",
                event_type=EventType.ANGER_DETECTED,
                call_id="call-2",
                direction="caller",
                timestamp=0.0,
                confidence=0.9,
                severity=SeverityLevel.HIGH,
            ),
            AIEvent(
                event_id="profanity-1",
                event_type=EventType.PROFANITY_DETECTED,
                call_id="call-3",
                direction="caller",
                timestamp=0.0,
                confidence=0.7,
                severity=SeverityLevel.MEDIUM,
            ),
        ]
        
        for event in events_to_add:
            event_store.add_event(event)
        
        # 타입별 조회
        anger_events = event_store.get_events_by_type(EventType.ANGER_DETECTED)
        profanity_events = event_store.get_events_by_type(EventType.PROFANITY_DETECTED)
        
        assert len(anger_events) == 2
        assert len(profanity_events) == 1
    
    def test_get_events_by_time_range(self, event_store):
        """시간 범위별 이벤트 조회"""
        now = datetime.utcnow()
        
        # 다양한 시간의 이벤트 추가
        for i in range(5):
            event = AIEvent(
                event_id=f"time-event-{i}",
                event_type=EventType.PROFANITY_DETECTED,
                call_id=f"call-{i}",
                direction="caller",
                timestamp=0.0,
                confidence=0.8,
                severity=SeverityLevel.MEDIUM,
            )
            # created_at 수동 설정
            event.created_at = now - timedelta(hours=i)
            event_store.add_event(event)
        
        # 시간 범위 조회
        start_time = now - timedelta(hours=3)
        end_time = now + timedelta(hours=1)
        
        events = event_store.get_events_by_time_range(start_time, end_time)
        
        # 0, 1, 2, 3 시간 전 이벤트가 포함되어야 함
        assert len(events) == 4
    
    def test_get_events_by_severity(self, event_store):
        """심각도별 이벤트 조회"""
        # 다양한 심각도의 이벤트 추가
        severities = [
            SeverityLevel.LOW,
            SeverityLevel.MEDIUM,
            SeverityLevel.HIGH,
            SeverityLevel.CRITICAL,
        ]
        
        for i, severity in enumerate(severities):
            event = AIEvent(
                event_id=f"severity-{i}",
                event_type=EventType.PROFANITY_DETECTED,
                call_id=f"call-{i}",
                direction="caller",
                timestamp=0.0,
                confidence=0.8,
                severity=severity,
            )
            event_store.add_event(event)
        
        # 심각도별 조회
        high_events = event_store.get_events_by_severity(SeverityLevel.HIGH)
        critical_events = event_store.get_events_by_severity(SeverityLevel.CRITICAL)
        
        assert len(high_events) == 1
        assert len(critical_events) == 1
    
    def test_filter_events(self, event_store):
        """이벤트 필터링"""
        # 다양한 이벤트 추가
        events_to_add = [
            AIEvent(
                event_id="filter-1",
                event_type=EventType.ANGER_DETECTED,
                call_id="call-filter",
                direction="caller",
                timestamp=0.0,
                confidence=0.9,
                severity=SeverityLevel.HIGH,
            ),
            AIEvent(
                event_id="filter-2",
                event_type=EventType.PROFANITY_DETECTED,
                call_id="call-filter",
                direction="caller",
                timestamp=0.0,
                confidence=0.6,
                severity=SeverityLevel.MEDIUM,
            ),
            AIEvent(
                event_id="filter-3",
                event_type=EventType.ANGER_DETECTED,
                call_id="call-other",
                direction="callee",
                timestamp=0.0,
                confidence=0.8,
                severity=SeverityLevel.HIGH,
            ),
        ]
        
        for event in events_to_add:
            event_store.add_event(event)
        
        # 여러 필터 조합
        filtered = event_store.filter_events(
            call_id="call-filter",
            event_type=EventType.ANGER_DETECTED,
            min_confidence=0.8,
        )
        
        assert len(filtered) == 1
        assert filtered[0].event_id == "filter-1"
    
    def test_cleanup_old_events(self):
        """오래된 이벤트 정리"""
        # 짧은 보존 시간으로 저장소 생성
        store = EventStore(retention_hours=1)
        
        # 오래된 이벤트 추가
        old_event = AIEvent(
            event_id="old-event",
            event_type=EventType.PROFANITY_DETECTED,
            call_id="call-old",
            direction="caller",
            timestamp=0.0,
            confidence=0.8,
            severity=SeverityLevel.MEDIUM,
        )
        old_event.created_at = datetime.utcnow() - timedelta(hours=2)
        store.add_event(old_event)
        
        # 최근 이벤트 추가
        new_event = AIEvent(
            event_id="new-event",
            event_type=EventType.PROFANITY_DETECTED,
            call_id="call-new",
            direction="caller",
            timestamp=0.0,
            confidence=0.8,
            severity=SeverityLevel.MEDIUM,
        )
        store.add_event(new_event)
        
        assert store.get_event_count() == 2
        
        # 오래된 이벤트 정리
        cleaned = store.cleanup_old_events()
        
        assert cleaned == 1
        assert store.get_event_count() == 1
        assert store.get_event("old-event") is None
        assert store.get_event("new-event") is not None
    
    def test_delete_events_by_call(self, event_store):
        """Call-ID별 이벤트 삭제"""
        # 여러 이벤트 추가
        for i in range(3):
            event = AIEvent(
                event_id=f"delete-{i}",
                event_type=EventType.PROFANITY_DETECTED,
                call_id="call-to-delete",
                direction="caller",
                timestamp=0.0,
                confidence=0.8,
                severity=SeverityLevel.MEDIUM,
            )
            event_store.add_event(event)
        
        # 다른 call_id 이벤트
        other_event = AIEvent(
            event_id="keep-event",
            event_type=EventType.PROFANITY_DETECTED,
            call_id="call-to-keep",
            direction="caller",
            timestamp=0.0,
            confidence=0.8,
            severity=SeverityLevel.MEDIUM,
        )
        event_store.add_event(other_event)
        
        initial_count = event_store.get_event_count()
        
        # 삭제
        deleted = event_store.delete_events_by_call("call-to-delete")
        
        assert deleted == 3
        assert event_store.get_event_count() == initial_count - 3
        assert len(event_store.get_events_by_call("call-to-delete")) == 0
        assert len(event_store.get_events_by_call("call-to-keep")) == 1
    
    def test_get_stats(self, event_store):
        """통계 조회"""
        # 이벤트 추가
        for i in range(5):
            event = AIEvent(
                event_id=f"stats-{i}",
                event_type=EventType.PROFANITY_DETECTED,
                call_id=f"call-{i}",
                direction="caller",
                timestamp=0.0,
                confidence=0.8,
                severity=SeverityLevel.HIGH,
            )
            event_store.add_event(event)
        
        stats = event_store.get_stats()
        
        assert "current_event_count" in stats
        assert "total_events" in stats
        assert "events_by_type" in stats
        assert stats["current_event_count"] == 5
        assert stats["total_events"] >= 5
    
    def test_thread_safety(self, event_store):
        """Thread safety"""
        import threading
        
        def add_events(start_id, count):
            for i in range(count):
                event = AIEvent(
                    event_id=f"thread-{start_id}-{i}",
                    event_type=EventType.PROFANITY_DETECTED,
                    call_id=f"call-{start_id}",
                    direction="caller",
                    timestamp=0.0,
                    confidence=0.8,
                    severity=SeverityLevel.MEDIUM,
                )
                event_store.add_event(event)
        
        # 여러 스레드에서 동시 추가
        threads = []
        for i in range(5):
            thread = threading.Thread(target=add_events, args=(i, 10))
            threads.append(thread)
            thread.start()
        
        for thread in threads:
            thread.join()
        
        # 모든 이벤트가 추가되었는지 확인
        assert event_store.get_event_count() >= 50

