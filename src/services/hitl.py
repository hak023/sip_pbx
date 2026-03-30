"""
HITL (Human-In-The-Loop) 서비스.

- 통화별 응답 큐 등록 (register_call)
- 통화 종료(BYE) 시 타이머 정리 (cancel_timer)
- fallback 긍정 응답 소비 (consume_fallback_affirm)
- start_fallback_timer: 비활성화(운영자 응답은 큐로만 전달, 타임아웃 멘트 미사용)
- HITL 요청 FIFO + 통화 종료 시 미저장 Q&A → 지식베이스 flush (hitl_kb_call_end)
"""

import asyncio
import logging
import time
from collections import deque
from dataclasses import dataclass
from typing import Any, Awaitable, Callable, Deque, Dict, List, Optional, Union

logger = logging.getLogger(__name__)

# 싱글톤
_hitl_service: Optional["HITLService"] = None


def get_hitl_service() -> "HITLService":
    global _hitl_service
    if _hitl_service is None:
        _hitl_service = HITLService()
    return _hitl_service


@dataclass
class HitlRequestContext:
    """needs_human 시점 질문과 intent (운영자 응답과 FIFO로 짝지음)."""

    question: str
    intent: str
    alert_type: str
    ts: float
    rewritten_query: str = ""  # LLM이 정제한 검색 쿼리 (STT 오인식 보정용)


class HITLService:
    """HITL 통화별 응답 큐 등록·정리. 타임아웃 자동 멘트는 사용하지 않음."""

    def __init__(self) -> None:
        self._queues: Dict[str, asyncio.Queue] = {}
        # 큐가 생성된 asyncio 이벤트 루프 (WebSocket 스레드 등 다른 루프에서 put 할 때 threadsafe 전달용)
        self._queue_loops: Dict[str, asyncio.AbstractEventLoop] = {}  # register/ensure 시에만 채움
        self._timer_tasks: Dict[str, asyncio.Task] = {}
        self._fallback_affirm: Dict[str, bool] = {}
        # HITL 요청 → 운영자 응답 순서 짝 (통화당 FIFO)
        self._hitl_request_fifo: Dict[str, Deque[HitlRequestContext]] = {}
        # save_to_kb=False 로 제출된 Q&A — 통화 종료 시 지식베이스 적재
        self._pending_kb_at_call_end: Dict[str, List[Dict[str, Any]]] = {}
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

    def _detach_response_queue(self, call_id: str) -> None:
        """응답 큐·타이머·fallback 플래그만 제거 (FIFO·pending은 별도)."""
        self.cancel_timer(call_id)
        self._queues.pop(call_id, None)
        self._queue_loops.pop(call_id, None)
        self._fallback_affirm.pop(call_id, None)

    def unregister_call(self, call_id: str) -> None:
        """통화 해제 시 응답 큐·타이머·FIFO 제거.

        `_pending_kb_at_call_end`는 여기서 지우지 않는다. BYE 시 `flush_hitl_kb_for_call`이
        pop 하기 전에 파이프라인 finally가 unregister만 호출하면 지식 반영이 누락되기 때문이다.
        """
        self._detach_response_queue(call_id)
        self._hitl_request_fifo.pop(call_id, None)

    def note_hitl_request(
        self,
        call_id: str,
        question: str,
        intent: str = "",
        alert_type: str = "",
        rewritten_query: str = "",
    ) -> None:
        """에이전트가 needs_human일 때 호출 — 이후 운영자 응답과 intent 매칭용.

        rewritten_query: LLM이 정제한 검색 쿼리. STT 오인식("기 삼성" 등)이 포함된
        question 대신 KB 저장 Q 텍스트로 우선 사용된다.
        """
        if not call_id:
            return
        q = (question or "").strip()
        rq = (rewritten_query or "").strip()
        self._hitl_request_fifo.setdefault(call_id, deque()).append(
            HitlRequestContext(
                question=q,
                intent=(intent or "").strip(),
                alert_type=(alert_type or "").strip(),
                ts=time.time(),
                rewritten_query=rq,
            )
        )
        logger.info(
            "hitl_request_context_recorded call_id=%s question_len=%s intent=%s "
            "queue_depth=%s has_rewritten_query=%s",
            call_id,
            len(q),
            intent,
            len(self._hitl_request_fifo[call_id]),
            bool(rq),
        )

    def pop_hitl_request_context(self, call_id: str) -> Optional[HitlRequestContext]:
        """운영자 응답 제출 시 가장 오래된 미짝 HITL 요청 컨텍스트를 꺼냄."""
        dq = self._hitl_request_fifo.get(call_id)
        if not dq:
            return None
        try:
            return dq.popleft()
        except IndexError:
            return None

    def queue_hitl_kb_for_call_end(
        self,
        call_id: str,
        question: str,
        answer: str,
        category: str,
        operator_id: str,
        owner: Optional[str] = None,
    ) -> None:
        """통화 종료 시 Chroma에 넣을 HITL Q&A (즉시 저장 안 한 건만).

        owner: 제출 시점에 해석한 테넌트 owner. BYE flush 시 SIP에서 넘어오는 owner보다 우선한다.
        """
        if not call_id or not (question or "").strip() or not (answer or "").strip():
            logger.info(
                "hitl_kb_call_end_queue_skip call_id=%s reason=empty_question_or_answer "
                "has_question=%s has_answer=%s",
                call_id,
                bool((question or "").strip()),
                bool((answer or "").strip()),
            )
            return
        own = (owner or "").strip() or None
        self._pending_kb_at_call_end.setdefault(call_id, []).append(
            {
                "question": question.strip(),
                "answer": answer.strip(),
                "category": category,
                "operator_id": operator_id,
                "owner": own,
            }
        )
        n = len(self._pending_kb_at_call_end[call_id])
        logger.info(
            "hitl_kb_queued_for_call_end call_id=%s category=%s pending_count=%s owner_queued=%s",
            call_id,
            category,
            n,
            bool(own),
        )

    async def flush_hitl_kb_for_call(
        self, call_id: str, owner: Optional[str]
    ) -> int:
        """
        BYE 등 통화 종료 시 대기 중인 HITL Q&A를 지식베이스에 반영.
        처리 후 해당 call_id의 HITL 보조 상태(FIFO·pending)를 정리한다.
        """
        items = self._pending_kb_at_call_end.pop(call_id, [])
        saved = 0
        if items:
            try:
                from src.services.knowledge_service import get_knowledge_service

                ks = get_knowledge_service()
            except Exception as e:
                logger.error(
                    "hitl_kb_flush_knowledge_service_failed call_id=%s error=%s",
                    call_id,
                    e,
                    exc_info=True,
                )
                self._pending_kb_at_call_end[call_id] = items
                self._hitl_request_fifo.pop(call_id, None)
                self._detach_response_queue(call_id)
                return 0

            for it in items:
                try:
                    item_owner = (it.get("owner") or "").strip() or None
                    eff_owner = item_owner or owner
                    result = await ks.add_from_hitl(
                        question=it["question"],
                        answer=it["answer"],
                        call_id=call_id,
                        operator_id=it.get("operator_id") or "call_end_flush",
                        category=it.get("category") or "question",
                        owner=eff_owner,
                        extra_metadata={"kb_timing": "call_end"},
                    )
                    if result.get("success"):
                        saved += 1
                        logger.info(
                            "hitl_kb_flushed_at_call_end call_id=%s doc_id=%s category=%s owner_set=%s "
                            "owner_source=%s",
                            call_id,
                            result.get("doc_id"),
                            it.get("category"),
                            bool(eff_owner),
                            "pending_item" if item_owner else "sip_cleanup",
                        )
                    else:
                        logger.warning(
                            "hitl_kb_flush_item_failed call_id=%s error=%s category=%s",
                            call_id,
                            result.get("error"),
                            it.get("category"),
                        )
                except Exception as e:
                    logger.error(
                        "hitl_kb_flush_item_exception call_id=%s error=%s",
                        call_id,
                        e,
                        exc_info=True,
                    )

            if saved > 0:
                try:
                    from src.websocket.server import emit_knowledge_updated

                    await emit_knowledge_updated(
                        call_id,
                        {
                            "message": f"통화 종료 시 HITL Q&A {saved}건이 지식 베이스에 반영되었습니다",
                            "source": "hitl_call_end",
                            "saved_count": saved,
                        },
                    )
                except Exception as e:
                    logger.debug(
                        "hitl_kb_flush_emit_knowledge_updated_failed call_id=%s error=%s",
                        call_id,
                        e,
                    )

        self._hitl_request_fifo.pop(call_id, None)
        self._detach_response_queue(call_id)
        logger.info(
            "hitl_call_end_kb_flush_done call_id=%s saved_count=%s sip_owner_fallback=%s",
            call_id,
            saved,
            bool(owner),
        )
        return saved
    
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
