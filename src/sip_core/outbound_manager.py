"""Outbound Call Manager

AI 아웃바운드 콜 기능의 핵심 관리자.
유저가 웹에서 요청한 발신 통화의 전체 생명주기를 관리합니다.
"""

import asyncio
from datetime import datetime
from typing import Dict, Optional, List, Callable, Any

from src.sip_core.models.enums import OutboundCallState
from src.sip_core.models.outbound import (
    OutboundCallRecord, OutboundCallResult, QuestionAnswer, TranscriptEntry
)
from src.common.logger import get_async_logger

logger = get_async_logger(__name__)


class OutboundCallManager:
    """AI Outbound Call 생명주기 관리
    
    웹 UI에서 요청받은 아웃바운드 콜을 대기열에 추가하고,
    SIP INVITE 발신 → 응답 처리 → AI 대화 → 결과 저장을 관리합니다.
    """
    
    def __init__(self, config: dict):
        """
        Args:
            config: outbound 관련 설정 (config.yaml의 ai_voicebot.outbound)
        """
        self.config = config
        
        # 활성 콜: outbound_id → OutboundCallRecord
        self.active_calls: Dict[str, OutboundCallRecord] = {}
        # call_id → outbound_id 매핑 (SIP 응답 라우팅용)
        self.call_id_map: Dict[str, str] = {}
        # 완료된 콜 이력 (최근 200건)
        self.call_history: List[OutboundCallRecord] = []
        self._max_history = 200
        
        # 대기열
        self.call_queue: asyncio.Queue = asyncio.Queue()
        
        # 링 타임아웃 태스크
        self._ring_timeout_tasks: Dict[str, asyncio.Task] = {}
        # 최대 통화 시간 태스크
        self._max_duration_tasks: Dict[str, asyncio.Task] = {}
        
        # 콜백 함수들
        self._send_invite_cb: Optional[Callable] = None
        self._send_cancel_cb: Optional[Callable] = None
        self._send_bye_cb: Optional[Callable] = None
        self._start_ai_cb: Optional[Callable] = None
        self._stop_ai_cb: Optional[Callable] = None
        self._emit_event_cb: Optional[Callable] = None
        
        # 설정값
        self.ring_timeout = config.get('ring_timeout', 30)
        self.max_call_duration = config.get('max_call_duration', 300)
        self.max_concurrent = config.get('max_concurrent_calls', 5)
        
        retry_config = config.get('retry', {})
        self.retry_enabled = retry_config.get('enabled', True)
        self.max_retries = retry_config.get('max_retries', 2)
        self.retry_interval = retry_config.get('retry_interval', 300)
        self.retry_on_states = retry_config.get('retry_on', ['no_answer', 'busy'])
        
        logger.info("outbound_manager_initialized",
                    ring_timeout=self.ring_timeout,
                    max_concurrent=self.max_concurrent,
                    max_call_duration=self.max_call_duration)
    
    # =========================================================================
    # 콜백 설정
    # =========================================================================
    
    def set_callbacks(
        self,
        send_invite: Callable = None,
        send_cancel: Callable = None,
        send_bye: Callable = None,
        start_ai: Callable = None,
        stop_ai: Callable = None,
        emit_event: Callable = None,
    ):
        """SIP/AI 콜백 함수 설정"""
        if send_invite:
            self._send_invite_cb = send_invite
        if send_cancel:
            self._send_cancel_cb = send_cancel
        if send_bye:
            self._send_bye_cb = send_bye
        if start_ai:
            self._start_ai_cb = start_ai
        if stop_ai:
            self._stop_ai_cb = stop_ai
        if emit_event:
            self._emit_event_cb = emit_event
    
    # =========================================================================
    # 콜 생성 + 발신
    # =========================================================================
    
    async def create_call(
        self,
        caller_number: str,
        callee_number: str,
        purpose: str,
        questions: List[str],
        caller_display_name: str = "",
        max_duration: int = 0,
        retry_on_no_answer: bool = True,
        metadata: Optional[Dict] = None,
    ) -> OutboundCallRecord:
        """아웃바운드 콜 요청 생성
        
        Returns:
            생성된 OutboundCallRecord
        """
        record = OutboundCallRecord(
            caller_number=caller_number,
            callee_number=callee_number,
            purpose=purpose,
            questions=questions,
            caller_display_name=caller_display_name,
            max_duration=max_duration or self.max_call_duration,
            retry_on_no_answer=retry_on_no_answer,
            max_retries=self.max_retries,
            metadata=metadata,
        )
        
        self.active_calls[record.outbound_id] = record
        
        logger.info("outbound_call_created",
                    outbound_id=record.outbound_id,
                    callee=callee_number,
                    purpose=purpose[:50])
        
        await self._emit_event("outbound_queued", record)
        
        # 동시 통화 수 체크 후 바로 발신 또는 대기열 추가
        active_dialing = sum(
            1 for r in self.active_calls.values()
            if r.state in (OutboundCallState.DIALING, OutboundCallState.RINGING, OutboundCallState.CONNECTED)
        )
        
        if active_dialing < self.max_concurrent:
            await self._dial(record)
        else:
            await self.call_queue.put(record.outbound_id)
            logger.info("outbound_call_queued",
                       outbound_id=record.outbound_id,
                       queue_size=self.call_queue.qsize())
        
        return record
    
    async def _dial(self, record: OutboundCallRecord):
        """실제 SIP INVITE 발신"""
        if not self._send_invite_cb:
            logger.error("send_invite_callback_not_set")
            record.state = OutboundCallState.FAILED
            record.failure_reason = "INVITE callback not configured"
            await self._complete(record)
            return
        
        record.state = OutboundCallState.DIALING
        record.started_at = datetime.utcnow()
        record.attempt_count += 1
        
        await self._emit_event("outbound_dialing", record)
        
        try:
            call_id = await self._send_invite_cb(
                to_number=record.callee_number,
                from_number=record.caller_number,
                from_display=record.caller_display_name,
                outbound_id=record.outbound_id,
            )
            record.call_id = call_id
            self.call_id_map[call_id] = record.outbound_id
            
            # 링 타임아웃 설정
            self._ring_timeout_tasks[record.outbound_id] = asyncio.create_task(
                self._ring_timeout_handler(record.outbound_id)
            )
            
            logger.info("outbound_invite_sent",
                       outbound_id=record.outbound_id,
                       call_id=call_id,
                       attempt=record.attempt_count)
            
        except Exception as e:
            logger.error("outbound_dial_error",
                        outbound_id=record.outbound_id, error=str(e))
            record.state = OutboundCallState.FAILED
            record.failure_reason = str(e)
            await self._complete(record)
    
    async def _ring_timeout_handler(self, outbound_id: str):
        """링 타임아웃 핸들러"""
        try:
            await asyncio.sleep(self.ring_timeout)
            
            record = self.active_calls.get(outbound_id)
            if record and record.state in (OutboundCallState.DIALING, OutboundCallState.RINGING):
                logger.warning("outbound_ring_timeout",
                              outbound_id=outbound_id,
                              timeout=self.ring_timeout)
                
                # CANCEL 전송
                if record.call_id and self._send_cancel_cb:
                    await self._send_cancel_cb(record.call_id)
                
                record.state = OutboundCallState.NO_ANSWER
                record.failure_reason = f"Ring timeout ({self.ring_timeout}s)"
                await self._handle_failure(record)
                
        except asyncio.CancelledError:
            pass
        except Exception as e:
            logger.error("ring_timeout_handler_error",
                        outbound_id=outbound_id, error=str(e))
    
    async def _max_duration_handler(self, outbound_id: str):
        """최대 통화 시간 핸들러"""
        try:
            record = self.active_calls.get(outbound_id)
            if not record:
                return
            await asyncio.sleep(record.max_duration)
            
            record = self.active_calls.get(outbound_id)
            if record and record.state == OutboundCallState.CONNECTED:
                logger.warning("outbound_max_duration_reached",
                              outbound_id=outbound_id,
                              max_duration=record.max_duration)
                
                # AI 중지 + 부분 결과 수집
                partial_result = None
                if self._stop_ai_cb:
                    partial_result = await self._stop_ai_cb(record.call_id)
                
                if partial_result:
                    record.result = partial_result
                
                # BYE 전송
                if record.call_id and self._send_bye_cb:
                    await self._send_bye_cb(record.call_id)
                
                record.state = OutboundCallState.COMPLETED
                record.failure_reason = "Max duration reached"
                await self._complete(record)
                
        except asyncio.CancelledError:
            pass
        except Exception as e:
            logger.error("max_duration_handler_error",
                        outbound_id=outbound_id, error=str(e))
    
    # =========================================================================
    # SIP 응답 핸들러
    # =========================================================================
    
    async def on_provisional(self, call_id: str, status_code: int):
        """180 Ringing 등 Provisional 응답"""
        outbound_id = self.call_id_map.get(call_id)
        if not outbound_id:
            return
        
        record = self.active_calls.get(outbound_id)
        if not record:
            return
        
        if status_code == 180:
            record.state = OutboundCallState.RINGING
            await self._emit_event("outbound_ringing", record)
        
        logger.info("outbound_provisional",
                    outbound_id=outbound_id,
                    status_code=status_code)
    
    async def on_answered(self, call_id: str, callee_sdp: str = ""):
        """200 OK 수신 → AI 대화 시작"""
        outbound_id = self.call_id_map.get(call_id)
        if not outbound_id:
            logger.warning("outbound_answered_unknown_call", call_id=call_id)
            return
        
        record = self.active_calls.get(outbound_id)
        if not record:
            return
        
        logger.info("outbound_answered",
                    outbound_id=outbound_id,
                    call_id=call_id)
        
        # 1. 링 타임아웃 취소
        self._cancel_ring_timeout(outbound_id)
        
        # 2. 상태 업데이트
        record.state = OutboundCallState.CONNECTED
        record.answered_at = datetime.utcnow()
        
        # 3. 최대 통화 시간 타이머 설정
        self._max_duration_tasks[outbound_id] = asyncio.create_task(
            self._max_duration_handler(outbound_id)
        )
        
        # 4. AI 모드 시작 (아웃바운드 컨텍스트 전달)
        if self._start_ai_cb:
            await self._start_ai_cb(
                call_id=call_id,
                outbound_context={
                    "outbound_id": record.outbound_id,
                    "purpose": record.purpose,
                    "questions": record.questions,
                    "caller_display_name": record.caller_display_name,
                    "callee_number": record.callee_number,
                }
            )
        
        await self._emit_event("outbound_connected", record)
    
    async def on_rejected(self, call_id: str, status_code: int, reason: str = ""):
        """4xx/5xx/6xx 수신"""
        outbound_id = self.call_id_map.get(call_id)
        if not outbound_id:
            return
        
        record = self.active_calls.get(outbound_id)
        if not record:
            return
        
        self._cancel_ring_timeout(outbound_id)
        
        if status_code == 486:
            record.state = OutboundCallState.BUSY
        elif status_code == 603:
            record.state = OutboundCallState.REJECTED
        elif status_code == 480:
            record.state = OutboundCallState.NO_ANSWER
        else:
            record.state = OutboundCallState.FAILED
        
        record.failure_reason = f"SIP {status_code} {reason}"
        
        logger.warning("outbound_rejected",
                       outbound_id=outbound_id,
                       status_code=status_code,
                       reason=reason)
        
        await self._handle_failure(record)
    
    async def on_task_completed(self, call_id: str, result: OutboundCallResult):
        """AI가 모든 태스크 완료 보고 → BYE 발신"""
        outbound_id = self.call_id_map.get(call_id)
        if not outbound_id:
            return
        
        record = self.active_calls.get(outbound_id)
        if not record:
            return
        
        logger.info("outbound_task_completed",
                    outbound_id=outbound_id,
                    task_completed=result.task_completed,
                    answers_count=len(result.answers))
        
        record.result = result
        record.state = OutboundCallState.COMPLETED
        record.completed_at = datetime.utcnow()
        
        # BYE 발신
        if record.call_id and self._send_bye_cb:
            await self._send_bye_cb(record.call_id)
        
        await self._complete(record)
        await self._emit_event("outbound_completed", record)
    
    async def on_bye_received(self, call_id: str):
        """상대방(착신자)이 먼저 끊음"""
        outbound_id = self.call_id_map.get(call_id)
        if not outbound_id:
            return False
        
        record = self.active_calls.get(outbound_id)
        if not record:
            return False
        
        logger.info("outbound_bye_received",
                    outbound_id=outbound_id,
                    state=record.state.value)
        
        if record.state == OutboundCallState.CONNECTED:
            # AI에서 현재까지 결과 수집
            partial_result = None
            if self._stop_ai_cb:
                partial_result = await self._stop_ai_cb(call_id)
            
            if partial_result:
                record.result = partial_result
        
        record.state = OutboundCallState.COMPLETED
        record.completed_at = datetime.utcnow()
        
        await self._complete(record)
        await self._emit_event("outbound_ended", record)
        
        return True
    
    # =========================================================================
    # 취소
    # =========================================================================
    
    async def cancel_call(self, outbound_id: str, reason: str = "operator_cancel"):
        """운영자가 콜 취소"""
        record = self.active_calls.get(outbound_id)
        if not record:
            return None
        
        logger.info("outbound_cancel_requested",
                    outbound_id=outbound_id, reason=reason)
        
        self._cancel_ring_timeout(outbound_id)
        self._cancel_max_duration(outbound_id)
        
        # CANCEL/BYE 전송
        if record.call_id:
            if record.state in (OutboundCallState.DIALING, OutboundCallState.RINGING):
                if self._send_cancel_cb:
                    await self._send_cancel_cb(record.call_id)
            elif record.state == OutboundCallState.CONNECTED:
                if self._stop_ai_cb:
                    await self._stop_ai_cb(record.call_id)
                if self._send_bye_cb:
                    await self._send_bye_cb(record.call_id)
        
        record.state = OutboundCallState.CANCELLED
        record.failure_reason = reason
        record.completed_at = datetime.utcnow()
        
        await self._complete(record)
        await self._emit_event("outbound_cancelled", record)
        
        return record
    
    # =========================================================================
    # 재시도
    # =========================================================================
    
    async def retry_call(self, outbound_id: str) -> Optional[OutboundCallRecord]:
        """콜 재시도 (수동)"""
        # 이력에서 찾기
        record = None
        for r in self.call_history:
            if r.outbound_id == outbound_id:
                record = r
                break
        
        if not record:
            return None
        
        if record.state not in (OutboundCallState.NO_ANSWER, OutboundCallState.BUSY,
                                OutboundCallState.FAILED, OutboundCallState.REJECTED):
            return None
        
        # 새 레코드 생성 (같은 요청 정보)
        return await self.create_call(
            caller_number=record.caller_number,
            callee_number=record.callee_number,
            purpose=record.purpose,
            questions=record.questions,
            caller_display_name=record.caller_display_name,
            max_duration=record.max_duration,
            retry_on_no_answer=False,  # 수동 재시도이므로 자동 재시도 비활성
        )
    
    async def _handle_failure(self, record: OutboundCallRecord):
        """실패 시 자동 재시도 또는 최종 실패 처리"""
        should_retry = (
            self.retry_enabled
            and record.retry_on_no_answer
            and record.attempt_count < record.max_retries
            and record.state.value in self.retry_on_states
        )
        
        if should_retry:
            logger.info("outbound_auto_retry_scheduled",
                       outbound_id=record.outbound_id,
                       attempt=record.attempt_count,
                       retry_after=self.retry_interval)
            
            await self._emit_event("outbound_retry_scheduled", record)
            
            # 재시도 스케줄링
            asyncio.create_task(self._retry_after_delay(record))
        else:
            record.completed_at = datetime.utcnow()
            await self._complete(record)
            await self._emit_event("outbound_failed", record)
    
    async def _retry_after_delay(self, record: OutboundCallRecord):
        """지연 후 재시도"""
        try:
            await asyncio.sleep(self.retry_interval)
            # 아직 활성 상태인지 확인 (취소되지 않았는지)
            if record.outbound_id in self.active_calls:
                record.state = OutboundCallState.QUEUED
                await self._dial(record)
        except asyncio.CancelledError:
            pass
        except Exception as e:
            logger.error("retry_delay_error",
                        outbound_id=record.outbound_id, error=str(e))
    
    # =========================================================================
    # 내부 헬퍼
    # =========================================================================
    
    def _cancel_ring_timeout(self, outbound_id: str):
        """링 타임아웃 취소"""
        task = self._ring_timeout_tasks.pop(outbound_id, None)
        if task:
            task.cancel()
    
    def _cancel_max_duration(self, outbound_id: str):
        """최대 통화 시간 타이머 취소"""
        task = self._max_duration_tasks.pop(outbound_id, None)
        if task:
            task.cancel()
    
    async def _complete(self, record: OutboundCallRecord):
        """콜 완료 처리 (정리)"""
        outbound_id = record.outbound_id
        
        self._cancel_ring_timeout(outbound_id)
        self._cancel_max_duration(outbound_id)
        
        # call_id_map 정리
        if record.call_id:
            self.call_id_map.pop(record.call_id, None)
        
        # active → history
        self.active_calls.pop(outbound_id, None)
        self.call_history.append(record)
        if len(self.call_history) > self._max_history:
            self.call_history = self.call_history[-self._max_history:]
        
        # 대기열 처리
        await self._process_queue()
    
    async def _process_queue(self):
        """대기열에서 다음 콜 발신"""
        active_dialing = sum(
            1 for r in self.active_calls.values()
            if r.state in (OutboundCallState.DIALING, OutboundCallState.RINGING, OutboundCallState.CONNECTED)
        )
        
        while active_dialing < self.max_concurrent and not self.call_queue.empty():
            try:
                outbound_id = self.call_queue.get_nowait()
                record = self.active_calls.get(outbound_id)
                if record and record.state == OutboundCallState.QUEUED:
                    await self._dial(record)
                    active_dialing += 1
            except asyncio.QueueEmpty:
                break
    
    async def _emit_event(self, event_type: str, record: OutboundCallRecord):
        """WebSocket 이벤트 발행"""
        if self._emit_event_cb:
            try:
                await self._emit_event_cb(event_type, record.to_dict())
            except Exception as e:
                logger.error("outbound_event_emit_error",
                            event=event_type, error=str(e))
    
    # =========================================================================
    # 조회
    # =========================================================================
    
    def get_call(self, outbound_id: str) -> Optional[OutboundCallRecord]:
        """콜 조회 (활성 + 이력)"""
        record = self.active_calls.get(outbound_id)
        if record:
            return record
        for r in self.call_history:
            if r.outbound_id == outbound_id:
                return r
        return None
    
    def get_active_calls(self) -> List[dict]:
        """활성 콜 목록"""
        return [r.to_dict() for r in self.active_calls.values()]
    
    def get_call_history(self, limit: int = 50) -> List[dict]:
        """콜 이력"""
        return [r.to_dict() for r in self.call_history[-limit:]]
    
    def get_stats(self) -> dict:
        """통계"""
        total = len(self.call_history)
        if total == 0:
            return {
                "total_calls": 0,
                "completed_count": 0,
                "success_rate": 0.0,
                "avg_duration_seconds": 0,
                "no_answer_count": 0,
                "busy_count": 0,
                "active_count": len(self.active_calls),
                "queue_size": self.call_queue.qsize(),
            }
        
        completed = sum(1 for r in self.call_history if r.state == OutboundCallState.COMPLETED)
        no_answer = sum(1 for r in self.call_history if r.state == OutboundCallState.NO_ANSWER)
        busy = sum(1 for r in self.call_history if r.state == OutboundCallState.BUSY)
        
        durations = []
        for r in self.call_history:
            if r.result and r.result.duration_seconds:
                durations.append(r.result.duration_seconds)
            elif r.answered_at and r.completed_at:
                durations.append(int((r.completed_at - r.answered_at).total_seconds()))
        
        avg_dur = sum(durations) / len(durations) if durations else 0
        
        task_completed_count = sum(
            1 for r in self.call_history
            if r.result and r.result.task_completed
        )
        
        return {
            "total_calls": total,
            "completed_count": completed,
            "task_completed_count": task_completed_count,
            "success_rate": round(completed / total, 3) if total > 0 else 0.0,
            "avg_duration_seconds": round(avg_dur, 1),
            "no_answer_count": no_answer,
            "busy_count": busy,
            "active_count": len(self.active_calls),
            "queue_size": self.call_queue.qsize(),
        }
    
    def is_outbound_call(self, call_id: str) -> bool:
        """해당 Call-ID가 아웃바운드 콜인지"""
        return call_id in self.call_id_map
