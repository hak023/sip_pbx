"""Transfer Manager

AI 호 연결(Transfer) 기능의 핵심 관리자.
B2BUA 기반 제3자 호 제어 (RFC 3725 3pcc 패턴).

발신자↔서버↔착신자 미디어 브릿지를 관리합니다.
"""

import asyncio
import time
from datetime import datetime
from typing import Dict, Optional, Tuple, Any, Callable
from uuid import uuid4

from src.sip_core.models.enums import TransferState
from src.sip_core.models.transfer import TransferRecord
from src.common.logger import get_async_logger

logger = get_async_logger(__name__)


class TransferManager:
    """호 전환 관리자
    
    AI Orchestrator의 전환 요청을 받아 SIP INVITE 발신,
    응답 처리, RTP Bridge 전환을 관리합니다.
    """
    
    def __init__(self, config: dict):
        """
        Args:
            config: transfer 관련 설정 (config.yaml의 ai_voicebot.transfer)
        """
        self.config = config
        
        # 활성 전환 기록: call_id → TransferRecord
        self.active_transfers: Dict[str, TransferRecord] = {}
        # transfer_leg_call_id → call_id 매핑
        self.transfer_leg_map: Dict[str, str] = {}
        # 완료된 전환 이력 (최근 100건)
        self.transfer_history: list = []
        self._max_history = 100
        
        # 링 타임아웃 태스크: call_id → asyncio.Task
        self._ring_timeout_tasks: Dict[str, asyncio.Task] = {}
        
        # 콜백 함수들 (SIPEndpoint에서 설정)
        self._send_invite_cb: Optional[Callable] = None
        self._send_cancel_cb: Optional[Callable] = None
        self._send_bye_cb: Optional[Callable] = None
        self._switch_to_bridge_cb: Optional[Callable] = None
        self._stop_ai_cb: Optional[Callable] = None
        self._resume_ai_cb: Optional[Callable] = None
        self._speak_to_caller_cb: Optional[Callable] = None
        
        # WebSocket 이벤트 발행 콜백
        self._emit_event_cb: Optional[Callable] = None
        
        # 설정값
        self.ring_timeout = config.get('ring_timeout', 30)
        self.announcement_mode = config.get('announcement_mode', 'template')
        self.announcement_template = config.get(
            'announcement_template',
            '{department}로 전화 연결하겠습니다. '
            '연결되는 전화번호는 {phone}입니다. '
            '연결되는 동안 잠시만 기다려주세요.'
        )
        self.waiting_message = config.get(
            'waiting_message',
            '연결 중입니다. 잠시만 기다려주세요.'
        )
        self.retry_enabled = config.get('retry_enabled', True)
        self.max_retries = config.get('max_retries', 2)
        self.min_similarity = config.get('min_similarity_threshold', 0.75)
        
        logger.info("transfer_manager_initialized",
                    ring_timeout=self.ring_timeout,
                    announcement_mode=self.announcement_mode)
    
    # =========================================================================
    # 콜백 설정
    # =========================================================================
    
    def set_callbacks(
        self,
        send_invite: Callable = None,
        send_cancel: Callable = None,
        send_bye: Callable = None,
        switch_to_bridge: Callable = None,
        stop_ai: Callable = None,
        resume_ai: Callable = None,
        speak_to_caller: Callable = None,
        emit_event: Callable = None,
    ):
        """SIP/RTP/AI 콜백 함수 설정"""
        if send_invite:
            self._send_invite_cb = send_invite
        if send_cancel:
            self._send_cancel_cb = send_cancel
        if send_bye:
            self._send_bye_cb = send_bye
        if switch_to_bridge:
            self._switch_to_bridge_cb = switch_to_bridge
        if stop_ai:
            self._stop_ai_cb = stop_ai
        if resume_ai:
            self._resume_ai_cb = resume_ai
        if speak_to_caller:
            self._speak_to_caller_cb = speak_to_caller
        if emit_event:
            self._emit_event_cb = emit_event
    
    # =========================================================================
    # 전환 시작
    # =========================================================================
    
    async def initiate_transfer(
        self,
        call_id: str,
        transfer_to: str,
        department_name: str,
        phone_display: str,
        user_request_text: str,
        caller_uri: str = "",
        caller_display: str = "",
    ) -> Optional[TransferRecord]:
        """호 전환 시작
        
        Args:
            call_id: 원래 호 ID
            transfer_to: 전환 대상 (SIP URI, 내선번호 등)
            department_name: 부서명
            phone_display: 표시 번호
            user_request_text: 발신자의 원래 요청
            caller_uri: 발신자 SIP URI
            caller_display: 발신자 표시명
            
        Returns:
            TransferRecord 또는 None (실패 시)
        """
        # 이미 활성 전환이 있으면 거부
        if call_id in self.active_transfers:
            logger.warning("transfer_already_active", call_id=call_id)
            return None
        
        # 전환 기록 생성
        transfer_leg_call_id = f"xfer-leg-{uuid4().hex[:8]}-{call_id[:8]}"
        
        record = TransferRecord(
            call_id=call_id,
            transfer_leg_call_id=transfer_leg_call_id,
            department_name=department_name,
            transfer_to=transfer_to,
            phone_display=phone_display,
            caller_uri=caller_uri,
            caller_display=caller_display,
            state=TransferState.ANNOUNCE,
            user_request_text=user_request_text,
        )
        
        self.active_transfers[call_id] = record
        self.transfer_leg_map[transfer_leg_call_id] = call_id
        
        logger.info("transfer_initiated",
                    call_id=call_id,
                    transfer_id=record.transfer_id,
                    department=department_name,
                    transfer_to=transfer_to)
        
        # 이벤트 발행
        await self._emit_event("transfer_initiated", record)
        
        # 안내 멘트 생성 및 재생
        announcement = self._build_announcement(department_name, phone_display)
        
        # 안내 멘트 재생 (비동기)
        if self._speak_to_caller_cb:
            asyncio.create_task(
                self._speak_and_invite(call_id, record, announcement)
            )
        else:
            # 콜백 미설정 시 바로 INVITE
            await self._send_transfer_invite(call_id, record)
        
        return record
    
    async def _speak_and_invite(
        self, call_id: str, record: TransferRecord, announcement: str
    ):
        """안내 멘트 재생 후 INVITE 발신"""
        try:
            # 안내 멘트 재생 (barge-in OFF)
            if self._speak_to_caller_cb:
                await self._speak_to_caller_cb(call_id, announcement, allow_barge_in=False)
            
            # INVITE 발신
            await self._send_transfer_invite(call_id, record)
            
        except Exception as e:
            logger.error("speak_and_invite_error",
                        call_id=call_id, error=str(e))
            await self._handle_transfer_failure(call_id, 500, f"Internal error: {e}")
    
    async def _send_transfer_invite(self, call_id: str, record: TransferRecord):
        """Transfer INVITE 발신"""
        if not self._send_invite_cb:
            logger.error("send_invite_callback_not_set", call_id=call_id)
            await self._handle_transfer_failure(call_id, 500, "INVITE callback not set")
            return
        
        try:
            # 상태 업데이트 → RINGING
            record.state = TransferState.RINGING
            record.ringing_at = datetime.utcnow()
            await self._emit_event("transfer_ringing", record)
            
            # SIP INVITE 발신 (SIPEndpoint에 위임)
            await self._send_invite_cb(
                call_id=call_id,
                transfer_leg_call_id=record.transfer_leg_call_id,
                transfer_to=record.transfer_to,
                caller_display=record.caller_display or record.caller_uri,
            )
            
            # 링 타임아웃 설정
            self._ring_timeout_tasks[call_id] = asyncio.create_task(
                self._ring_timeout_handler(call_id)
            )
            
            logger.info("transfer_invite_sent",
                        call_id=call_id,
                        transfer_leg=record.transfer_leg_call_id,
                        transfer_to=record.transfer_to)
            
            # 대기 안내
            if self._speak_to_caller_cb:
                asyncio.create_task(
                    self._speak_to_caller_cb(call_id, self.waiting_message, allow_barge_in=True)
                )
            
        except Exception as e:
            logger.error("transfer_invite_error",
                        call_id=call_id, error=str(e))
            await self._handle_transfer_failure(call_id, 500, str(e))
    
    async def _ring_timeout_handler(self, call_id: str):
        """링 타임아웃 핸들러"""
        try:
            await asyncio.sleep(self.ring_timeout)
            
            record = self.active_transfers.get(call_id)
            if record and record.state == TransferState.RINGING:
                logger.warning("transfer_ring_timeout",
                              call_id=call_id,
                              timeout=self.ring_timeout)
                
                # CANCEL 전송
                if self._send_cancel_cb:
                    await self._send_cancel_cb(record.transfer_leg_call_id)
                
                await self._handle_transfer_failure(call_id, 408, "Ring timeout")
                
        except asyncio.CancelledError:
            pass  # 정상 취소 (착신자가 응답함)
        except Exception as e:
            logger.error("ring_timeout_handler_error",
                        call_id=call_id, error=str(e))
    
    # =========================================================================
    # 응답 처리
    # =========================================================================
    
    async def on_transfer_provisional(self, transfer_leg_call_id: str, status_code: int):
        """전환 호 Provisional 응답 (180 Ringing 등)"""
        call_id = self.transfer_leg_map.get(transfer_leg_call_id)
        if not call_id:
            return
        
        record = self.active_transfers.get(call_id)
        if not record:
            return
        
        logger.info("transfer_provisional",
                    call_id=call_id,
                    status_code=status_code)
    
    async def on_transfer_answered(
        self, transfer_leg_call_id: str, callee_sdp: str = ""
    ):
        """착신자 응답 (200 OK) → 미디어 브릿지 구성
        
        Args:
            transfer_leg_call_id: 전환 레그 Call-ID
            callee_sdp: 착신자 SDP (미디어 포트 정보)
        """
        call_id = self.transfer_leg_map.get(transfer_leg_call_id)
        if not call_id:
            logger.warning("transfer_answered_unknown_leg",
                          transfer_leg=transfer_leg_call_id)
            return
        
        record = self.active_transfers.get(call_id)
        if not record:
            return
        
        logger.info("transfer_answered",
                    call_id=call_id,
                    transfer_id=record.transfer_id,
                    department=record.department_name)
        
        # 1. 링 타임아웃 취소
        if call_id in self._ring_timeout_tasks:
            self._ring_timeout_tasks[call_id].cancel()
            del self._ring_timeout_tasks[call_id]
        
        # 2. AI 모드 중단
        if self._stop_ai_cb:
            await self._stop_ai_cb(call_id)
        
        # 3. RTP Relay를 Bridge 모드로 전환
        if self._switch_to_bridge_cb:
            await self._switch_to_bridge_cb(
                call_id=call_id,
                transfer_leg_call_id=transfer_leg_call_id,
                callee_sdp=callee_sdp,
            )
        
        # 4. 상태 업데이트
        record.state = TransferState.CONNECTED
        record.connected_at = datetime.utcnow()
        
        # 5. 이벤트 발행
        await self._emit_event("transfer_connected", record)
        
        logger.info("transfer_bridge_established",
                    call_id=call_id,
                    transfer_id=record.transfer_id,
                    department=record.department_name)
    
    async def on_transfer_rejected(
        self, transfer_leg_call_id: str, status_code: int, reason: str = ""
    ):
        """전환 호 거절/실패 (4xx/5xx/6xx)"""
        call_id = self.transfer_leg_map.get(transfer_leg_call_id)
        if not call_id:
            return
        
        logger.warning("transfer_rejected",
                       call_id=call_id,
                       status_code=status_code,
                       reason=reason)
        
        await self._handle_transfer_failure(call_id, status_code, reason)
    
    # =========================================================================
    # BYE 처리
    # =========================================================================
    
    async def on_bye_received(self, leg_call_id: str, initiator: str = "unknown"):
        """전환 상태에서 BYE 수신
        
        Args:
            leg_call_id: BYE를 받은 레그의 Call-ID
            initiator: "caller" 또는 "callee"
        """
        # call_id 찾기 (transfer_leg인지 원래 leg인지)
        call_id = self.transfer_leg_map.get(leg_call_id, leg_call_id)
        record = self.active_transfers.get(call_id)
        
        if not record:
            return False  # 이 TransferManager가 관리하는 호가 아님
        
        logger.info("transfer_bye_received",
                    call_id=call_id,
                    initiator=initiator,
                    state=record.state.value)
        
        if record.state == TransferState.CONNECTED:
            # 한쪽이 끊으면 양쪽 모두 BYE
            if self._send_bye_cb:
                if initiator == "caller":
                    await self._send_bye_cb(record.transfer_leg_call_id)
                else:
                    await self._send_bye_cb(record.call_id)
        
        elif record.state in (TransferState.ANNOUNCE, TransferState.RINGING):
            # 전환 진행 중 발신자 종료 → CANCEL
            if self._send_cancel_cb:
                await self._send_cancel_cb(record.transfer_leg_call_id)
            record.state = TransferState.CANCELLED
        
        # 기록 업데이트
        record.ended_at = datetime.utcnow()
        if record.connected_at:
            record.duration_seconds = int(
                (record.ended_at - record.connected_at).total_seconds()
            )
        
        await self._cleanup_transfer(call_id)
        await self._emit_event("transfer_ended", record)
        
        return True
    
    # =========================================================================
    # 취소
    # =========================================================================
    
    async def cancel_transfer(self, call_id: str, reason: str = "user_cancelled"):
        """전환 취소 (발신자 barge-in 등)"""
        record = self.active_transfers.get(call_id)
        if not record:
            return
        
        logger.info("transfer_cancelled",
                    call_id=call_id,
                    reason=reason)
        
        # 링 타임아웃 취소
        if call_id in self._ring_timeout_tasks:
            self._ring_timeout_tasks[call_id].cancel()
            del self._ring_timeout_tasks[call_id]
        
        # CANCEL 전송 (RINGING 상태일 때)
        if record.state == TransferState.RINGING and self._send_cancel_cb:
            await self._send_cancel_cb(record.transfer_leg_call_id)
        
        record.state = TransferState.CANCELLED
        record.failure_reason = reason
        record.ended_at = datetime.utcnow()
        
        await self._cleanup_transfer(call_id)
        await self._emit_event("transfer_cancelled", record)
    
    # =========================================================================
    # 내부 헬퍼
    # =========================================================================
    
    def _build_announcement(self, department_name: str, phone_display: str) -> str:
        """전환 안내 멘트 생성"""
        return self.announcement_template.format(
            department=department_name,
            phone=phone_display,
        )
    
    def _get_failure_message(self, department_name: str, status_code: int) -> str:
        """상태 코드별 실패 메시지"""
        messages = {
            408: f"죄송합니다. {department_name}에서 응답이 없습니다. 다른 도움이 필요하시면 말씀해주세요.",
            480: f"죄송합니다. {department_name}이 현재 통화 불가능 상태입니다. 다른 도움이 필요하시면 말씀해주세요.",
            486: f"죄송합니다. {department_name}이 현재 통화 중입니다. 다른 도움이 필요하시면 말씀해주세요.",
            603: f"죄송합니다. {department_name}에서 전화를 받지 않았습니다. 다른 도움이 필요하시면 말씀해주세요.",
        }
        return messages.get(
            status_code,
            f"죄송합니다. {department_name}과 연결이 되지 않았습니다. "
            f"다른 도움이 필요하시면 말씀해주세요."
        )
    
    async def _handle_transfer_failure(self, call_id: str, status_code: int, reason: str):
        """전환 실패 공통 처리"""
        record = self.active_transfers.get(call_id)
        if not record:
            return
        
        # 링 타임아웃 취소
        if call_id in self._ring_timeout_tasks:
            self._ring_timeout_tasks[call_id].cancel()
            del self._ring_timeout_tasks[call_id]
        
        record.state = TransferState.FAILED
        record.failure_reason = f"{status_code} {reason}"
        record.ended_at = datetime.utcnow()
        
        # 실패 안내 멘트
        failure_msg = self._get_failure_message(record.department_name, status_code)
        if self._speak_to_caller_cb:
            await self._speak_to_caller_cb(call_id, failure_msg, allow_barge_in=False)
        
        # AI 모드 복귀
        if self._resume_ai_cb:
            await self._resume_ai_cb(call_id)
        
        await self._cleanup_transfer(call_id)
        await self._emit_event("transfer_failed", record)
    
    async def _cleanup_transfer(self, call_id: str):
        """전환 기록 정리"""
        record = self.active_transfers.pop(call_id, None)
        if record:
            # 이력에 추가
            self.transfer_history.append(record)
            if len(self.transfer_history) > self._max_history:
                self.transfer_history = self.transfer_history[-self._max_history:]
            
            # transfer_leg_map에서 제거
            self.transfer_leg_map.pop(record.transfer_leg_call_id, None)
    
    async def _emit_event(self, event_type: str, record: TransferRecord):
        """WebSocket 이벤트 발행"""
        if self._emit_event_cb:
            try:
                await self._emit_event_cb(event_type, record.to_dict())
            except Exception as e:
                logger.error("transfer_event_emit_error",
                            event=event_type, error=str(e))
    
    # =========================================================================
    # 조회
    # =========================================================================
    
    def get_active_transfer(self, call_id: str) -> Optional[TransferRecord]:
        """활성 전환 조회"""
        return self.active_transfers.get(call_id)
    
    def get_active_transfers(self) -> list:
        """모든 활성 전환 목록"""
        return [r.to_dict() for r in self.active_transfers.values()]
    
    def get_transfer_history(self, limit: int = 50) -> list:
        """전환 이력 조회"""
        return [r.to_dict() for r in self.transfer_history[-limit:]]
    
    def get_stats(self) -> dict:
        """전환 통계"""
        total = len(self.transfer_history)
        if total == 0:
            return {
                "total_transfers": 0,
                "success_rate": 0.0,
                "avg_ring_duration_seconds": 0,
                "active_count": len(self.active_transfers),
            }
        
        successful = sum(1 for r in self.transfer_history if r.state == TransferState.CONNECTED)
        
        ring_durations = []
        for r in self.transfer_history:
            if r.ringing_at and (r.connected_at or r.ended_at):
                end = r.connected_at or r.ended_at
                ring_durations.append((end - r.ringing_at).total_seconds())
        
        avg_ring = sum(ring_durations) / len(ring_durations) if ring_durations else 0
        
        call_durations = [r.duration_seconds for r in self.transfer_history if r.duration_seconds]
        avg_call = sum(call_durations) / len(call_durations) if call_durations else 0
        
        return {
            "total_transfers": total,
            "success_rate": round(successful / total, 3) if total > 0 else 0.0,
            "avg_ring_duration_seconds": round(avg_ring, 1),
            "avg_call_duration_seconds": round(avg_call, 1),
            "active_count": len(self.active_transfers),
        }
    
    def is_transfer_active(self, call_id: str) -> bool:
        """해당 호에 활성 전환이 있는지"""
        return call_id in self.active_transfers
    
    def is_transfer_leg(self, call_id: str) -> bool:
        """해당 Call-ID가 전환 레그인지"""
        return call_id in self.transfer_leg_map
