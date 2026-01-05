"""Event Store

메모리 내 이벤트 저장소
"""

import threading
from typing import List, Optional, Dict, Any
from datetime import datetime, timedelta
from collections import defaultdict

from src.ai.event_models import AIEvent, EventType, SeverityLevel
from src.common.logger import get_logger

logger = get_logger(__name__)


class EventStore:
    """이벤트 저장소
    
    Thread-safe 메모리 내 이벤트 저장 및 조회
    """
    
    def __init__(self, retention_hours: int = 24):
        """초기화
        
        Args:
            retention_hours: 이벤트 보존 시간 (시간)
        """
        self.retention_hours = retention_hours
        self.retention_delta = timedelta(hours=retention_hours)
        
        # 이벤트 저장소
        # Key: event_id, Value: AIEvent
        self._events: Dict[str, AIEvent] = {}
        
        # Call-ID별 인덱스
        # Key: call_id, Value: List[event_id]
        self._call_index: Dict[str, List[str]] = defaultdict(list)
        
        # 이벤트 타입별 인덱스
        # Key: event_type, Value: List[event_id]
        self._type_index: Dict[EventType, List[str]] = defaultdict(list)
        
        # Thread safety
        self._lock = threading.RLock()
        
        # 통계
        self.stats = {
            "total_events": 0,
            "events_by_type": defaultdict(int),
            "events_by_severity": defaultdict(int),
            "events_cleaned": 0,
        }
        
        logger.info("event_store_initialized", retention_hours=retention_hours)
    
    def add_event(self, event: AIEvent) -> bool:
        """이벤트 추가
        
        Args:
            event: AIEvent 객체
            
        Returns:
            성공 여부
        """
        with self._lock:
            # 중복 체크
            if event.event_id in self._events:
                logger.warning("duplicate_event_id", event_id=event.event_id)
                return False
            
            # 저장
            self._events[event.event_id] = event
            
            # 인덱스 업데이트
            self._call_index[event.call_id].append(event.event_id)
            self._type_index[event.event_type].append(event.event_id)
            
            # 통계 업데이트
            self.stats["total_events"] += 1
            self.stats["events_by_type"][event.event_type.value] += 1
            self.stats["events_by_severity"][event.severity.value] += 1
            
            logger.debug("event_added",
                        event_id=event.event_id,
                        call_id=event.call_id,
                        event_type=event.event_type.value)
            
            return True
    
    def get_event(self, event_id: str) -> Optional[AIEvent]:
        """이벤트 조회
        
        Args:
            event_id: 이벤트 ID
            
        Returns:
            AIEvent 또는 None
        """
        with self._lock:
            return self._events.get(event_id)
    
    def get_events_by_call(self, call_id: str) -> List[AIEvent]:
        """Call-ID별 이벤트 조회
        
        Args:
            call_id: Call ID
            
        Returns:
            이벤트 리스트 (시간 순)
        """
        with self._lock:
            event_ids = self._call_index.get(call_id, [])
            events = [self._events[eid] for eid in event_ids if eid in self._events]
            
            # 시간 순 정렬
            events.sort(key=lambda e: e.created_at)
            
            return events
    
    def get_events_by_type(self, event_type: EventType) -> List[AIEvent]:
        """이벤트 타입별 조회
        
        Args:
            event_type: 이벤트 타입
            
        Returns:
            이벤트 리스트
        """
        with self._lock:
            event_ids = self._type_index.get(event_type, [])
            events = [self._events[eid] for eid in event_ids if eid in self._events]
            
            return events
    
    def get_events_by_time_range(
        self,
        start_time: datetime,
        end_time: datetime
    ) -> List[AIEvent]:
        """시간 범위별 이벤트 조회
        
        Args:
            start_time: 시작 시간
            end_time: 종료 시간
            
        Returns:
            이벤트 리스트
        """
        with self._lock:
            events = [
                event for event in self._events.values()
                if start_time <= event.created_at <= end_time
            ]
            
            # 시간 순 정렬
            events.sort(key=lambda e: e.created_at)
            
            return events
    
    def get_events_by_severity(self, severity: SeverityLevel) -> List[AIEvent]:
        """심각도별 이벤트 조회
        
        Args:
            severity: 심각도 레벨
            
        Returns:
            이벤트 리스트
        """
        with self._lock:
            events = [
                event for event in self._events.values()
                if event.severity == severity
            ]
            
            return events
    
    def filter_events(
        self,
        call_id: Optional[str] = None,
        event_type: Optional[EventType] = None,
        severity: Optional[SeverityLevel] = None,
        min_confidence: Optional[float] = None,
        start_time: Optional[datetime] = None,
        end_time: Optional[datetime] = None,
    ) -> List[AIEvent]:
        """이벤트 필터링
        
        Args:
            call_id: Call ID
            event_type: 이벤트 타입
            severity: 심각도
            min_confidence: 최소 신뢰도
            start_time: 시작 시간
            end_time: 종료 시간
            
        Returns:
            필터링된 이벤트 리스트
        """
        with self._lock:
            events = list(self._events.values())
            
            # 필터 적용
            if call_id:
                events = [e for e in events if e.call_id == call_id]
            
            if event_type:
                events = [e for e in events if e.event_type == event_type]
            
            if severity:
                events = [e for e in events if e.severity == severity]
            
            if min_confidence is not None:
                events = [e for e in events if e.confidence >= min_confidence]
            
            if start_time:
                events = [e for e in events if e.created_at >= start_time]
            
            if end_time:
                events = [e for e in events if e.created_at <= end_time]
            
            # 시간 순 정렬
            events.sort(key=lambda e: e.created_at)
            
            return events
    
    def get_all_events(self) -> List[AIEvent]:
        """모든 이벤트 조회
        
        Returns:
            모든 이벤트 리스트 (시간 순)
        """
        with self._lock:
            events = list(self._events.values())
            events.sort(key=lambda e: e.created_at)
            
            return events
    
    def cleanup_old_events(self) -> int:
        """오래된 이벤트 정리
        
        Returns:
            정리된 이벤트 수
        """
        with self._lock:
            cutoff_time = datetime.utcnow() - self.retention_delta
            
            # 오래된 이벤트 찾기
            old_event_ids = [
                event_id for event_id, event in self._events.items()
                if event.created_at < cutoff_time
            ]
            
            # 삭제
            for event_id in old_event_ids:
                event = self._events[event_id]
                
                # 저장소에서 삭제
                del self._events[event_id]
                
                # 인덱스에서 삭제
                if event.call_id in self._call_index:
                    self._call_index[event.call_id].remove(event_id)
                    
                    # 빈 리스트 정리
                    if not self._call_index[event.call_id]:
                        del self._call_index[event.call_id]
                
                if event.event_type in self._type_index:
                    self._type_index[event.event_type].remove(event_id)
                    
                    # 빈 리스트 정리
                    if not self._type_index[event.event_type]:
                        del self._type_index[event.event_type]
            
            cleaned_count = len(old_event_ids)
            
            if cleaned_count > 0:
                self.stats["events_cleaned"] += cleaned_count
                logger.info("old_events_cleaned",
                           count=cleaned_count,
                           cutoff_time=cutoff_time.isoformat())
            
            return cleaned_count
    
    def delete_events_by_call(self, call_id: str) -> int:
        """Call-ID별 이벤트 삭제
        
        Args:
            call_id: Call ID
            
        Returns:
            삭제된 이벤트 수
        """
        with self._lock:
            event_ids = self._call_index.get(call_id, []).copy()
            
            for event_id in event_ids:
                if event_id in self._events:
                    event = self._events[event_id]
                    
                    # 저장소에서 삭제
                    del self._events[event_id]
                    
                    # 타입 인덱스에서 삭제
                    if event.event_type in self._type_index:
                        self._type_index[event.event_type].remove(event_id)
            
            # Call 인덱스에서 삭제
            if call_id in self._call_index:
                del self._call_index[call_id]
            
            logger.debug("events_deleted_by_call",
                        call_id=call_id,
                        count=len(event_ids))
            
            return len(event_ids)
    
    def get_event_count(self) -> int:
        """이벤트 개수 조회"""
        with self._lock:
            return len(self._events)
    
    def get_stats(self) -> Dict[str, Any]:
        """통계 조회"""
        with self._lock:
            return {
                "current_event_count": len(self._events),
                "call_count": len(self._call_index),
                **self.stats,
            }
    
    def clear_all(self):
        """모든 이벤트 삭제 (테스트용)"""
        with self._lock:
            self._events.clear()
            self._call_index.clear()
            self._type_index.clear()
            
            logger.warning("all_events_cleared")

