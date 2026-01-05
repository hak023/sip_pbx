"""Prometheus Metrics

시스템 모니터링을 위한 Prometheus 메트릭 정의 및 수집
"""

from prometheus_client import (
    Counter,
    Gauge,
    Histogram,
    CollectorRegistry,
    generate_latest,
    CONTENT_TYPE_LATEST,
)
from typing import Optional
import threading

from src.common.logger import get_logger

logger = get_logger(__name__)


class PrometheusMetrics:
    """Prometheus 메트릭 관리자
    
    모든 시스템 메트릭을 중앙에서 관리
    """
    
    _instance: Optional['PrometheusMetrics'] = None
    _lock = threading.Lock()
    
    def __new__(cls):
        """Singleton 패턴"""
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
        return cls._instance
    
    def __init__(self):
        """메트릭 초기화"""
        # 이미 초기화된 경우 스킵
        if hasattr(self, '_initialized'):
            return
        
        self._initialized = True
        self.registry = CollectorRegistry()
        
        # ===== SIP 메트릭 =====
        self.sip_requests_total = Counter(
            'sip_requests_total',
            'Total SIP requests',
            ['method', 'status'],
            registry=self.registry
        )
        
        self.sip_active_calls = Gauge(
            'sip_active_calls',
            'Current number of active SIP calls',
            registry=self.registry
        )
        
        self.sip_call_duration_seconds = Histogram(
            'sip_call_duration_seconds',
            'SIP call duration in seconds',
            buckets=[1, 5, 10, 30, 60, 120, 300, 600, 1800, 3600],
            registry=self.registry
        )
        
        # ===== 미디어 메트릭 =====
        self.media_port_pool_available = Gauge(
            'media_port_pool_available',
            'Available media ports in the pool',
            registry=self.registry
        )
        
        self.media_port_pool_used = Gauge(
            'media_port_pool_used',
            'Used media ports in the pool',
            registry=self.registry
        )
        
        self.rtp_packets_received_total = Counter(
            'rtp_packets_received_total',
            'Total RTP packets received',
            ['direction'],
            registry=self.registry
        )
        
        self.rtp_packets_dropped_total = Counter(
            'rtp_packets_dropped_total',
            'Total RTP packets dropped',
            ['direction', 'reason'],
            registry=self.registry
        )
        
        # ===== AI 메트릭 =====
        self.ai_stt_latency_seconds = Histogram(
            'ai_stt_latency_seconds',
            'STT inference latency in seconds',
            buckets=[0.1, 0.5, 1.0, 2.0, 3.0, 5.0, 10.0],
            registry=self.registry
        )
        
        self.ai_emotion_latency_seconds = Histogram(
            'ai_emotion_latency_seconds',
            'Emotion analysis latency in seconds',
            buckets=[0.05, 0.1, 0.2, 0.5, 1.0, 2.0],
            registry=self.registry
        )
        
        self.ai_text_classification_latency_seconds = Histogram(
            'ai_text_classification_latency_seconds',
            'Text classification latency in seconds',
            buckets=[0.01, 0.05, 0.1, 0.2, 0.5, 1.0],
            registry=self.registry
        )
        
        self.ai_gpu_utilization_percent = Gauge(
            'ai_gpu_utilization_percent',
            'GPU utilization percentage',
            registry=self.registry
        )
        
        self.ai_gpu_memory_used_bytes = Gauge(
            'ai_gpu_memory_used_bytes',
            'GPU memory used in bytes',
            registry=self.registry
        )
        
        self.ai_inference_total = Counter(
            'ai_inference_total',
            'Total AI inferences',
            ['module'],
            registry=self.registry
        )
        
        # ===== 이벤트 메트릭 =====
        self.events_generated_total = Counter(
            'events_generated_total',
            'Total events generated',
            ['event_type', 'severity'],
            registry=self.registry
        )
        
        self.webhook_sent_total = Counter(
            'webhook_sent_total',
            'Total webhooks sent',
            ['status'],
            registry=self.registry
        )
        
        self.cdr_written_total = Counter(
            'cdr_written_total',
            'Total CDRs written',
            registry=self.registry
        )
        
        logger.info("prometheus_metrics_initialized")
    
    # ===== SIP 메트릭 업데이트 메서드 =====
    
    def record_sip_request(self, method: str, status: str):
        """SIP 요청 기록
        
        Args:
            method: SIP 메서드 (INVITE, BYE, etc.)
            status: 응답 상태 (2xx, 4xx, 5xx)
        """
        self.sip_requests_total.labels(method=method, status=status).inc()
    
    def set_active_calls(self, count: int):
        """활성 통화 수 설정
        
        Args:
            count: 활성 통화 수
        """
        self.sip_active_calls.set(count)
    
    def record_call_duration(self, duration_seconds: float):
        """통화 시간 기록
        
        Args:
            duration_seconds: 통화 시간 (초)
        """
        self.sip_call_duration_seconds.observe(duration_seconds)
    
    # ===== 미디어 메트릭 업데이트 메서드 =====
    
    def set_port_pool_stats(self, available: int, used: int):
        """포트 풀 통계 설정
        
        Args:
            available: 사용 가능한 포트 수
            used: 사용 중인 포트 수
        """
        self.media_port_pool_available.set(available)
        self.media_port_pool_used.set(used)
    
    def record_rtp_packet_received(self, direction: str):
        """RTP 패킷 수신 기록
        
        Args:
            direction: 방향 (caller, callee)
        """
        self.rtp_packets_received_total.labels(direction=direction).inc()
    
    def record_rtp_packet_dropped(self, direction: str, reason: str = "unknown"):
        """RTP 패킷 드롭 기록
        
        Args:
            direction: 방향 (caller, callee)
            reason: 드롭 사유
        """
        self.rtp_packets_dropped_total.labels(direction=direction, reason=reason).inc()
    
    # ===== AI 메트릭 업데이트 메서드 =====
    
    def record_stt_latency(self, latency_seconds: float):
        """STT 지연 시간 기록
        
        Args:
            latency_seconds: 지연 시간 (초)
        """
        self.ai_stt_latency_seconds.observe(latency_seconds)
        self.ai_inference_total.labels(module="stt").inc()
    
    def record_emotion_latency(self, latency_seconds: float):
        """감정 분석 지연 시간 기록
        
        Args:
            latency_seconds: 지연 시간 (초)
        """
        self.ai_emotion_latency_seconds.observe(latency_seconds)
        self.ai_inference_total.labels(module="emotion").inc()
    
    def record_text_classification_latency(self, latency_seconds: float):
        """텍스트 분류 지연 시간 기록
        
        Args:
            latency_seconds: 지연 시간 (초)
        """
        self.ai_text_classification_latency_seconds.observe(latency_seconds)
        self.ai_inference_total.labels(module="text_classifier").inc()
    
    def set_gpu_utilization(self, utilization_percent: float):
        """GPU 사용률 설정
        
        Args:
            utilization_percent: 사용률 (%)
        """
        self.ai_gpu_utilization_percent.set(utilization_percent)
    
    def set_gpu_memory_used(self, memory_bytes: int):
        """GPU 메모리 사용량 설정
        
        Args:
            memory_bytes: 메모리 사용량 (bytes)
        """
        self.ai_gpu_memory_used_bytes.set(memory_bytes)
    
    # ===== 이벤트 메트릭 업데이트 메서드 =====
    
    def record_event_generated(self, event_type: str, severity: str):
        """이벤트 생성 기록
        
        Args:
            event_type: 이벤트 타입
            severity: 심각도
        """
        self.events_generated_total.labels(
            event_type=event_type,
            severity=severity
        ).inc()
    
    def record_webhook_sent(self, success: bool):
        """Webhook 전송 기록
        
        Args:
            success: 전송 성공 여부
        """
        status = "success" if success else "failure"
        self.webhook_sent_total.labels(status=status).inc()
    
    def record_cdr_written(self):
        """CDR 작성 기록"""
        self.cdr_written_total.inc()
    
    # ===== 메트릭 출력 =====
    
    def generate_metrics(self) -> bytes:
        """Prometheus 형식으로 메트릭 생성
        
        Returns:
            메트릭 데이터 (bytes)
        """
        return generate_latest(self.registry)
    
    def get_content_type(self) -> str:
        """Content-Type 헤더 반환
        
        Returns:
            Content-Type
        """
        return CONTENT_TYPE_LATEST


# Singleton 인스턴스 가져오기
def get_metrics() -> PrometheusMetrics:
    """메트릭 인스턴스 조회
    
    Returns:
        PrometheusMetrics 인스턴스
    """
    return PrometheusMetrics()

