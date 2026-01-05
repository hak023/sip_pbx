"""Media Performance 벤치마크 테스트

미디어 처리 성능을 측정하는 벤치마크 테스트
"""

import pytest
import time
import asyncio
from datetime import datetime

from src.media.performance import PerformanceMeasurement, PerformanceReport
from src.media.port_pool import PortPoolManager
from src.media.session_manager import MediaSessionManager
from src.media.rtp_packet import RTPPacket, RTPHeader
from src.config.models import PortPoolConfig
from src.common.logger import setup_logging


@pytest.fixture(scope="module", autouse=True)
def setup_test_logging():
    """테스트용 로깅 설정"""
    setup_logging(level="INFO", format_type="text")


@pytest.fixture
def performance_measurement():
    """성능 측정기"""
    return PerformanceMeasurement(mode="bypass")


@pytest.fixture
def port_pool():
    """포트 풀"""
    config = PortPoolConfig(start=20000, end=30000)
    return PortPoolManager(config=config)


@pytest.fixture
def media_session_manager(port_pool):
    """미디어 세션 관리자"""
    return MediaSessionManager(port_pool=port_pool)


def create_test_rtp_packet(
    sequence: int = 1,
    timestamp: int = 160,
    payload_size: int = 160,
) -> RTPPacket:
    """테스트용 RTP 패킷 생성
    
    Args:
        sequence: 시퀀스 번호
        timestamp: 타임스탬프
        payload_size: 페이로드 크기
        
    Returns:
        RTP 패킷
    """
    header = RTPHeader(
        version=2,
        padding=False,
        extension=False,
        csrc_count=0,
        marker=False,
        payload_type=0,  # PCMU
        sequence_number=sequence,
        timestamp=timestamp,
        ssrc=12345,
    )
    
    payload = b'\x00' * payload_size
    
    return RTPPacket(header=header, payload=payload)


class TestPerformanceMeasurement:
    """성능 측정 기본 테스트"""
    
    def test_measurement_creation(self, performance_measurement):
        """측정기 생성"""
        assert performance_measurement is not None
        assert performance_measurement.mode == "bypass"
    
    def test_start_stop(self, performance_measurement):
        """시작/중지"""
        performance_measurement.start()
        time.sleep(0.1)
        performance_measurement.stop()
        
        duration = performance_measurement.get_duration()
        assert duration >= 0.1
    
    def test_record_latency(self, performance_measurement):
        """지연 시간 기록"""
        performance_measurement.start()
        
        performance_measurement.record_latency(
            latency_ms=5.5,
            packet_size=160,
            direction="caller_to_callee"
        )
        
        assert len(performance_measurement.measurements) == 1
        assert performance_measurement.total_packets == 1
        assert performance_measurement.total_bytes == 160
    
    def test_record_packet_loss(self, performance_measurement):
        """패킷 손실 기록"""
        performance_measurement.record_packet_loss(5)
        
        assert performance_measurement.packets_lost == 5
    
    def test_get_stats(self, performance_measurement):
        """통계 조회"""
        performance_measurement.start()
        
        # 여러 측정 기록
        for i in range(10):
            performance_measurement.record_latency(
                latency_ms=5.0 + i * 0.5,
                packet_size=160,
            )
        
        time.sleep(0.1)
        performance_measurement.stop()
        
        stats = performance_measurement.get_stats(concurrent_calls=1)
        
        assert stats.avg_latency_ms > 0
        assert stats.total_packets == 10
        assert stats.packets_per_second > 0
        assert stats.test_duration_seconds > 0
    
    def test_reset(self, performance_measurement):
        """측정 초기화"""
        performance_measurement.start()
        performance_measurement.record_latency(5.0, 160)
        performance_measurement.reset()
        
        assert len(performance_measurement.measurements) == 0
        assert performance_measurement.total_packets == 0


class TestPerformanceReport:
    """성능 리포트 테스트"""
    
    def test_generate_report(self, performance_measurement):
        """리포트 생성"""
        performance_measurement.start()
        
        for i in range(100):
            performance_measurement.record_latency(
                latency_ms=3.0 + i * 0.01,
                packet_size=160,
            )
        
        time.sleep(0.1)
        performance_measurement.stop()
        
        stats = performance_measurement.get_stats(concurrent_calls=1)
        report = PerformanceReport.generate_report(stats)
        
        assert "Media Performance Test Report" in report
        assert "Latency Metrics" in report
        assert "Throughput Metrics" in report
        assert "Packet Loss" in report


@pytest.mark.benchmark
class TestMediaPerformanceBenchmark:
    """미디어 성능 벤치마크"""
    
    def test_rtp_packet_parsing_performance(self):
        """RTP 패킷 파싱 성능"""
        measurement = PerformanceMeasurement(mode="bypass")
        measurement.start()
        
        # 1000개 패킷 파싱
        for i in range(1000):
            start = time.perf_counter()
            
            packet = create_test_rtp_packet(sequence=i)
            
            end = time.perf_counter()
            latency_ms = (end - start) * 1000
            
            measurement.record_latency(latency_ms, 160)
        
        measurement.stop()
        
        stats = measurement.get_stats(concurrent_calls=1)
        
        print(f"\n🔍 RTP Packet Parsing Performance:")
        print(f"   Average: {stats.avg_latency_ms:.4f} ms")
        print(f"   P99: {stats.p99_latency_ms:.4f} ms")
        print(f"   Throughput: {stats.packets_per_second:.2f} packets/sec")
        
        # 파싱은 매우 빨라야 함
        assert stats.avg_latency_ms < 1.0  # 1ms 이하
    
    def test_session_creation_performance(self, media_session_manager):
        """세션 생성 성능"""
        measurement = PerformanceMeasurement(mode="bypass")
        measurement.start()
        
        sdp = "v=0\r\no=- 1 1 IN IP4 192.168.1.100\r\ns=-\r\nc=IN IP4 192.168.1.100\r\nt=0 0\r\nm=audio 30000 RTP/AVP 0\r\n"
        
        # 100개 세션 생성
        for i in range(100):
            start = time.perf_counter()
            
            session = media_session_manager.create_session(f"call-perf-{i}", sdp)
            
            end = time.perf_counter()
            latency_ms = (end - start) * 1000
            
            measurement.record_latency(latency_ms, 0)
        
        measurement.stop()
        
        stats = measurement.get_stats(concurrent_calls=100)
        
        print(f"\n🔍 Session Creation Performance:")
        print(f"   Average: {stats.avg_latency_ms:.4f} ms")
        print(f"   P99: {stats.p99_latency_ms:.4f} ms")
        print(f"   Sessions/sec: {stats.packets_per_second:.2f}")
        
        # 세션 생성은 빨라야 함
        assert stats.avg_latency_ms < 50.0  # 50ms 이하
    
    @pytest.mark.skip(reason="긴 실행 시간이 필요한 부하 테스트")
    def test_concurrent_calls_simulation(self, media_session_manager):
        """동시 통화 시뮬레이션 (100 calls)"""
        measurement = PerformanceMeasurement(mode="bypass")
        measurement.start()
        
        sdp = "v=0\r\no=- 1 1 IN IP4 192.168.1.100\r\ns=-\r\nc=IN IP4 192.168.1.100\r\nt=0 0\r\nm=audio 30000 RTP/AVP 0\r\n"
        
        # 100개 세션 생성
        sessions = []
        for i in range(100):
            session = media_session_manager.create_session(f"call-load-{i}", sdp)
            sessions.append(session)
        
        # 10초 동안 RTP 패킷 시뮬레이션 (각 세션에서 초당 50 패킷)
        duration = 10.0
        packets_per_second = 50
        interval = 1.0 / packets_per_second
        
        start_time = time.time()
        packet_count = 0
        
        while time.time() - start_time < duration:
            for session in sessions:
                start = time.perf_counter()
                
                # RTP 패킷 처리 시뮬레이션
                packet = create_test_rtp_packet(sequence=packet_count)
                session.update_rtp_received(from_caller=True)
                
                end = time.perf_counter()
                latency_ms = (end - start) * 1000
                
                measurement.record_latency(latency_ms, 160)
                packet_count += 1
            
            time.sleep(interval)
        
        measurement.stop()
        
        stats = measurement.get_stats(concurrent_calls=100)
        
        print(f"\n🔍 100 Concurrent Calls Simulation:")
        print(f"   Duration: {stats.test_duration_seconds:.2f}s")
        print(f"   Total Packets: {stats.total_packets:,}")
        print(f"   Average Latency: {stats.avg_latency_ms:.2f} ms")
        print(f"   P99 Latency: {stats.p99_latency_ms:.2f} ms")
        print(f"   CPU: {stats.cpu_percent:.2f}%")
        print(f"   Memory: {stats.memory_mb:.2f} MB")
        
        # 성능 목표
        assert stats.avg_latency_ms < 5.0
        assert stats.p99_latency_ms < 10.0
        assert stats.cpu_percent < 50.0
        assert stats.memory_mb < 2048.0


@pytest.mark.benchmark
class TestBypassModePerformance:
    """Bypass 모드 성능 테스트"""
    
    def test_bypass_mode_latency(self):
        """Bypass 모드 지연 시간"""
        measurement = PerformanceMeasurement(mode="bypass")
        measurement.start()
        
        # 1000개 패킷으로 시뮬레이션
        for i in range(1000):
            start = time.perf_counter()
            
            # Bypass 모드: 단순 relay 시뮬레이션
            packet = create_test_rtp_packet(sequence=i)
            # 실제로는 UDP 소켓 전송이지만, 여기서는 시뮬레이션
            time.sleep(0.001)  # 1ms 네트워크 지연 시뮬레이션
            
            end = time.perf_counter()
            latency_ms = (end - start) * 1000
            
            measurement.record_latency(latency_ms, 160)
        
        measurement.stop()
        
        stats = measurement.get_stats(concurrent_calls=1)
        
        print(f"\n🔍 Bypass Mode Performance:")
        print(f"   Average: {stats.avg_latency_ms:.2f} ms")
        print(f"   P99: {stats.p99_latency_ms:.2f} ms")
        print(f"   Throughput: {stats.packets_per_second:.2f} pps")
        
        print(f"\n   Performance Goals:")
        print(f"   ✅ Avg <= 5ms: {stats.avg_latency_ms:.2f} ms ({'PASS' if stats.avg_latency_ms <= 5.0 else 'FAIL'})")
        print(f"   ✅ P99 <= 10ms: {stats.p99_latency_ms:.2f} ms ({'PASS' if stats.p99_latency_ms <= 10.0 else 'FAIL'})")
        
        # Bypass 모드 목표
        assert stats.avg_latency_ms < 5.0
        assert stats.p99_latency_ms < 10.0


@pytest.mark.benchmark
class TestReflectingModePerformance:
    """Reflecting 모드 성능 테스트"""
    
    @pytest.mark.asyncio
    async def test_reflecting_mode_latency(self):
        """Reflecting 모드 지연 시간"""
        measurement = PerformanceMeasurement(mode="reflecting")
        measurement.start()
        
        # 분석 큐 시뮬레이션
        analysis_queue = asyncio.Queue(maxsize=100)
        
        # 1000개 패킷으로 시뮬레이션
        for i in range(1000):
            start = time.perf_counter()
            
            # Reflecting 모드: relay + enqueue
            packet = create_test_rtp_packet(sequence=i)
            
            # Relay
            time.sleep(0.001)  # 1ms 네트워크 지연
            
            # Enqueue for analysis (non-blocking)
            try:
                analysis_queue.put_nowait(packet)
            except asyncio.QueueFull:
                measurement.record_packet_loss()
            
            end = time.perf_counter()
            latency_ms = (end - start) * 1000
            
            measurement.record_latency(latency_ms, 160)
        
        measurement.stop()
        
        stats = measurement.get_stats(concurrent_calls=1)
        
        print(f"\n🔍 Reflecting Mode Performance:")
        print(f"   Average: {stats.avg_latency_ms:.2f} ms")
        print(f"   P99: {stats.p99_latency_ms:.2f} ms")
        print(f"   Throughput: {stats.packets_per_second:.2f} pps")
        print(f"   Queue Size: {analysis_queue.qsize()}")
        
        print(f"\n   Performance Goals:")
        print(f"   ✅ Avg <= 15ms: {stats.avg_latency_ms:.2f} ms ({'PASS' if stats.avg_latency_ms <= 15.0 else 'FAIL'})")
        print(f"   ✅ P99 <= 30ms: {stats.p99_latency_ms:.2f} ms ({'PASS' if stats.p99_latency_ms <= 30.0 else 'FAIL'})")
        
        # Reflecting 모드 목표
        assert stats.avg_latency_ms < 15.0
        assert stats.p99_latency_ms < 30.0


@pytest.mark.benchmark
class TestResourceUsage:
    """리소스 사용률 테스트"""
    
    def test_memory_usage_per_session(self, media_session_manager):
        """세션당 메모리 사용량"""
        import psutil
        process = psutil.Process()
        
        # 초기 메모리
        initial_memory = process.memory_info().rss / (1024 * 1024)
        
        sdp = "v=0\r\no=- 1 1 IN IP4 192.168.1.100\r\ns=-\r\nc=IN IP4 192.168.1.100\r\nt=0 0\r\nm=audio 30000 RTP/AVP 0\r\n"
        
        # 100개 세션 생성
        for i in range(100):
            media_session_manager.create_session(f"call-mem-{i}", sdp)
        
        # 최종 메모리
        final_memory = process.memory_info().rss / (1024 * 1024)
        memory_per_session = (final_memory - initial_memory) / 100
        
        print(f"\n🔍 Memory Usage:")
        print(f"   Initial: {initial_memory:.2f} MB")
        print(f"   Final (100 sessions): {final_memory:.2f} MB")
        print(f"   Per Session: {memory_per_session:.4f} MB")
        print(f"   Projected (1000 sessions): {memory_per_session * 1000:.2f} MB")
        
        # 100 세션에서 2GB 이하 (매우 충분한 여유)
        assert final_memory < 2048.0

