"""Statistics Collector 테스트"""

import pytest
from datetime import datetime, timedelta

from src.events.statistics import StatisticsCollector, get_statistics
from src.ai.event_models import AIEvent, EventType, SeverityLevel
from src.common.logger import setup_logging


@pytest.fixture(scope="module", autouse=True)
def setup_test_logging():
    """테스트용 로깅 설정"""
    setup_logging(level="DEBUG", format_type="text")


@pytest.fixture
def statistics():
    """통계 수집기"""
    stats = get_statistics()
    stats.reset_stats()  # 테스트 전 초기화
    return stats


class TestStatisticsCollector:
    """StatisticsCollector 테스트"""
    
    def test_singleton_pattern(self):
        """Singleton 패턴"""
        stats1 = StatisticsCollector()
        stats2 = StatisticsCollector()
        
        assert stats1 is stats2
    
    def test_get_statistics(self):
        """get_statistics 함수"""
        stats1 = get_statistics()
        stats2 = get_statistics()
        
        assert stats1 is stats2


class TestCallStatistics:
    """통화 통계 테스트"""
    
    def test_start_call(self, statistics):
        """통화 시작"""
        statistics.start_call("call-1")
        
        assert statistics.get_active_call_count() == 1
        assert statistics.total_calls_today == 1
    
    def test_end_call(self, statistics):
        """통화 종료"""
        statistics.start_call("call-2")
        statistics.end_call("call-2", 60.5)
        
        assert statistics.get_active_call_count() == 0
        assert len(statistics.call_durations) == 1
    
    def test_get_active_calls(self, statistics):
        """활성 통화 리스트"""
        statistics.start_call("call-3")
        statistics.start_call("call-4")
        
        active_calls = statistics.get_active_calls()
        
        assert len(active_calls) == 2
        assert any(c["call_id"] == "call-3" for c in active_calls)
        assert any(c["call_id"] == "call-4" for c in active_calls)
    
    def test_average_call_duration(self, statistics):
        """평균 통화 시간"""
        statistics.end_call("call-5", 60.0)
        statistics.end_call("call-6", 120.0)
        statistics.end_call("call-7", 90.0)
        
        avg = statistics.get_average_call_duration()
        
        assert avg == pytest.approx(90.0, rel=0.1)
    
    def test_average_call_duration_empty(self, statistics):
        """빈 통화 시간 (평균 0)"""
        avg = statistics.get_average_call_duration()
        
        assert avg == 0.0


class TestEventStatistics:
    """이벤트 통계 테스트"""
    
    def test_record_event(self, statistics):
        """이벤트 기록"""
        event = AIEvent(
            event_id="event-1",
            event_type=EventType.PROFANITY_DETECTED,
            call_id="call-1",
            direction="caller",
            timestamp=0.0,
            confidence=0.9,
            severity=SeverityLevel.HIGH,
        )
        
        statistics.record_event(event)
        
        counts = statistics.get_event_counts()
        assert counts["total"] == 1
        assert counts["profanity"] == 1
    
    def test_record_multiple_event_types(self, statistics):
        """여러 이벤트 타입 기록"""
        events = [
            AIEvent(
                event_id=f"event-prof-{i}",
                event_type=EventType.PROFANITY_DETECTED,
                call_id="call-1",
                direction="caller",
                timestamp=0.0,
                confidence=0.9,
                severity=SeverityLevel.HIGH,
            )
            for i in range(3)
        ] + [
            AIEvent(
                event_id=f"event-anger-{i}",
                event_type=EventType.ANGER_DETECTED,
                call_id="call-1",
                direction="caller",
                timestamp=0.0,
                confidence=0.8,
                severity=SeverityLevel.MEDIUM,
            )
            for i in range(2)
        ] + [
            AIEvent(
                event_id="event-threat",
                event_type=EventType.THREATENING_LANGUAGE,
                call_id="call-1",
                direction="caller",
                timestamp=0.0,
                confidence=0.95,
                severity=SeverityLevel.CRITICAL,
            )
        ]
        
        for event in events:
            statistics.record_event(event)
        
        counts = statistics.get_event_counts()
        assert counts["total"] == 6
        assert counts["profanity"] == 3
        assert counts["anger"] == 2
        assert counts["threatening"] == 1
    
    def test_get_top_keywords(self, statistics):
        """Top 키워드 조회"""
        # 키워드가 있는 이벤트 생성
        for i in range(5):
            event = AIEvent(
                event_id=f"event-kw-{i}",
                event_type=EventType.PROFANITY_DETECTED,
                call_id="call-1",
                direction="caller",
                timestamp=0.0,
                confidence=0.9,
                severity=SeverityLevel.HIGH,
                details={"keywords": ["bad", "word"]},
            )
            statistics.record_event(event)
        
        top_keywords = statistics.get_top_keywords(limit=5)
        
        assert len(top_keywords) > 0
        # "bad"와 "word"가 모두 5번씩 기록되어야 함
        keyword_dict = {kw["keyword"]: kw["count"] for kw in top_keywords}
        assert keyword_dict.get("bad", 0) == 5
        assert keyword_dict.get("word", 0) == 5
    
    def test_get_recent_events(self, statistics):
        """최근 이벤트 조회"""
        # 여러 이벤트 생성
        for i in range(10):
            event = AIEvent(
                event_id=f"recent-{i}",
                event_type=EventType.PROFANITY_DETECTED,
                call_id="call-1",
                direction="caller",
                timestamp=0.0,
                confidence=0.9,
                severity=SeverityLevel.HIGH,
            )
            statistics.record_event(event)
        
        recent = statistics.get_recent_events(limit=5)
        
        assert len(recent) == 5
        # 최신순으로 정렬되어야 함
        assert recent[0]["event_id"] == "recent-9"
    
    def test_get_hourly_heatmap(self, statistics):
        """시간대별 히트맵 데이터"""
        event = AIEvent(
            event_id="heatmap-event",
            event_type=EventType.PROFANITY_DETECTED,
            call_id="call-1",
            direction="caller",
            timestamp=0.0,
            confidence=0.9,
            severity=SeverityLevel.HIGH,
        )
        statistics.record_event(event)
        
        heatmap = statistics.get_hourly_heatmap()
        
        assert "data" in heatmap
        assert "day_names" in heatmap
        assert len(heatmap["day_names"]) == 7
        assert len(heatmap["data"]) > 0
    
    def test_get_minute_timeseries(self, statistics):
        """분 단위 시계열 데이터"""
        event = AIEvent(
            event_id="timeseries-event",
            event_type=EventType.PROFANITY_DETECTED,
            call_id="call-1",
            direction="caller",
            timestamp=0.0,
            confidence=0.9,
            severity=SeverityLevel.HIGH,
        )
        statistics.record_event(event)
        
        timeseries = statistics.get_minute_timeseries(duration_minutes=10)
        
        assert len(timeseries) == 10
        # 각 데이터 포인트에 timestamp와 count가 있어야 함
        for point in timeseries:
            assert "timestamp" in point
            assert "count" in point


class TestDashboardStatistics:
    """대시보드 통계 테스트"""
    
    def test_get_dashboard_stats(self, statistics):
        """대시보드 통계 조회"""
        # 통화 시작
        statistics.start_call("dash-call-1")
        statistics.start_call("dash-call-2")
        
        # 이벤트 기록
        event = AIEvent(
            event_id="dash-event",
            event_type=EventType.PROFANITY_DETECTED,
            call_id="dash-call-1",
            direction="caller",
            timestamp=0.0,
            confidence=0.9,
            severity=SeverityLevel.HIGH,
            details={"keywords": ["test"]},
        )
        statistics.record_event(event)
        
        # 통화 종료
        statistics.end_call("dash-call-1", 120.5)
        
        # 대시보드 통계 조회
        stats = statistics.get_dashboard_stats()
        
        assert "calls" in stats
        assert "events" in stats
        assert "top_keywords" in stats
        assert "timestamp" in stats
        
        # 통화 통계 확인
        assert stats["calls"]["active"] == 1  # dash-call-2만 활성
        assert stats["calls"]["average_duration"] > 0
        
        # 이벤트 통계 확인
        assert stats["events"]["total"] == 1
        assert stats["events"]["profanity"] == 1
    
    def test_full_scenario(self, statistics):
        """전체 시나리오"""
        # 1. 통화 시작
        for i in range(5):
            statistics.start_call(f"scenario-call-{i}")
        
        # 2. 일부 통화 종료
        statistics.end_call("scenario-call-0", 30.0)
        statistics.end_call("scenario-call-1", 60.0)
        statistics.end_call("scenario-call-2", 90.0)
        
        # 3. 이벤트 발생
        event_types = [
            EventType.PROFANITY_DETECTED,
            EventType.ANGER_DETECTED,
            EventType.THREATENING_LANGUAGE,
            EventType.PROFANITY_DETECTED,
            EventType.ANGER_DETECTED,
        ]
        
        for i, event_type in enumerate(event_types):
            event = AIEvent(
                event_id=f"scenario-event-{i}",
                event_type=event_type,
                call_id=f"scenario-call-{i}",
                direction="caller",
                timestamp=0.0,
                confidence=0.9,
                severity=SeverityLevel.HIGH,
                details={"keywords": [f"keyword-{i}"]},
            )
            statistics.record_event(event)
        
        # 4. 통계 확인
        stats = statistics.get_dashboard_stats()
        
        assert stats["calls"]["active"] == 2  # call-3, call-4
        assert stats["calls"]["today"] == 5
        assert stats["events"]["total"] == 5
        assert stats["events"]["profanity"] == 2
        assert stats["events"]["anger"] == 2
        assert stats["events"]["threatening"] == 1


class TestStatisticsReset:
    """통계 초기화 테스트"""
    
    def test_reset_stats(self, statistics):
        """통계 초기화"""
        # 데이터 추가
        statistics.start_call("reset-call")
        
        event = AIEvent(
            event_id="reset-event",
            event_type=EventType.PROFANITY_DETECTED,
            call_id="reset-call",
            direction="caller",
            timestamp=0.0,
            confidence=0.9,
            severity=SeverityLevel.HIGH,
        )
        statistics.record_event(event)
        
        # 초기화
        statistics.reset_stats()
        
        # 확인
        assert statistics.get_active_call_count() == 0
        assert statistics.total_calls_today == 0
        counts = statistics.get_event_counts()
        assert counts["total"] == 0

