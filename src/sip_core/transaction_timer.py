"""Transaction Timer (RFC 3261)

SIP 트랜잭션 타이머 구현
"""

import asyncio
from typing import Dict, Optional, Callable
from enum import Enum
import structlog

from src.common.logger import get_logger

logger = get_logger(__name__)


class TransactionType(str, Enum):
    """트랜잭션 타입"""
    INVITE = "INVITE"
    NON_INVITE = "NON_INVITE"


class TransactionState(str, Enum):
    """트랜잭션 상태"""
    CALLING = "calling"       # INVITE 전송 후 응답 대기
    PROCEEDING = "proceeding" # 1xx 응답 수신
    COMPLETED = "completed"   # 최종 응답 수신
    TERMINATED = "terminated" # 트랜잭션 종료


class TransactionTimer:
    """SIP 트랜잭션 타이머 관리자
    
    RFC 3261 Section 17 구현:
    - Timer A: INVITE 재전송 간격
    - Timer B: INVITE 트랜잭션 타임아웃
    - Timer D: 응답 재전송 수락 대기
    - Timer E: Non-INVITE 재전송 간격
    - Timer F: Non-INVITE 트랜잭션 타임아웃
    - Timer H: ACK 수신 대기
    - Timer I: ACK 재전송 수락 대기
    """
    
    def __init__(
        self,
        t1: float = 0.5,   # RTT Estimate
        t2: float = 4.0,   # 최대 재전송 간격
        t4: float = 5.0    # 최대 메시지 수명
    ):
        """초기화
        
        Args:
            t1: RTT Estimate (초)
            t2: 최대 재전송 간격 (초)
            t4: 최대 메시지 수명 (초)
        """
        self.t1 = t1
        self.t2 = t2
        self.t4 = t4
        
        # 활성 트랜잭션: {transaction_id: {'timers', 'state', ...}}
        self.transactions: Dict[str, Dict] = {}
        
        logger.info("TransactionTimer initialized",
                   t1=t1, t2=t2, t4=t4)
    
    async def start_invite_transaction(
        self,
        transaction_id: str,
        retransmit_callback: Optional[Callable] = None,
        timeout_callback: Optional[Callable] = None
    ) -> None:
        """INVITE 트랜잭션 시작
        
        Args:
            transaction_id: 트랜잭션 ID
            retransmit_callback: 재전송 콜백
            timeout_callback: 타임아웃 콜백
        """
        # Timer A: INVITE 재전송 (T1, T1*2, T1*4, ...)
        timer_a = asyncio.create_task(
            self._timer_a_loop(transaction_id, retransmit_callback)
        )
        
        # Timer B: INVITE 트랜잭션 타임아웃 (64*T1)
        timer_b = asyncio.create_task(
            self._timer_b(transaction_id, 64 * self.t1, timeout_callback)
        )
        
        self.transactions[transaction_id] = {
            'type': TransactionType.INVITE,
            'state': TransactionState.CALLING,
            'timer_a': timer_a,
            'timer_b': timer_b,
            'retransmit_count': 0
        }
        
        logger.info("INVITE transaction started",
                   transaction_id=transaction_id,
                   timer_b_timeout=64 * self.t1)
    
    async def _timer_a_loop(
        self,
        transaction_id: str,
        callback: Optional[Callable]
    ) -> None:
        """Timer A: INVITE 재전송 루프
        
        Args:
            transaction_id: 트랜잭션 ID
            callback: 재전송 콜백
        """
        try:
            interval = self.t1
            
            while True:
                await asyncio.sleep(interval)
                
                # 트랜잭션 상태 확인
                if transaction_id not in self.transactions:
                    break
                
                trans = self.transactions[transaction_id]
                
                # CALLING 상태가 아니면 중단
                if trans['state'] != TransactionState.CALLING:
                    break
                
                # 재전송 콜백 호출
                if callback:
                    try:
                        if asyncio.iscoroutinefunction(callback):
                            await callback(transaction_id)
                        else:
                            callback(transaction_id)
                        
                        trans['retransmit_count'] += 1
                        
                        logger.debug("INVITE retransmitted",
                                    transaction_id=transaction_id,
                                    count=trans['retransmit_count'],
                                    interval=interval)
                        
                    except Exception as e:
                        logger.error("Retransmit callback failed",
                                    transaction_id=transaction_id,
                                    error=str(e))
                        break
                
                # 재전송 간격 증가 (최대 T2까지)
                interval = min(interval * 2, self.t2)
                
        except asyncio.CancelledError:
            logger.debug("Timer A cancelled", transaction_id=transaction_id)
        except Exception as e:
            logger.error("Timer A error",
                        transaction_id=transaction_id,
                        error=str(e),
                        exc_info=True)
    
    async def _timer_b(
        self,
        transaction_id: str,
        timeout: float,
        callback: Optional[Callable]
    ) -> None:
        """Timer B: INVITE 트랜잭션 타임아웃
        
        Args:
            transaction_id: 트랜잭션 ID
            timeout: 타임아웃 시간 (초)
            callback: 타임아웃 콜백
        """
        try:
            await asyncio.sleep(timeout)
            
            # 트랜잭션이 아직 있으면 타임아웃 처리
            if transaction_id in self.transactions:
                trans = self.transactions[transaction_id]
                
                if trans['state'] == TransactionState.CALLING:
                    logger.warning("INVITE transaction timeout",
                                 transaction_id=transaction_id,
                                 timeout=timeout)
                    
                    # 타임아웃 콜백 호출
                    if callback:
                        try:
                            if asyncio.iscoroutinefunction(callback):
                                await callback(transaction_id)
                            else:
                                callback(transaction_id)
                        except Exception as e:
                            logger.error("Timeout callback failed",
                                        transaction_id=transaction_id,
                                        error=str(e))
                    
                    # 트랜잭션 종료
                    await self.terminate_transaction(transaction_id)
                
        except asyncio.CancelledError:
            logger.debug("Timer B cancelled", transaction_id=transaction_id)
        except Exception as e:
            logger.error("Timer B error",
                        transaction_id=transaction_id,
                        error=str(e),
                        exc_info=True)
    
    async def start_bye_transaction(
        self,
        transaction_id: str,
        timeout_callback: Optional[Callable] = None,
        timeout_seconds: int = 32
    ) -> None:
        """BYE 트랜잭션 시작
        
        Args:
            transaction_id: 트랜잭션 ID
            timeout_callback: 타임아웃 콜백
            timeout_seconds: 타임아웃 시간 (초)
        """
        # Timer F: Non-INVITE 트랜잭션 타임아웃
        timer_f = asyncio.create_task(
            self._timer_f(transaction_id, timeout_seconds, timeout_callback)
        )
        
        self.transactions[transaction_id] = {
            'type': TransactionType.NON_INVITE,
            'state': TransactionState.CALLING,
            'timer_f': timer_f
        }
        
        logger.info("BYE transaction started",
                   transaction_id=transaction_id,
                   timeout=timeout_seconds)
    
    async def _timer_f(
        self,
        transaction_id: str,
        timeout: float,
        callback: Optional[Callable]
    ) -> None:
        """Timer F: Non-INVITE 트랜잭션 타임아웃
        
        Args:
            transaction_id: 트랜잭션 ID
            timeout: 타임아웃 시간 (초)
            callback: 타임아웃 콜백
        """
        try:
            await asyncio.sleep(timeout)
            
            if transaction_id in self.transactions:
                trans = self.transactions[transaction_id]
                
                if trans['state'] == TransactionState.CALLING:
                    logger.warning("Non-INVITE transaction timeout",
                                 transaction_id=transaction_id,
                                 timeout=timeout)
                    
                    if callback:
                        try:
                            if asyncio.iscoroutinefunction(callback):
                                await callback(transaction_id)
                            else:
                                callback(transaction_id)
                        except Exception as e:
                            logger.error("Timeout callback failed",
                                        transaction_id=transaction_id,
                                        error=str(e))
                    
                    await self.terminate_transaction(transaction_id)
                
        except asyncio.CancelledError:
            logger.debug("Timer F cancelled", transaction_id=transaction_id)
        except Exception as e:
            logger.error("Timer F error",
                        transaction_id=transaction_id,
                        error=str(e),
                        exc_info=True)
    
    async def response_received(
        self,
        transaction_id: str,
        status_code: int
    ) -> None:
        """응답 수신 처리
        
        Args:
            transaction_id: 트랜잭션 ID
            status_code: SIP 응답 코드
        """
        if transaction_id not in self.transactions:
            return
        
        trans = self.transactions[transaction_id]
        
        if 100 <= status_code < 200:
            # 1xx 응답: Timer A 중지
            trans['state'] = TransactionState.PROCEEDING
            
            if 'timer_a' in trans:
                trans['timer_a'].cancel()
            
            logger.debug("Transaction proceeding",
                        transaction_id=transaction_id,
                        status_code=status_code)
            
        elif 200 <= status_code < 700:
            # 최종 응답: 트랜잭션 완료
            trans['state'] = TransactionState.COMPLETED
            
            logger.info("Transaction completed",
                       transaction_id=transaction_id,
                       status_code=status_code)
            
            # 모든 타이머 취소
            await self.terminate_transaction(transaction_id)
    
    async def terminate_transaction(self, transaction_id: str) -> None:
        """트랜잭션 종료
        
        Args:
            transaction_id: 트랜잭션 ID
        """
        if transaction_id not in self.transactions:
            return
        
        trans = self.transactions[transaction_id]
        trans['state'] = TransactionState.TERMINATED
        
        # 모든 타이머 취소
        for key in ['timer_a', 'timer_b', 'timer_f']:
            if key in trans:
                task = trans[key]
                if not task.done():
                    task.cancel()
                    try:
                        await task
                    except asyncio.CancelledError:
                        pass
        
        # 트랜잭션 제거 (안전하게)
        if transaction_id in self.transactions:
            del self.transactions[transaction_id]
            logger.debug("Transaction terminated", transaction_id=transaction_id)
        else:
            logger.debug("Transaction already removed", transaction_id=transaction_id)
    
    def get_transaction_state(self, transaction_id: str) -> Optional[str]:
        """트랜잭션 상태 조회
        
        Args:
            transaction_id: 트랜잭션 ID
        
        Returns:
            상태 (없으면 None)
        """
        if transaction_id in self.transactions:
            return self.transactions[transaction_id]['state'].value
        return None
    
    def get_stats(self) -> Dict:
        """통계 조회
        
        Returns:
            통계 정보
        """
        return {
            "active_transactions": len(self.transactions),
            "t1": self.t1,
            "t2": self.t2,
            "t4": self.t4
        }
    
    async def cleanup_all(self) -> None:
        """모든 트랜잭션 정리"""
        transaction_ids = list(self.transactions.keys())
        
        for transaction_id in transaction_ids:
            await self.terminate_transaction(transaction_id)
        
        logger.info("All transactions cleaned up", count=len(transaction_ids))

