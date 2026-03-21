"""
HITL (Human-In-The-Loop) 서비스.

- 통화별 응답 큐 등록 (register_call)
- 통화 종료(BYE) 시 타이머 정리 (cancel_timer)
- fallback 긍정 응답 소비 (consume_fallback_affirm)
- start_fallback_timer: 비활성화(운영자 응답은 큐로만 전달, 타임아웃 멘트 미사용)
"""

import asyncio
from typing import Any, Awaitable, Callable, Dict, Optional, Union

# 싱글톤
_hitl_service: Optional["HITLService"] = None


def get_hitl_service() -> "HITLService":
    global _hitl_service
    if _hitl_service is None:
        _hitl_service = HITLService()
    return _hitl_service


class HITLService:
    """HITL 통화별 응답 큐 등록·정리. 타임아웃 자동 멘트는 사용하지 않음."""

    def __init__(self) -> None:
        self._queues: Dict[str, asyncio.Queue] = {}
        # 큐가 생성된 asyncio 이벤트 루프 (WebSocket 스레드 등 다른 루프에서 put 할 때 threadsafe 전달용)
        self._queue_loops: Dict[str, asyncio.AbstractEventLoop] = {}  # register/ensure 시에만 채움
        self._timer_tasks: Dict[str, asyncio.Task] = {}
        self._fallback_affirm: Dict[str, bool] = {}
        self._on_timeout_callback: Optional[
            Union[Callable[[str], None], Callable[[str], Awaitable[Any]]]
        ] = None
        self._timeout_seconds: float = 1200.0  # 레거시 설정 보관 (타이머 미사용)
        self._timeout_message: Optional[str] = None

    def register_on_hitl_timeout(self, callback: Callable[[str], None]) -> None:
        """타임아웃 발생 시 호출할 전역 콜백 등록 (예: AI 재연결)."""
        self._on_timeout_callback = callback

    def set_config(
        self,
        timeout_seconds: Optional[float] = None,
        timeout_message: Optional[str] = None,
    ) -> None:
        """fallback 타이머 기본값 및 타임아웃 메시지 설정."""
        if timeout_seconds is not None:
            self._timeout_seconds = float(timeout_seconds)
        if timeout_message is not None:
            self._timeout_message = timeout_message

    def register_call(self, call_id: str, queue: asyncio.Queue) -> None:
        self._queues[call_id] = queue
        try:
            self._queue_loops[call_id] = asyncio.get_running_loop()
        except RuntimeError:
            # RAGLLMProcessor.__init__ 등 동기 컨텍스트 → build_and_run / consumer에서 ensure_queue_loop
            pass

    def ensure_queue_loop(self, call_id: str) -> None:
        """큐 소비 태스크가 돌아가는 루프를 등록 (register_call 시점에 루프를 못 잡은 경우)."""
        if call_id not in self._queues:
            return
        if call_id in self._queue_loops:
            return
        try:
            self._queue_loops[call_id] = asyncio.get_running_loop()
        except RuntimeError:
            pass

    async def enqueue_response(self, call_id: str, item: Dict[str, Any]) -> bool:
        """HITL/타임아웃 메시지를 통화 큐에 넣음. WebSocket 루프 ≠ SIP 루프일 때 thread-safe put."""
        queue = self._queues.get(call_id)
        if not queue:
            return False
        target_loop = self._queue_loops.get(call_id)
        if target_loop is None:
            target_loop = getattr(queue, "_loop", None)
            if target_loop is not None:
                self._queue_loops[call_id] = target_loop
        try:
            running = asyncio.get_running_loop()
        except RuntimeError:
            running = None

        if target_loop is None:
            return False

        if target_loop is running:
            await queue.put(item)
            return True

        fut = asyncio.run_coroutine_threadsafe(queue.put(item), target_loop)
        await asyncio.wrap_future(fut)
        return True

    def start_fallback_timer(self, call_id: str, timeout_sec: Optional[float] = None) -> None:
        """통화 중 운영자 실제 응답이 오면 즉시 안내하므로, 타이머로 hitl_timeout을 넣지 않습니다."""
        self.cancel_timer(call_id)

    def cancel_timer(self, call_id: str) -> None:
        """해당 통화의 fallback 타이머 취소 (BYE/cleanup 시 호출)."""
        task = self._timer_tasks.pop(call_id, None)
        if task and not task.done():
            task.cancel()

    def unregister_call(self, call_id: str) -> None:
        """통화 해제 시 큐 참조 제거 및 타이머 취소."""
        self.cancel_timer(call_id)
        self._queues.pop(call_id, None)
        self._queue_loops.pop(call_id, None)
        self._fallback_affirm.pop(call_id, None)
    
    def get_response_queue(self, call_id: str) -> Optional[asyncio.Queue]:
        """통화별 응답 큐 반환
        
        Args:
            call_id: 통화 ID
            
        Returns:
            해당 통화의 응답 큐 (없으면 None)
        """
        return self._queues.get(call_id)

    def consume_fallback_affirm(self, call_id: str, intent: str) -> bool:
        """'별도 연락 드릴까요?'에 대한 긍정 응답 여부. True면 한 번만 True 반환 후 소비."""
        if intent in ("affirm", "yes", "응", "네", "예"):
            if not self._fallback_affirm.get(call_id):
                self._fallback_affirm[call_id] = True
                return True
        return False
