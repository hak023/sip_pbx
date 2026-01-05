"""Prometheus Metrics 테스트"""

import pytest
from prometheus_client import REGISTRY

from src.monitoring.metrics import PrometheusMetrics, get_metrics
from src.common.logger import setup_logging


@pytest.fixture(scope="module", autouse=True)
def setup_test_logging():
    """테스트용 로깅 설정"""
    setup_logging(level="DEBUG", format_type="text")


@pytest.fixture
def metrics():
    """메트릭 인스턴스"""
    return get_metrics()


class TestPrometheusMetrics:
    """PrometheusMetrics 테스트"""
    
    def test_singleton_pattern(self):
        """Singleton 패턴"""
        metrics1 = PrometheusMetrics()
        metrics2 = PrometheusMetrics()
        
        assert metrics1 is metrics2
    
    def test_get_metrics(self):
        """get_metrics 함수"""
        metrics1 = get_metrics()
        metrics2 = get_metrics()
        
        assert metrics1 is metrics2
    
    def test_sip_metrics_exist(self, metrics):
        """SIP 메트릭 존재 확인"""
        assert hasattr(metrics, 'sip_requests_total')
        assert hasattr(metrics, 'sip_active_calls')
        assert hasattr(metrics, 'sip_call_duration_seconds')
    
    def test_media_metrics_exist(self, metrics):
        """미디어 메트릭 존재 확인"""
        assert hasattr(metrics, 'media_port_pool_available')
        assert hasattr(metrics, 'media_port_pool_used')
        assert hasattr(metrics, 'rtp_packets_received_total')
        assert hasattr(metrics, 'rtp_packets_dropped_total')
    
    def test_ai_metrics_exist(self, metrics):
        """AI 메트릭 존재 확인"""
        assert hasattr(metrics, 'ai_stt_latency_seconds')
        assert hasattr(metrics, 'ai_emotion_latency_seconds')
        assert hasattr(metrics, 'ai_text_classification_latency_seconds')
        assert hasattr(metrics, 'ai_gpu_utilization_percent')
        assert hasattr(metrics, 'ai_gpu_memory_used_bytes')
        assert hasattr(metrics, 'ai_inference_total')
    
    def test_event_metrics_exist(self, metrics):
        """이벤트 메트릭 존재 확인"""
        assert hasattr(metrics, 'events_generated_total')
        assert hasattr(metrics, 'webhook_sent_total')
        assert hasattr(metrics, 'cdr_written_total')


class TestSIPMetrics:
    """SIP 메트릭 테스트"""
    
    def test_record_sip_request(self, metrics):
        """SIP 요청 기록"""
        metrics.record_sip_request("INVITE", "2xx")
        metrics.record_sip_request("INVITE", "4xx")
        metrics.record_sip_request("BYE", "2xx")
        
        # 메트릭 생성 확인
        output = metrics.generate_metrics().decode('utf-8')
        assert 'sip_requests_total' in output
    
    def test_set_active_calls(self, metrics):
        """활성 통화 수 설정"""
        metrics.set_active_calls(10)
        
        output = metrics.generate_metrics().decode('utf-8')
        assert 'sip_active_calls' in output
    
    def test_record_call_duration(self, metrics):
        """통화 시간 기록"""
        metrics.record_call_duration(30.5)
        metrics.record_call_duration(120.0)
        metrics.record_call_duration(600.5)
        
        output = metrics.generate_metrics().decode('utf-8')
        assert 'sip_call_duration_seconds' in output


class TestMediaMetrics:
    """미디어 메트릭 테스트"""
    
    def test_set_port_pool_stats(self, metrics):
        """포트 풀 통계 설정"""
        metrics.set_port_pool_stats(available=100, used=50)
        
        output = metrics.generate_metrics().decode('utf-8')
        assert 'media_port_pool_available' in output
        assert 'media_port_pool_used' in output
    
    def test_record_rtp_packet_received(self, metrics):
        """RTP 패킷 수신 기록"""
        metrics.record_rtp_packet_received("caller")
        metrics.record_rtp_packet_received("callee")
        
        output = metrics.generate_metrics().decode('utf-8')
        assert 'rtp_packets_received_total' in output
    
    def test_record_rtp_packet_dropped(self, metrics):
        """RTP 패킷 드롭 기록"""
        metrics.record_rtp_packet_dropped("caller", "timeout")
        metrics.record_rtp_packet_dropped("callee", "buffer_full")
        
        output = metrics.generate_metrics().decode('utf-8')
        assert 'rtp_packets_dropped_total' in output


class TestAIMetrics:
    """AI 메트릭 테스트"""
    
    def test_record_stt_latency(self, metrics):
        """STT 지연 시간 기록"""
        metrics.record_stt_latency(1.5)
        metrics.record_stt_latency(2.3)
        
        output = metrics.generate_metrics().decode('utf-8')
        assert 'ai_stt_latency_seconds' in output
        assert 'ai_inference_total{module="stt"}' in output
    
    def test_record_emotion_latency(self, metrics):
        """감정 분석 지연 시간 기록"""
        metrics.record_emotion_latency(0.5)
        metrics.record_emotion_latency(0.8)
        
        output = metrics.generate_metrics().decode('utf-8')
        assert 'ai_emotion_latency_seconds' in output
    
    def test_record_text_classification_latency(self, metrics):
        """텍스트 분류 지연 시간 기록"""
        metrics.record_text_classification_latency(0.1)
        metrics.record_text_classification_latency(0.2)
        
        output = metrics.generate_metrics().decode('utf-8')
        assert 'ai_text_classification_latency_seconds' in output
    
    def test_set_gpu_utilization(self, metrics):
        """GPU 사용률 설정"""
        metrics.set_gpu_utilization(75.5)
        
        output = metrics.generate_metrics().decode('utf-8')
        assert 'ai_gpu_utilization_percent' in output
    
    def test_set_gpu_memory_used(self, metrics):
        """GPU 메모리 사용량 설정"""
        metrics.set_gpu_memory_used(8589934592)  # 8GB
        
        output = metrics.generate_metrics().decode('utf-8')
        assert 'ai_gpu_memory_used_bytes' in output


class TestEventMetrics:
    """이벤트 메트릭 테스트"""
    
    def test_record_event_generated(self, metrics):
        """이벤트 생성 기록"""
        metrics.record_event_generated("profanity_detected", "high")
        metrics.record_event_generated("anger_detected", "medium")
        metrics.record_event_generated("threatening_language", "critical")
        
        output = metrics.generate_metrics().decode('utf-8')
        assert 'events_generated_total' in output
    
    def test_record_webhook_sent(self, metrics):
        """Webhook 전송 기록"""
        metrics.record_webhook_sent(success=True)
        metrics.record_webhook_sent(success=False)
        
        output = metrics.generate_metrics().decode('utf-8')
        assert 'webhook_sent_total' in output
    
    def test_record_cdr_written(self, metrics):
        """CDR 작성 기록"""
        metrics.record_cdr_written()
        metrics.record_cdr_written()
        
        output = metrics.generate_metrics().decode('utf-8')
        assert 'cdr_written_total' in output


class TestMetricsExport:
    """메트릭 출력 테스트"""
    
    def test_generate_metrics(self, metrics):
        """메트릭 생성"""
        output = metrics.generate_metrics()
        
        assert isinstance(output, bytes)
        assert len(output) > 0
    
    def test_metrics_format(self, metrics):
        """Prometheus 형식 확인"""
        # 몇 가지 메트릭 기록
        metrics.record_sip_request("INVITE", "2xx")
        metrics.set_active_calls(5)
        metrics.record_call_duration(60.0)
        
        output = metrics.generate_metrics().decode('utf-8')
        
        # Prometheus 형식 확인
        lines = output.strip().split('\n')
        
        # HELP와 TYPE 주석 확인
        help_lines = [l for l in lines if l.startswith('# HELP')]
        type_lines = [l for l in lines if l.startswith('# TYPE')]
        
        assert len(help_lines) > 0
        assert len(type_lines) > 0
    
    def test_get_content_type(self, metrics):
        """Content-Type 확인"""
        content_type = metrics.get_content_type()
        
        assert isinstance(content_type, str)
        assert 'text/plain' in content_type or 'text' in content_type


class TestMetricsIntegration:
    """메트릭 통합 테스트"""
    
    def test_full_call_metrics(self, metrics):
        """전체 통화 메트릭"""
        # 통화 시작
        metrics.record_sip_request("INVITE", "2xx")
        metrics.set_active_calls(1)
        
        # 미디어 할당
        metrics.set_port_pool_stats(available=95, used=5)
        
        # RTP 처리
        for _ in range(100):
            metrics.record_rtp_packet_received("caller")
            metrics.record_rtp_packet_received("callee")
        
        # AI 분석
        metrics.record_stt_latency(1.2)
        metrics.record_emotion_latency(0.5)
        metrics.record_text_classification_latency(0.1)
        
        # 이벤트 생성
        metrics.record_event_generated("profanity_detected", "high")
        metrics.record_webhook_sent(success=True)
        
        # 통화 종료
        metrics.record_sip_request("BYE", "2xx")
        metrics.set_active_calls(0)
        metrics.record_call_duration(120.5)
        metrics.record_cdr_written()
        
        # 메트릭 확인
        output = metrics.generate_metrics().decode('utf-8')
        
        assert 'sip_requests_total' in output
        assert 'sip_active_calls' in output
        assert 'sip_call_duration_seconds' in output
        assert 'rtp_packets_received_total' in output
        assert 'ai_stt_latency_seconds' in output
        assert 'events_generated_total' in output
        assert 'webhook_sent_total' in output
        assert 'cdr_written_total' in output
    
    def test_metrics_labels(self, metrics):
        """메트릭 레이블 확인"""
        # 다양한 레이블로 기록
        metrics.record_sip_request("INVITE", "2xx")
        metrics.record_sip_request("INVITE", "4xx")
        metrics.record_sip_request("BYE", "2xx")
        
        metrics.record_rtp_packet_received("caller")
        metrics.record_rtp_packet_received("callee")
        
        metrics.record_event_generated("profanity_detected", "high")
        metrics.record_event_generated("anger_detected", "medium")
        
        output = metrics.generate_metrics().decode('utf-8')
        
        # 레이블 확인
        assert 'method="INVITE"' in output
        assert 'method="BYE"' in output
        assert 'status="2xx"' in output
        assert 'status="4xx"' in output
        assert 'direction="caller"' in output
        assert 'direction="callee"' in output
        assert 'event_type="profanity_detected"' in output
        assert 'severity="high"' in output

