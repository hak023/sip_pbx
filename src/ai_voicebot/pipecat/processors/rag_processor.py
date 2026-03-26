"""
RAG-enhanced LLM Processor for Pipecat Pipeline (Phase 2: LangGraph).

Phase 1: 단순 RAG + LLM
Phase 2: LangGraph ConversationAgent로 교체
  - 의도 분류, Semantic Cache, Query Rewriting, Adaptive RAG,
    Step-back Prompting, HITL Alert, Business State Tracking

STT TranscriptionFrame → LangGraph Agent → TextFrame(응답) → TTS
"""

import asyncio
import re
from datetime import datetime
from typing import Any, Dict, Optional, List, Callable, Awaitable

import structlog

from src.common.call_data_record_logger import log_call_data
from src.common.rag_hit_serializer import build_rag_hits_llm_context, build_rag_hits_retrieval

from pipecat.frames.frames import (
    EndFrame,
    Frame,
    LLMFullResponseEndFrame,
    LLMFullResponseStartFrame,
    StartFrame,
    TextFrame,
    TranscriptionFrame,
    InterimTranscriptionFrame,
)
from pipecat.processors.frame_processor import FrameDirection, FrameProcessor

logger = structlog.get_logger(__name__)


class RAGLLMProcessor(FrameProcessor):
    """
    RAG + LLM 통합 프로세서 (Phase 2: LangGraph Agent 기반).
    
    Pipecat 파이프라인에서 STT 결과(TranscriptionFrame)를 받아
    LangGraph ConversationAgent로 의도 분류 → Semantic Cache → Adaptive RAG
    → LLM 응답 생성 → TextFrame 출력.
    
    Phase 1 대비 변경점:
      - ConversationAgent가 모든 RAG/LLM 로직 관리
      - Semantic Cache로 반복 질문 즉시 응답
      - 비즈니스 상태 추적 (initial → inquiry → resolution → closing)
      - HITL 알림 지원
    """
    
    def __init__(
        self,
        llm_client,
        rag_engine=None,
        org_manager=None,
        embedder=None,
        vector_db=None,
        system_prompt: str = "",
        max_history_turns: int = 10,
        owner: str = "",
        caller_id: Optional[str] = None,  # 발신자 식별 (이전 통화 맥락용)
        tts_sync_context: Optional[Dict[str, Any]] = None,
        call_id: Optional[str] = None,  # 통화 ID (WebSocket 이벤트용)
        hitl_on_alert: Optional[Callable[..., Awaitable[None]]] = None,
        hitl_response_queue: Optional[asyncio.Queue] = None,
        stt_post_filter_config: Optional[Dict[str, Any]] = None,
        stt_post_filter_reply_on_drop: bool = False,
        stt_post_filter_reply_message: str = "다시 말씀해 주시겠어요?",
        stt_final_debounce_sec: float = 1.0,
        **kwargs,
    ):
        super().__init__(**kwargs)
        self._llm = llm_client
        self._tts_sync_context = tts_sync_context or {}
        self._call_id = call_id  # 통화 ID 저장
        # STT 후처리 필터 (짧은/불완전/감탄만 발화 스킵) — 설계: STT_ADDITIONAL_CONSIDERATIONS.md §6
        from src.ai_voicebot.pipecat.stt_post_filter import STTPostFilter
        self._stt_post_filter = STTPostFilter.from_config(stt_post_filter_config or {})
        self._stt_post_filter_reply_on_drop = stt_post_filter_reply_on_drop
        self._stt_post_filter_reply_message = stt_post_filter_reply_message
        self._rag = rag_engine
        self._embedder = embedder
        self._vector_db = vector_db  # Legacy 인사말·지식 greeting_phase 조회용
        self._org_manager = org_manager
        self._system_prompt = system_prompt
        self._max_history_turns = max_history_turns
        self._owner = owner  # 착신번호 (테넌트 ID)
        self._caller_id = caller_id  # 발신자 (이전 통화 맥락 조회용)
        # HITL 관리자 응답 전달: 미지정 시 call_id가 있으면 큐 생성 후 HITLService에 등록 (설계 §5.5)
        if call_id and hitl_response_queue is None:
            hitl_response_queue = asyncio.Queue()
            try:
                from src.services.hitl import get_hitl_service
                get_hitl_service().register_call(call_id, hitl_response_queue)
            except Exception as e:
                logger.debug("hitl_register_call_failed", call_id=call_id, error=str(e))
        self._hitl_response_queue = hitl_response_queue
        self._hitl_consumer_started = False

        # LangGraph ConversationAgent (Phase 2)
        self._agent = None
        self._agent_available = False
        self._greeting_sent = False
        # Phase2 인사말 전송 완료 시 set → 사용자 발화는 이 시점 이후에만 LLM으로 전달 (Phase2가 첫 턴 응답에 덮이지 않도록)
        self._greeting_phase2_done = asyncio.Event()
        # 사용자 발화 큐 + 워커: process_frame은 즉시 return → 파이프라인 블로킹 없음, TTS/STT 2-way 독립
        self._user_message_queue: asyncio.Queue = asyncio.Queue()
        self._user_message_worker_task: Optional[asyncio.Task] = None
        # 연속 STT 최종 결과 병합: "…찾아가려고 하는데요" + "때 어떻게…" 같은 짧은 간격 분할 대응
        self._stt_final_debounce_sec: float = float(stt_final_debounce_sec or 0.0)
        self._stt_debounce_task: Optional[asyncio.Task] = None
        self._stt_debounce_chunks: List[str] = []
        # 후속 STT 최종이 도착했을 때 진행 중인 에이전트 턴 취소·문장 병합 (seq N 처리 중 seq N+1)
        self._stt_enqueue_lock: Optional[asyncio.Lock] = None
        self._agent_turn_task: Optional[asyncio.Task] = None
        self._utterance_in_flight: Optional[str] = None
        self._agent_superseded: bool = False
        # 발신자 맥락: 통화당 1회 이력 행 생성 (설계: CALLER_MEMORY_DESIGN.md)
        self._call_history_ensured = False
        # STT 원인 규명: RAG에 도달한 TranscriptionFrame(최종) 개수
        self._transcription_frame_count = 0
        # Pipecat: push_frame()은 StartFrame 처리 후에만 동작. 인사/HITL이 먼저 돌면 프레임이 드롭되어 TTS/RTP 없음.
        self._pipeline_start_event = asyncio.Event()

        # HITL Manager (Phase 3): on_alert 연결 시 프론트에 hitl_requested 발송
        self._hitl_manager = None
        try:
            from src.ai_voicebot.pipecat.processors.hitl_processor import HITLManager
            self._hitl_manager = HITLManager(on_alert=hitl_on_alert)
            logger.info("hitl_manager_initialized", has_on_alert=hitl_on_alert is not None)
        except Exception as e:
            logger.debug("hitl_manager_not_available", error=str(e))
        
        # Phase 2: LangGraph Agent 초기화 시도
        try:
            from src.ai_voicebot.langgraph.agent import ConversationAgent
            self._agent = ConversationAgent(
                llm_client=llm_client,
                rag_engine=rag_engine,
                embedder=embedder,
                vector_db=vector_db,
                org_manager=org_manager,
                owner=owner,
            )
            self._agent_available = True
            logger.info("rag_llm_processor_langgraph_mode",
                       has_rag=rag_engine is not None,
                       has_cache=(vector_db is not None and embedder is not None),
                       owner=owner)
        except Exception as e:
            logger.warning("langgraph_agent_init_failed",
                          error=str(e),
                          message="Falling back to legacy RAG+LLM mode")
            self._agent_available = False
            # Legacy fallback: 기존 messages 기반
            self._messages: List[dict] = []
    
    @staticmethod
    def _pipeline_tx_caller(call_id: Optional[str], text: str) -> None:
        if not call_id or not (text or "").strip():
            return
        try:
            from src.common.pipeline_transcript_buffer import record_pipeline_caller
            record_pipeline_caller(call_id, text)
        except Exception:
            pass

    @staticmethod
    def _pipeline_tx_callee(call_id: Optional[str], text: str) -> None:
        if not call_id or not (text or "").strip():
            return
        try:
            from src.common.pipeline_transcript_buffer import record_pipeline_callee
            record_pipeline_callee(call_id, text)
        except Exception:
            pass

    async def _wait_for_pipecat_started(self, *, context: str, timeout_sec: float = 60.0) -> bool:
        """Pipecat FrameProcessor.push_frame은 __started(StartFrame 수신) 전에는 무시된다."""
        if self._pipeline_start_event.is_set():
            return True
        try:
            await asyncio.wait_for(self._pipeline_start_event.wait(), timeout=timeout_sec)
            return True
        except asyncio.TimeoutError:
            logger.error(
                "rag_llm_pipecat_start_timeout",
                call_id=self._call_id or "",
                context=context,
                timeout_sec=timeout_sec,
                note="StartFrame 미도달 — push_frame 드롭으로 TTS·RTP 없음",
            )
            return False

    def _start_hitl_response_consumer(self):
        """운영자 응답 큐 소비 태스크 시작 (한 번만)"""
        if self._hitl_consumer_started or not self._hitl_response_queue:
            return
        self._hitl_consumer_started = True
        proc = self

        async def _consume():
            try:
                cid = proc._call_id or ""
                if cid:
                    try:
                        from src.services.hitl import get_hitl_service
                        get_hitl_service().ensure_queue_loop(cid)
                    except Exception as e:
                        logger.debug("hitl_ensure_queue_loop_in_consumer_failed", call_id=cid, error=str(e))
                while True:
                    response_data = await proc._hitl_response_queue.get()
                    if not response_data:
                        continue
                    
                    # response_data는 dict: {"type": "hitl_response"|"hitl_timeout", "text": "...", "call_id": "...", "original_question": "..."}
                    if isinstance(response_data, dict):
                        msg_type = response_data.get("type", "hitl_response")
                        text = response_data.get("text", "")
                        original_question = response_data.get("original_question", "")

                        if msg_type == "hitl_timeout":
                            logger.info(
                                "hitl_timeout_skipped",
                                call=True,
                                call_id=proc._call_id or "",
                                note="타임아웃 자동 멘트 비활성화 — 큐 항목 무시",
                            )
                            continue

                        if msg_type == "hitl_response" and text.strip() and proc._llm:
                            try:
                                fn = getattr(proc._llm, "format_hitl_reply_for_customer", None)
                                if fn:
                                    if asyncio.iscoroutinefunction(fn):
                                        refined = await fn(original_question, text.strip())
                                    else:
                                        refined = fn(original_question, text.strip())
                                    if refined and len(refined.strip()) > 2:
                                        text = refined.strip()
                                        logger.info(
                                            "hitl_response_llm_formatted",
                                            call=True,
                                            call_id=proc._call_id or "",
                                            text_preview=text,
                                        )
                            except Exception as e:
                                logger.warning(
                                    "hitl_reply_format_failed",
                                    call_id=proc._call_id or "",
                                    error=str(e),
                                )

                    else:
                        # 호환성: 문자열로 직접 전달된 경우
                        text = str(response_data)
                    
                    if not text or len(text.strip()) < 2:
                        continue
                    
                    logger.info("hitl_response_received",
                               call=True,
                               call_id=proc._call_id or "",
                               text_len=len(text),
                               text_preview=text)
                    log_call_data(
                        proc._call_id or "",
                        "hitl",
                        "hitl_response_received",
                        msg_type=msg_type,
                        text_len=len(text),
                        text_preview=text,
                    )
                    if not await proc._wait_for_pipecat_started(context="hitl_response"):
                        logger.warning(
                            "hitl_tts_skipped_no_startframe",
                            call_id=proc._call_id or "",
                            note="Pipecat StartFrame 전 — 멘트 드롭",
                        )
                        continue
                    # TextFrame으로 TTS 파이프라인에 전달
                    await proc.push_frame(LLMFullResponseStartFrame())
                    await proc.push_frame(TextFrame(text=text))
                    await proc.push_frame(LLMFullResponseEndFrame())
                    RAGLLMProcessor._pipeline_tx_callee(proc._call_id or "", text)
                    
            except asyncio.CancelledError:
                pass
            except Exception as e:
                logger.error("hitl_response_consumer_error", call_id=proc._call_id, error=str(e))

        asyncio.create_task(_consume())

    async def _user_message_worker(self) -> None:
        """사용자 발화를 큐에서 꺼내 순서대로 LLM 호출 → process_frame 블로킹 제거, TTS/STT 2-way 독립."""
        while True:
            try:
                user_text = await self._user_message_queue.get()
                if user_text is None:
                    break
                try:
                    await asyncio.wait_for(self._greeting_phase2_done.wait(), timeout=60.0)
                except asyncio.TimeoutError:
                    logger.warning("greeting_phase2_wait_timeout",
                                  call_id=self._call_id or "",
                                  note="Phase2 대기 60s 타임아웃, 사용자 발화 처리 진행")

                self._utterance_in_flight = (user_text or "").strip()

                async def _run_turn(text: str) -> None:
                    if self._agent_available:
                        await self._process_with_agent(text)
                    else:
                        await self._generate_response_legacy(text)

                superseded = False
                self._agent_turn_task = asyncio.create_task(_run_turn(user_text))
                try:
                    await self._agent_turn_task
                except asyncio.CancelledError:
                    if self._agent_superseded:
                        self._agent_superseded = False
                        superseded = True
                        logger.info(
                            "agent_turn_superseded_aborted",
                            call_id=self._call_id or "",
                            merged_preview=(self._utterance_in_flight or ""),
                            note="후속 STT 최종 도착 → 진행 중 에이전트 턴 취소, 병합 문장으로 재큐",
                        )
                    else:
                        raise
                finally:
                    self._agent_turn_task = None

                if superseded:
                    continue
                self._utterance_in_flight = None
            except asyncio.CancelledError:
                break
            except Exception as e:
                self._utterance_in_flight = None
                logger.error("user_message_worker_error",
                             call_id=self._call_id or "",
                             error=str(e),
                             exc_info=True)

    def _get_stt_enqueue_lock(self) -> asyncio.Lock:
        if self._stt_enqueue_lock is None:
            self._stt_enqueue_lock = asyncio.Lock()
        return self._stt_enqueue_lock

    @staticmethod
    def _merge_stt_user_text(prev: str, nxt: str) -> str:
        a, b = (prev or "").strip(), (nxt or "").strip()
        if not a:
            return b
        if not b:
            return a
        return re.sub(r"\s+", " ", f"{a} {b}").strip()

    async def _enqueue_user_text_to_worker_async(self, user_text: str) -> None:
        """STT 최종(또는 디바운스 병합) 문장을 큐에 넣고 워커 기동. 진행 중 턴이 있으면 취소 후 문장 병합·큐 헤드 교체."""
        from datetime import datetime

        lock = self._get_stt_enqueue_lock()
        incoming = (user_text or "").strip()
        async with lock:
            queued_text = incoming
            if self._agent_turn_task and not self._agent_turn_task.done():
                base = (self._utterance_in_flight or "").strip()
                merged = self._merge_stt_user_text(base, incoming)
                self._utterance_in_flight = merged
                self._agent_superseded = True
                self._agent_turn_task.cancel()
                log_call_data(
                    self._call_id or "",
                    "stt",
                    "stt_turn_superseded",
                    base_preview=base,
                    incoming_preview=incoming,
                    merged_preview=merged,
                    merged_len=len(merged),
                    mode="langgraph" if self._agent_available else "legacy",
                )
                logger.info(
                    "stt_turn_superseded",
                    call_id=self._call_id or "",
                    base_preview=base,
                    incoming_preview=incoming,
                    merged_preview=merged,
                    note="seq N 처리 중 seq N+1 → N+N 병합 후 진행 턴 취소",
                )
                try:
                    self._user_message_queue.get_nowait()
                except asyncio.QueueEmpty:
                    pass
                queued_text = merged
            elif (self._utterance_in_flight or "").strip():
                tail = self._utterance_in_flight.strip()
                merged = self._merge_stt_user_text(tail, incoming)
                self._utterance_in_flight = merged
                log_call_data(
                    self._call_id or "",
                    "stt",
                    "stt_pending_coalesce",
                    tail_preview=tail,
                    incoming_preview=incoming,
                    merged_preview=merged,
                    note="에이전트 유휴 직전 구간: 큐 헤드와 후속 STT 병합",
                )
                try:
                    self._user_message_queue.get_nowait()
                except asyncio.QueueEmpty:
                    pass
                queued_text = merged

        ts_iso = datetime.now().isoformat(timespec="milliseconds")
        logger.info(
            "rag_llm_user_input",
            call=True,
            call_id=self._call_id or "",
            category="stt",
            progress="stt",
            text=queued_text,
            ts_iso=ts_iso,
            mode="langgraph" if self._agent_available else "legacy",
        )
        log_call_data(
            self._call_id or "",
            "stt",
            "stt_to_llm",
            text=queued_text,
            text_len=len(queued_text),
            mode="langgraph" if self._agent_available else "legacy",
        )
        self._pipeline_tx_caller(self._call_id or "", queued_text)
        tts_context = self._tts_sync_context or {}
        is_tts_active = tts_context.get("_tts_active", False)
        tts_pending_bytes = tts_context.get("_tts_pending_pcm_bytes", 0)
        logger.info(
            "timing_stt_final_to_rag",
            call=True,
            call_id=self._call_id or "",
            progress="timing",
            ts_iso=ts_iso,
            text_preview=queued_text,
            tts_active_during_stt=is_tts_active,
            tts_pending_bytes=tts_pending_bytes,
            note="STT 최종 결과가 RAG에 도달한 시점 (LLM 호출 직전, TTS 동시 처리 여부 확인)",
        )
        if self._call_id:
            try:
                from src.websocket import manager as ws_manager

                asyncio.create_task(
                    ws_manager.emit_stt_transcript(
                        self._call_id,
                        text=queued_text,
                        is_final=True,
                        speaker="caller",
                        source="ai_pipecat",
                    )
                )
            except Exception as e:
                logger.debug("stt_event_failed", error=str(e))
        self._ensure_call_history_entry()
        self._user_message_queue.put_nowait(queued_text)
        if self._user_message_worker_task is None or self._user_message_worker_task.done():
            self._user_message_worker_task = asyncio.create_task(self._user_message_worker())
            logger.debug("user_message_worker_started", call_id=self._call_id or "")

    async def _run_stt_debounce_flush(self) -> None:
        try:
            await asyncio.sleep(self._stt_final_debounce_sec)
        except asyncio.CancelledError:
            return
        chunks = self._stt_debounce_chunks[:]
        self._stt_debounce_chunks.clear()
        if not chunks:
            return
        merged = " ".join(chunks).strip()
        if len(chunks) > 1:
            logger.info(
                "stt_final_debounced_merge",
                call_id=self._call_id or "",
                chunk_count=len(chunks),
                debounce_sec=self._stt_final_debounce_sec,
                merged_preview=merged,
                note="짧은 간격 연속 STT 최종 → 한 문장으로 합쳐 에이전트에 전달",
            )
            log_call_data(
                self._call_id or "",
                "stt",
                "stt_final_merged",
                text=merged,
                chunk_count=len(chunks),
            )
        await self._enqueue_user_text_to_worker_async(merged)

    def _schedule_stt_debounced_enqueue(self, user_text: str) -> None:
        self._stt_debounce_chunks.append(user_text)
        if self._stt_debounce_task and not self._stt_debounce_task.done():
            self._stt_debounce_task.cancel()
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            loop = asyncio.get_event_loop()
        self._stt_debounce_task = loop.create_task(self._run_stt_debounce_flush())

    async def process_frame(self, frame: Frame, direction: FrameDirection):
        self._start_hitl_response_consumer()
        await super().process_frame(frame, direction)
        if isinstance(frame, StartFrame) and not self._pipeline_start_event.is_set():
            self._pipeline_start_event.set()
            logger.info(
                "rag_llm_pipecat_startframe_received",
                call_id=self._call_id or "",
                note="이후 push_frame 허용(인사·HITL·LLM→TTS)",
            )

        if isinstance(frame, TranscriptionFrame):
            user_text = frame.text.strip()
            self._transcription_frame_count += 1
            # STT 원인 규명: 최종 결과가 몇 번 RAG에 도달했는지 (말했는데 결과 없음 → 이 수가 1이면 STT가 한 번만 최종 전송)
            logger.info("transcription_frame_received",
                        call_id=self._call_id or "",
                        category="stt",
                        progress="stt",
                        seq=self._transcription_frame_count,
                        text_preview=user_text if user_text else "",
                        text_len=len(user_text),
                        note="STT 최종(TranscriptionFrame) RAG 도달 — seq 증가 시 여러 발화 인식됨")
            log_call_data(
                self._call_id or "",
                "stt",
                "stt_final",
                seq=self._transcription_frame_count,
                text=user_text if user_text else "",
                text_len=len(user_text),
            )
            logger.info("stt_path_stt_to_rag",
                        call_id=self._call_id or "",
                        seq=self._transcription_frame_count,
                        text_len=len(user_text),
                        note="[STT 경로] STT 최종 결과 → RAG 도달")
            if self._transcription_frame_count == 1:
                logger.info("stt_path_stt_first",
                            call_id=self._call_id or "",
                            text_len=len(user_text),
                            note="[STT 경로] 통화 중 STT → RAG 첫 도달 (이 로그가 있으면 실시간 STT 동작함)")
            if user_text:
                from datetime import datetime
                ts_iso = datetime.now().isoformat(timespec="milliseconds")

                # STT 후처리 필터: 짧은/불완전/감탄만 발화는 LLM으로 넘기지 않음
                should_use, filter_reason = self._stt_post_filter.filter(user_text)
                if not should_use:
                    logger.info("stt_post_filter_dropped",
                               call=True,
                               call_id=self._call_id or "",
                               category="stt",
                               progress="stt",
                               text_preview=user_text,
                               reason=filter_reason,
                               ts_iso=ts_iso)
                    log_call_data(
                        self._call_id or "",
                        "stt",
                        "stt_post_filter_dropped",
                        text=user_text,
                        reason=filter_reason,
                    )
                    if self._stt_post_filter_reply_on_drop and self._stt_post_filter_reply_message:
                        self._pipeline_tx_callee(
                            self._call_id or "", self._stt_post_filter_reply_message
                        )
                        if await self._wait_for_pipecat_started(
                            context="stt_post_filter_reply", timeout_sec=10.0
                        ):
                            await self.push_frame(LLMFullResponseStartFrame())
                            await self.push_frame(
                                TextFrame(text=self._stt_post_filter_reply_message)
                            )
                            await self.push_frame(LLMFullResponseEndFrame())
                        else:
                            logger.warning(
                                "stt_post_filter_tts_skipped_no_startframe",
                                call_id=self._call_id or "",
                            )
                    return

                # 연속 STT 최종을 짧게 합친 뒤 1회만 큐 투입 (문맥·의도 분류 일치)
                if self._stt_final_debounce_sec > 0:
                    self._schedule_stt_debounced_enqueue(user_text)
                else:
                    await self._enqueue_user_text_to_worker_async(user_text)
        elif isinstance(frame, InterimTranscriptionFrame):
            # Interim STT (중간 결과)
            interim_text = frame.text.strip()
            if interim_text and self._call_id:
                try:
                    from src.websocket import manager as ws_manager
                    asyncio.create_task(
                        ws_manager.emit_stt_transcript(
                            self._call_id,
                            text=interim_text,
                            is_final=False,
                            speaker="caller",
                            source="ai_pipecat",
                        )
                    )
                except Exception as e:
                    logger.debug("interim_stt_event_failed", error=str(e))
            # Interim은 downstream으로 전달하지 않음
            return
        else:
            await self.push_frame(frame, direction)
    
    # =========================================================================
    # Phase 2: LangGraph Agent 경로
    # =========================================================================
    
    def _ensure_call_history_entry(self) -> None:
        """통화당 1회: call_history에 행이 있도록 append. 통화 종료 시 요약 저장용. 설계: CALLER_MEMORY_DESIGN.md §6.2"""
        if self._call_history_ensured or not self._call_id or not self._owner:
            return
        try:
            from datetime import datetime, timezone
            from src.api.routers.call_history import append_call_history
            now = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
            append_call_history({
                "call_id": self._call_id,
                "caller_id": getattr(self, "_caller_id", None) or "",
                "callee_id": self._owner,
                "start_time": now,
                "end_time": None,
                "is_ai_handled": True,
                "transcripts": [],
            })
            self._call_history_ensured = True
        except Exception as e:
            logger.debug("ensure_call_history_entry_failed", call_id=self._call_id, error=str(e))

    async def _process_with_agent(self, user_text: str):
        """LangGraph ConversationAgent를 통한 응답 생성"""
        import time
        import asyncio  # 로컬 참조 보장 (다른 모듈/스레드에서 shadow 시 UnboundLocalError 방지)
        pipeline_start = time.time()

        # 새 사용자 발화가 오면 이전 HITL fallback 타이머 취소 (장시간 LLM 대기 중 타임아웃 멘트·대기 TTS 겹침 완화)
        if self._call_id:
            try:
                from src.services.hitl import get_hitl_service
                get_hitl_service().cancel_timer(self._call_id)
            except Exception as e:
                logger.debug("hitl_cancel_timer_on_new_utterance_skip", call_id=self._call_id, error=str(e))
        
        # ✅ 시간 표현 정규화 (temporal 패키지)
        try:
            from ..temporal.normalizer import TemporalExpressionNormalizer
            normalizer = TemporalExpressionNormalizer()
            normalized_text = normalizer.rewrite_query(user_text)
            if normalized_text != user_text:
                logger.info("temporal_expression_applied",
                           call_id=self._call_id or "",
                           original=user_text,
                           normalized=normalized_text,
                           note="시간 표현을 절대 날짜로 변환하여 RAG 검색 정확도 향상")
                user_text = normalized_text
        except Exception as e:
            logger.debug("temporal_normalizer_skip", call_id=self._call_id or "", error=str(e))
        
        # ✅ 호 전환 요청 감지 (Quick Check)
        from ..intents import IntentClassifier, Intent
        quick_intent = IntentClassifier.classify_quick(user_text)
        
        if quick_intent == Intent.TRANSFER_REQUEST:
            logger.info("transfer_request_detected",
                       call_id=self._call_id or "",
                       query=user_text,
                       note="호 전환 요청 감지 → 연락처 검색 시작")
            log_call_data(
                self._call_id or "",
                "call_event",
                "transfer_request_detected",
                query=user_text,
            )
            # 연락처 검색 (ContactKnowledgeExtractor는 ai_voicebot.knowledge에 있음 — pipecat.knowledge 아님)
            from src.ai_voicebot.knowledge import ContactKnowledgeExtractor
            # RAGEngine은 vector_db·embedder (underscore 없음). 파이프라인 레거시 self._vector_db 폴백.
            _vdb = None
            _emb = None
            if self._rag:
                _vdb = getattr(self._rag, "vector_db", None)
                _emb = getattr(self._rag, "embedder", None)
            contact_extractor = ContactKnowledgeExtractor(
                vector_db=_vdb or self._vector_db,
                embedder=_emb,
            )
            
            contact = await contact_extractor.search_contact(
                query=user_text,
                tenant_id=self._owner or ""
            )
            
            if contact:
                logger.info("transfer_contact_found",
                           call_id=self._call_id or "",
                           department=contact.get('department'),
                           phone_number=contact.get('phone_number'))
                
                # 호 전환 안내 멘트 생성
                from ..intents import build_transfer_announcement_prompt
                prompt = build_transfer_announcement_prompt(
                    department=contact['department'],
                    phone_number=contact['phone_number']
                )
                
                try:
                    announcement = await self._llm.generate_simple(prompt, max_tokens=150)
                    if not announcement or len(announcement.strip()) < 5:
                        announcement = f"{contact['department']}로 바로 연결해 드리겠습니다."
                except Exception as e:
                    logger.warning("transfer_announcement_generation_failed", error=str(e))
                    announcement = f"{contact['department']}로 바로 연결해 드리겠습니다."
                
                # TTS로 안내 멘트 출력
                await self.push_frame(LLMFullResponseStartFrame())
                await self.push_frame(TextFrame(text=announcement))
                await self.push_frame(LLMFullResponseEndFrame())
                self._pipeline_tx_callee(self._call_id or "", announcement)
                
                logger.info("transfer_announcement_sent",
                           call_id=self._call_id or "",
                           announcement=announcement)
                log_call_data(
                    self._call_id or "",
                    "call_event",
                    "transfer_announcement_sent",
                    department=contact.get("department"),
                    text=announcement,
                )
                # WebSocket: 호 전환 이벤트 발송 (실제 구현)
                if self._call_id:
                    try:
                        from src.websocket_events import emit_transfer_initiated
                        await emit_transfer_initiated(
                            call_id=self._call_id,
                            target_number=contact['phone_number'],
                            department=contact['department']
                        )
                    except Exception as e:
                        logger.warning("transfer_event_emit_failed", error=str(e))
                
                # Call Manager에 호 전환 요청 (TransferManager 활용)
                try:
                    from src.call_transfer import initiate_call_transfer
                    transfer_success = await initiate_call_transfer(
                        call_id=self._call_id or "",
                        target_number=contact['phone_number'],
                        department=contact['department'],
                        phone_display=contact.get('phone_number'),
                        user_request_text=user_text
                    )
                    
                    if transfer_success:
                        logger.info("call_transfer_initiated_successfully",
                                   call_id=self._call_id or "",
                                   target=contact['phone_number'],
                                   department=contact['department'])
                        log_call_data(
                            self._call_id or "",
                            "call_event",
                            "call_transfer_initiated",
                            department=contact.get("department"),
                            target=contact.get("phone_number"),
                            success=True,
                        )
                    else:
                        logger.warning("call_transfer_initiation_failed",
                                      call_id=self._call_id or "",
                                      note="TransferManager가 설정되지 않았거나 이미 활성 전환이 있음")
                        log_call_data(
                            self._call_id or "",
                            "call_event",
                            "call_transfer_initiated",
                            success=False,
                            department=contact.get("department"),
                        )
                except Exception as e:
                    logger.error("call_transfer_error",
                                call_id=self._call_id or "",
                                error=str(e))
                    log_call_data(
                        self._call_id or "",
                        "call_event",
                        "call_transfer_error",
                        error=str(e),
                    )
                
                return
            else:
                logger.info("transfer_contact_not_found",
                           call_id=self._call_id or "",
                           query=user_text,
                           note="연락처를 찾지 못함 → 일반 상담원 연결 안내")
                log_call_data(
                    self._call_id or "",
                    "call_event",
                    "transfer_contact_not_found",
                    query=user_text,
                )
                
                # 연락처를 찾지 못한 경우 일반 응답
                response = "죄송합니다. 해당 부서의 연락처를 찾지 못했습니다. 일반 상담원으로 연결해 드리겠습니다."
                await self.push_frame(LLMFullResponseStartFrame())
                await self.push_frame(TextFrame(text=response))
                await self.push_frame(LLMFullResponseEndFrame())
                self._pipeline_tx_callee(self._call_id or "", response)
                return
        
        # 🚀 간단한 query는 캐시 활용 또는 rewrite 스킵 힌트 전달
        query_complexity = self._analyze_query_complexity(user_text)
        should_skip_rewrite = query_complexity == "simple"
        
        if should_skip_rewrite:
            logger.info("query_rewrite_skip_candidate",
                       call_id=self._call_id or "",
                       query_preview=user_text,
                       complexity=query_complexity,
                       note="간단한 query → rewrite 스킵 가능")
        
        # 발신자 맥락: Agent가 caller_context 인자를 지원하면 전달 (설계: CALLER_MEMORY_DESIGN.md)
        caller_context = self._get_caller_context_sync()
        
        # LLM 대기 안내: 너무 이르면 HITL/이전 턴 TTS와 겹침 → 12초 후 1회만 짧게 안내
        _LLM_WAIT_NOTIFY_SEC = 12.0
        notify_task = None
        done = asyncio.Event()
        
        async def wait_and_notify():
            """장시간 LLM 처리 시에만 중간 안내 (짧은 구간과의 TTS 겹침 완화).

            한 개의 TextFrame + 단일 EndFrame이면 TTS가 문장 경계에서 내부 분할할 때
            Notifier/Output 프레임 수 불일치(tts_rtp_duration_mismatch)가 나기 쉬움.
            본 응답(llm_response_sent)과 같이 문장별 Start/Text/End + 짧은 간격으로 정렬한다.
            """
            _wait_parts = ("정보를 확인 중입니다.", "잠시만 기다려 주세요.")
            _wait_full = " ".join(_wait_parts)
            try:
                await asyncio.sleep(_LLM_WAIT_NOTIFY_SEC)
                if not done.is_set():
                    logger.info(
                        "llm_processing_notification",
                        call_id=self._call_id or "",
                        wait_sec=_LLM_WAIT_NOTIFY_SEC,
                        note="LLM 처리 장시간 경과 → 대기 안내 TTS 1회 (문장별 LLM 구간 정렬)",
                    )
                    for i, part in enumerate(_wait_parts):
                        await self.push_frame(LLMFullResponseStartFrame())
                        await self.push_frame(TextFrame(text=part))
                        await self.push_frame(LLMFullResponseEndFrame())
                        if i < len(_wait_parts) - 1:
                            await asyncio.sleep(0.05)
                    self._pipeline_tx_callee(self._call_id or "", _wait_full)
            except asyncio.CancelledError:
                pass
        
        notify_task = asyncio.create_task(wait_and_notify())
        
        result: Optional[Dict[str, Any]] = None
        agent_elapsed = 0.0
        try:
            agent_start = time.time()
            
            # 💡 TODO: LangGraph Agent 내부 최적화 필요 (외부 패키지)
            # - classify_intent + rewrite_query 병렬 실행으로 시간 단축
            # - 현재: classify_intent(3.5s) + rewrite_query(5.2s) = 8.7초 순차
            # - 개선: asyncio.gather()로 병렬 실행 → max(3.5, 5.2) = 5.2초
            # - 예상 효과: -3.5초 단축 (전체 LLM 처리 14초 → 10.5초)
            
            if caller_context:
                try:
                    result = await self._agent.process_utterance(
                        user_text,
                        call_id=self._call_id or "",
                        caller_context=caller_context,
                    )
                except TypeError:
                    result = await self._agent.process_utterance(user_text, call_id=self._call_id or "")
            else:
                result = await self._agent.process_utterance(user_text, call_id=self._call_id or "")
            agent_elapsed = time.time() - agent_start
        except asyncio.CancelledError:
            logger.info(
                "langgraph_agent_turn_cancelled",
                call_id=self._call_id or "",
                user_text_preview=(user_text or ""),
                note="후속 STT로 턴 취소됨 → 병합 문장으로 재시도",
            )
            raise
        finally:
            # 대기 안내 태스크 취소
            done.set()
            if notify_task:
                notify_task.cancel()
                try:
                    await notify_task
                except asyncio.CancelledError:
                    pass
        
        if not result:
            return

        try:
            response = result.get("response", "")
            confidence = result.get("confidence", 0.0)
            intent = result.get("intent", "unknown")
            cache_hit = result.get("rag_cache_hit", False)
            needs_human = result.get("needs_human", False)
            business_state = result.get("business_state", "")
            chunks = result.get("response_chunks", [])

            # 디버깅용: LLM 질의/답변 전체 (잘림 없이 무조건 전부 로깅)
            logger.info("llm_exchange_full",
                       call=True,
                       category="llm",
                       progress="llm",
                       user_text_full=user_text,
                       response_full=response,
                       response_len=len(response),
                       note="전체 질의/답변 로그")
            _llm_rag = result.get("llm_rag_applied") or []
            log_call_data(
                self._call_id or "",
                "llm",
                "llm_exchange",
                user_text=user_text,
                user_text_full=user_text,
                user_text_len=len(user_text or ""),
                response=response,
                response_full=response,
                response_len=len(response),
                intent=result.get("intent", ""),
                confidence=result.get("confidence", 0),
                cache_hit=result.get("rag_cache_hit", False),
                agent_elapsed=f"{agent_elapsed:.3f}s",
                llm_rag_context_source=result.get("llm_rag_context_source") or "",
                llm_rag_applied=_llm_rag,
                llm_rag_applied_count=len(_llm_rag),
                rag_search_trace=result.get("rag_search_trace") or {},
                semantic_cache_score=result.get("semantic_cache_score"),
                greeting_farewell_cache_score=result.get("greeting_farewell_cache_score"),
            )

            logger.info("langgraph_agent_result",
                       call=True,
                       category="llm",
                       progress="llm",
                       intent=intent,
                       confidence=f"{confidence:.3f}",
                       cache_hit=cache_hit,
                       needs_human=needs_human,
                       business_state=business_state,
                       response_len=len(response),
                       response_preview=response,
                       response_full=response,
                       user_text_full=user_text,
                       agent_elapsed=f"{agent_elapsed:.3f}s")
            
            # HITL: 운영자 개입 필요 시 HITLManager로 위임 + 프론트엔드에 hitl_requested 발송 (Phase 3)
            if needs_human:
                hitl_reason = result.get("hitl_reason", "")
                if self._hitl_manager:
                    hitl_message = await self._hitl_manager.handle_hitl_result(
                        call_id=self._call_id or "",
                        needs_human=True,
                        hitl_reason=hitl_reason,
                        intent=intent,
                        confidence=confidence,
                        user_text=user_text,
                    )
                    if hitl_message and not response:
                        response = hitl_message
                else:
                    logger.warning("hitl_alert_from_agent",
                                 reason=hitl_reason)
                    if not response:
                        response = "담당자에게 연결해 드리겠습니다. 잠시만 기다려 주세요."

                log_call_data(
                    self._call_id or "",
                    "hitl",
                    "hitl_requested",
                    question=user_text,
                    intent=intent,
                    confidence=confidence,
                    reason=hitl_reason or "",
                )
                # 프론트엔드(운영자 대시보드)에 HITL 요청 이벤트 전송 (hitl_on_alert 미연결 시에도 동작)
                try:
                    from src.websocket import manager as ws_manager
                    from src.common.sip_owner import normalize_owner_username

                    urgency = "transfer" if intent == "transfer" else ("complaint" if intent == "complaint" else "low_confidence")
                    _own = normalize_owner_username(self._owner or "") or (self._owner or "").strip()
                    await ws_manager.emit_hitl_requested(
                        call_id=self._call_id or "",
                        question=user_text,
                        context={
                            "intent": intent,
                            "confidence": confidence,
                            "reason": hitl_reason,
                            "alert_type": urgency,
                            "owner": _own,
                        },
                        urgency=urgency,
                    )
                    logger.info(
                        "emit_hitl_requested_context",
                        call_id=self._call_id or "",
                        owner_in_context=bool(_own),
                        owner_preview=_own,
                    )
                except Exception as e:
                    logger.warning("emit_hitl_requested_failed", error=str(e))

                # 통화 이력에 HITL 건 기록 (미처리 HITL 탭 데이터 소스). 설계: HITL_CALL_HISTORY_INTEGRATION.md
                try:
                    from src.api.routers.call_history import record_hitl_request
                    record_hitl_request(
                        call_id=self._call_id or "",
                        callee_id=self._owner or "",
                        user_question=user_text,
                        ai_confidence=confidence,
                        caller_id=getattr(self, "_caller_id", None),
                    )
                except Exception as e:
                    logger.warning("record_hitl_request_failed", call_id=self._call_id, error=str(e))

            # 발신자가 '별도 연락 드릴까요?' 후 긍정(affirm)한 경우 → frontend에 fallback 가능 표시
            try:
                from src.services.hitl import get_hitl_service
                from src.websocket import manager as ws_manager
                if get_hitl_service().consume_fallback_affirm(self._call_id or "", result.get("intent", "")):
                    await ws_manager.emit_hitl_fallback_available(self._call_id or "")
            except Exception as e:
                logger.warning("hitl_fallback_affirm_emit_failed", error=str(e))

            # 후처리(확인 필요): AI가 모르는 내용으로 응답한 건 저장 → 대시보드에서 나중에 처리
            needs_follow_up = result.get("needs_follow_up", False)
            follow_up_query = result.get("follow_up_user_query", "")
            if needs_follow_up and follow_up_query and response:
                try:
                    from src.services.follow_up_service import get_follow_up_service
                    await get_follow_up_service().save_pending_follow_up(
                        call_id=self._call_id or "",
                        user_question=follow_up_query,
                        ai_response=response,
                        callee_id=self._owner,
                    )
                except Exception as e:
                    logger.warning("pending_follow_up_save_failed",
                                  call_id=self._call_id,
                                  error=str(e))
            
            
            if response:
                if intent == "farewell":
                    logger.info("farewell_closing_pushed",
                               call=True,
                               call_id=self._call_id or "",
                               response_preview=response,
                               response_full=response,
                               response_len=len(response))
                # Streaming RAG: 청크 단위 전송
                tts_push_start = time.time()
                
                log_call_data(
                    self._call_id or "",
                    "tts",
                    "tts_text_pushed",
                    text=response,
                    text_len=len(response),
                    intent=intent,
                )
                self._pipeline_tx_callee(self._call_id or "", response)
                # WebSocket: TTS 시작 이벤트
                if self._call_id:
                    try:
                        from src.websocket import manager as ws_manager
                        asyncio.create_task(
                            ws_manager.emit_tts_started(
                                self._call_id,
                                text=response,
                                role="assistant",
                                source="ai_pipecat",
                            )
                        )
                    except Exception as e:
                        logger.debug("tts_started_event_failed", error=str(e))
                
                await self.push_frame(LLMFullResponseStartFrame())
                if chunks and len(chunks) > 1:
                    for chunk in chunks:
                        await self.push_frame(TextFrame(text=chunk))
                        await asyncio.sleep(0.05)  # 청크 간 간격
                else:
                    await self.push_frame(TextFrame(text=response))
                await self.push_frame(LLMFullResponseEndFrame())
                
                # WebSocket: TTS 완료 이벤트
                if self._call_id:
                    try:
                        from src.websocket import manager as ws_manager
                        asyncio.create_task(
                            ws_manager.emit_tts_completed(
                                self._call_id,
                                role="assistant",
                                source="ai_pipecat",
                            )
                        )
                    except Exception as e:
                        logger.debug("tts_completed_event_failed", error=str(e))
                
                tts_push_elapsed = time.time() - tts_push_start
                
                total_elapsed = time.time() - pipeline_start
                logger.info("llm_response_sent",
                           call=True,
                           category="llm",
                           progress="llm",
                           user_text=user_text,
                           user_text_full=user_text,
                           response_preview=response,
                           response_full=response,
                           agent_elapsed=f"{agent_elapsed:.3f}s",
                           tts_push_elapsed=f"{tts_push_elapsed:.3f}s",
                           total_elapsed=f"{total_elapsed:.3f}s",
                           response_len=len(response))
            else:
                _efail = "죄송합니다. 답변을 생성하지 못했습니다. 다시 말씀해주시겠어요?"
                self._pipeline_tx_callee(self._call_id or "", _efail)
                await self.push_frame(TextFrame(text=_efail))
        except Exception as e:
            logger.error("langgraph_agent_process_error", call=True, category="llm", error=str(e), exc_info=True)
            _eerr = "죄송합니다. 오류가 발생했습니다."
            self._pipeline_tx_callee(self._call_id or "", _eerr)
            await self.push_frame(TextFrame(text=_eerr))
    
    # Phase1↔Phase2 사이 예상 대기 시간을 계산하기 위한 상수
    # 한국어 TTS는 대략 초당 5~7글자 속도로 발화
    _TTS_CHARS_PER_SEC = 5.5
    _PHASE_GAP_BUFFER_SEC = 1.0  # Phase1 발화 완료 후 추가 여유 (RTP 큐 비우기 + 자연스러운 호흡)
    _TTS_COMPLETE_WAIT_TIMEOUT_SEC = 60.0  # TTS 완료 이벤트 대기 최대 시간

    async def send_greeting(self):
        """지식 베이스 문구만 TTS (LLM 없음).

        - greeting_phase1 / greeting_phase2 카테고리 문서의 **본문(text)** 우선.
        - 지식/ Chroma에 없으면 `greeting_defaults` 기본 문구로 Phase1·2 TTS.
        - Phase1+2 모두 있으면 Phase1 재생 후 동기화하여 Phase2 전송 (기존 Notifier 흐름).
        """
        if self._greeting_sent:
            return

        if not await self._wait_for_pipecat_started(context="send_greeting"):
            self._greeting_phase2_done.set()
            self._greeting_sent = True
            logger.warning(
                "send_greeting_aborted_no_startframe",
                call_id=self._call_id or "",
                note="인사 TTS 생략 — 사용자 발화는 진행 가능",
            )
            return

        self._greeting_sent = True
        logger.info("send_greeting_started",
                    call_id=self._call_id,
                    owner=self._owner,
                    note="[AI 응대] RAG send_greeting() — KB greeting_phase1/2 → TTS")
        
        import time
        greeting_start = time.time()
        
        try:
            if self._agent_available:
                greeting = await self._agent.generate_greeting()
            else:
                greeting = await self._generate_greeting_legacy()
            p1 = (greeting or "").strip()

            if self._agent_available:
                try:
                    cap_raw = await self._agent.generate_capability_guide()
                except Exception as e:
                    logger.warning("capability_guide_generation_error", error=str(e))
                    cap_raw = ""
            else:
                cap_raw = self._generate_capability_guide_legacy()
            p2 = (cap_raw or "").strip()

            if not p1 and not p2:
                logger.warning(
                    "greeting_skipped_both_empty",
                    call_id=self._call_id,
                    owner=self._owner,
                    note="greeting_phase1·2 지식 없음 — 초기 인사 TTS 생략",
                )
                self._greeting_phase2_done.set()
                return

            if p1:
                logger.info(
                    "rag_llm_greeting_phase1",
                    call=True,
                    category="tts",
                    text=p1,
                    mode="langgraph" if self._agent_available else "legacy",
                )
            if p2:
                logger.info("rag_llm_greeting_phase2", call=True, category="tts", text=p2)

            # Phase2만 (Phase1 없음)
            if not p1 and p2:
                await self.push_frame(LLMFullResponseStartFrame())
                await self.push_frame(TextFrame(text=p2))
                await self.push_frame(LLMFullResponseEndFrame())
                _chunks = [p2[i : i + 60] for i in range(0, len(p2), 60)]
                logger.info(
                    "greeting_phase2_sent",
                    call=True,
                    category="tts",
                    progress="tts",
                    text_len=len(p2),
                    text_chunk_count=len(_chunks),
                    text_chunk_0=_chunks[0] if _chunks else "",
                    text_chunk_1=_chunks[1] if len(_chunks) > 1 else "",
                    text_chunk_2=_chunks[2] if len(_chunks) > 2 else "",
                    text_last_chunk=_chunks[-1] if _chunks else "",
                    total_elapsed=f"{time.time() - greeting_start:.3f}s",
                    note="Phase2만 전송 (Phase1 지식 없음)",
                )
                log_call_data(
                    self._call_id or "",
                    "tts",
                    "greeting_phase2_sent",
                    text_len=len(p2),
                    text=p2,
                )
                self._pipeline_tx_callee(self._call_id or "", p2)
                if self._call_id:
                    try:
                        from src.ai_voicebot.greeting_store import set_greeting
                        set_greeting(self._call_id, greeting_phase2=p2)
                        from src.websocket import manager as ws_manager
                        asyncio.create_task(ws_manager.emit_ai_greeting(self._call_id, 2, p2))
                    except Exception as e:
                        logger.debug("greeting_store_or_emit_failed", phase=2, error=str(e))
                self._greeting_phase2_done.set()
                logger.info(
                    "greeting_total_elapsed",
                    call_id=self._call_id or "",
                    elapsed=f"{time.time() - greeting_start:.3f}s",
                )
                return

            # Phase1 전송 (Phase2 유무와 무관하게 먼저 송출)
            await self.push_frame(LLMFullResponseStartFrame())
            await self.push_frame(TextFrame(text=p1))
            await self.push_frame(LLMFullResponseEndFrame())

            _c1 = [p1[i : i + 60] for i in range(0, len(p1), 60)]
            logger.info(
                "greeting_phase1_sent",
                call=True,
                category="tts",
                progress="tts",
                text_len=len(p1),
                text_chunk_0=_c1[0] if _c1 else "",
                text_chunk_1=_c1[1] if len(_c1) > 1 else "",
                elapsed=f"{time.time() - greeting_start:.3f}s",
                note="Phase1 전송 (지식 베이스 본문)",
            )
            log_call_data(
                self._call_id or "",
                "tts",
                "greeting_phase1_sent",
                text_len=len(p1),
                text=p1,
            )
            self._pipeline_tx_callee(self._call_id or "", p1)
            if self._call_id:
                try:
                    from src.ai_voicebot.greeting_store import set_greeting
                    set_greeting(self._call_id, greeting_phase1=p1)
                    from src.websocket import manager as ws_manager
                    asyncio.create_task(ws_manager.emit_ai_greeting(self._call_id, 1, p1))
                except Exception as e:
                    logger.debug("greeting_store_or_emit_failed", phase=1, error=str(e))

            if not p2:
                self._greeting_phase2_done.set()
                logger.info(
                    "greeting_total_elapsed",
                    call_id=self._call_id or "",
                    elapsed=f"{time.time() - greeting_start:.3f}s",
                )
                return

            # Phase1 + Phase2: Phase1 TTS 완료 후 Phase2
            event = asyncio.Event()
            self._tts_sync_context["on_tts_complete"] = event
            from src.ai_voicebot.pipecat.processors.tts_complete_notifier import (
                KEY_LAST_TTS_DURATION_SEC,
            )
            estimated_phase1_sec = len(p1) / self._TTS_CHARS_PER_SEC
            wait_timeout = min(
                self._TTS_COMPLETE_WAIT_TIMEOUT_SEC,
                max(estimated_phase1_sec * 2 + 15.0, 20.0),
            )
            logger.info(
                "greeting_phase_waiting_tts_complete",
                call=True,
                category="tts",
                progress="tts",
                wait_timeout_sec=round(wait_timeout, 1),
                estimated_phase1_sec=round(estimated_phase1_sec, 1),
                note="Phase1 재생 완료 이벤트 대기 후 Phase2",
            )
            try:
                logger.info(
                    "rag_greeting_blocking_start",
                    call_id=getattr(self, "_call_id", ""),
                    note="[STT 블로킹 추적] RAG가 event.wait() 진입",
                )
                await asyncio.wait_for(event.wait(), timeout=wait_timeout)
                logger.info(
                    "rag_greeting_blocking_end",
                    call_id=getattr(self, "_call_id", ""),
                    note="[STT 블로킹 추적] event.wait() 해제됨",
                )
                await asyncio.sleep(0.25)
                from src.ai_voicebot.pipecat.rtp_transport import KEY_LAST_RTP_SENT_SEC
                play_sec = self._tts_sync_context.pop(KEY_LAST_TTS_DURATION_SEC, None)
                rtp_sent_sec = self._tts_sync_context.pop(KEY_LAST_RTP_SENT_SEC, None)
                estimated_full_sec = max(0.5, len(p1) / self._TTS_CHARS_PER_SEC)
                play_sec_val = play_sec if isinstance(play_sec, (int, float)) and play_sec > 0 else 0
                rtp_sent_val = rtp_sent_sec if isinstance(rtp_sent_sec, (int, float)) and rtp_sent_sec > 0 else 0
                remaining_rtp_sec = max(0.0, (play_sec_val - rtp_sent_val)) if play_sec_val else estimated_full_sec
                gap_sec = remaining_rtp_sec + self._PHASE_GAP_BUFFER_SEC
                logger.info(
                    "rag_greeting_gap_sleep_start",
                    call_id=getattr(self, "_call_id", ""),
                    gap_sec=round(gap_sec, 2),
                    note="Phase1→Phase2 gap sleep",
                )
                await asyncio.sleep(gap_sec)
                logger.info(
                    "rag_greeting_gap_sleep_done",
                    call_id=getattr(self, "_call_id", ""),
                    note="gap sleep 완료, Phase2 전송",
                )
                phase1_short = play_sec_val > 0 and play_sec_val < estimated_full_sec * 0.8
                if phase1_short:
                    logger.warning(
                        "phase1_duration_short_possible_interrupt",
                        call_id=getattr(self, "_call_id", ""),
                        phase1_audio_sec=round(play_sec_val, 2),
                        estimated_full_sec=round(estimated_full_sec, 2),
                        note="Phase1 재생이 예상보다 짧음",
                    )
                logger.info(
                    "greeting_phase_gap_tts_complete_signalled",
                    call=True,
                    category="tts",
                    phase1_audio_sec=round(play_sec_val, 2) if play_sec_val else None,
                    phase1_rtp_sent_sec=round(rtp_sent_val, 2) if rtp_sent_val else None,
                    remaining_rtp_sec=round(remaining_rtp_sec, 2),
                    estimated_full_sec=round(estimated_full_sec, 2),
                    gap_sec=round(gap_sec, 2),
                    phase1_short=phase1_short,
                    note="Phase1 RTP 남은 시간만큼 대기 후 Phase2",
                )
            except asyncio.TimeoutError:
                self._tts_sync_context.pop(KEY_LAST_TTS_DURATION_SEC, None)
                phase1_play_sec = max(0.5, len(p1) / self._TTS_CHARS_PER_SEC)
                gap_sec = phase1_play_sec + self._PHASE_GAP_BUFFER_SEC
                await asyncio.sleep(gap_sec)
                logger.warning(
                    "greeting_phase_gap_tts_complete_timeout",
                    call=True,
                    category="tts",
                    phase1_chars=len(p1),
                    wait_timeout_sec=round(wait_timeout, 1),
                    fallback_gap_sec=round(gap_sec, 2),
                )
            finally:
                self._tts_sync_context.pop("on_tts_complete", None)

            self._tts_sync_context["_greeting_phase2_no_flush"] = True
            await self.push_frame(LLMFullResponseStartFrame())
            await self.push_frame(TextFrame(text=p2))
            await self.push_frame(LLMFullResponseEndFrame())

            _chunks = [p2[i : i + 60] for i in range(0, len(p2), 60)]
            logger.info(
                "greeting_phase2_sent",
                call=True,
                category="tts",
                progress="tts",
                text_len=len(p2),
                text_chunk_count=len(_chunks),
                text_chunk_0=_chunks[0] if _chunks else "",
                text_chunk_1=_chunks[1] if len(_chunks) > 1 else "",
                text_chunk_2=_chunks[2] if len(_chunks) > 2 else "",
                text_last_chunk=_chunks[-1] if _chunks else "",
                total_elapsed=f"{time.time() - greeting_start:.3f}s",
                note="Phase2 전송",
            )
            log_call_data(
                self._call_id or "",
                "tts",
                "greeting_phase2_sent",
                text_len=len(p2),
                text=p2,
            )
            self._pipeline_tx_callee(self._call_id or "", p2)
            if self._call_id:
                try:
                    from src.ai_voicebot.greeting_store import set_greeting
                    set_greeting(self._call_id, greeting_phase2=p2)
                    from src.websocket import manager as ws_manager
                    asyncio.create_task(ws_manager.emit_ai_greeting(self._call_id, 2, p2))
                except Exception as e:
                    logger.debug("greeting_store_or_emit_failed", phase=2, error=str(e))

            self._greeting_phase2_done.set()
            logger.info(
                "greeting_total_elapsed",
                call_id=self._call_id or "",
                elapsed=f"{time.time() - greeting_start:.3f}s",
            )

        except Exception as e:
            logger.error("greeting_generation_error", call=True, category="tts", error=str(e), exc_info=True)
            self._greeting_phase2_done.set()
    
    def _analyze_query_complexity(self, query: str) -> str:
        """
        Query 복잡도 분석 (간단한 query는 rewrite 스킵 가능)
        
        Returns:
            "simple": 간단한 query (rewrite 불필요)
            "complex": 복잡한 query (rewrite 필요)
        """
        query_lower = query.lower()
        
        # 1. 짧은 query (15자 미만)
        if len(query) < 15:
            return "simple"
        
        # 2. 직접적인 질문 키워드
        simple_patterns = [
            "날씨", "기온", "예보", "강수", "비", "눈", "특보",
            "전화", "연결", "담당자", "상담사",
            "시간", "영업시간", "위치", "주소",
            "요금", "가격", "비용",
        ]
        if any(keyword in query_lower for keyword in simple_patterns):
            return "simple"
        
        # 3. 복잡한 query: 여러 절, 조건문
        if any(keyword in query_lower for keyword in ["그런데", "하지만", "근데", "그리고", "또한"]):
            return "complex"
        
        # 기본값: simple
        return "simple"
    
    def reset(self):
        """대화 상태 초기화 (새 통화)"""
        self._greeting_sent = False
        self._greeting_phase2_done = asyncio.Event()  # 새 통화마다 새 이벤트 (Phase2 대기용)
        self._utterance_in_flight = None
        self._agent_superseded = False
        if self._agent_turn_task and not self._agent_turn_task.done():
            self._agent_turn_task.cancel()
        self._agent_turn_task = None
        # 워커 취소 및 큐 비우기 (이전 통화 발화가 새 통화에 섞이지 않도록)
        if self._user_message_worker_task and not self._user_message_worker_task.done():
            self._user_message_worker_task.cancel()
        self._user_message_worker_task = None
        while not self._user_message_queue.empty():
            try:
                self._user_message_queue.get_nowait()
            except Exception:
                break
        if self._agent_available and self._agent:
            self._agent.reset()
        elif hasattr(self, '_messages'):
            self._messages = []
        logger.info("rag_llm_processor_reset")
    
    # =========================================================================
    # Legacy fallback (Phase 1 호환)
    # =========================================================================
    
    async def _generate_greeting_legacy(self) -> str:
        """지식베이스 greeting_phase1 본문 우선; 없으면 기본 TTS 문구 (Legacy)."""
        if self._vector_db and self._owner:
            try:
                from src.ai_voicebot.knowledge.knowledge_service import get_knowledge_greeting_text

                kb = get_knowledge_greeting_text(
                    self._vector_db, self._owner, "greeting_phase1"
                )
                if kb and len(kb.strip()) >= 2:
                    logger.info(
                        "legacy_greeting_from_kb_greeting_phase1",
                        owner=self._owner,
                        preview=kb,
                    )
                    return kb.strip()
            except Exception as e:
                logger.debug("legacy_greeting_kb_failed", error=str(e))
        from src.ai_voicebot.greeting_defaults import DEFAULT_GREETING_PHASE1

        logger.info(
            "legacy_greeting_phase1_default_tts_fallback",
            owner=self._owner or "",
            reason="kb_empty_or_no_owner_or_lookup_failed",
            text_len=len(DEFAULT_GREETING_PHASE1),
        )
        return DEFAULT_GREETING_PHASE1

    def _generate_capability_guide_legacy(self) -> str:
        """지식베이스 greeting_phase2 본문 우선; 없으면 기본 TTS 문구 (Legacy)."""
        if self._vector_db and self._owner:
            try:
                from src.ai_voicebot.knowledge.knowledge_service import get_knowledge_greeting_text

                kb = get_knowledge_greeting_text(
                    self._vector_db, self._owner, "greeting_phase2"
                )
                if kb and len(kb.strip()) >= 2:
                    logger.info(
                        "legacy_capability_from_kb_greeting_phase2",
                        owner=self._owner,
                        preview=kb,
                    )
                    return kb.strip()
            except Exception as e:
                logger.debug("legacy_capability_kb_failed", error=str(e))
        from src.ai_voicebot.greeting_defaults import DEFAULT_GREETING_PHASE2

        logger.info(
            "legacy_greeting_phase2_default_tts_fallback",
            owner=self._owner or "",
            reason="kb_empty_or_no_owner_or_lookup_failed",
            text_len=len(DEFAULT_GREETING_PHASE2),
        )
        return DEFAULT_GREETING_PHASE2
    
    async def _generate_response_legacy(self, user_text: str):
        """RAG 검색 + LLM 응답 생성 (Legacy)"""
        try:
            self._messages.append({
                "role": "user",
                "content": user_text,
                "timestamp": datetime.now().isoformat(),
            })
            
            rag_context = ""
            _legacy_ctx: list = []
            _rag_trace: dict = {}
            if self._rag:
                try:
                    # 레거시 경로에서도 테넌트 격리: owner_filter 전달
                    _rag_out = await self._rag.search(user_text, owner_filter=self._owner or None)
                    results = _rag_out.documents
                    _rag_trace = getattr(_rag_out, "trace", None) or {}
                    if not results:
                        log_call_data(
                            self._call_id or "",
                            "rag",
                            "rag_search_done",
                            query=user_text,
                            result_count=0,
                            mode="legacy",
                            rag_hits_retrieval=[],
                            rag_hits_llm_context=[],
                            rag_search_trace=_rag_trace,
                        )
                    if results:
                        rag_context = "\n\n".join([
                            doc.text if hasattr(doc, 'text') else
                            (doc.get("text", "") if isinstance(doc, dict) else str(doc))
                            for doc in results
                        ])
                        first_text = (results[0].text if hasattr(results[0], "text") else results[0].get("text", "")) if results else ""
                        logger.info("rag_search_results",
                                     call=True,
                                     category="rag",
                                     progress="rag",
                                     query=user_text,
                                     query_len=len(user_text),
                                     doc_count=len(results),
                                     top_doc_preview=first_text,
                                     top_doc_full=first_text,
                                     note="레거시 RAG 검색 결과")
                        _legacy_ctx = [
                            {
                                "text": (
                                    results[j].text
                                    if hasattr(results[j], "text")
                                    else results[j].get("text", "")
                                ),
                                "score": (
                                    results[j].score
                                    if hasattr(results[j], "score")
                                    else results[j].get("score", 0.0)
                                ),
                                "metadata": (
                                    results[j].metadata
                                    if hasattr(results[j], "metadata")
                                    else results[j].get("metadata") or {}
                                ),
                                "source": "legacy_top_k",
                            }
                            for j in range(len(results))
                        ]
                        log_call_data(
                            self._call_id or "",
                            "rag",
                            "rag_search_done",
                            query=user_text,
                            result_count=len(results),
                            mode="legacy",
                            rag_hits_retrieval=build_rag_hits_retrieval(results, max_items=8),
                            rag_hits_llm_context=build_rag_hits_llm_context(_legacy_ctx, max_items=8),
                            rag_search_trace=_rag_trace,
                        )
                except Exception as e:
                    logger.warning("rag_search_error", call=True, category="rag", progress="rag", error=str(e))
            
            org_context = ""
            if self._org_manager:
                try:
                    org_context = self._org_manager.get_system_prompt()
                except Exception:
                    pass
            
            caller_context = self._get_caller_context_sync()
            system_prompt = self._build_system_prompt(org_context, rag_context, caller_context)
            conversation_history = self._format_history()
            
            response = await self._call_llm(system_prompt, conversation_history, user_text)
            
            if response:
                logger.info("llm_legacy_response",
                           call=True,
                           category="llm",
                           progress="llm",
                           user_text_full=user_text,
                           response_full=response,
                           response_len=len(response),
                           note="레거시 RAG+LLM 응답 (전체 로깅)")
                _legacy_llm_rag = build_rag_hits_llm_context(_legacy_ctx, max_items=8)
                _legacy_rag_src = "legacy_vector_knowledge" if _legacy_ctx else "legacy_prompt_no_reference"
                log_call_data(
                    self._call_id or "",
                    "llm",
                    "llm_exchange",
                    user_text=user_text,
                    user_text_full=user_text,
                    user_text_len=len(user_text or ""),
                    response=response,
                    response_full=response,
                    response_len=len(response),
                    mode="legacy",
                    llm_rag_context_source=_legacy_rag_src,
                    llm_rag_applied=_legacy_llm_rag,
                    llm_rag_applied_count=len(_legacy_llm_rag),
                    rag_search_trace=_rag_trace,
                )
                log_call_data(
                    self._call_id or "",
                    "tts",
                    "tts_text_pushed",
                    text=response,
                    text_len=len(response),
                    mode="legacy",
                )
                self._pipeline_tx_callee(self._call_id or "", response)
                self._messages.append({
                    "role": "assistant",
                    "content": response,
                    "timestamp": datetime.now().isoformat(),
                })
                self._trim_history()
                
                await self.push_frame(LLMFullResponseStartFrame())
                await self.push_frame(TextFrame(text=response))
                await self.push_frame(LLMFullResponseEndFrame())
            else:
                _lfail = "죄송합니다. 답변을 생성하지 못했습니다."
                self._pipeline_tx_callee(self._call_id or "", _lfail)
                await self.push_frame(TextFrame(text=_lfail))
                
        except Exception as e:
            logger.error("rag_llm_response_error", call=True, category="llm", error=str(e), exc_info=True)
            _lerr = "죄송합니다. 오류가 발생했습니다."
            self._pipeline_tx_callee(self._call_id or "", _lerr)
            await self.push_frame(TextFrame(text=_lerr))
    
    def _get_caller_context_sync(self) -> str:
        """발신자별 이전 통화 요약을 DB에서 조회해 [이전 통화 맥락] 블록 문자열로 반환. 설계: CALLER_MEMORY_DESIGN.md"""
        if not self._owner or not getattr(self, "_caller_id", None) or not self._caller_id:
            return ""
        try:
            from src.db import get_recent_summaries_by_caller
            summaries = get_recent_summaries_by_caller(
                tenant_id=self._owner,
                caller_id=self._caller_id,
                limit=5,
            )
            if not summaries:
                return ""
            lines = [s.get("summary_text", "").strip() for s in summaries if s.get("summary_text")]
            if not lines:
                return ""
            return "\n\n[이전 통화 맥락]\n" + "\n".join(f"- {t}" for t in lines)
        except Exception as e:
            logger.debug("get_caller_context_failed", error=str(e))
            return ""

    def _build_system_prompt(self, org_context: str, rag_context: str, caller_context: str = "") -> str:
        parts = []
        if self._system_prompt:
            parts.append(self._system_prompt)
        elif org_context:
            parts.append(org_context)
        else:
            parts.append(
                "당신은 전화 통화를 응대하는 AI 비서입니다. "
                "친절하고 간결하게 답변하세요. "
                "사용자 질문을 그대로 반복하거나 인용하지 말고 바로 답변하세요."
            )
        if caller_context:
            parts.append(caller_context)
        if rag_context:
            parts.append(f"\n\n[참고 정보]\n{rag_context}")
        return "\n".join(parts)
    
    def _format_history(self) -> str:
        lines = []
        for msg in self._messages[-self._max_history_turns * 2:]:
            role = "사용자" if msg["role"] == "user" else "AI"
            lines.append(f"{role}: {msg['content']}")
        return "\n".join(lines)
    
    async def _call_llm(
        self, system_prompt: str, history: str, user_text: str
    ) -> Optional[str]:
        full_prompt = f"{system_prompt}\n\n[대화 기록]\n{history}\n\n사용자: {user_text}\n\nAI:"
        try:
            if hasattr(self._llm, 'generate_response'):
                return await self._llm.generate_response(full_prompt, context_docs=[])
            elif hasattr(self._llm, 'generate'):
                return await self._llm.generate(full_prompt)
            return None
        except Exception as e:
            logger.error("llm_call_error", error=str(e))
            return None
    
    def _trim_history(self):
        max_messages = self._max_history_turns * 2
        if len(self._messages) > max_messages:
            self._messages = self._messages[-max_messages:]
