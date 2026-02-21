"""Port Pool Manager

RTP/RTCP 포트 풀 관리
"""

from typing import Dict, List, Set
from threading import RLock
from dataclasses import dataclass

from src.config.models import PortPoolConfig
from src.common.exceptions import PortPoolExhaustedError
from src.common.logger import get_logger

logger = get_logger(__name__)


@dataclass
class PortAllocation:
    """포트 할당 정보"""
    call_id: str
    ports: List[int]  # 8개 포트 (각 leg RTP/RTCP 쌍 x 2)
    
    def __repr__(self) -> str:
        return f"PortAllocation(call_id={self.call_id}, ports={self.ports})"


class PortPoolManager:
    """포트 풀 관리자
    
    동시 통화를 위한 RTP/RTCP 포트 동적 할당 및 해제
    
    포트 할당 구조:
    - 호당 8개 포트 할당
    - Incoming Leg: RTP (짝수), RTCP (홀수) 쌍 x 2 (audio, video)
    - Outgoing Leg: RTP (짝수), RTCP (홀수) 쌍 x 2 (audio, video)
    - 예: [10000, 10001, 10002, 10003, 10004, 10005, 10006, 10007]
    """
    
    PORTS_PER_CALL = 8  # 호당 할당 포트 수
    
    def __init__(self, config: PortPoolConfig):
        """초기화
        
        Args:
            config: 포트 풀 설정
        """
        self.config = config
        self._lock = RLock()  # Reentrant lock for thread safety
        
        # 사용 가능한 포트 풀 (짝수 포트만)
        self._available_ports: Set[int] = set()
        
        # 할당된 포트 매핑 {call_id: PortAllocation}
        self._allocations: Dict[str, PortAllocation] = {}
        
        # 포트 풀 초기화
        self._initialize_pool()
        
        logger.info("port_pool_manager_initialized",
                   start_port=self.config.start,
                   end_port=self.config.end,
                   total_ports=len(self._available_ports),
                   max_concurrent_calls=self.get_max_concurrent_calls())
    
    def _initialize_pool(self) -> None:
        """포트 풀 초기화 (짝수 포트만)"""
        # 짝수 포트만 추가 (RTP용, RTCP는 +1)
        for port in range(self.config.start, self.config.end + 1, 2):
            if port % 2 == 0 and port + 1 <= self.config.end:
                self._available_ports.add(port)
        
        logger.debug("port_pool_initialized",
                    available_ports=len(self._available_ports))
    
    def allocate_ports(self, call_id: str) -> List[int]:
        """포트 할당
        
        Args:
            call_id: 통화 ID
            
        Returns:
            할당된 8개 포트 리스트
            
        Raises:
            PortPoolExhaustedError: 사용 가능한 포트 부족
            ValueError: 이미 할당된 call_id
        """
        with self._lock:
            # 중복 할당 체크
            if call_id in self._allocations:
                raise ValueError(f"Ports already allocated for call_id: {call_id}")
            
            # 사용 가능한 포트 체크 (8개 필요)
            if len(self._available_ports) < self.PORTS_PER_CALL // 2:
                # 짝수 포트만 관리하므로 4개 필요
                utilization = self.get_utilization()
                logger.warning("port_pool_exhausted",
                             call_id=call_id,
                             available_pairs=len(self._available_ports),
                             utilization=utilization)
                raise PortPoolExhaustedError(
                    f"Insufficient ports: need {self.PORTS_PER_CALL // 2} pairs, "
                    f"available {len(self._available_ports)} (utilization: {utilization:.1%})"
                )
            
            # 4개의 짝수 포트 할당 (각각 +1하여 RTCP 포트로 사용)
            # 🔧 가장 작은 포트부터 순차적으로 할당 (테스트/디버깅 용이)
            allocated_base_ports = []
            for _ in range(self.PORTS_PER_CALL // 2):
                port = min(self._available_ports)  # 가장 작은 포트 선택
                self._available_ports.remove(port)
                allocated_base_ports.append(port)
            
            # RTP/RTCP 쌍으로 확장
            allocated_ports = []
            for base_port in sorted(allocated_base_ports):
                allocated_ports.append(base_port)      # RTP (짝수)
                allocated_ports.append(base_port + 1)  # RTCP (홀수)
            
            # 할당 정보 저장
            allocation = PortAllocation(call_id=call_id, ports=allocated_ports)
            self._allocations[call_id] = allocation
            
            logger.info("ports_allocated",
                       call_id=call_id,
                       ports=allocated_ports,
                       available_pairs=len(self._available_ports),
                       utilization=self.get_utilization())
            
            return allocated_ports
    
    def release_ports(self, call_id: str) -> bool:
        """포트 해제
        
        Args:
            call_id: 통화 ID
            
        Returns:
            성공 여부
        """
        with self._lock:
            allocation = self._allocations.pop(call_id, None)
            
            if not allocation:
                logger.warning("port_release_failed_not_found", call_id=call_id)
                return False
            
            # 짝수 포트만 반환 (홀수는 자동으로 사용 가능)
            for port in allocation.ports:
                if port % 2 == 0:  # 짝수 포트만 풀에 반환
                    self._available_ports.add(port)
            
            logger.info("ports_released",
                       call_id=call_id,
                       ports=allocation.ports,
                       available_pairs=len(self._available_ports),
                       utilization=self.get_utilization())
            
            return True
    
    def get_allocation(self, call_id: str) -> PortAllocation | None:
        """할당 정보 조회
        
        Args:
            call_id: 통화 ID
            
        Returns:
            PortAllocation 또는 None
        """
        with self._lock:
            return self._allocations.get(call_id)
    
    def get_max_concurrent_calls(self) -> int:
        """최대 동시 통화 수
        
        Returns:
            최대 호 수
        """
        total_pairs = (self.config.end - self.config.start + 1) // 2
        return total_pairs // (self.PORTS_PER_CALL // 2)
    
    def get_active_call_count(self) -> int:
        """활성 통화 수
        
        Returns:
            현재 활성 통화 개수
        """
        with self._lock:
            return len(self._allocations)
    
    def get_utilization(self) -> float:
        """포트 사용률
        
        Returns:
            사용률 (0.0 ~ 1.0)
        """
        with self._lock:
            total_pairs = (self.config.end - self.config.start + 1) // 2
            if total_pairs == 0:
                return 1.0
            used_pairs = (total_pairs - len(self._available_ports))
            return used_pairs / total_pairs
    
    def is_low_on_ports(self, threshold: float = 0.9) -> bool:
        """포트 부족 상태 확인
        
        Args:
            threshold: 임계치 (기본 90%)
            
        Returns:
            임계치 초과 여부
        """
        return self.get_utilization() >= threshold
    
    def get_stats(self) -> Dict[str, any]:
        """통계 정보
        
        Returns:
            통계 딕셔너리
        """
        with self._lock:
            return {
                "max_calls": self.get_max_concurrent_calls(),
                "active_calls": self.get_active_call_count(),
                "available_port_pairs": len(self._available_ports),
                "utilization": self.get_utilization(),
                "port_range": f"{self.config.start}-{self.config.end}",
            }

