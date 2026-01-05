"""Media Performance Measurement

미디어 처리 성능 측정 유틸리티
"""

import time
import psutil
import statistics
from typing import List, Dict, Optional
from dataclasses import dataclass, field
from datetime import datetime

from src.common.logger import get_logger

logger = get_logger(__name__)


@dataclass
class LatencyMeasurement:
    """지연 시간 측정"""
    timestamp: float
    latency_ms: float
    packet_size: int
    direction: str  # "caller_to_callee" or "callee_to_caller"


@dataclass
class PerformanceStats:
    """성능 통계"""
    # 지연 시간 (밀리초)
    avg_latency_ms: float = 0.0
    min_latency_ms: float = 0.0
    max_latency_ms: float = 0.0
    p50_latency_ms: float = 0.0
    p95_latency_ms: float = 0.0
    p99_latency_ms: float = 0.0
    
    # 처리량
    total_packets: int = 0
    packets_per_second: float = 0.0
    bytes_per_second: float = 0.0
    
    # 패킷 손실
    packets_lost: int = 0
    packet_loss_rate: float = 0.0
    
    # 리소스 사용률
    cpu_percent: float = 0.0
    memory_mb: float = 0.0
    
    # 테스트 메타데이터
    test_duration_seconds: float = 0.0
    concurrent_calls: int = 0
    mode: str = "bypass"  # "bypass" or "reflecting"


class PerformanceMeasurement:
    """성능 측정기
    
    RTP 패킷 처리 성능을 측정하고 통계를 수집
    """
    
    def __init__(self, mode: str = "bypass"):
        """초기화
        
        Args:
            mode: 측정 모드 ("bypass" or "reflecting")
        """
        self.mode = mode
        self.measurements: List[LatencyMeasurement] = []
        self.start_time: Optional[float] = None
        self.end_time: Optional[float] = None
        
        # 패킷 통계
        self.total_packets = 0
        self.total_bytes = 0
        self.packets_lost = 0
        
        # 프로세스 정보
        self.process = psutil.Process()
        
        logger.info("performance_measurement_initialized", mode=mode)
    
    def start(self) -> None:
        """측정 시작"""
        self.start_time = time.time()
        logger.info("performance_measurement_started")
    
    def stop(self) -> None:
        """측정 종료"""
        self.end_time = time.time()
        logger.info("performance_measurement_stopped",
                   duration=self.get_duration())
    
    def record_latency(
        self,
        latency_ms: float,
        packet_size: int,
        direction: str = "caller_to_callee"
    ) -> None:
        """지연 시간 기록
        
        Args:
            latency_ms: 지연 시간 (밀리초)
            packet_size: 패킷 크기 (바이트)
            direction: 패킷 방향
        """
        measurement = LatencyMeasurement(
            timestamp=time.time(),
            latency_ms=latency_ms,
            packet_size=packet_size,
            direction=direction,
        )
        
        self.measurements.append(measurement)
        self.total_packets += 1
        self.total_bytes += packet_size
    
    def record_packet_loss(self, count: int = 1) -> None:
        """패킷 손실 기록
        
        Args:
            count: 손실된 패킷 수
        """
        self.packets_lost += count
    
    def get_duration(self) -> float:
        """측정 기간 (초)
        
        Returns:
            측정 기간
        """
        if self.start_time is None:
            return 0.0
        
        end = self.end_time if self.end_time else time.time()
        return end - self.start_time
    
    def get_stats(self, concurrent_calls: int = 1) -> PerformanceStats:
        """성능 통계 계산
        
        Args:
            concurrent_calls: 동시 통화 수
            
        Returns:
            성능 통계
        """
        stats = PerformanceStats(
            mode=self.mode,
            concurrent_calls=concurrent_calls,
        )
        
        # 지연 시간 통계
        if self.measurements:
            latencies = [m.latency_ms for m in self.measurements]
            latencies.sort()
            
            stats.avg_latency_ms = statistics.mean(latencies)
            stats.min_latency_ms = min(latencies)
            stats.max_latency_ms = max(latencies)
            stats.p50_latency_ms = self._percentile(latencies, 0.50)
            stats.p95_latency_ms = self._percentile(latencies, 0.95)
            stats.p99_latency_ms = self._percentile(latencies, 0.99)
        
        # 처리량 통계
        duration = self.get_duration()
        if duration > 0:
            stats.packets_per_second = self.total_packets / duration
            stats.bytes_per_second = self.total_bytes / duration
        
        stats.total_packets = self.total_packets
        
        # 패킷 손실률
        if self.total_packets > 0:
            stats.packet_loss_rate = (self.packets_lost / self.total_packets) * 100
        
        stats.packets_lost = self.packets_lost
        
        # 리소스 사용률
        try:
            stats.cpu_percent = self.process.cpu_percent()
            stats.memory_mb = self.process.memory_info().rss / (1024 * 1024)
        except Exception as e:
            logger.warning("failed_to_get_resource_usage", error=str(e))
        
        stats.test_duration_seconds = duration
        
        return stats
    
    @staticmethod
    def _percentile(data: List[float], percentile: float) -> float:
        """백분위수 계산
        
        Args:
            data: 정렬된 데이터
            percentile: 백분위 (0.0 ~ 1.0)
            
        Returns:
            백분위수 값
        """
        if not data:
            return 0.0
        
        index = int(len(data) * percentile)
        if index >= len(data):
            index = len(data) - 1
        
        return data[index]
    
    def reset(self) -> None:
        """측정 데이터 초기화"""
        self.measurements.clear()
        self.start_time = None
        self.end_time = None
        self.total_packets = 0
        self.total_bytes = 0
        self.packets_lost = 0
        
        logger.info("performance_measurement_reset")


class PerformanceReport:
    """성능 리포트 생성기"""
    
    @staticmethod
    def generate_report(stats: PerformanceStats) -> str:
        """성능 리포트 생성
        
        Args:
            stats: 성능 통계
            
        Returns:
            리포트 문자열
        """
        report = []
        report.append("=" * 60)
        report.append(f"Media Performance Test Report - {stats.mode.upper()} Mode")
        report.append("=" * 60)
        report.append("")
        
        # 테스트 설정
        report.append("Test Configuration:")
        report.append(f"  Mode: {stats.mode}")
        report.append(f"  Concurrent Calls: {stats.concurrent_calls}")
        report.append(f"  Duration: {stats.test_duration_seconds:.2f}s")
        report.append("")
        
        # 지연 시간
        report.append("Latency Metrics (ms):")
        report.append(f"  Average: {stats.avg_latency_ms:.2f} ms")
        report.append(f"  Min: {stats.min_latency_ms:.2f} ms")
        report.append(f"  Max: {stats.max_latency_ms:.2f} ms")
        report.append(f"  P50: {stats.p50_latency_ms:.2f} ms")
        report.append(f"  P95: {stats.p95_latency_ms:.2f} ms")
        report.append(f"  P99: {stats.p99_latency_ms:.2f} ms")
        report.append("")
        
        # 처리량
        report.append("Throughput Metrics:")
        report.append(f"  Total Packets: {stats.total_packets:,}")
        report.append(f"  Packets/sec: {stats.packets_per_second:.2f}")
        report.append(f"  Bytes/sec: {stats.bytes_per_second:,.2f} ({stats.bytes_per_second / (1024*1024):.2f} MB/s)")
        report.append("")
        
        # 패킷 손실
        report.append("Packet Loss:")
        report.append(f"  Packets Lost: {stats.packets_lost}")
        report.append(f"  Loss Rate: {stats.packet_loss_rate:.4f}%")
        report.append("")
        
        # 리소스 사용률
        report.append("Resource Usage:")
        report.append(f"  CPU: {stats.cpu_percent:.2f}%")
        report.append(f"  Memory: {stats.memory_mb:.2f} MB")
        report.append("")
        
        # 성능 목표 달성 여부
        report.append("Performance Goals:")
        
        if stats.mode == "bypass":
            avg_target = 5.0
            p99_target = 10.0
        else:  # reflecting
            avg_target = 15.0
            p99_target = 30.0
        
        avg_pass = stats.avg_latency_ms <= avg_target
        p99_pass = stats.p99_latency_ms <= p99_target
        loss_pass = stats.packet_loss_rate <= 0.1
        
        report.append(f"  Avg Latency <= {avg_target} ms: {'✅ PASS' if avg_pass else '❌ FAIL'}")
        report.append(f"  P99 Latency <= {p99_target} ms: {'✅ PASS' if p99_pass else '❌ FAIL'}")
        report.append(f"  Packet Loss <= 0.1%: {'✅ PASS' if loss_pass else '❌ FAIL'}")
        
        report.append("")
        report.append("=" * 60)
        
        return "\n".join(report)
    
    @staticmethod
    def save_report(stats: PerformanceStats, filename: str) -> None:
        """리포트를 파일로 저장
        
        Args:
            stats: 성능 통계
            filename: 파일 이름
        """
        report = PerformanceReport.generate_report(stats)
        
        with open(filename, "w", encoding="utf-8") as f:
            f.write(report)
        
        logger.info("performance_report_saved", filename=filename)

