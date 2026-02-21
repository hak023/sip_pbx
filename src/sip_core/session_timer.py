"""Session Timer Handler (RFC 4028)

SIP Session-Expires 메커니즘 구현
장시간 통화 시 주기적 UPDATE/re-INVITE로 세션 유지
"""

import asyncio
from typing import Dict, Optional
from datetime import datetime, timedelta
import structlog

from src.common.logger import get_logger

logger = get_logger(__name__)


class SessionTimer:
    """Session Timer 관리자
    
    RFC 4028 구현:
    - Session-Expires 헤더 처리
    - Min-SE (최소 세션 간격) 검증
    - Refresher 역할 결정 (UAC/UAS)
    - 주기적 세션 갱신 (UPDATE 메시지)
    """
    
    def __init__(
        self,
        session_expires: int = 1800,
        min_se: int = 90,
        default_refresher: str = "uas"
    ):
        """초기화
        
        Args:
            session_expires: 세션 만료 시간 (초)
            min_se: 최소 세션 갱신 간격 (초)
            default_refresher: 기본 갱신 주체 (uac/uas)
        """
        self.session_expires = session_expires
        self.min_se = min_se
        self.default_refresher = default_refresher
        
        # 활성 세션 타이머: {call_id: {'task', 'expires_at', 'refresher', ...}}
        self.active_timers: Dict[str, Dict] = {}
        
        logger.info("SessionTimer initialized",
                   session_expires=session_expires,
                   min_se=min_se,
                   default_refresher=default_refresher)
    
    def parse_session_expires(self, header_value: str) -> Dict:
        """Session-Expires 헤더 파싱
        
        Args:
            header_value: Session-Expires 헤더 값
                예: "1800;refresher=uac"
        
        Returns:
            {
                'expires': int,
                'refresher': str
            }
        """
        parts = header_value.split(';')
        expires = int(parts[0].strip())
        
        refresher = self.default_refresher
        for part in parts[1:]:
            if 'refresher=' in part:
                refresher = part.split('=')[1].strip().lower()
        
        return {
            'expires': expires,
            'refresher': refresher
        }
    
    def create_session_expires_header(
        self,
        expires: Optional[int] = None,
        refresher: Optional[str] = None
    ) -> str:
        """Session-Expires 헤더 생성
        
        Args:
            expires: 만료 시간 (None이면 기본값 사용)
            refresher: 갱신 주체 (None이면 기본값 사용)
        
        Returns:
            Session-Expires 헤더 값
        """
        expires = expires or self.session_expires
        refresher = refresher or self.default_refresher
        
        return f"{expires};refresher={refresher}"
    
    async def start_timer(
        self,
        call_id: str,
        expires: int,
        refresher: str,
        refresh_callback=None
    ) -> None:
        """세션 타이머 시작
        
        Args:
            call_id: Call-ID
            expires: 세션 만료 시간 (초)
            refresher: 갱신 주체 (uac/uas)
            refresh_callback: 갱신 콜백 함수
        """
        # 기존 타이머 취소
        await self.cancel_timer(call_id)
        
        # 갱신 시점 계산 (만료 시간의 50% 시점)
        refresh_interval = expires / 2
        
        # 타이머 태스크 생성
        task = asyncio.create_task(
            self._refresh_loop(call_id, refresh_interval, refresh_callback)
        )
        
        self.active_timers[call_id] = {
            'task': task,
            'expires': expires,
            'refresher': refresher,
            'started_at': datetime.now(),
            'last_refresh': datetime.now(),
            'refresh_interval': refresh_interval
        }
        
        logger.info("Session timer started",
                   call_id=call_id,
                   expires=expires,
                   refresher=refresher,
                   refresh_interval=refresh_interval)
    
    async def _refresh_loop(
        self,
        call_id: str,
        interval: float,
        callback
    ) -> None:
        """세션 갱신 루프
        
        Args:
            call_id: Call-ID
            interval: 갱신 간격 (초)
            callback: 갱신 콜백
        """
        try:
            while True:
                await asyncio.sleep(interval)
                
                # 타이머가 취소되었는지 확인
                if call_id not in self.active_timers:
                    break
                
                # 갱신 콜백 호출
                if callback:
                    try:
                        if asyncio.iscoroutinefunction(callback):
                            await callback(call_id)
                        else:
                            callback(call_id)
                        
                        # 갱신 시간 업데이트
                        self.active_timers[call_id]['last_refresh'] = datetime.now()
                        
                        logger.info("Session refreshed",
                                   call_id=call_id,
                                   interval=interval)
                        
                    except Exception as e:
                        logger.error("Session refresh callback failed",
                                    call_id=call_id,
                                    error=str(e),
                                    exc_info=True)
                        # 콜백 실패 시 타이머 중단
                        break
                
        except asyncio.CancelledError:
            logger.debug("Session timer cancelled", call_id=call_id)
        except Exception as e:
            logger.error("Session timer error",
                        call_id=call_id,
                        error=str(e),
                        exc_info=True)
    
    async def cancel_timer(self, call_id: str) -> bool:
        """세션 타이머 취소
        
        Args:
            call_id: Call-ID
        
        Returns:
            취소 성공 여부
        """
        if call_id in self.active_timers:
            timer_info = self.active_timers[call_id]
            task = timer_info['task']
            
            if not task.done():
                task.cancel()
                try:
                    await task
                except asyncio.CancelledError:
                    pass
            
            del self.active_timers[call_id]
            
            logger.info("Session timer cancelled", call_id=call_id)
            return True
        
        return False
    
    def get_timer_info(self, call_id: str) -> Optional[Dict]:
        """세션 타이머 정보 조회
        
        Args:
            call_id: Call-ID
        
        Returns:
            타이머 정보 (없으면 None)
        """
        if call_id in self.active_timers:
            info = self.active_timers[call_id].copy()
            # Task 객체는 제외
            info.pop('task', None)
            return info
        return None
    
    def is_active(self, call_id: str) -> bool:
        """세션 타이머 활성 여부
        
        Args:
            call_id: Call-ID
        
        Returns:
            활성 여부
        """
        return call_id in self.active_timers
    
    def get_stats(self) -> Dict:
        """통계 조회
        
        Returns:
            타이머 통계
        """
        return {
            "active_timers": len(self.active_timers),
            "session_expires": self.session_expires,
            "min_se": self.min_se,
            "default_refresher": self.default_refresher
        }
    
    async def cleanup_all(self) -> None:
        """모든 세션 타이머 정리"""
        call_ids = list(self.active_timers.keys())
        
        for call_id in call_ids:
            await self.cancel_timer(call_id)
        
        logger.info("All session timers cleaned up", count=len(call_ids))

