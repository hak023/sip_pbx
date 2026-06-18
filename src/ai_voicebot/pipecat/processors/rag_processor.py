"""
RAG-enhanced LLM Processor for Pipecat Pipeline (Phase 2: LangGraph).

Phase 1: 단순 RAG + LLM
Phase 2: LangGraph ConversationAgent로 교체
  - 의도 분류, Semantic Cache, Query Rewriting, Adaptive RAG,
    Step-back Prompting, HITL Alert, Business State Tracking

STT TranscriptionFrame → LangGraph Agent → TextFrame(응답) → TTS
"""

import asyncio
import os
import re
import time
import weakref
from datetime import datetime
from typing import Any, Dict, Optional, List, Callable, Awaitable

import structlog

from src.common.ai_response_latency_compare import (
    apply_llm_first_sentence_timing,
    begin_turn,
    mark_first_audio_and_compare,
    mark_llm_complete,
    mark_llm_start,
    mark_stt_final,
    mark_tts_text_pushed,
)
from src.common.call_data_record_logger import log_call_data
from src.common.rag_hit_serializer import build_rag_hits_llm_context, build_rag_hits_retrieval
from src.common.tts_output_sanitize import sanitize_voice_assistant_text
from src.common.tts_streaming_chunk_dedupe import dedupe_streaming_tts_chunks

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
try:
    from pipecat.frames.frames import ErrorFrame, FatalErrorFrame as _FatalErrorFrame
    _ERROR_FRAME_TYPES: tuple = (ErrorFrame, _FatalErrorFrame)
except ImportError:
    try:
        from pipecat.frames.frames import ErrorFrame
        _ERROR_FRAME_TYPES = (ErrorFrame,)
    except ImportError:
        _ERROR_FRAME_TYPES = ()
from pipecat.processors.frame_processor import FrameDirection, FrameProcessor

# STT 결과 무응답 감지: 마지막 TranscriptionFrame 이후 이 시간(초) 동안 결과 없으면 경고
# 오디오는 오는데 STT 결과가 없으면 STT 스트리밍 세션 이상 의심
_STT_TRANSCRIPT_WATCHDOG_SEC = 30.0

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
        stt_final_debounce_sec: float = 0.0,
        rtp_worker: Optional[Any] = None,
        **kwargs,
    ):
        super().__init__(**kwargs)
        self._llm = llm_client
        self._tts_sync_context = tts_sync_context or {}
        self._call_id = call_id  # 통화 ID 저장
        # STT 워치독·진단: Pipecat 입력과 RTP 릴레이 상태 상관 (weakref — 파이프라인 수명 ≤ 워커)
        self._rtp_worker_ref: Optional[Callable[[], Any]] = (
            weakref.ref(rtp_worker) if rtp_worker is not None else None
        )
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
        # STT Debounce: 개선안 3에서 0으로 설정 → Supersede 방식으로 대체.
        # stt_final_debounce_sec > 0 으로 설정 시 이전 Debounce 방식 동작 가능(하위 호환).
        self._stt_final_debounce_sec: float = float(stt_final_debounce_sec or 0.0)
        self._stt_debounce_task: Optional[asyncio.Task] = None
        self._stt_debounce_chunks: List[str] = []
        # HITL TTS: 비어 있지 않은 STT interim 수신 시각 (없으면 hangover 미적용)
        self._stt_last_nonempty_interim_monotonic: Optional[float] = None
        # 후속 STT 최종이 도착했을 때 진행 중인 에이전트 턴 취소·문장 병합 (seq N 처리 중 seq N+1)
        self._stt_enqueue_lock: Optional[asyncio.Lock] = None
        self._agent_turn_task: Optional[asyncio.Task] = None
        self._utterance_in_flight: Optional[str] = None
        self._agent_superseded: bool = False
        # 발신자 맥락: 통화당 1회 이력 행 생성 (설계: CALLER_MEMORY_DESIGN.md)
        self._call_history_ensured = False
        # STT 원인 규명: RAG에 도달한 TranscriptionFrame(최종) 개수
        self._transcription_frame_count = 0
        # STT 무응답 워치독: 마지막 TranscriptionFrame 수신 시각 (monotonic)
        self._last_transcription_time: Optional[float] = None
        self._stt_transcript_watchdog_task: Optional[asyncio.Task] = None
        self._stt_transcript_watchdog_alerted = False
        # Pipecat: push_frame()은 StartFrame 처리 후에만 동작. 인사/HITL이 먼저 돌면 프레임이 드롭되어 TTS/RTP 없음.
        self._pipeline_start_event = asyncio.Event()

        # 대기 안내 멘트 상태: 턴별 중복 발화 방지 + 멘트 순환 인덱스
        self._waiting_phrase_active: bool = False
        self._waiting_phrase_idx: int = 0
        # 배치 vs 조기 TTS 체감 비교 로그용 턴 번호
        self._latency_turn_seq: int = 0

        # HITL Manager (Phase 3): on_alert 연결 시 프론트에 hitl_requested 발송
        self._hitl_manager = None
        try:
            from src.ai_voicebot.pipecat.processors.hitl_processor import HITLManager
            self._hitl_manager = HITLManager(on_alert=hitl_on_alert)
            logger.info("hitl_manager_initialized", has_on_alert=hitl_on_alert is not None)
        except Exception as e:
            logger.debug("hitl_manager_not_available", error=str(e))

        # 아웃바운드 미션 추적
        # hangup_callback: 미션 완료 시 호출 → SIP BYE 전송 (아웃바운드 전용)
        self._outbound_questions: List[str] = []
        self._outbound_answers: dict = {}
        self._outbound_mission_done: bool = False
        self._outbound_purpose: str = ""
        self._hangup_callback: Optional[Callable[..., Any]] = None
        
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
    
    def set_outbound_mission(
        self,
        purpose: str,
        questions: List[str],
        hangup_callback: Optional[Callable[..., Any]] = None,
    ) -> None:
        """아웃바운드 미션 설정. build_and_run 이후 pipeline._rag_llm을 통해 호출한다."""
        self._outbound_purpose = purpose
        self._outbound_questions = list(questions)
        self._outbound_answers = {}
        self._outbound_mission_done = False
        self._hangup_callback = hangup_callback
        logger.info(
            "outbound_mission_set",
            call_id=self._call_id,
            purpose=purpose,
            question_count=len(questions),
            has_hangup_callback=hangup_callback is not None,
        )

    async def _check_outbound_mission_complete(self, ai_response: str) -> None:
        """AI 응답 후 아웃바운드 미션 완료 여부를 판단한다.

        generate_response_node가 LLM JSON 단일 호출로 답변을 이미 추출해
        _outbound_answers에 적용했으므로, 여기서는 answers 완료 여부만 확인한다.
        LLM을 추가로 호출하지 않는다.

        완료 조건:
          - 질문 목록이 있는 경우: 모든 질문이 _outbound_answers에 채워진 경우
          - 질문 목록이 없는 경우: purpose만 있을 때는 미션 완료 판단 불가 → 로그만 남김
        """
        if self._outbound_mission_done:
            return
        if not self._outbound_purpose and not self._outbound_questions:
            return

        call_id = self._call_id or ""

        if self._outbound_questions:
            unanswered = [q for q in self._outbound_questions if q not in self._outbound_answers]
            if not unanswered:
                logger.info(
                    "outbound_mission_complete_answers_full",
                    call_id=call_id,
                    total=len(self._outbound_questions),
                    note="모든 질문 답변 수집 완료 → 미션 종료",
                )
                await self._trigger_mission_complete(call_id)
            else:
                logger.info(
                    "outbound_mission_incomplete_waiting_next_turn",
                    call_id=call_id,
                    answered_count=len(self._outbound_answers),
                    remaining_count=len(unanswered),
                    remaining_questions=[q[:40] for q in unanswered],
                    note="generate_response_node가 재질문 포함 응답 출력함 — 다음 턴 대기",
                )
        else:
            # purpose만 있는 경우: 질문 목록 없이 완료 여부를 판단할 기준이 없음
            # generate_response_node의 응답에서 완료 신호를 감지하는 방식으로 처리
            logger.info(
                "outbound_purpose_only_no_questions",
                call_id=call_id,
                purpose=self._outbound_purpose[:50],
                note="질문 목록 없음 — purpose 달성 여부는 generate_response_node 응답 기반으로 판단 필요",
            )

    async def _trigger_mission_complete(self, call_id: str) -> None:
        """미션 완료 처리: farewell TTS 송출 후 hangup_callback 호출."""
        if self._outbound_mission_done:
            return
        self._outbound_mission_done = True

        logger.info("outbound_mission_complete",
                    call_id=call_id,
                    answered_count=len(self._outbound_answers),
                    purpose=self._outbound_purpose[:50] if self._outbound_purpose else "")

        # farewell 멘트: KB farewell 카테고리 우선, 없으면 하드코딩 폴백
        farewell_text = ""
        if self._agent_available and self._agent:
            try:
                farewell_text = (await self._agent.generate_farewell() or "").strip()
                if farewell_text:
                    logger.info("outbound_farewell_from_kb",
                                call_id=call_id, text_preview=farewell_text[:80])
            except Exception as e:
                logger.warning("outbound_farewell_kb_error", call_id=call_id, error=str(e))

        if not farewell_text:
            # purpose 기반으로 자연스러운 마무리 문구 생성
            farewell_text = "통화에 응해주셔서 감사합니다. 좋은 하루 되세요."
            logger.info("outbound_farewell_hardcoded",
                        call_id=call_id,
                        note="KB farewell 없음 — 기본 마무리 멘트 사용. KB에 farewell 카테고리 문서를 등록하면 커스텀 멘트로 교체됩니다.")

        # farewell TTS 송출
        tts_done_event = asyncio.Event()
        self._tts_sync_context["on_tts_complete"] = tts_done_event
        try:
            await self.push_frame(LLMFullResponseStartFrame())
            await self.push_frame(TextFrame(text=farewell_text))
            await self.push_frame(LLMFullResponseEndFrame())
            logger.info("outbound_farewell_sent", call_id=call_id, text=farewell_text)
        except Exception as e:
            logger.warning("outbound_farewell_failed", call_id=call_id, error=str(e))

        # TTS 완료 이벤트 대기 (최대 15초), 타임아웃 시 5초 sleep 폴백
        # ※ 이 이벤트는 "PCM 큐 투입 완료" 시점에 set 된다 (RTP 송출 완료가 아님).
        #    이벤트 수신 후 last_tts_duration_sec 만큼 추가 대기해야
        #    RTP 전송이 끝난 뒤 BYE를 전송할 수 있다.
        tts_rtp_play_duration: float = 0.0
        try:
            await asyncio.wait_for(tts_done_event.wait(), timeout=15.0)
            tts_rtp_play_duration = float(
                self._tts_sync_context.get("last_tts_duration_sec") or 0.0
            )
            logger.info("outbound_farewell_tts_done_by_event",
                        call_id=call_id,
                        tts_rtp_play_duration=round(tts_rtp_play_duration, 3))
        except asyncio.TimeoutError:
            logger.warning("outbound_farewell_tts_timeout",
                           call_id=call_id,
                           note="TTS 완료 이벤트 15초 미수신 — sleep 5초 폴백")
            await asyncio.sleep(5.0)
        finally:
            self._tts_sync_context.pop("on_tts_complete", None)

        # PCM 큐에 투입된 오디오가 실제로 RTP 전송될 때까지 대기
        # (합성 완료 시점과 RTP 재생 완료 시점 사이 갭 보정)
        if tts_rtp_play_duration > 0.1:
            # 안전 마진 0.3초 추가 (RTP 지터·큐 소비 딜레이 흡수)
            wait_sec = tts_rtp_play_duration + 0.3
            logger.info("outbound_farewell_rtp_wait",
                        call_id=call_id,
                        tts_duration_sec=round(tts_rtp_play_duration, 3),
                        wait_sec=round(wait_sec, 3),
                        note="farewell RTP 재생 완료 대기 (BYE 조기 전송 방지)")
            await asyncio.sleep(wait_sec)

        # hangup_callback 호출 → SIP BYE 전송
        if self._hangup_callback:
            try:
                if asyncio.iscoroutinefunction(self._hangup_callback):
                    await self._hangup_callback(call_id)
                else:
                    self._hangup_callback(call_id)
                logger.info("outbound_hangup_triggered", call_id=call_id)
            except Exception as e:
                logger.error("outbound_hangup_callback_error", call_id=call_id, error=str(e))

        # Pipecat 파이프라인 종료: BYE 후에도 STT 큐 폴링이 계속되는 것을 방지
        # EndFrame을 push하면 파이프라인이 정상 종료됨 (max_duration 타임아웃 대기 불필요)
        try:
            await self.push_frame(EndFrame())
            logger.info("outbound_pipeline_end_frame_sent", call_id=call_id)
        except Exception as e:
            logger.warning("outbound_pipeline_end_frame_error", call_id=call_id, error=str(e))

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

    def _effective_call_id_for_ws(self) -> str:
        """대시보드 Socket emit용 call_id. 생성자에 None이어도 pipeline_builder가 tts_sync_context에 넣을 수 있음."""
        cid = (self._call_id or "").strip()
        if cid:
            return cid
        ctx = self._tts_sync_context or {}
        raw = ctx.get("_call_id")
        if raw is None:
            return ""
        return str(raw).strip()

    async def _emit_greeting_to_dashboard(self, *, phase: int, text: str) -> None:
        """인사 Phase1/2 문구를 대시보드 실시간 대화(ai_greeting) 및 greeting_store에 반영."""
        ws_cid = self._effective_call_id_for_ws()
        if not ws_cid:
            logger.warning(
                "greeting_dashboard_emit_skipped_no_call_id",
                phase=phase,
                text_len=len((text or "").strip()),
                note="RAGLLMProcessor._call_id·tts_sync_context._call_id 모두 비어 ai_greeting 미전송",
            )
            return
        try:
            from src.ai_voicebot.greeting_store import set_greeting
            from src.websocket import manager as ws_manager

            if phase == 1:
                set_greeting(ws_cid, greeting_phase1=text)
            elif phase == 2:
                set_greeting(ws_cid, greeting_phase2=text)
            await ws_manager.emit_ai_greeting(ws_cid, phase, text)
            logger.info(
                "greeting_dashboard_emit_ok",
                call_id=ws_cid,
                phase=phase,
                text_len=len((text or "").strip()),
            )
        except Exception as e:
            logger.warning(
                "greeting_store_or_emit_failed",
                phase=phase,
                call_id=ws_cid,
                error=str(e),
                exc_info=True,
            )

    def _hitl_defer_due_to_stt_ingress(self) -> bool:
        """운영자 HITL 멘트 송출을 미룰지: STT 중간 결과가 최근에 있었거나 최종 디바운스 대기 중."""
        if self._stt_debounce_chunks:
            return True
        if self._stt_debounce_task is not None and not self._stt_debounce_task.done():
            return True
        if self._stt_last_nonempty_interim_monotonic is not None:
            try:
                hang = float(os.environ.get("HITL_STT_INTERIM_HANGOVER_SEC", "0.45"))
            except ValueError:
                hang = 0.45
            if hang > 0 and (time.monotonic() - self._stt_last_nonempty_interim_monotonic) < hang:
                return True
        return False

    async def _wait_until_stt_ingress_idle_for_hitl(self) -> None:
        """HITL 응답 TTS 전: 발화 인입(STT interim·최종 디바운스)이 끝날 때까지 대기."""
        if not self._hitl_defer_due_to_stt_ingress():
            return
        try:
            max_wait = float(os.environ.get("HITL_STT_DEFER_MAX_WAIT_SEC", "120"))
        except ValueError:
            max_wait = 120.0
        max_wait = max(1.0, min(max_wait, 600.0))
        deadline = time.monotonic() + max_wait
        poll = 0.05
        started = time.monotonic()
        logger.info(
            "hitl_response_deferred_for_stt_ingress",
            call=True,
            call_id=self._call_id or "",
            note="STT interim/디바운스 활성 — 송출 대기",
        )
        log_call_data(
            self._call_id or "",
            "hitl",
            "hitl_response_deferred_stt_ingress",
            note="stt_interim_or_debounce",
        )
        while self._hitl_defer_due_to_stt_ingress():
            if time.monotonic() >= deadline:
                logger.warning(
                    "hitl_response_stt_ingress_max_wait_exceeded",
                    call=True,
                    call_id=self._call_id or "",
                    max_wait_sec=max_wait,
                    note="타임아웃 후 HITL 멘트 송출 진행",
                )
                log_call_data(
                    self._call_id or "",
                    "hitl",
                    "hitl_response_defer_timeout",
                    max_wait_sec=max_wait,
                )
                break
            await asyncio.sleep(poll)
        waited = time.monotonic() - started
        if waited >= poll:
            logger.info(
                "hitl_response_stt_ingress_idle_proceeding",
                call=True,
                call_id=self._call_id or "",
                waited_sec=round(waited, 3),
            )

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
                    if response_data is None:
                        # cleanup() 에서 보낸 종료 sentinel
                        break
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

                        if msg_type == "hitl_response" and text.strip():
                            oq = (original_question or "").strip()
                            if proc._llm:
                                try:
                                    fn = getattr(proc._llm, "format_hitl_reply_for_customer", None)
                                    if fn:
                                        if asyncio.iscoroutinefunction(fn):
                                            refined = await fn(oq, text.strip())
                                        else:
                                            refined = fn(oq, text.strip())
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
                            elif oq:
                                # LLM 없을 때: 질문·답변을 한 멘트로 이어붙임 (TTS용)
                                text = f"{oq}에 대해서는 {text.strip()}라고 안내드립니다."
                                logger.info(
                                    "hitl_response_fallback_no_llm",
                                    call=True,
                                    call_id=proc._call_id or "",
                                    note="질문+답변 문자열 합성",
                                )

                    else:
                        # 호환성: 문자열로 직접 전달된 경우
                        msg_type = "hitl_response"
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
                    await proc._wait_until_stt_ingress_idle_for_hitl()
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

    def _rtp_snapshot_for_stt_watchdog(self) -> Dict[str, Any]:
        """STT 워치독과 RTP/브릿지 상태 상관용 스냅샷(알림 시점 값)."""
        r = self._rtp_worker_ref
        if not r:
            return {}
        rw = r()
        if rw is None:
            return {"rtp_worker_ref_dead": True}
        snap: Dict[str, Any] = {"rtp_worker_ref_dead": False}
        ms = getattr(rw, "media_session", None)
        if ms is not None:
            snap["ms_call_id"] = getattr(ms, "call_id", None)
            snap["ms_callee"] = getattr(ms, "callee", None)
            snap["ms_codec"] = getattr(ms, "codec", None)
        snap["relay_mode"] = getattr(rw, "relay_mode", None)
        snap["ai_mode"] = getattr(rw, "ai_mode", None)
        snap["pipecat_mode"] = getattr(rw, "_pipecat_mode", None)
        st = getattr(rw, "stats", None) or {}
        snap["stat_bypass_relay_sent"] = st.get("bypass_relay_sent")
        snap["stat_bypass_relay_send_failed"] = st.get("bypass_relay_send_failed")
        snap["stat_caller_audio_packets"] = st.get("caller_audio_packets")
        snap["stat_callee_audio_packets"] = st.get("callee_audio_packets")
        _pq = getattr(rw, "_pipecat_audio_queue", None)
        if _pq is not None:
            try:
                snap["pipecat_stt_input_queue_size"] = _pq.qsize()
            except Exception:
                snap["pipecat_stt_input_queue_size"] = None
        _pcm = getattr(rw, "_pipecat_pcm_queue", None)
        if _pcm is not None:
            try:
                snap["pipecat_tts_pcm_queue_size"] = _pcm.qsize()
            except Exception:
                snap["pipecat_tts_pcm_queue_size"] = None
        return snap

    async def _stt_transcript_watchdog(self) -> None:
        """STT TranscriptionFrame 무응답 워치독.

        StartFrame 이후 _STT_TRANSCRIPT_WATCHDOG_SEC 초 동안 TranscriptionFrame이 없으면 경고.
        마지막 TranscriptionFrame 수신 후 _STT_TRANSCRIPT_WATCHDOG_SEC 초 경과해도 재경고.

        근거: Pipecat GoogleSTTService 스트리밍 세션이 에러·timeout으로 종료되면
        ErrorFrame 없이 조용히 멈추는 경우가 있음 (app.log에 안 찍힘).
        이 워치독이 운영 중 STT 동결을 탐지하는 안전망 역할.
        """
        check_interval = _STT_TRANSCRIPT_WATCHDOG_SEC / 3
        # 통화 시작 직후 첫 발화까지 충분한 여유 시간 (인사말·안내 TTS 재생 포함)
        initial_grace = _STT_TRANSCRIPT_WATCHDOG_SEC
        try:
            await asyncio.sleep(initial_grace)
            while True:
                await asyncio.sleep(check_interval)
                if self._stt_transcript_watchdog_alerted:
                    # 이미 경보 발령 → 추가 대기 후 재경보 (연속 경보 방지)
                    await asyncio.sleep(_STT_TRANSCRIPT_WATCHDOG_SEC)
                    self._stt_transcript_watchdog_alerted = False
                    continue

                now_m = time.monotonic()
                # 기준 시각: 마지막 TranscriptionFrame 수신 or None(한 번도 없음)
                baseline = self._last_transcription_time
                if baseline is None:
                    # 한 번도 TranscriptionFrame 없음 — initial_grace 이미 지난 후이므로 경보
                    elapsed = initial_grace + check_interval
                else:
                    elapsed = now_m - baseline

                if elapsed >= _STT_TRANSCRIPT_WATCHDOG_SEC:
                    self._stt_transcript_watchdog_alerted = True
                    _rtp_snap = self._rtp_snapshot_for_stt_watchdog()
                    logger.error(
                        "stt_transcript_watchdog_alert",
                        call_id=self._call_id or "",
                        progress="stt",
                        category="stt",
                        elapsed_sec=round(elapsed, 1),
                        transcription_count=self._transcription_frame_count,
                        rtp_snapshot=_rtp_snap,
                        note=(
                            f"[STT 동결 확인] {elapsed:.0f}s 동안 TranscriptionFrame 없음 — "
                            "Pipecat GoogleSTTService 스트리밍 세션이 조용히 종료됐을 가능성. "
                            "pipecat_stt_error_frame 로그 또는 vad_consecutive_bargein_alert 확인. "
                            "rtp_snapshot(relay_mode·pipecat_mode·큐·bypass 패킷)으로 "
                            "착신/바이패스 경로와의 상관을 함께 본다. 서버 재시작은 최후 수단."
                        ),
                    )
        except asyncio.CancelledError:
            pass

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
        """STT 최종 문장을 큐에 넣고 워커 기동.

        Supersede 방식 (개선안 3):
          - LLM 처리 중에 새 STT 최종 도착 → 진행 중 태스크를 cancel() + 두 문장 병합 → 병합 문장으로 재처리.
          - Debounce 대기 없음 → 완결 발화는 STT 도착 즉시 LLM 시작.
          - cancel()은 비동기이므로 워커가 CancelledError를 처리해 continue 할 때까지
            큐에서 병합 문장을 꺼내 처리. 레이스컨디션 방지를 위해 큐를 먼저 비운 뒤 병합 문장 투입.
        """
        from datetime import datetime

        lock = self._get_stt_enqueue_lock()
        incoming = (user_text or "").strip()
        async with lock:
            queued_text = incoming
            if self._agent_turn_task and not self._agent_turn_task.done():
                # ── Supersede: LLM 처리 중 새 STT 도착 ──
                base = (self._utterance_in_flight or "").strip()
                merged = self._merge_stt_user_text(base, incoming)
                self._utterance_in_flight = merged
                self._agent_superseded = True
                # 큐에 대기 중인 항목 모두 비움 (이전 Debounce 잔여분 포함)
                while not self._user_message_queue.empty():
                    try:
                        self._user_message_queue.get_nowait()
                    except asyncio.QueueEmpty:
                        break
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
                    note="[Supersede] LLM 처리 중 새 STT 도착 → 병합 후 진행 턴 취소·재처리",
                )
                queued_text = merged
            elif (self._utterance_in_flight or "").strip():
                # ── Coalesce: 워커가 태스크 시작 직전 구간 ──
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
                    note="[Coalesce] 워커 유휴 직전 구간: 큐 헤드와 후속 STT 병합",
                )
                while not self._user_message_queue.empty():
                    try:
                        self._user_message_queue.get_nowait()
                    except asyncio.QueueEmpty:
                        break
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
        self._latency_turn_seq += 1
        begin_turn(
            self._tts_sync_context,
            call_id=self._call_id or "",
            turn_id=self._latency_turn_seq,
            user_text_preview=queued_text,
        )
        mark_stt_final(self._tts_sync_context, call_id=self._call_id or "")
        logger.info(
            "timing_stt_final_to_rag",
            call=True,
            call_id=self._call_id or "",
            progress="timing",
            turn_id=self._latency_turn_seq,
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
            # STT 무응답 워치독 시작 (StartFrame 이후 통화 활성)
            if self._stt_transcript_watchdog_task is None or self._stt_transcript_watchdog_task.done():
                self._stt_transcript_watchdog_task = asyncio.create_task(
                    self._stt_transcript_watchdog()
                )

        # Pipecat STT 에러 프레임 처리 — GoogleSTTService 내부 에러 노출
        if _ERROR_FRAME_TYPES and isinstance(frame, _ERROR_FRAME_TYPES):
            error_msg = getattr(frame, "error", "") or getattr(frame, "message", "") or str(frame)
            is_fatal = type(frame).__name__ == "FatalErrorFrame"
            logger.error(
                "pipecat_stt_error_frame",
                call_id=self._call_id or "",
                error=error_msg,
                frame_type=type(frame).__name__,
                is_fatal=is_fatal,
                note=(
                    "[STT 에러] Pipecat 파이프라인에서 ErrorFrame 수신 — "
                    "GoogleSTTService 스트리밍 세션 에러 또는 파이프라인 이상. "
                    "이 에러 직후 STT 결과가 없으면 stt_silence_watchdog_alert 확인"
                ),
            )
            # ErrorFrame은 하류로 전달 (파이프라인이 자체 처리하도록)
            await self.push_frame(frame, direction)
            return

        if isinstance(frame, TranscriptionFrame):
            user_text = frame.text.strip()
            self._transcription_frame_count += 1
            # STT 무응답 워치독 갱신 — 정상 결과 수신 시 알림 리셋
            self._last_transcription_time = time.monotonic()
            self._stt_transcript_watchdog_alerted = False
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
            if interim_text:
                self._stt_last_nonempty_interim_monotonic = time.monotonic()
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

        # 새 발화 턴 시작: 대기 안내 멘트 상태 초기화
        self._waiting_phrase_active = False

        # 시간 정규화 전 STT 원문 — RAG 이중 검색(adaptive_rag)에 전달
        stt_query_raw = (user_text or "").strip()

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

        try:
            from src.ai_voicebot.stt_korean_normalize import normalize_stt_short_korean

            _stt_norm = normalize_stt_short_korean(user_text)
            if _stt_norm != user_text:
                logger.info(
                    "stt_short_korean_normalized",
                    call_id=self._call_id or "",
                    before_preview=(user_text or "")[:80],
                    after_preview=_stt_norm[:80],
                    note="짧은 한국어 STT 보정 (요 잘림·점이요 등)",
                )
                user_text = _stt_norm
        except Exception as e:
            logger.debug("stt_short_korean_normalize_skip", call_id=self._call_id or "", error=str(e))
        
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
                _announce_ctx = (
                    (contact.get("transfer_label") or contact.get("department") or "")
                    .strip()
                )
                _pn = (contact.get("phone_number") or "").strip()
                _phone_for_prompt = _pn
                if _pn.lower().startswith("fwd:"):
                    _phone_for_prompt = "착신 전환에 등록된 대상(내선 자동 선택)"
                logger.info(
                    "transfer_contact_found",
                    call_id=self._call_id or "",
                    announce_ctx_preview=_announce_ctx[:40] if _announce_ctx else "",
                    phone_meta_preview=_pn[:24] if _pn else "",
                )

                # 호 전환 안내 멘트 생성
                from ..intents import (
                    build_transfer_announcement_prompt,
                    choose_transfer_announcement,
                    default_transfer_announcement,
                )
                prompt = build_transfer_announcement_prompt(
                    department=_announce_ctx,
                    phone_number=_phone_for_prompt,
                )

                try:
                    _raw_announcement = await self._llm.generate_simple(prompt, max_tokens=150)
                    announcement = choose_transfer_announcement(
                        _raw_announcement, _announce_ctx
                    )
                    _raw_s = (_raw_announcement or "").strip()
                    if _raw_s and _raw_s != announcement:
                        logger.info(
                            "transfer_announcement_llm_coerced",
                            call_id=self._call_id or "",
                            raw_preview=_raw_s[:120],
                            chosen=announcement,
                            note="LLM 출력이 짧거나 연결·대기 안내 없음 → 템플릿 폴백",
                        )
                except Exception as e:
                    logger.warning("transfer_announcement_generation_failed", error=str(e))
                    announcement = default_transfer_announcement(_announce_ctx)
                
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
                    department=_announce_ctx or contact.get("department"),
                    text=announcement,
                )
                # WebSocket: 호 전환 이벤트 발송 (실제 구현)
                if self._call_id:
                    try:
                        from src.websocket_events import emit_transfer_initiated
                        await emit_transfer_initiated(
                            call_id=self._call_id,
                            target_number=contact['phone_number'],
                            department=_announce_ctx or contact.get("department"),
                        )
                    except Exception as e:
                        logger.warning("transfer_event_emit_failed", error=str(e))
                
                # Call Manager에 호 전환 요청 (TransferManager 활용)
                try:
                    from src.call_transfer import initiate_call_transfer
                    transfer_success = await initiate_call_transfer(
                        call_id=self._call_id or "",
                        target_number=contact['phone_number'],
                        department=_announce_ctx or None,
                        phone_display=_announce_ctx or contact.get("phone_number"),
                        user_request_text=user_text
                    )
                    
                    if transfer_success:
                        logger.info("call_transfer_initiated_successfully",
                                   call_id=self._call_id or "",
                                   target=contact['phone_number'],
                                   department=_announce_ctx or contact.get("department"))
                        log_call_data(
                            self._call_id or "",
                            "call_event",
                            "call_transfer_initiated",
                            department=_announce_ctx or contact.get("department"),
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
                           note="연락처를 찾지 못함 → 착신 규칙 폴백 또는 일반 안내")
                log_call_data(
                    self._call_id or "",
                    "call_event",
                    "transfer_contact_not_found",
                    query=user_text,
                )
                # 지식 연락처 없음 → 착신 규칙(call-control)으로 전환 대상 시도
                try:
                    from src.call_control.escalation_transfer import (
                        build_escalation_sip_context,
                        resolve_escalation_transfer_extension,
                    )
                    from src.call_transfer import initiate_call_transfer

                    reg, busy = build_escalation_sip_context()
                    ext, cc_reason = resolve_escalation_transfer_extension(
                        (self._owner or "").strip(),
                        (getattr(self, "_caller_id", None) or "").strip() or None,
                        registered_extensions=reg,
                        is_extension_busy=busy,
                    )
                    if ext:
                        logger.info(
                            "transfer_call_control_fallback",
                            call_id=self._call_id or "",
                            extension=ext,
                            reason=cc_reason,
                        )
                        announcement = (
                            "잠시만요. 담당 상담원에게 연결해 드리겠습니다. 잠시 기다려 주세요."
                        )
                        await self.push_frame(LLMFullResponseStartFrame())
                        await self.push_frame(TextFrame(text=announcement))
                        await self.push_frame(LLMFullResponseEndFrame())
                        self._pipeline_tx_callee(self._call_id or "", announcement)
                        ok = await initiate_call_transfer(
                            call_id=self._call_id or "",
                            target_number=ext,
                            department="착신 규칙",
                            phone_display=ext,
                            user_request_text=user_text,
                        )
                        if ok:
                            log_call_data(
                                self._call_id or "",
                                "call_event",
                                "call_transfer_initiated",
                                target=ext,
                                success=True,
                                source="call_control",
                            )
                            return
                except Exception as e:
                    logger.warning("transfer_call_control_fallback_failed", error=str(e))

                # 연락처·착신 규칙 모두 실패 시 일반 응답
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
        
        # ── LLM 대기 안내 멘트: LLM 질의 시작 직전에 즉시 발화 ──
        # - 아웃바운드: 어색하므로 스킵
        # - 복수 LLM 호출(booking_agent 내부 tool loop 등) 시 중복 발화 방지:
        #   인스턴스 레벨 _waiting_phrase_idx / _waiting_phrase_active 로 1턴에 1회만 발화
        _is_outbound_call = bool(self._outbound_purpose or self._outbound_questions)
        notify_task = None
        done = asyncio.Event()

        async def send_waiting_phrase_now():
            """LLM 질의 시작과 동시에 KB 대기 안내 멘트를 즉시 발화.

            복수 호출 시에도 해당 턴(done 이벤트 기준)에서 1회만 발화한다.
            멘트가 여러 개면 호출 순서대로 순환하여 다음 번 멘트를 사용한다.
            """
            _DEFAULT_WAITING_PHRASES = ["잠시만 기다려 주세요.", "정보를 확인하고 있습니다."]

            try:
                # KB에서 waiting_phrase 카테고리 문서를 직접 조회
                # 1순위: 파이프라인 rag_engine (이미 초기화된 인스턴스 재사용)
                # 2순위: VectorDB 직접 조회
                # fallback: 기본 멘트
                phrases: list = []
                owner = self._owner or ""
                try:
                    rag_engine = getattr(self, "_rag_engine", None)
                    if rag_engine is not None:
                        def _query_rag():
                            results = rag_engine.search(
                                "대기 안내",
                                owner_filter=owner,
                                n_results=10,
                                category_filter="waiting_phrase",
                            )
                            return [r["content"] for r in results if r.get("content", "").strip()]
                        phrases = await asyncio.get_event_loop().run_in_executor(None, _query_rag)
                        logger.debug("waiting_phrase_rag_engine_hit",
                                     call_id=self._call_id or "",
                                     count=len(phrases))
                    if not phrases:
                        def _query_vectordb():
                            from src.ai_voicebot.knowledge.vector_db import VectorDB
                            vdb = VectorDB(owner=owner)
                            results = vdb.search(
                                query_embedding=None,
                                query_text="대기 안내",
                                n_results=10,
                                where={"category": "waiting_phrase"},
                            )
                            return [r.get("text", "").strip() for r in results if r.get("text", "").strip()]
                        phrases = await asyncio.get_event_loop().run_in_executor(None, _query_vectordb)
                        logger.debug("waiting_phrase_vectordb_hit",
                                     call_id=self._call_id or "",
                                     count=len(phrases))
                except Exception as e:
                    logger.debug("waiting_phrase_kb_load_failed",
                                 call_id=self._call_id or "", error=str(e))

                if not phrases:
                    phrases = _DEFAULT_WAITING_PHRASES
                    logger.debug("waiting_phrase_using_default",
                                 call_id=self._call_id or "")

                if not phrases:
                    return

                # 이번 턴에 발화할 멘트 인덱스 (순환)
                idx = getattr(self, "_waiting_phrase_idx", 0) % len(phrases)
                phrase = phrases[idx].strip()
                self._waiting_phrase_idx = (idx + 1) % len(phrases)

                if not phrase:
                    return

                logger.info(
                    "llm_waiting_phrase_sending",
                    call_id=self._call_id or "",
                    phrase_idx=idx,
                    phrase_preview=phrase[:30],
                    note="LLM 질의 시작 — 대기 안내 멘트 즉시 발화",
                )

                event = asyncio.Event()
                self._tts_sync_context["on_tts_complete"] = event

                await self.push_frame(LLMFullResponseStartFrame())
                await self.push_frame(TextFrame(text=phrase))
                await self.push_frame(LLMFullResponseEndFrame())

                # TTS 완료 대기 (완료 후 LLM 응답 TTS와의 겹침 방지)
                estimated_sec = len(phrase) / 5.5
                wait_timeout = max(estimated_sec * 3.5, 8.0)
                try:
                    await asyncio.wait_for(event.wait(), timeout=wait_timeout)
                    logger.info("llm_waiting_phrase_tts_ok",
                                call_id=self._call_id or "",
                                note="대기 안내 TTS 완료 확인됨")
                except asyncio.TimeoutError:
                    logger.warning("llm_waiting_phrase_tts_timeout",
                                   call_id=self._call_id or "",
                                   timeout=wait_timeout,
                                   note="대기 안내 TTS 완료 이벤트 타임아웃")

                self._pipeline_tx_callee(self._call_id or "", phrase)

            except asyncio.CancelledError:
                pass
            finally:
                self._waiting_phrase_active = False

        # TTS RTP 전송 중 여부 확인: 이미 다른 응답이 재생 중이면 대기 안내 멘트 불필요
        # _tts_active: LLMFullResponseEndFrame 이전까지 True (TTS 프레임 처리 중)
        # _tts_pending_pcm_bytes: EndFrame 시 0 초기화되지만 PCM 큐에 잔량이 남을 수 있음
        # _rtp_worker_ref._pipecat_pcm_queue: RTP 송신 스레드가 소비하는 실제 PCM 큐
        _tts_ctx = self._tts_sync_context or {}
        _tts_currently_active = bool(_tts_ctx.get("_tts_active", False))
        _tts_pending_bytes = int(_tts_ctx.get("_tts_pending_pcm_bytes", 0) or 0)
        # PCM 큐 잔량도 확인 (EndFrame 이후 아직 RTP로 나가지 않은 오디오)
        _pcm_queue_size = 0
        try:
            _rtp_worker = _tts_ctx.get("_rtp_worker_ref")
            if _rtp_worker is not None:
                _pcm_q = getattr(_rtp_worker, "_pipecat_pcm_queue", None)
                if _pcm_q is not None:
                    _pcm_queue_size = _pcm_q.qsize()
        except Exception:
            pass
        _tts_rtp_busy = _tts_currently_active or _tts_pending_bytes > 0 or _pcm_queue_size > 3

        if _is_outbound_call:
            logger.info("llm_waiting_phrase_skip_outbound",
                        call_id=self._call_id or "",
                        note="아웃바운드 모드 — 대기 안내 멘트 스킵")
            notify_task = None
        elif getattr(self, "_waiting_phrase_active", False):
            # 이미 이번 턴에 대기 멘트가 발화 중(또는 완료) → 중복 방지
            logger.info("llm_waiting_phrase_skip_duplicate",
                        call_id=self._call_id or "",
                        note="이번 턴 대기 멘트 이미 발화됨 — 중복 스킵")
            notify_task = None
        elif _tts_rtp_busy:
            # TTS RTP가 이미 전송 중 — 고객이 이미 다른 응답을 듣는 중이므로 대기 안내 불필요
            logger.info("llm_waiting_phrase_skip_tts_busy",
                        call_id=self._call_id or "",
                        tts_active=_tts_currently_active,
                        tts_pending_bytes=_tts_pending_bytes,
                        pcm_queue_size=_pcm_queue_size,
                        note="TTS RTP 전송 중 — 대기 안내 멘트 스킵 (중복 재생 방지)")
            notify_task = None
        else:
            self._waiting_phrase_active = True
            notify_task = asyncio.create_task(send_waiting_phrase_now())
        
        result: Optional[Dict[str, Any]] = None
        agent_elapsed = 0.0
        mark_llm_start(self._tts_sync_context)
        try:
            agent_start = time.time()
            
            # 💡 TODO: LangGraph Agent 내부 최적화 필요 (외부 패키지)
            # - classify_intent + rewrite_query 병렬 실행으로 시간 단축
            # - 현재: classify_intent(3.5s) + rewrite_query(5.2s) = 8.7초 순차
            # - 개선: asyncio.gather()로 병렬 실행 → max(3.5, 5.2) = 5.2초
            # - 예상 효과: -3.5초 단축 (전체 LLM 처리 14초 → 10.5초)
            
            # 아웃바운드 컨텍스트: purpose/questions를 LangGraph state에 주입
            # _hangup_callback은 직렬화 불가 객체 → call_context ContextVar로 전달 (agent.py에서 처리)
            outbound_extra: dict = {}
            if self._outbound_purpose or self._outbound_questions:
                outbound_extra = {
                    "outbound_purpose": self._outbound_purpose,
                    "outbound_questions": list(self._outbound_questions),
                    "outbound_answers": dict(self._outbound_answers),
                    "outbound_mission_done": self._outbound_mission_done,
                    "_hangup_callback": self._hangup_callback,  # agent.py에서 call_context로 이동 처리
                }

            # 발신자 전화번호 — rag_processor의 _caller_id를 LangGraph _caller_number로 주입
            caller_number_for_agent = getattr(self, "_caller_id", None) or ""

            if caller_context:
                try:
                    result = await self._agent.process_utterance(
                        user_text,
                        call_id=self._call_id or "",
                        caller_context=caller_context,
                        caller_number=caller_number_for_agent,
                        user_query_raw=stt_query_raw,
                        **outbound_extra,
                    )
                except TypeError:
                    result = await self._agent.process_utterance(
                        user_text, call_id=self._call_id or "",
                        caller_number=caller_number_for_agent,
                        user_query_raw=stt_query_raw,
                        **outbound_extra,
                    )
            else:
                result = await self._agent.process_utterance(
                    user_text, call_id=self._call_id or "",
                    caller_number=caller_number_for_agent,
                    user_query_raw=stt_query_raw,
                    **outbound_extra,
                )
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

        # ── Cancellation checkpoint: LLM 완료 후 TTS push 직전 ──
        # Supersede cancel()이 LLM awaitable 완료 직후에 inject된 경우,
        # 이미 완료된 LLM 응답이 TTS 파이프라인으로 흘러들어가는 것을 방지한다.
        # (cancel()은 await 경계에서만 효력 → LLM 완료 후 이 sleep(0)이 첫 번째 체크포인트)
        try:
            await asyncio.sleep(0)
        except asyncio.CancelledError:
            logger.info(
                "langgraph_agent_tts_push_cancelled",
                call_id=self._call_id or "",
                user_text_preview=(user_text or ""),
                note="[Supersede checkpoint] LLM 완료 후 TTS push 직전에 취소됨 → 병합 문장으로 재처리",
            )
            raise

        try:
            response = result.get("response", "")
            confidence = result.get("confidence", 0.0)
            intent = result.get("intent", "unknown")
            cache_hit = result.get("rag_cache_hit", False)
            needs_human = result.get("needs_human", False)
            business_state = result.get("business_state", "")
            chunks = result.get("response_chunks", [])
            _gen_elapsed = result.get("llm_gen_elapsed_sec")
            _first_in_gen = result.get("llm_first_sentence_elapsed_sec")
            if _first_in_gen is not None:
                try:
                    _gen_f = float(_gen_elapsed) if _gen_elapsed is not None else float(agent_elapsed)
                    _overhead = max(0.0, float(agent_elapsed) - _gen_f)
                    apply_llm_first_sentence_timing(
                        self._tts_sync_context,
                        offset_from_llm_start_sec=_overhead + float(_first_in_gen),
                        sentence_preview=result.get("llm_first_sentence_preview") or "",
                        source=result.get("llm_first_sentence_source") or "unknown",
                        elapsed_within_generate_response_sec=float(_first_in_gen),
                    )
                except (TypeError, ValueError):
                    pass
            elif (response or "").strip():
                # 캐시·템플릿 등 generate_response 미경유 — 첫 문장 길이 비율로 추정
                _parts = re.split(r"(?<=[.?!])\s+", (response or "").strip())
                _first = (_parts[0] if _parts else (response or "")).strip()
                if _first:
                    _ratio = len(_first) / max(len(response or ""), 1)
                    apply_llm_first_sentence_timing(
                        self._tts_sync_context,
                        offset_from_llm_start_sec=float(agent_elapsed) * _ratio,
                        sentence_preview=_first[:120],
                        source="shortcut_char_ratio_estimate",
                        elapsed_within_generate_response_sec=None,
                    )
            _tts_mode_planned = (
                "chunked_after_llm_complete"
                if chunks and len(chunks) > 1
                else "batch_after_llm_complete"
            )
            mark_llm_complete(
                self._tts_sync_context,
                agent_elapsed_sec=agent_elapsed,
                response_len=len(response or ""),
                chunk_count=len(chunks or []),
                tts_push_mode=_tts_mode_planned,
                llm_first_sentence_elapsed_sec=_first_in_gen,
                llm_first_sentence_source=result.get("llm_first_sentence_source"),
            )

            # ── 아웃바운드: LLM이 추출한 답변을 _outbound_answers에 직접 적용 ──
            # generate_response_node가 JSON으로 반환한 answered 목록을 읽어
            # fuzzy 매핑 후 _outbound_answers에 저장한다.
            # (별도 LLM 재확인 호출 없이 단일 LLM 호출로 답변 수집 완료)
            _outbound_is_answer: bool = result.get("outbound_is_answer", True)
            if self._outbound_questions and not self._outbound_mission_done:
                _answered_from_llm: list = result.get("outbound_answered") or []
                _unanswered_now = [
                    q for q in self._outbound_questions if q not in self._outbound_answers
                ]
                if _answered_from_llm:
                    for item in _answered_from_llm:
                        q_raw = (item.get("question") or "").strip()
                        a = (item.get("answer") or "").strip()
                        if not a or not _unanswered_now:
                            continue
                        # 정확 매핑 우선
                        target_q = None
                        if q_raw in _unanswered_now:
                            target_q = q_raw
                        elif len(_unanswered_now) == 1:
                            # 미답변이 1개면 LLM question 키 불일치와 무관하게 매핑
                            target_q = _unanswered_now[0]
                            logger.info(
                                "outbound_llm_answer_fuzzy_single",
                                call_id=self._call_id or "",
                                llm_q=q_raw[:40],
                                mapped_to=target_q[:40],
                            )
                        else:
                            # 부분 문자열 매칭
                            for uq in _unanswered_now:
                                if q_raw in uq or uq in q_raw or (len(q_raw) >= 8 and q_raw[:20] in uq):
                                    target_q = uq
                                    break
                        if target_q:
                            self._outbound_answers[target_q] = a
                            _unanswered_now = [
                                q for q in self._outbound_questions if q not in self._outbound_answers
                            ]
                            logger.info(
                                "outbound_llm_answer_applied",
                                call_id=self._call_id or "",
                                question=target_q[:50],
                                answer=a[:50],
                                remaining=len(_unanswered_now),
                            )

                # ── fallback: answered가 비었으나 LLM이 is_answer=true로 판단한 경우 ──
                # 미답변 질문이 1개이면 user_text를 직접 답변으로 등록한다.
                # (LLM이 answered 필드를 빠뜨리는 경우 대비)
                _unanswered_now = [
                    q for q in self._outbound_questions if q not in self._outbound_answers
                ]
                if not _answered_from_llm and _outbound_is_answer and _unanswered_now and user_text:
                    if len(_unanswered_now) == 1:
                        fallback_q = _unanswered_now[0]
                        fallback_a = (user_text or "").strip()
                        self._outbound_answers[fallback_q] = fallback_a
                        logger.info(
                            "outbound_llm_answer_fallback_applied",
                            call_id=self._call_id or "",
                            question=fallback_q[:50],
                            answer=fallback_a[:50],
                            note="LLM answered 빈 배열 + is_answer=true + 미답변 1개 → user_text 직접 등록",
                        )
                    else:
                        logger.warning(
                            "outbound_llm_answer_fallback_skipped",
                            call_id=self._call_id or "",
                            unanswered_count=len(_unanswered_now),
                            note="is_answer=true이나 answered 빈 배열 + 미답변 복수 → fallback 불가",
                        )
                elif not _answered_from_llm and not _outbound_is_answer:
                    logger.info(
                        "outbound_llm_non_answer",
                        call_id=self._call_id or "",
                        user_preview=(user_text or "")[:60],
                        note="LLM 판단: 이번 발화는 미션 질문의 유효한 답변이 아님",
                    )

            # 디버깅용: LangGraph 원본 응답 (farewell 템플릿 치환 전)
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
                       agent_elapsed=f"{agent_elapsed:.3f}s",
                       note="LangGraph 원본 응답 (템플릿 치환 전)")
            
            # HITL: 운영자 개입 필요 시 HITLManager로 위임 + 프론트엔드에 hitl_requested 발송 (Phase 3)
            if needs_human:
                hitl_reason = result.get("hitl_reason", "")
                needs_follow_up = result.get("needs_follow_up", False)
                needs_transfer = result.get("needs_transfer", False)
                transfer_extension = result.get("transfer_extension") or None
                if self._hitl_manager:
                    hitl_message = await self._hitl_manager.handle_hitl_result(
                        call_id=self._call_id or "",
                        needs_human=True,
                        hitl_reason=hitl_reason,
                        intent=intent,
                        confidence=confidence,
                        user_text=user_text,
                        needs_transfer=needs_transfer,
                        transfer_extension=transfer_extension,
                    )
                    if hitl_message:
                        # transfer 모드 또는 모르는 내용(needs_follow_up): 고객 TTS를 고정 멘트로 통일
                        if needs_transfer or needs_follow_up:
                            response = hitl_message
                        elif not (response or "").strip():
                            response = hitl_message
                else:
                    logger.warning("hitl_alert_from_agent",
                                 reason=hitl_reason,
                                 needs_transfer=needs_transfer)
                    if not response:
                        if needs_transfer:
                            response = "담당 상담원에게 연결해 드리겠습니다. 잠시만 기다려 주세요."
                        else:
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

                # HITL → 통화 종료 시 KB 카테고리(intent 매칭)용 FIFO (emit 실패와 무관하게 동일 규칙)
                try:
                    from src.services.hitl import get_hitl_service

                    _hitl_alert = (
                        "transfer"
                        if intent == "transfer"
                        else ("complaint" if intent == "complaint" else "low_confidence")
                    )
                    # rewritten_query: LLM이 정제한 쿼리 — STT 오인식 보정 목적으로 KB Q 텍스트에 우선 사용
                    _rq = (result.get("rewritten_query") or "").strip()
                    get_hitl_service().note_hitl_request(
                        self._call_id or "",
                        user_text,
                        intent=intent,
                        alert_type=_hitl_alert,
                        rewritten_query=_rq,
                    )
                    logger.info(
                        "note_hitl_request_rewritten_query",
                        call_id=self._call_id or "",
                        has_rewritten_query=bool(_rq),
                        rewritten_query_preview=_rq[:60] if _rq else "",
                        note="STT 오인식 보정: rewritten_query 있으면 KB Q 텍스트로 우선 사용",
                    )
                except Exception as e:
                    logger.warning(
                        "note_hitl_request_failed",
                        call_id=self._call_id,
                        error=str(e),
                    )

                # 통화 이력: HITL 에스컬레이션만( needs_follow_up 아님 ) → AI 한계 목록에 별도 적재
                try:
                    _nfu = bool(result.get("needs_follow_up", False))
                    _fq = (result.get("follow_up_user_query", "") or "").strip()
                    if not (_nfu and _fq):
                        from src.common.call_insights_buffer import record_ai_limitation

                        record_ai_limitation(
                            self._call_id or "",
                            user_text,
                            (response or "").strip(),
                            kind="hitl_escalation",
                            reason=(hitl_reason or "")[:300],
                        )
                except Exception as e:
                    logger.debug(
                        "record_hitl_escalation_insight_failed",
                        call_id=self._call_id,
                        error=str(e),
                    )

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
                try:
                    from src.common.call_insights_buffer import record_ai_limitation

                    record_ai_limitation(
                        self._call_id or "",
                        follow_up_query,
                        response,
                        kind="needs_follow_up",
                        reason="needs_follow_up",
                    )
                except Exception as e:
                    logger.debug(
                        "record_needs_follow_up_insight_failed",
                        call_id=self._call_id,
                        error=str(e),
                    )

            # LLM 구조화 출력 조각(```json, tool_ 등)이 그대로 TTS로 나가지 않도록 정화
            if (response or "").strip():
                _san, _tts_frag_reason = sanitize_voice_assistant_text(
                    response, intent=str(intent or "")
                )
                if _tts_frag_reason:
                    logger.warning(
                        "tts_output_sanitized_llm_fragment",
                        call_id=self._call_id or "",
                        intent=intent,
                        reason=_tts_frag_reason,
                        response_len_before=len(response or ""),
                        original_preview=(response or "")[:160],
                    )
                    response = _san
                    chunks = []

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
                _delivery = (
                    "chunked_after_llm_complete"
                    if chunks and len(chunks) > 1
                    else "batch_after_llm_complete"
                )
                mark_tts_text_pushed(
                    self._tts_sync_context,
                    text_len=len(response),
                    chunk_count=len(chunks) if chunks else 1,
                    delivery_mode=_delivery,
                )
                
                # 📌 실제 TTS로 나가는 최종 텍스트 로깅 (farewell 템플릿, HITL 멘트 등 모든 override 반영 후)
                _llm_rag = result.get("llm_rag_applied") or []
                logger.info("llm_exchange_full",
                           call=True,
                           category="llm",
                           progress="llm",
                           user_text_full=user_text,
                           response_full=response,
                           response_len=len(response),
                           note="실제 TTS 텍스트 (모든 override 반영 후)")
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
                
                log_call_data(
                    self._call_id or "",
                    "tts",
                    "tts_text_pushed",
                    text=response,
                    text_len=len(response),
                    intent=intent,
                )
                self._pipeline_tx_callee(self._call_id or "", response)
                # WebSocket: TTS 시작 이벤트 (실제 발화 텍스트 반영)
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
                
                # ✅ TTS 완료 이벤트를 EndFrame 전에 설정 (Notifier가 event.set() 가능하도록)
                event = asyncio.Event()
                self._tts_sync_context["on_tts_complete"] = event
                
                await self.push_frame(LLMFullResponseStartFrame())
                
                # 📌 RAG → TTS 전달 직전 로깅 (분할 여부 추적)
                logger.info("rag_textframe_pushed",
                           call=True,
                           call_id=self._call_id or "",
                           progress="tts",
                           category="tts",
                           text_len=len(response),
                           text_preview=response[:120] if response else "",
                           note="RAG → 파이프라인 TextFrame 전송 (단일 프레임 확인용)")
                
                # 스트리밍 TTS: response_chunks가 있으면 문장 단위로 TTS 전송 (체감 지연 감소)
                # 없으면 전체 텍스트를 한 번에 전송 (기존 동작)
                if chunks and len(chunks) > 1:
                    chunks = dedupe_streaming_tts_chunks(chunks)
                    logger.info("rag_streaming_tts_chunks",
                               call_id=self._call_id or "",
                               chunk_count=len(chunks),
                               note="스트리밍 LLM → 문장 단위 TTS 전달(선행 프리픽스 턴당 1회 dedupe 적용)")
                    for chunk_text in chunks:
                        if chunk_text.strip():
                            await self.push_frame(TextFrame(text=chunk_text.strip()))
                else:
                    await self.push_frame(TextFrame(text=response))
                await self.push_frame(LLMFullResponseEndFrame())
                
                # ✅ TTS 완료 대기 (오디오 생성 확인)
                estimated_tts_sec = len(response) / self._TTS_CHARS_PER_SEC
                tts_wait_timeout = min(
                    self._TTS_COMPLETE_WAIT_TIMEOUT_SEC,
                    max(estimated_tts_sec * 2 + 15.0, 20.0),
                )
                logger.info(
                    "llm_response_waiting_tts_complete",
                    call=True,
                    category="tts",
                    progress="tts",
                    wait_timeout_sec=round(tts_wait_timeout, 1),
                    estimated_tts_sec=round(estimated_tts_sec, 1),
                    note="LLM 응답 TTS 완료 대기 (오디오 생성 확인)",
                )
                try:
                    await asyncio.wait_for(event.wait(), timeout=tts_wait_timeout)
                    logger.info(
                        "llm_response_tts_complete_ok",
                        call_id=self._call_id or "",
                        note="LLM 응답 TTS 완료 확인됨",
                    )
                except asyncio.TimeoutError:
                    logger.warning(
                        "llm_response_tts_timeout",
                        call_id=self._call_id or "",
                        timeout=tts_wait_timeout,
                        note="LLM 응답 TTS 완료 이벤트 타임아웃 (오디오 미생성 가능)",
                    )
                
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

                # 아웃바운드 미션 완료 여부 체크
                # LLM이 이미 답변을 추출해 _outbound_answers에 적용했으므로
                # _check_outbound_mission_complete는 answers 완료 여부만 확인한다 (LLM 재호출 없음)
                if self._outbound_purpose or self._outbound_questions:
                    asyncio.create_task(
                        self._check_outbound_mission_complete(response),
                        name=f"outbound_mission_check_{self._call_id}",
                    )
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

    async def _generate_outbound_opening(self, purpose: str, first_question: str) -> str:
        """아웃바운드 통화 오프닝 문장을 LLM으로 생성한다.

        "통화 목적을 위해 전화드렸습니다. 첫 질문"을 상황에 맞게 자연스럽게 다듬어 반환한다.
        LLM 호출 실패 시 단순 조합 문자열로 폴백한다.
        """
        if not purpose:
            return first_question or ""

        if first_question:
            prompt = (
                "당신은 아웃바운드 AI 전화 봇입니다.\n"
                "아래 [통화 목적]과 [첫 번째 질문]을 자연스럽게 연결하는 2문장을 작성하세요.\n\n"
                "규칙:\n"
                "1. 첫 문장: '[통화 목적]을 위해 전화드렸습니다.' 또는 '[통화 목적]과 관련하여 전화드렸습니다.' 형태로 시작.\n"
                "2. 두 번째 문장: [첫 번째 질문]을 그대로 또는 자연스럽게 변형해서 반드시 포함시키세요.\n"
                "3. 반드시 2문장으로 작성하고, [첫 번째 질문]이 출력에 포함되어야 합니다.\n"
                "4. 따옴표나 부가 설명 없이 말하는 문장 그대로만 출력.\n\n"
                f"[통화 목적]: {purpose}\n"
                f"[첫 번째 질문]: {first_question}\n\n"
                "출력 예시 형태: '(목적) 전화드렸습니다. (질문)?'\n\n"
                "출력:"
            )
        else:
            prompt = (
                "당신은 아웃바운드 AI 전화 봇입니다.\n"
                "아래 [통화 목적]을 고객에게 자연스럽게 안내하는 1~2문장을 작성하세요.\n\n"
                "규칙:\n"
                "1. '[통화 목적]을 위해 / [통화 목적]과 관련하여 전화드렸습니다.' 형태로 시작.\n"
                "2. 1~2문장 이내, 간결하게.\n"
                "3. 따옴표나 부가 설명 없이 말하는 문장 그대로만 출력.\n\n"
                f"[통화 목적]: {purpose}\n\n"
                "출력:"
            )

        try:
            generated = ""
            if hasattr(self._llm, "generate_simple"):
                # 한국어 1토큰 ≈ 1~2자 → 3문장(최대 120자) 기준 충분한 토큰 확보
                generated = await self._llm.generate_simple(
                    prompt, max_tokens=300, timeout_seconds=8.0
                )
            generated = (generated or "").strip()

            # 완성 문장 방어 1: 마침표/물음표/느낌표 등으로 끝나지 않으면 폴백
            _sentence_ends = (".", "?", "!", "요", "까", "다", "죠", "네")
            _is_complete = generated.endswith(_sentence_ends) if generated else False

            # 완성 문장 방어 2: 한국어 질문은 물음표 없이 명령형(주세요/부탁)으로 끝나는 경우가 많음
            _fq = (first_question or "").strip()
            _gen_compact = generated.replace(" ", "") if generated else ""
            _fq_head = _fq.replace(" ", "")[:24] if _fq else ""
            _embeds_first_q = (
                bool(_fq_head) and len(_fq_head) >= 6 and _fq_head in _gen_compact
            ) if generated else False
            _has_question_mark = (
                ("?" in generated or "？" in generated) if generated else False
            )
            _has_command_cue = any(
                x in (generated or "")
                for x in ("주세요", "부탁", "평가해", "알려주", "말씀해")
            )
            _question_missing = bool(first_question) and not (
                _has_question_mark or _has_command_cue or _embeds_first_q
            )

            if generated and _is_complete and not _question_missing:
                logger.info(
                    "outbound_opening_llm_generated",
                    call_id=self._call_id or "",
                    purpose_preview=purpose[:60],
                    first_q_preview=first_question[:60] if first_question else "",
                    generated_preview=generated[:120],
                    note="LLM으로 아웃바운드 오프닝 문장 생성",
                )
                return generated
            elif generated and (not _is_complete or _question_missing):
                logger.warning(
                    "outbound_opening_llm_truncated",
                    call_id=self._call_id or "",
                    generated_preview=generated[:120],
                    is_complete=_is_complete,
                    question_missing=_question_missing,
                    note="LLM 응답이 잘렸거나 질문이 누락됨 → 폴백",
                )
        except Exception as e:
            logger.warning(
                "outbound_opening_llm_failed",
                call_id=self._call_id or "",
                error=str(e),
                note="LLM 오프닝 생성 실패 → 폴백",
            )

        # 폴백: 단순 조합 (LLM 실패·잘림 시)
        # 조사 선택: 목적이 받침으로 끝나면 "을", 그렇지 않으면 "를"
        _last_char = purpose[-1] if purpose else ""
        try:
            import unicodedata as _ud
            _decomposed = _ud.normalize("NFD", _last_char)
            _has_jongseong = len(_decomposed) == 3  # 초성+중성+종성
        except Exception:
            _has_jongseong = False
        _particle = "을" if _has_jongseong else "를"
        intro = f"{purpose}{_particle} 위해 전화드렸습니다."
        fallback = f"{intro} {first_question}".strip() if first_question else intro
        logger.info(
            "outbound_opening_fallback",
            call_id=self._call_id or "",
            fallback_preview=fallback[:120],
            note="LLM 오프닝 실패·잘림 → 폴백 문자열 사용",
        )
        return fallback

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
            if self._outbound_purpose:
                # ── 아웃바운드 모드 ──
                # Phase1: KB greeting_phase1 (인사)
                if self._agent_available:
                    greeting = await self._agent.generate_greeting()
                else:
                    greeting = await self._generate_greeting_legacy()
                p1 = (greeting or "").strip()

                # Phase2: LLM으로 "통화 목적 → 첫 질문"을 자연스러운 한 흐름으로 생성
                first_q = self._outbound_questions[0] if self._outbound_questions else ""
                p2 = await self._generate_outbound_opening(
                    purpose=self._outbound_purpose,
                    first_question=first_q,
                )

                logger.info(
                    "outbound_greeting_with_purpose",
                    call_id=self._call_id,
                    purpose_preview=self._outbound_purpose[:80],
                    first_question_preview=first_q[:80],
                    p2_preview=p2[:100],
                    note="아웃바운드 인사: KB p1 + LLM 생성 p2 (통화목적→질문)",
                )
            else:
                # ── 인바운드 모드 (기존 로직) ──
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
                # ✅ TTS 완료 이벤트를 EndFrame 전에 설정
                event = asyncio.Event()
                self._tts_sync_context["on_tts_complete"] = event
                
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
                await self._emit_greeting_to_dashboard(phase=2, text=p2)
                
                # ✅ Phase2 TTS 완료 대기
                estimated_phase2_sec = len(p2) / self._TTS_CHARS_PER_SEC
                phase2_wait_timeout = min(
                    self._TTS_COMPLETE_WAIT_TIMEOUT_SEC,
                    max(estimated_phase2_sec * 2 + 15.0, 20.0),
                )
                logger.info(
                    "greeting_phase2_waiting_tts_complete",
                    call=True,
                    category="tts",
                    progress="tts",
                    wait_timeout_sec=round(phase2_wait_timeout, 1),
                    note="Phase2 TTS 완료 대기",
                )
                try:
                    await asyncio.wait_for(event.wait(), timeout=phase2_wait_timeout)
                    logger.info(
                        "greeting_phase2_tts_complete_ok",
                        call_id=self._call_id or "",
                        note="Phase2 TTS 완료 확인됨",
                    )
                except asyncio.TimeoutError:
                    logger.warning(
                        "greeting_phase2_tts_timeout",
                        call_id=self._call_id or "",
                        timeout=phase2_wait_timeout,
                        note="Phase2 TTS 완료 이벤트 타임아웃 (오디오 미생성 가능)",
                    )
                
                self._greeting_phase2_done.set()
                logger.info(
                    "greeting_total_elapsed",
                    call_id=self._call_id or "",
                    elapsed=f"{time.time() - greeting_start:.3f}s",
                )
                return

            # Phase1 전송 (Phase2 유무와 무관하게 먼저 송출)
            # ✅ TTS 완료 이벤트를 EndFrame 전에 설정 (Notifier가 event.set() 가능하도록)
            event = asyncio.Event()
            self._tts_sync_context["on_tts_complete"] = event
            
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
            await self._emit_greeting_to_dashboard(phase=1, text=p1)

            # Phase1 TTS 완료 대기 (Phase2 유무와 무관)
            from src.ai_voicebot.pipecat.processors.tts_complete_notifier import (
                KEY_LAST_TTS_DURATION_SEC,
            )
            estimated_phase1_sec = len(p1) / self._TTS_CHARS_PER_SEC
            wait_timeout = min(
                self._TTS_COMPLETE_WAIT_TIMEOUT_SEC,
                max(estimated_phase1_sec * 2 + 15.0, 20.0),
            )
            
            if not p2:
                # Phase1만 있는 경우: TTS 완료 대기 후 종료
                logger.info(
                    "greeting_phase1_waiting_tts_complete",
                    call=True,
                    category="tts",
                    progress="tts",
                    wait_timeout_sec=round(wait_timeout, 1),
                    estimated_phase1_sec=round(estimated_phase1_sec, 1),
                    note="Phase1 TTS 완료 대기 (Phase2 없음)",
                )
                try:
                    await asyncio.wait_for(event.wait(), timeout=wait_timeout)
                    logger.info(
                        "greeting_phase1_tts_complete_ok",
                        call_id=self._call_id or "",
                        note="Phase1 TTS 완료 확인됨",
                    )
                except asyncio.TimeoutError:
                    logger.warning(
                        "greeting_phase1_tts_timeout",
                        call_id=self._call_id or "",
                        timeout=wait_timeout,
                        note="Phase1 TTS 완료 이벤트 타임아웃 (오디오 미생성 가능)",
                    )
                self._greeting_phase2_done.set()
                logger.info(
                    "greeting_total_elapsed",
                    call_id=self._call_id or "",
                    elapsed=f"{time.time() - greeting_start:.3f}s",
                )
                return

            # Phase1 + Phase2: Phase1 TTS 완료 후 Phase2
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
            await self._emit_greeting_to_dashboard(phase=2, text=p2)

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
        self._stt_last_nonempty_interim_monotonic = None
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

    async def send_end_call_summary_sms_async(self) -> None:
        """통화 종료 시 SIP MESSAGE(RCS) 요약 — LangGraph ``booking_context``·assistant 발화 반영."""
        caller = (self._caller_id or "").strip()
        if not caller:
            logger.debug("pipecat_end_call_sms_skip_no_caller", call_id=self._call_id or "")
            return
        if self._transcription_frame_count < 1:
            logger.debug(
                "pipecat_end_call_sms_skip_no_user_turns",
                call_id=self._call_id or "",
                transcription_count=self._transcription_frame_count,
            )
            return

        snippets: list[str] = []
        booking_ctx = None
        if self._agent_available and self._agent is not None:
            st = getattr(self._agent, "_state", None) or {}
            for m in st.get("messages") or []:
                if isinstance(m, dict) and m.get("role") == "assistant":
                    c = (m.get("content") or "").strip()
                    if c:
                        snippets.append(c)
            bc = st.get("booking_context")
            if isinstance(bc, dict):
                booking_ctx = bc

        if not snippets:
            logger.debug("pipecat_end_call_sms_skip_no_assistant", call_id=self._call_id or "")
            return

        try:
            from src.services.end_call_sms_service import send_end_call_summary_sms

            await send_end_call_summary_sms(
                call_id=self._call_id or "",
                caller=caller,
                owner=(self._owner or "").strip(),
                llm_client=self._llm,
                assistant_snippets=snippets,
                booking_context=booking_ctx,
            )
        except Exception as e:
            logger.warning(
                "pipecat_end_call_sms_failed",
                call_id=self._call_id or "",
                error=str(e),
                exc_info=True,
            )

    async def cleanup(self):
        """파이프라인 종료 시 실행 — dangling task 방지."""
        # _user_message_worker 취소
        task = self._user_message_worker_task
        if task and not task.done():
            task.cancel()
            try:
                await task
            except (asyncio.CancelledError, Exception):
                pass
        self._user_message_worker_task = None

        # 진행 중인 LLM 에이전트 턴 취소
        agent_task = self._agent_turn_task
        if agent_task and not agent_task.done():
            agent_task.cancel()
            try:
                await agent_task
            except (asyncio.CancelledError, Exception):
                pass
        self._agent_turn_task = None

        # STT TranscriptionFrame 무응답 워치독 취소
        watchdog_task = self._stt_transcript_watchdog_task
        if watchdog_task and not watchdog_task.done():
            watchdog_task.cancel()
            try:
                await watchdog_task
            except (asyncio.CancelledError, Exception):
                pass
        self._stt_transcript_watchdog_task = None

        # HITL 소비 큐에 종료 sentinel 전송 (Task-203 _consume 종료 유도)
        if self._hitl_response_queue:
            try:
                self._hitl_response_queue.put_nowait(None)
            except Exception:
                pass

        logger.info("rag_llm_processor_cleanup", call_id=self._call_id or "")

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

            if (response or "").strip():
                _san_l, _tts_legacy_reason = sanitize_voice_assistant_text(response, intent="")
                if _tts_legacy_reason:
                    logger.warning(
                        "tts_output_sanitized_llm_fragment",
                        call_id=self._call_id or "",
                        intent="legacy_llm",
                        reason=_tts_legacy_reason,
                        response_len_before=len(response or ""),
                        original_preview=(response or "")[:160],
                    )
                    response = _san_l

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
