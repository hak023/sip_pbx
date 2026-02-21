"""
RAG-enhanced LLM Processor for Pipecat Pipeline (Phase 2: LangGraph).

Phase 1: 단순 RAG + LLM
Phase 2: LangGraph ConversationAgent로 교체
  - 의도 분류, Semantic Cache, Query Rewriting, Adaptive RAG,
    Step-back Prompting, HITL Alert, Business State Tracking

STT TranscriptionFrame → LangGraph Agent → TextFrame(응답) → TTS
"""

import asyncio
from datetime import datetime
from typing import Any, Dict, Optional, List, Callable, Awaitable

import structlog

from pipecat.frames.frames import (
    EndFrame,
    Frame,
    LLMFullResponseEndFrame,
    LLMFullResponseStartFrame,
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
        tts_sync_context: Optional[Dict[str, Any]] = None,
        call_id: Optional[str] = None,  # 통화 ID (WebSocket 이벤트용)
        hitl_on_alert: Optional[Callable[..., Awaitable[None]]] = None,
        hitl_response_queue: Optional[asyncio.Queue] = None,
        **kwargs,
    ):
        super().__init__(**kwargs)
        self._llm = llm_client
        self._tts_sync_context = tts_sync_context or {}
        self._call_id = call_id  # 통화 ID 저장
        self._rag = rag_engine
        self._org_manager = org_manager
        self._system_prompt = system_prompt
        self._max_history_turns = max_history_turns
        self._owner = owner  # 착신번호 (테넌트 ID)
        self._hitl_response_queue = hitl_response_queue
        self._hitl_consumer_started = False

        # LangGraph ConversationAgent (Phase 2)
        self._agent = None
        self._agent_available = False
        self._greeting_sent = False

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
    
    async def _format_hitl_response_for_customer(self, raw_text: str) -> str:
        """HITL 담당자 답변을 LLM으로 고객용 한 문장으로 정리 (설계 2.2)."""
        if not raw_text or not getattr(self, "_llm", None):
            return raw_text
        try:
            if asyncio.iscoroutinefunction(self._llm.format_for_customer):
                return await self._llm.format_for_customer(raw_text)
            return self._llm.format_for_customer(raw_text)
        except Exception as e:
            logger.warning("hitl_format_for_customer_failed", error=str(e))
            return raw_text

    def _start_hitl_response_consumer(self):
        """운영자 응답 큐 소비 태스크 시작 (한 번만)"""
        if self._hitl_consumer_started or not self._hitl_response_queue:
            return
        self._hitl_consumer_started = True
        proc = self

        async def _consume():
            try:
                while True:
                    text = await proc._hitl_response_queue.get()
                    if not text:
                        continue
                    # 설계 2.2: 담당자 답변을 LLM으로 고객용 문장 정리 후 TTS
                    formatted = await proc._format_hitl_response_for_customer(text)
                    await proc.push_frame(TextFrame(text=formatted))
            except asyncio.CancelledError:
                pass
            except Exception as e:
                logger.error("hitl_response_consumer_error", error=str(e))

        asyncio.create_task(_consume())

    async def process_frame(self, frame: Frame, direction: FrameDirection):
        self._start_hitl_response_consumer()
        await super().process_frame(frame, direction)
        
        if isinstance(frame, TranscriptionFrame):
            user_text = frame.text.strip()
            if user_text:
                logger.info("rag_llm_user_input",
                           call=True,
                           category="stt",
                           progress="stt",
                           text=user_text[:100],
                           mode="langgraph" if self._agent_available else "legacy")
                
                # WebSocket: STT 이벤트 발송
                if self._call_id:
                    try:
                        from src.websocket import manager as ws_manager
                        import asyncio
                        asyncio.create_task(ws_manager.emit_stt_transcript(
                            call_id=self._call_id,
                            text=user_text,
                            is_final=True
                        ))
                    except Exception as e:
                        logger.debug("stt_event_failed", error=str(e))
                
                if self._agent_available:
                    await self._process_with_agent(user_text)
                else:
                    await self._generate_response_legacy(user_text)
        elif isinstance(frame, InterimTranscriptionFrame):
            # Interim STT (중간 결과)
            interim_text = frame.text.strip()
            if interim_text and self._call_id:
                try:
                    from src.websocket import manager as ws_manager
                    import asyncio
                    asyncio.create_task(ws_manager.emit_stt_transcript(
                        call_id=self._call_id,
                        text=interim_text,
                        is_final=False
                    ))
                except Exception as e:
                    logger.debug("interim_stt_event_failed", error=str(e))
            # Interim은 downstream으로 전달하지 않음
            return
        else:
            await self.push_frame(frame, direction)
    
    # =========================================================================
    # Phase 2: LangGraph Agent 경로
    # =========================================================================
    
    async def _process_with_agent(self, user_text: str):
        """LangGraph ConversationAgent를 통한 응답 생성"""
        import time
        pipeline_start = time.time()
        
        try:
            agent_start = time.time()
            result = await self._agent.process_utterance(user_text, call_id=self._call_id or "")
            agent_elapsed = time.time() - agent_start

            response = result.get("response", "")
            confidence = result.get("confidence", 0.0)
            intent = result.get("intent", "unknown")
            cache_hit = result.get("rag_cache_hit", False)
            needs_human = result.get("needs_human", False)
            business_state = result.get("business_state", "")
            chunks = result.get("response_chunks", [])

            # 디버깅용: LLM 질의/답변 전체 (call 키로 필터 가능)
            _max_full = 2000
            logger.info("llm_exchange_full",
                       call=True,
                       category="llm",
                       progress="llm",
                       user_text_full=user_text[:_max_full] if len(user_text) > _max_full else user_text,
                       response_full=response[:_max_full] if len(response) > _max_full else response,
                       response_len=len(response),
                       note="전체 질의/답변 로그")

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
                       response_preview=response[:150] + "..." if len(response) > 150 else response,
                       response_full=response[:_max_full] if len(response) > _max_full else response,
                       user_text_full=user_text[:_max_full] if len(user_text) > _max_full else user_text,
                       agent_elapsed=f"{agent_elapsed:.3f}s")
            
            # HITL: 운영자 개입 필요 시 HITLManager로 위임 (Phase 3)
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
            
            if response:
                # Streaming RAG: 청크 단위 전송
                tts_push_start = time.time()
                
                # WebSocket: TTS 시작 이벤트
                if self._call_id:
                    try:
                        from src.websocket import manager as ws_manager
                        import asyncio
                        asyncio.create_task(ws_manager.emit_tts_started(
                            call_id=self._call_id,
                            text=response
                        ))
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
                        asyncio.create_task(ws_manager.emit_tts_completed(
                            call_id=self._call_id
                        ))
                    except Exception as e:
                        logger.debug("tts_completed_event_failed", error=str(e))
                
                tts_push_elapsed = time.time() - tts_push_start
                
                total_elapsed = time.time() - pipeline_start
                _max_full = 2000
                logger.info("llm_response_sent",
                           call=True,
                           category="llm",
                           progress="llm",
                           user_text=user_text[:80],
                           user_text_full=user_text[:_max_full] if len(user_text) > _max_full else user_text,
                           response_preview=response[:150] + "..." if len(response) > 150 else response,
                           response_full=response[:_max_full] if len(response) > _max_full else response,
                           agent_elapsed=f"{agent_elapsed:.3f}s",
                           tts_push_elapsed=f"{tts_push_elapsed:.3f}s",
                           total_elapsed=f"{total_elapsed:.3f}s",
                           response_len=len(response))
            else:
                await self.push_frame(
                    TextFrame(text="죄송합니다. 답변을 생성하지 못했습니다. 다시 말씀해주시겠어요?")
                )
                
        except Exception as e:
            logger.error("langgraph_agent_process_error", call=True, category="llm", error=str(e), exc_info=True)
            await self.push_frame(
                TextFrame(text="죄송합니다. 오류가 발생했습니다.")
            )
    
    # Phase1↔Phase2 사이 예상 대기 시간을 계산하기 위한 상수
    # 한국어 TTS는 대략 초당 5~7글자 속도로 발화
    _TTS_CHARS_PER_SEC = 5.5
    _PHASE_GAP_BUFFER_SEC = 0.8  # Phase1 발화 완료 후 추가 여유 (자연스러운 호흡)
    _TTS_COMPLETE_WAIT_TIMEOUT_SEC = 60.0  # TTS 완료 이벤트 대기 최대 시간

    async def send_greeting(self):
        """AI 인사말 생성 및 전송 (2-Phase Greeting, 순차 재생)
        
        Phase 1: 고정 인사말 (템플릿 기반, TextFrame 1개로 전송)
          → "안녕하세요. 기상청 AI 통화 비서입니다. 무엇을 도와드릴까요?"
          → TTS는 aggregate_sentences=False로 한 덩어리 합성(문장 잘림 방지).
        Phase 2: 업무 안내 (capabilities 기반, Phase1 재생 완료 후 전송)
          → "저는 날씨 예보 조회, 기상 특보 안내, ... 등을 도와드릴 수 있습니다."
        
        Phase1 재생 시간: TTSCompleteNotifier가 오디오 프레임 길이를 누적해
        LLMFullResponseEndFrame 시 last_tts_duration_sec에 넣고 event를 set.
        그 값으로 추가 대기(재생 시간 + 호흡 여유) 후 Phase2 전송.
        Notifier 미수신 시 예상 길이(글자수/5.5초)로 fallback.
        """
        if self._greeting_sent:
            return
        
        self._greeting_sent = True
        
        import time
        greeting_start = time.time()
        
        try:
            # Phase 1: 인사말
            if self._agent_available:
                greeting = await self._agent.generate_greeting()
            else:
                greeting = await self._generate_greeting_legacy()
            
            if greeting:
                logger.info("rag_llm_greeting_phase1",
                           call=True,
                           category="tts",
                           text=greeting[:120],
                           mode="langgraph" if self._agent_available else "legacy")
            
            # Phase 2: 업무 안내 (capability guide)
            capability_guide = None
            if self._agent_available:
                try:
                    capability_guide = await self._agent.generate_capability_guide()
                except Exception as e:
                    logger.warning("capability_guide_generation_error", error=str(e))
            else:
                capability_guide = self._generate_capability_guide_legacy()
            
            if capability_guide:
                logger.info("rag_llm_greeting_phase2",
                           call=True,
                           category="tts",
                           text=capability_guide[:120])
            
            # Phase2 동기화: TTS 완료 이벤트를 Phase1 push 전에 등록 (레이스 방지)
            event = None
            if capability_guide:
                event = asyncio.Event()
                self._tts_sync_context["on_tts_complete"] = event
            
            # Phase1 전송
            phase1_text = greeting or "안녕하세요. 무엇을 도와드릴까요?"
            
            await self.push_frame(LLMFullResponseStartFrame())
            await self.push_frame(TextFrame(text=phase1_text))
            await self.push_frame(LLMFullResponseEndFrame())
            
            logger.info("greeting_phase1_sent",
                       call=True,
                       category="tts",
                       progress="tts",
                       text=phase1_text[:100],
                       elapsed=f"{time.time() - greeting_start:.3f}s")
            
            # Phase2: Phase1 TTS 재생 완료 시점까지 대기 후 전송 (동기화)
            # - TTSCompleteNotifier가 Phase1 오디오 길이를 누적해 EndFrame 시 last_tts_duration_sec에 넣음.
            # - event.wait() 해제 시 해당 값으로 추가 대기(재생 시간 + 호흡 여유) 후 Phase2 전송.
            if capability_guide and event is not None:
                from src.ai_voicebot.pipecat.processors.tts_complete_notifier import (
                    KEY_LAST_TTS_DURATION_SEC,
                )
                # Notifier 미수신 시 60초까지 기다리지 않고, Phase1 예상 재생 시간 + 여유만 대기
                estimated_phase1_sec = len(phase1_text) / self._TTS_CHARS_PER_SEC
                wait_timeout = min(
                    self._TTS_COMPLETE_WAIT_TIMEOUT_SEC,
                    estimated_phase1_sec + 5.0,
                )
                logger.info("greeting_phase_waiting_tts_complete",
                            call=True,
                            category="tts",
                            progress="tts",
                            wait_timeout_sec=round(wait_timeout, 1),
                            estimated_phase1_sec=round(estimated_phase1_sec, 1),
                            note="Phase1 재생 완료 이벤트 대기 (Notifier가 EndFrame 수신 시 해제)")
                try:
                    await asyncio.wait_for(
                        event.wait(),
                        timeout=wait_timeout,
                    )
                    # Output이 EndFrame을 처리해 KEY_LAST_RTP_SENT_SEC를 넣을 시간 확보 (파이프라인 순서: Notifier → Output)
                    await asyncio.sleep(0.05)
                    # Phase1 대기: RTP로 실제 전송된 시간 기준 사용(전화기 재생 시간에 맞춤). 없으면 Notifier 누적값 사용.
                    from src.ai_voicebot.pipecat.rtp_transport import KEY_LAST_RTP_SENT_SEC
                    play_sec = self._tts_sync_context.pop(KEY_LAST_TTS_DURATION_SEC, None)
                    rtp_sent_sec = self._tts_sync_context.pop(KEY_LAST_RTP_SENT_SEC, None)
                    if isinstance(rtp_sent_sec, (int, float)) and rtp_sent_sec > 0:
                        gap_sec = rtp_sent_sec + self._PHASE_GAP_BUFFER_SEC
                        await asyncio.sleep(gap_sec)
                        logger.info("greeting_phase_gap_tts_complete_signalled",
                                   call=True, category="tts",
                                   phase1_audio_sec=round(play_sec, 2) if isinstance(play_sec, (int, float)) else None,
                                   phase1_rtp_sent_sec=round(rtp_sent_sec, 2),
                                   gap_sec=round(gap_sec, 2),
                                   note="RTP 전송량 기준 대기(전화기 재생 시간 반영)")
                    elif isinstance(play_sec, (int, float)) and play_sec > 0:
                        gap_sec = play_sec + self._PHASE_GAP_BUFFER_SEC
                        await asyncio.sleep(gap_sec)
                        logger.info("greeting_phase_gap_tts_complete_signalled",
                                   call=True, category="tts",
                                   phase1_audio_sec=round(play_sec, 2),
                                   phase1_rtp_sent_sec=None,
                                   gap_sec=round(gap_sec, 2))
                    else:
                        await asyncio.sleep(self._PHASE_GAP_BUFFER_SEC)
                        logger.info("greeting_phase_gap_tts_complete_signalled",
                                   call=True, category="tts", gap_sec=self._PHASE_GAP_BUFFER_SEC)
                except asyncio.TimeoutError:
                    self._tts_sync_context.pop(KEY_LAST_TTS_DURATION_SEC, None)
                    phase1_play_sec = max(0.5, len(phase1_text) / self._TTS_CHARS_PER_SEC)
                    gap_sec = phase1_play_sec + self._PHASE_GAP_BUFFER_SEC
                    await asyncio.sleep(gap_sec)
                    logger.warning("greeting_phase_gap_tts_complete_timeout",
                                  call=True, category="tts",
                                  phase1_chars=len(phase1_text),
                                  wait_timeout_sec=round(wait_timeout, 1),
                                  fallback_gap_sec=round(gap_sec, 2))
                finally:
                    self._tts_sync_context.pop("on_tts_complete", None)

                await self.push_frame(LLMFullResponseStartFrame())
                await self.push_frame(TextFrame(text=capability_guide))
                await self.push_frame(LLMFullResponseEndFrame())
                
                logger.info("greeting_phase2_sent",
                           call=True,
                           category="tts",
                           progress="tts",
                           text=capability_guide[:100],
                           total_elapsed=f"{time.time() - greeting_start:.3f}s")
            
            logger.info("⏱️ [TIMING] greeting_total",
                       call_id="",
                       elapsed=f"{time.time() - greeting_start:.3f}s")
                
        except Exception as e:
            logger.error("greeting_generation_error", call=True, category="tts", error=str(e))
            fallback = "안녕하세요. 무엇을 도와드릴까요?"
            await self.push_frame(TextFrame(text=fallback))
    
    def reset(self):
        """대화 상태 초기화 (새 통화)"""
        self._greeting_sent = False
        if self._agent_available and self._agent:
            self._agent.reset()
        elif hasattr(self, '_messages'):
            self._messages = []
        logger.info("rag_llm_processor_reset")
    
    # =========================================================================
    # Legacy fallback (Phase 1 호환)
    # =========================================================================
    
    async def _generate_greeting_legacy(self) -> str:
        """기관 정보 기반 인사말 생성 (Legacy)"""
        if self._org_manager:
            try:
                org_name = self._org_manager.get_organization_name()
                # ✅ get_random_greeting_template() 사용 (get_greeting_template은 존재하지 않음)
                greeting_template = self._org_manager.get_random_greeting_template()
                if greeting_template:
                    return greeting_template
                return f"안녕하세요. {org_name} AI 통화 비서입니다. 무엇을 도와드릴까요?"
            except Exception:
                pass
        return "안녕하세요. AI 통화 비서입니다. 무엇을 도와드릴까요?"
    
    def _generate_capability_guide_legacy(self) -> str:
        """기관 capabilities 기반 업무 안내 생성 (Legacy)"""
        if self._org_manager:
            try:
                capabilities = self._org_manager.get_capabilities()
                if capabilities:
                    cap_text = ", ".join(capabilities[:-1])
                    if len(capabilities) > 1:
                        cap_text += f", {capabilities[-1]}"
                    else:
                        cap_text = capabilities[0]
                    return f"저는 {cap_text} 등을 도와드릴 수 있습니다. 어떤 것이 궁금하신가요?"
            except Exception:
                pass
        return "어떤 내용이 궁금하시면 편하게 말씀해 주세요."
    
    async def _generate_response_legacy(self, user_text: str):
        """RAG 검색 + LLM 응답 생성 (Legacy)"""
        try:
            self._messages.append({
                "role": "user",
                "content": user_text,
                "timestamp": datetime.now().isoformat(),
            })
            
            rag_context = ""
            if self._rag:
                try:
                    results = await self._rag.search(user_text)
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
                                     top_doc_preview=(first_text[:200] + "...") if len(first_text) > 200 else first_text,
                                     note="레거시 RAG 검색 결과")
                except Exception as e:
                    logger.warning("rag_search_error", call=True, category="rag", progress="rag", error=str(e))
            
            org_context = ""
            if self._org_manager:
                try:
                    org_context = self._org_manager.get_system_prompt()
                except Exception:
                    pass
            
            system_prompt = self._build_system_prompt(org_context, rag_context)
            conversation_history = self._format_history()
            
            response = await self._call_llm(system_prompt, conversation_history, user_text)
            
            if response:
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
                await self.push_frame(
                    TextFrame(text="죄송합니다. 답변을 생성하지 못했습니다.")
                )
                
        except Exception as e:
            logger.error("rag_llm_response_error", call=True, category="llm", error=str(e), exc_info=True)
            await self.push_frame(
                TextFrame(text="죄송합니다. 오류가 발생했습니다.")
            )
    
    def _build_system_prompt(self, org_context: str, rag_context: str) -> str:
        parts = []
        if self._system_prompt:
            parts.append(self._system_prompt)
        elif org_context:
            parts.append(org_context)
        else:
            parts.append(
                "당신은 전화 통화를 응대하는 AI 비서입니다. "
                "친절하고 간결하게 답변하세요."
            )
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
