"""Port Pool Manager 단위 테스트"""

import pytest
from src.media.port_pool import PortPoolManager, PortAllocation
from src.config.models import PortPoolConfig
from src.common.exceptions import PortPoolExhaustedError
from src.common.logger import setup_logging


@pytest.fixture(scope="module", autouse=True)
def setup_test_logging():
    """테스트용 로깅 설정"""
    setup_logging(level="DEBUG", format_type="text")


@pytest.fixture
def port_pool_config():
    """테스트용 포트 풀 설정 (작은 범위)"""
    return PortPoolConfig(start=10000, end=10100)


@pytest.fixture
def port_pool(port_pool_config):
    """테스트용 Port Pool Manager"""
    return PortPoolManager(port_pool_config)


class TestPortPoolManager:
    """Port Pool Manager 기본 테스트"""
    
    def test_initialization(self, port_pool):
        """초기화 테스트"""
        assert port_pool is not None
        assert port_pool.get_active_call_count() == 0
        assert port_pool.get_utilization() == 0.0
        
        # 짝수 포트만 사용하므로 (10100-10000+1)//2 = 51개 쌍
        # 최대 호수: 51 // 4 = 12
        max_calls = port_pool.get_max_concurrent_calls()
        assert max_calls == 12
    
    def test_allocate_ports_success(self, port_pool):
        """포트 할당 성공 테스트"""
        call_id = "test-call-1"
        ports = port_pool.allocate_ports(call_id)
        
        # 8개 포트 할당 확인
        assert len(ports) == 8
        
        # 짝수/홀수 쌍 확인 (RTP/RTCP)
        for i in range(0, 8, 2):
            assert ports[i] % 2 == 0  # RTP (짝수)
            assert ports[i+1] == ports[i] + 1  # RTCP (홀수)
        
        # 활성 통화 수 증가
        assert port_pool.get_active_call_count() == 1
        
        # 할당 정보 조회
        allocation = port_pool.get_allocation(call_id)
        assert allocation is not None
        assert allocation.call_id == call_id
        assert allocation.ports == ports
    
    def test_allocate_ports_duplicate_call_id(self, port_pool):
        """중복 call_id 할당 시도 (에러)"""
        call_id = "test-call-duplicate"
        port_pool.allocate_ports(call_id)
        
        with pytest.raises(ValueError) as exc_info:
            port_pool.allocate_ports(call_id)  # 중복
        
        assert "already allocated" in str(exc_info.value).lower()
    
    def test_release_ports_success(self, port_pool):
        """포트 해제 성공 테스트"""
        call_id = "test-call-release"
        ports = port_pool.allocate_ports(call_id)
        
        assert port_pool.get_active_call_count() == 1
        
        # 해제
        result = port_pool.release_ports(call_id)
        
        assert result is True
        assert port_pool.get_active_call_count() == 0
        assert port_pool.get_allocation(call_id) is None
    
    def test_release_ports_not_found(self, port_pool):
        """존재하지 않는 call_id 해제"""
        result = port_pool.release_ports("non-existent-call")
        assert result is False
    
    def test_multiple_allocations(self, port_pool):
        """여러 호 동시 할당 테스트"""
        call_ids = [f"call-{i}" for i in range(5)]
        
        for call_id in call_ids:
            ports = port_pool.allocate_ports(call_id)
            assert len(ports) == 8
        
        assert port_pool.get_active_call_count() == 5
        
        # 각 호의 포트가 겹치지 않는지 확인
        all_ports = set()
        for call_id in call_ids:
            allocation = port_pool.get_allocation(call_id)
            for port in allocation.ports:
                assert port not in all_ports  # 중복 없음
                all_ports.add(port)
    
    def test_port_exhaustion(self, port_pool):
        """포트 고갈 테스트"""
        max_calls = port_pool.get_max_concurrent_calls()
        
        # 최대 호수까지 할당
        for i in range(max_calls):
            call_id = f"call-max-{i}"
            port_pool.allocate_ports(call_id)
        
        assert port_pool.get_active_call_count() == max_calls
        # 96% 이상이면 거의 고갈
        assert port_pool.get_utilization() >= 0.95
        
        # 추가 할당 시도 (실패)
        with pytest.raises(PortPoolExhaustedError) as exc_info:
            port_pool.allocate_ports("overflow-call")
        
        assert "Insufficient ports" in str(exc_info.value)
    
    def test_allocation_and_release_cycle(self, port_pool):
        """할당-해제 사이클 테스트"""
        call_id = "cycle-call"
        
        # 할당
        ports1 = port_pool.allocate_ports(call_id)
        initial_utilization = port_pool.get_utilization()
        
        # 해제
        port_pool.release_ports(call_id)
        assert port_pool.get_utilization() == 0.0
        
        # 재할당 (동일 call_id는 에러이므로 다른 ID 사용)
        call_id2 = "cycle-call-2"
        ports2 = port_pool.allocate_ports(call_id2)
        
        # 포트가 재사용됨
        assert len(ports2) == 8
        assert port_pool.get_utilization() == initial_utilization
    
    def test_get_stats(self, port_pool):
        """통계 정보 테스트"""
        # 초기 상태
        stats = port_pool.get_stats()
        assert stats["active_calls"] == 0
        assert stats["utilization"] == 0.0
        assert stats["max_calls"] > 0
        assert "port_range" in stats
        
        # 할당 후
        port_pool.allocate_ports("stats-call")
        stats = port_pool.get_stats()
        assert stats["active_calls"] == 1
        assert stats["utilization"] > 0.0
    
    def test_is_low_on_ports(self, port_pool):
        """포트 부족 감지 테스트"""
        max_calls = port_pool.get_max_concurrent_calls()
        
        # 90% 이상 사용 시 low 상태
        threshold = 0.9
        # max_calls만큼 할당하면 96%이므로 충분
        target_calls = max_calls
        
        for i in range(target_calls):
            port_pool.allocate_ports(f"low-call-{i}")
        
        assert port_pool.is_low_on_ports(threshold=threshold)


class TestPortAllocation:
    """Port Allocation 데이터 클래스 테스트"""
    
    def test_port_allocation_creation(self):
        """PortAllocation 생성 테스트"""
        ports = [10000, 10001, 10002, 10003, 10004, 10005, 10006, 10007]
        allocation = PortAllocation(call_id="test-call", ports=ports)
        
        assert allocation.call_id == "test-call"
        assert allocation.ports == ports
        assert len(allocation.ports) == 8
    
    def test_port_allocation_repr(self):
        """PortAllocation 문자열 표현 테스트"""
        allocation = PortAllocation(
            call_id="repr-call",
            ports=[10000, 10001, 10002, 10003, 10004, 10005, 10006, 10007]
        )
        repr_str = repr(allocation)
        
        assert "repr-call" in repr_str
        assert "10000" in repr_str


class TestPortPoolEdgeCases:
    """Port Pool 엣지 케이스 테스트"""
    
    def test_very_small_port_range(self):
        """매우 작은 포트 범위 (최소 1개 호만 가능)"""
        config = PortPoolConfig(start=10000, end=10007)
        pool = PortPoolManager(config)
        
        # 최대 1개 호
        assert pool.get_max_concurrent_calls() == 1
        
        # 1개 할당 성공
        pool.allocate_ports("small-call-1")
        assert pool.get_active_call_count() == 1
        
        # 2번째 할당 실패
        with pytest.raises(PortPoolExhaustedError):
            pool.allocate_ports("small-call-2")
    
    def test_utilization_calculation(self):
        """사용률 계산 정확성 테스트"""
        config = PortPoolConfig(start=10000, end=10100)
        pool = PortPoolManager(config)
        
        max_calls = pool.get_max_concurrent_calls()
        
        for i in range(max_calls // 2):
            pool.allocate_ports(f"util-call-{i}")
        
        utilization = pool.get_utilization()
        expected_utilization = 0.5  # 50%
        
        # 부동소수점 오차 허용
        assert abs(utilization - expected_utilization) < 0.05
    
    def test_thread_safety_simulation(self, port_pool):
        """스레드 안전성 시뮬레이션 (순차 테스트)"""
        import concurrent.futures
        
        def allocate_and_release(call_id):
            try:
                ports = port_pool.allocate_ports(call_id)
                return (call_id, ports, True)
            except Exception as e:
                return (call_id, None, False)
        
        # 10개 동시 할당 시도
        with concurrent.futures.ThreadPoolExecutor(max_workers=5) as executor:
            futures = [
                executor.submit(allocate_and_release, f"thread-call-{i}")
                for i in range(10)
            ]
            results = [f.result() for f in concurrent.futures.as_completed(futures)]
        
        # 성공한 할당 확인
        successful = [r for r in results if r[2]]
        assert len(successful) > 0
        
        # 모든 할당된 포트가 유니크한지 확인
        all_ports = set()
        for call_id, ports, success in successful:
            if ports:
                for port in ports:
                    assert port not in all_ports
                    all_ports.add(port)

