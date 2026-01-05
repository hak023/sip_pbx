"""Statistics Collector

실시간 통계 수집 및 제공
"""

import threading
from datetime import datetime, timedelta
from typing import Dict, List, Any, Optional
from collections import defaultdict, deque

from src.ai.event_models import AIEvent
from src.events.cdr import CDR
from src.common.logger import get_logger

logger = get_logger(__name__)


class StatisticsCollector:
    """통계 수집기
    
    시스템 전체의 실시간 통계 수집 및 제공
    """
    
    _instance: Optional['StatisticsCollector'] = None
    _lock = threading.Lock()
    
    def __new__(cls):
        """Singleton 패턴"""
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
        return cls._instance
    
    def __init__(self):
        """초기화"""
        # 이미 초기화된 경우 스킵
        if hasattr(self, '_initialized'):
            return
        
        self._initialized = True
        
        # Thread safety
        self._stats_lock = threading.RLock()
        
        # 통화 통계
        self.active_calls: Dict[str, datetime] = {}
        self.total_calls_today = 0
        self.total_calls_week = 0
        self.total_calls_month = 0
        self.call_durations: deque = deque(maxlen=1000)  # 최근 1000개
        
        # 이벤트 통계
        self.event_counts = {
            "profanity": 0,
            "anger": 0,
            "threatening": 0,
            "total": 0,
        }
        
        # 시간대별 이벤트 (히트맵용)
        # Key: (hour, day_of_week), Value: count
        self.hourly_events: Dict[tuple, int] = defaultdict(int)
        
        # 키워드 빈도
        # Key: keyword, Value: count
        self.keyword_counts: Dict[str, int] = defaultdict(int)
        
        # 최근 이벤트 (최대 1000개)
        self.recent_events: deque = deque(maxlen=1000)
        
        # 시계열 데이터 (분 단위)
        # Key: timestamp (minute), Value: count
        self.minute_stats: Dict[str, int] = defaultdict(int)
        
        logger.info("statistics_collector_initialized")
    
    # ===== 통화 통계 =====
    
    def start_call(self, call_id: str):
        """통화 시작 기록
        
        Args:
            call_id: Call ID
        """
        with self._stats_lock:
            self.active_calls[call_id] = datetime.utcnow()
            self.total_calls_today += 1
            self.total_calls_week += 1
            self.total_calls_month += 1
            
            logger.debug("call_started_stats", call_id=call_id)
    
    def end_call(self, call_id: str, duration: float):
        """통화 종료 기록
        
        Args:
            call_id: Call ID
            duration: 통화 시간 (초)
        """
        with self._stats_lock:
            if call_id in self.active_calls:
                del self.active_calls[call_id]
            
            self.call_durations.append(duration)
            
            logger.debug("call_ended_stats", call_id=call_id, duration=duration)
    
    def get_active_call_count(self) -> int:
        """활성 통화 수 조회"""
        with self._stats_lock:
            return len(self.active_calls)
    
    def get_active_calls(self) -> List[Dict[str, Any]]:
        """활성 통화 리스트 조회"""
        with self._stats_lock:
            now = datetime.utcnow()
            return [
                {
                    "call_id": call_id,
                    "start_time": start_time.isoformat(),
                    "duration_seconds": (now - start_time).total_seconds(),
                }
                for call_id, start_time in self.active_calls.items()
            ]
    
    def get_average_call_duration(self) -> float:
        """평균 통화 시간 조회 (초)"""
        with self._stats_lock:
            if not self.call_durations:
                return 0.0
            
            return sum(self.call_durations) / len(self.call_durations)
    
    # ===== 이벤트 통계 =====
    
    def record_event(self, event: AIEvent):
        """이벤트 기록
        
        Args:
            event: AIEvent 객체
        """
        with self._stats_lock:
            # 이벤트 카운트
            self.event_counts["total"] += 1
            
            event_type = event.event_type.value.lower()
            
            if "profanity" in event_type:
                self.event_counts["profanity"] += 1
            
            if "anger" in event_type:
                self.event_counts["anger"] += 1
            
            if "threatening" in event_type:
                self.event_counts["threatening"] += 1
            
            # 시간대별 이벤트 (히트맵)
            now = datetime.utcnow()
            hour = now.hour
            day_of_week = now.weekday()  # 0=Monday, 6=Sunday
            self.hourly_events[(hour, day_of_week)] += 1
            
            # 키워드 추출 (details에서)
            if "keywords" in event.details:
                keywords = event.details.get("keywords", [])
                if isinstance(keywords, list):
                    for keyword in keywords:
                        self.keyword_counts[str(keyword)] += 1
            
            # 최근 이벤트 저장
            self.recent_events.append({
                "event_id": event.event_id,
                "call_id": event.call_id,
                "event_type": event.event_type.value,
                "severity": event.severity.value,
                "confidence": event.confidence,
                "timestamp": event.created_at.isoformat(),
            })
            
            # 분 단위 시계열
            minute_key = now.strftime("%Y-%m-%d %H:%M")
            self.minute_stats[minute_key] += 1
            
            logger.debug("event_recorded_stats", event_id=event.event_id)
    
    def get_event_counts(self) -> Dict[str, int]:
        """이벤트 카운트 조회"""
        with self._stats_lock:
            return self.event_counts.copy()
    
    def get_top_keywords(self, limit: int = 10) -> List[Dict[str, Any]]:
        """Top 키워드 조회
        
        Args:
            limit: 반환할 키워드 수
            
        Returns:
            키워드 리스트 (빈도 순)
        """
        with self._stats_lock:
            sorted_keywords = sorted(
                self.keyword_counts.items(),
                key=lambda x: x[1],
                reverse=True
            )[:limit]
            
            return [
                {"keyword": keyword, "count": count}
                for keyword, count in sorted_keywords
            ]
    
    def get_hourly_heatmap(self) -> Dict[str, Any]:
        """시간대별 히트맵 데이터 조회
        
        Returns:
            히트맵 데이터 (hour, day_of_week, count)
        """
        with self._stats_lock:
            heatmap_data = []
            
            for (hour, day_of_week), count in self.hourly_events.items():
                heatmap_data.append({
                    "hour": hour,
                    "day_of_week": day_of_week,
                    "count": count,
                })
            
            return {
                "data": heatmap_data,
                "day_names": ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"],
            }
    
    def get_recent_events(self, limit: int = 100) -> List[Dict[str, Any]]:
        """최근 이벤트 조회
        
        Args:
            limit: 반환할 이벤트 수
            
        Returns:
            최근 이벤트 리스트
        """
        with self._stats_lock:
            # deque를 리스트로 변환하고 역순 (최신순)
            events = list(self.recent_events)
            events.reverse()
            
            return events[:limit]
    
    def get_minute_timeseries(self, duration_minutes: int = 60) -> List[Dict[str, Any]]:
        """분 단위 시계열 데이터 조회
        
        Args:
            duration_minutes: 조회할 기간 (분)
            
        Returns:
            시계열 데이터
        """
        with self._stats_lock:
            now = datetime.utcnow()
            timeseries = []
            
            for i in range(duration_minutes):
                time_point = now - timedelta(minutes=duration_minutes - i - 1)
                minute_key = time_point.strftime("%Y-%m-%d %H:%M")
                
                count = self.minute_stats.get(minute_key, 0)
                
                timeseries.append({
                    "timestamp": minute_key,
                    "count": count,
                })
            
            return timeseries
    
    # ===== 전체 통계 =====
    
    def get_dashboard_stats(self) -> Dict[str, Any]:
        """대시보드용 전체 통계 조회
        
        Returns:
            전체 통계 데이터
        """
        with self._stats_lock:
            return {
                "calls": {
                    "active": len(self.active_calls),
                    "today": self.total_calls_today,
                    "week": self.total_calls_week,
                    "month": self.total_calls_month,
                    "average_duration": self.get_average_call_duration(),
                },
                "events": self.event_counts.copy(),
                "top_keywords": self.get_top_keywords(10),
                "timestamp": datetime.utcnow().isoformat(),
            }
    
    def reset_stats(self):
        """통계 초기화 (테스트용)"""
        with self._stats_lock:
            self.active_calls.clear()
            self.total_calls_today = 0
            self.total_calls_week = 0
            self.total_calls_month = 0
            self.call_durations.clear()
            self.event_counts = {
                "profanity": 0,
                "anger": 0,
                "threatening": 0,
                "total": 0,
            }
            self.hourly_events.clear()
            self.keyword_counts.clear()
            self.recent_events.clear()
            self.minute_stats.clear()
            
            logger.warning("statistics_reset")


# Singleton 인스턴스 가져오기
def get_statistics() -> StatisticsCollector:
    """통계 수집기 인스턴스 조회
    
    Returns:
        StatisticsCollector 인스턴스
    """
    return StatisticsCollector()

