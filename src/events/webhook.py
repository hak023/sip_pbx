"""Webhook Notifier

이벤트를 외부 시스템으로 전송하는 Webhook 통합
"""

import asyncio
import aiohttp
from typing import List, Optional
from datetime import datetime
import json

from src.ai.event_models import AIEvent
from src.common.logger import get_logger

logger = get_logger(__name__)


class WebhookNotifier:
    """Webhook 알림 전송기
    
    이벤트를 HTTP POST로 webhook URL에 전송
    """
    
    def __init__(
        self,
        webhook_urls: List[str],
        timeout: float = 5.0,
        max_retries: int = 3,
        backoff_factor: float = 2.0,
    ):
        """초기화
        
        Args:
            webhook_urls: Webhook URL 리스트
            timeout: HTTP 요청 타임아웃 (초)
            max_retries: 최대 재시도 횟수
            backoff_factor: Exponential backoff 계수
        """
        self.webhook_urls = webhook_urls
        self.timeout = timeout
        self.max_retries = max_retries
        self.backoff_factor = backoff_factor
        
        # 통계
        self.stats = {
            "total_sent": 0,
            "total_success": 0,
            "total_failed": 0,
            "retries": 0,
        }
        
        logger.info("webhook_notifier_initialized",
                   webhook_count=len(webhook_urls),
                   timeout=timeout,
                   max_retries=max_retries)
    
    async def send_event(self, event: AIEvent) -> bool:
        """이벤트 전송
        
        Args:
            event: AIEvent 객체
            
        Returns:
            전송 성공 여부
        """
        if not self.webhook_urls:
            logger.debug("no_webhook_urls_configured")
            return True
        
        # 이벤트를 JSON으로 변환
        payload = self._create_payload(event)
        
        # 모든 webhook URL에 전송
        tasks = [
            self._send_to_url(url, payload, event.event_id)
            for url in self.webhook_urls
        ]
        
        results = await asyncio.gather(*tasks, return_exceptions=True)
        
        # 최소 하나라도 성공하면 True
        success = any(result is True for result in results)
        
        self.stats["total_sent"] += 1
        if success:
            self.stats["total_success"] += 1
        else:
            self.stats["total_failed"] += 1
        
        return success
    
    async def _send_to_url(
        self,
        url: str,
        payload: dict,
        event_id: str
    ) -> bool:
        """특정 URL에 전송
        
        Args:
            url: Webhook URL
            payload: JSON 페이로드
            event_id: 이벤트 ID
            
        Returns:
            전송 성공 여부
        """
        retry_count = 0
        last_error = None
        
        while retry_count <= self.max_retries:
            try:
                async with aiohttp.ClientSession() as session:
                    timeout = aiohttp.ClientTimeout(total=self.timeout)
                    
                    async with session.post(
                        url,
                        json=payload,
                        timeout=timeout,
                        headers={"Content-Type": "application/json"}
                    ) as response:
                        
                        if response.status >= 200 and response.status < 300:
                            logger.info("webhook_sent_successfully",
                                       event_id=event_id,
                                       url=url,
                                       status=response.status)
                            return True
                        
                        else:
                            logger.warning("webhook_failed_http_error",
                                          event_id=event_id,
                                          url=url,
                                          status=response.status)
                            last_error = f"HTTP {response.status}"
            
            except asyncio.TimeoutError:
                logger.warning("webhook_timeout",
                              event_id=event_id,
                              url=url,
                              retry_count=retry_count)
                last_error = "Timeout"
            
            except aiohttp.ClientError as e:
                logger.warning("webhook_client_error",
                              event_id=event_id,
                              url=url,
                              error=str(e),
                              retry_count=retry_count)
                last_error = str(e)
            
            except Exception as e:
                logger.error("webhook_unexpected_error",
                            event_id=event_id,
                            url=url,
                            error=str(e),
                            retry_count=retry_count)
                last_error = str(e)
            
            # 재시도
            if retry_count < self.max_retries:
                retry_count += 1
                self.stats["retries"] += 1
                
                # Exponential backoff
                backoff_delay = self.backoff_factor ** retry_count
                logger.debug("webhook_retry",
                            event_id=event_id,
                            url=url,
                            retry_count=retry_count,
                            backoff_delay=backoff_delay)
                
                await asyncio.sleep(backoff_delay)
            else:
                break
        
        # 모든 재시도 실패
        logger.error("webhook_all_retries_failed",
                    event_id=event_id,
                    url=url,
                    retries=retry_count,
                    last_error=last_error)
        
        return False
    
    def _create_payload(self, event: AIEvent) -> dict:
        """이벤트를 JSON 페이로드로 변환
        
        Args:
            event: AIEvent 객체
            
        Returns:
            JSON 페이로드
        """
        return {
            "event_id": event.event_id,
            "call_id": event.call_id,
            "timestamp": event.created_at.isoformat(),
            "event_type": event.event_type.value,
            "severity": event.severity.value,
            "confidence": event.confidence,
            "direction": event.direction,
            "details": event.details,
            "call_timestamp": event.timestamp,
        }
    
    def get_stats(self) -> dict:
        """통계 조회"""
        return {
            **self.stats,
            "webhook_urls_count": len(self.webhook_urls),
        }
    
    def add_webhook_url(self, url: str):
        """Webhook URL 추가 (동적 추가)
        
        Args:
            url: Webhook URL
        """
        if url not in self.webhook_urls:
            self.webhook_urls.append(url)
            logger.info("webhook_url_added", url=url)
    
    def remove_webhook_url(self, url: str):
        """Webhook URL 제거
        
        Args:
            url: Webhook URL
        """
        if url in self.webhook_urls:
            self.webhook_urls.remove(url)
            logger.info("webhook_url_removed", url=url)

