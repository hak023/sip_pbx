"""
AI Orchestrator

AI 보이스봇의 핵심 로직 - 모든 컴포넌트를 통합하고 대화 흐름을 제어합니다.
"""

import asyncio
from typing import Optional, Dict, Any
import structlog

from ..models.conversation import AIConversation, ConversationState
from ..audio_buffer import AudioBuffer
from ..vad_detector import VADDetector
from ..ai_pipeline.stt_client import STTClient
from ..ai_pipeline.tts_client import TTSClient
from ..ai_pipeline.llm_client import LLMClient
from ..ai_pipeline.rag_engine import RAGEngine
from ..recording.recorder import CallRecorder
from ..knowledge.knowledge_extractor import KnowledgeExtractor
from ..knowledge.organization_info import get_organization_manager, OrganizationInfoManager
from .barge_in_controller import BargeInController
from src.sip_core.models.outbound import OutboundCallResult, TranscriptEntry

logger = structlog.get_logger(__name__)

# HITL 관련 import (선택적)
try:
    from ...services.hitl import HITLService
    from ...websocket import manager as websocket_manager
    HITL_AVAILABLE = True
except ImportError:
    logger.info("hitl_not_available", 
                message="HITL modules not available. HITL features will be disabled.")
    HITLService = None
    websocket_manager = None
    HITL_AVAILABLE = False


class AIOrchestrator:
    """
    AI Orchestrator
    
    AI 보이스봇의 핵심 컴포넌트로, 모든 AI 파이프라인을 통합하고
    대화 흐름을 제어합니다.
    """
    
    def __init__(self, config: Dict[str, Any]):
        """
        Args:
            config: AI 보이스봇 설정
        """
        self.config = config
        
        # 대화 상태
        self.conversation: Optional[AIConversation] = None
        self.state = ConversationState.IDLE
        self.is_speaking = False
        self.current_user_speech = ""
        
        # 통화 정보
        self.call_id: Optional[str] = None
        self.caller: Optional[str] = None
        self.callee: Optional[str] = None
        
        # 컴포넌트 초기화 (지연 초기화)
        self.audio_buffer: Optional[AudioBuffer] = None
        self.vad: Optional[VADDetector] = None
        self.stt: Optional[STTClient] = None
        self.tts: Optional[TTSClient] = None
        self.llm: Optional[LLMClient] = None
        self.rag: Optional[RAGEngine] = None
        self.recorder: Optional[CallRecorder] = None
        self.extractor: Optional[KnowledgeExtractor] = None
        
        # ✅ 기관 정보 관리자
        self.org_manager = get_organization_manager()
        
        # ✅ Barge-in 제어기
        self.barge_in_controller = BargeInController(
            silence_threshold=config.get('silence_threshold', 2.0)
        )
        
        # RTP 전송 콜백
        self.rtp_send_callback = None
        
        # 통계
        self.total_calls = 0
        self.total_turns = 0
        
        # HITL 지원 (추가)
        self.hitl_service: Optional[HITLService] = None
        self.hitl_enabled = config.get('hitl', {}).get('enabled', False)
        self.hitl_confidence_threshold = config.get('hitl', {}).get('confidence_threshold', 0.6)
        self.hitl_response_event: Optional[asyncio.Event] = None
        self.hitl_response_text: Optional[str] = None
        self.is_waiting_for_human = False
        
        logger.info("AIOrchestrator created", hitl_enabled=self.hitl_enabled)
    
    async def initialize(
        self,
        audio_buffer: AudioBuffer,
        vad: VADDetector,
        stt: STTClient,
        tts: TTSClient,
        llm: LLMClient,
        rag: RAGEngine,
        recorder: CallRecorder,
        extractor: KnowledgeExtractor
    ):
        """
        컴포넌트 초기화
        
        Args:
            audio_buffer: Audio Buffer
            vad: VAD Detector
            stt: STT Client
            tts: TTS Client
            llm: LLM Client
            rag: RAG Engine
            recorder: Call Recorder
            extractor: Knowledge Extractor
        """
        self.audio_buffer = audio_buffer
        self.vad = vad
        self.stt = stt
        self.tts = tts
        self.llm = llm
        self.rag = rag
        self.recorder = recorder
        self.extractor = extractor
        
        logger.info("AIOrchestrator initialized with all components")
    
    def set_rtp_callback(self, callback):
        """
        RTP 전송 콜백 설정
        
        Args:
            callback: async def callback(audio_data: bytes)
        """
        self.rtp_send_callback = callback
    
    async def handle_call(
        self, 
        call_id: str, 
        caller: str,
        callee: str
    ):
        """
        AI 통화 처리 메인 로직
        
        Args:
            call_id: 통화 ID
            caller: 발신자
            callee: 착신자
        """
        try:
            self.call_id = call_id
            self.caller = caller
            self.callee = callee
            self.total_calls += 1
            
            # 대화 세션 생성
            from datetime import datetime
            self.conversation = AIConversation(
                session_id=f"ai_{call_id}",
                call_id=call_id,
                caller=caller,
                callee=callee,
                started_at=datetime.now()
            )
            
            # 녹음 시작
            self.recorder.start_recording(call_id)
            
            # 오디오 버퍼 시작
            await self.audio_buffer.start()
            
            # STT 스트리밍 시작
            await self.stt.start_stream(self._on_stt_result)
            
            # 1. 고정 인사말 재생
            self.state = ConversationState.GREETING
            await self.play_greeting()
            
            # 2. 대화 루프 시작
            self.state = ConversationState.LISTENING
            
            logger.info("AI call handling started",
                       call_id=call_id,
                       caller=caller,
                       callee=callee)
            
        except Exception as e:
            logger.error("Handle call error", error=str(e), exc_info=True)
            self.state = ConversationState.ENDED
    
    async def on_audio_packet(self, audio_data: bytes, direction: str = "caller"):
        """
        RTP 패킷 수신 처리
        
        Args:
            audio_data: 오디오 데이터
            direction: 방향 (caller/callee)
        """
        if self.state == ConversationState.ENDED:
            return
        
        try:
            # 녹음
            if direction == "caller":
                self.recorder.add_caller_audio(audio_data)
            else:
                self.recorder.add_callee_audio(audio_data)
            
            # Caller 음성만 처리 (AI가 Callee 역할)
            if direction != "caller":
                return
            
            # VAD 검사
            is_speech = self.vad.detect(audio_data)
            
            # Barge-in 확인
            if self.vad.is_barge_in() and self.is_speaking:
                logger.info("Barge-in detected, stopping TTS")
                await self.stop_speaking()
                self.state = ConversationState.LISTENING
            
            # STT로 전송
            await self.stt.send_audio(audio_data)
            
        except Exception as e:
            logger.error("Audio packet processing error", error=str(e))
    
    async def _on_stt_result(self, text: str, is_final: bool):
        """
        STT 결과 수신 콜백 (Barge-in 제어 통합)
        
        Args:
            text: 인식된 텍스트
            is_final: 최종 결과 여부
        """
        # 1. Barge-in Controller로 필터링
        if not self.barge_in_controller.should_process_speech(is_final):
            logger.debug("STT result ignored (TTS speaking or barge-in disabled)",
                        text=text[:50] if text else "",
                        is_final=is_final)
            return
        
        # 2. 음성 감지 등록
        self.barge_in_controller.on_speech_detected(text, is_final)
        
        if not is_final:
            # Interim result
            self.current_user_speech = text
            logger.debug("STT interim", text=text[:50])
            return
        
        # 3. 침묵 감지 (2초 이상 말이 없으면 발화 완료로 간주)
        await asyncio.sleep(2.0)
        
        if self.barge_in_controller.check_silence():
            # 4. 발화 완료 - 누적된 텍스트 가져오기
            user_text = self.barge_in_controller.get_and_reset_utterance()
            
            if not user_text:
                return
            
            logger.info("STT final result (after silence)", text=user_text)
            
            # 5. 대화 메시지 추가
            if self.conversation:
                self.conversation.add_message("user", user_text)
            
            self.total_turns += 1
            
            # 6. 답변 생성 및 재생
            await self.generate_and_speak_response(user_text)
    
    async def generate_and_speak_response(self, user_text: str):
        """
        답변 생성 및 재생 (기관 정보 컨텍스트 포함 + Transfer Intent 감지)
        
        Args:
            user_text: 사용자 질문
        """
        try:
            self.state = ConversationState.THINKING
            
            # 1. 기관 정보 컨텍스트 생성
            org_context = self.org_manager.get_full_context_for_llm(user_text)
            
            logger.info("Organization context prepared",
                       context_length=len(org_context))
            
            # 2. RAG 검색 (call_id 전달)
            documents = await self.rag.search(
                query=user_text,
                owner_filter=self.callee,
                call_id=self.call_id  # DB 로깅용
            )
            
            # ★ Transfer intent 감지: 상위 결과의 response_type 확인
            if documents and len(documents) > 0:
                top_doc = documents[0]
                response_type = getattr(top_doc, 'metadata', {}).get('response_type', 'info') if hasattr(top_doc, 'metadata') else 'info'
                similarity_score = getattr(top_doc, 'score', 0.0)
                
                # Transfer intent 감지 (높은 유사도 + transfer 타입)
                transfer_threshold = self.config.get('transfer', {}).get('min_similarity_threshold', 0.75) if isinstance(self.config.get('transfer'), dict) else 0.75
                if response_type == "transfer" and similarity_score >= transfer_threshold:
                    logger.info("transfer_intent_detected",
                               call_id=self.call_id,
                               user_text=user_text,
                               department=getattr(top_doc, 'metadata', {}).get('display_name', '') if hasattr(top_doc, 'metadata') else '',
                               score=similarity_score)
                    await self._handle_transfer_intent(user_text, top_doc)
                    return
            
            context_docs = [doc.text for doc in documents]
            
            # 기관 정보를 컨텍스트 맨 앞에 추가
            context_docs.insert(0, org_context)
            
            logger.info("RAG search completed", 
                       docs_count=len(context_docs))
            
            # 3. 시스템 프롬프트 생성
            system_prompt = self.org_manager.get_system_prompt()
            
            # 4. LLM 답변 생성 (call_id 전달)
            response_text = await self.llm.generate_response(
                user_text=user_text,
                context_docs=context_docs,
                call_id=self.call_id,  # DB 로깅용
                system_prompt=system_prompt
            )
            
            logger.info("LLM response generated", 
                       response_length=len(response_text),
                       response_preview=response_text[:100] if len(response_text) > 100 else response_text)
            
            # 대화 메시지 추가
            if self.conversation:
                self.conversation.add_message("assistant", response_text)
            
            # 5. TTS 재생
            await self.speak(response_text)
            
        except Exception as e:
            logger.error("Response generation error", error=str(e), exc_info=True)
            # 오류 시 기본 응답
            await self.speak("죄송합니다, 답변을 생성하는 중 오류가 발생했습니다.")
    
    async def speak(self, text: str):
        """
        TTS 음성 재생 (Barge-in 제어 통합)
        
        Args:
            text: 재생할 텍스트
        """
        self.state = ConversationState.SPEAKING
        self.is_speaking = True
        
        try:
            # 1. Barge-in Controller에 TTS 시작 알림
            await self.barge_in_controller.on_tts_start()
            
            logger.info("🔊 TTS started", text_length=len(text), 
                       text_preview=text[:50] if len(text) > 50 else text)
            
            # 2. TTS 스트리밍 생성
            async for audio_chunk in self.tts.synthesize_stream(text):
                if not self.is_speaking:  # Barge-in 체크
                    logger.info("Speaking interrupted by barge-in")
                    break
                
                # RTP로 전송
                if self.rtp_send_callback:
                    await self.rtp_send_callback(audio_chunk)
                
                # 녹음
                self.recorder.add_callee_audio(audio_chunk)
            
            logger.info("✅ TTS completed", text_length=len(text))
            
        except Exception as e:
            logger.error("TTS playback error", error=str(e), exc_info=True)
        finally:
            self.is_speaking = False
            
            # 3. Barge-in Controller에 TTS 종료 알림
            await self.barge_in_controller.on_tts_end()
            
            if self.state == ConversationState.SPEAKING:
                self.state = ConversationState.LISTENING
    
    async def stop_speaking(self):
        """TTS 재생 중단 (Barge-in)"""
        self.is_speaking = False
        self.tts.stop()
        logger.info("TTS stopped")
    
    # 가이드 멘트 캐시 (owner별)
    _capability_guide_cache: dict = {}

    async def play_greeting(self):
        """
        2-Phase AI 인사말 재생
        
        Phase 1: config.yaml의 greeting_message를 즉시 TTS (고정, 지연 0)
        Phase 2: VectorDB에서 활성 capability 목록 → LLM 자연어 요약 → TTS
        """
        try:
            logger.info("🔄 [AI Takeover] 2-Phase Greeting start", call_id=self.call_id)
            
            # ═══ Phase 1: 고정 인사말 (config.yaml) ═══
            fixed_greeting = self.config.get(
                'greeting_message',
                '안녕하세요. AI 비서입니다.'
            )
            logger.info("✅ [Phase 1] Fixed greeting", greeting=fixed_greeting)
            
            if self.conversation:
                self.conversation.add_message("assistant", fixed_greeting)
            
            # Barge-in OFF (인사말 중 끊지 못하게)
            await self.barge_in_controller.on_tts_start()
            
            # Phase 2를 Phase 1 발화 중 병렬 생성
            guide_task = asyncio.create_task(self._generate_capability_guide())
            
            # Phase 1 TTS 발화
            await self.speak(fixed_greeting)
            
            # ═══ Phase 2: 가이드 멘트 (VectorDB 기반) ═══
            try:
                guide_text = await guide_task
            except Exception as guide_err:
                logger.warning("guide_generation_failed", error=str(guide_err))
                guide_text = None
            
            if guide_text:
                logger.info("✅ [Phase 2] Capability guide", guide=guide_text)
                if self.conversation:
                    self.conversation.add_message("assistant", guide_text)
                
                # Barge-in ON (가이드 중에는 끊을 수 있게)
                await self.barge_in_controller.on_tts_end()
                await self.speak(guide_text)
            else:
                await self.barge_in_controller.on_tts_end()
            
            logger.info("✅ [AI Takeover] 2-Phase Greeting completed", call_id=self.call_id)
            
        except Exception as e:
            logger.error("Greeting error", error=str(e), exc_info=True)
            fallback = "안녕하세요. AI 상담원입니다. 무엇을 도와드릴까요?"
            if self.conversation:
                self.conversation.add_message("assistant", fallback)
            await self.speak(fallback)

    async def _generate_capability_guide(self) -> Optional[str]:
        """VectorDB에서 활성 서비스 목록 → LLM 자연어 요약 (캐시 지원)"""
        try:
            cache_key = self.callee or "__default__"
            
            # 캐시 확인
            if cache_key in AIOrchestrator._capability_guide_cache:
                cached = AIOrchestrator._capability_guide_cache[cache_key]
                import time
                if time.time() - cached.get("ts", 0) < 3600:
                    logger.debug("capability_guide_cache_hit", owner=cache_key)
                    return cached["text"]
            
            # VectorDB에서 capability 조회
            from src.services.knowledge_service import get_knowledge_service
            ks = get_knowledge_service()
            capabilities = await ks.get_all_capabilities(
                owner=self.callee,
                active_only=True,
            )
            
            if not capabilities:
                return None
            
            # display_name 추출 (priority 순, 최대 5개)
            max_items = self.config.get('capability_guide', {}).get('max_items', 5) if isinstance(self.config.get('capability_guide'), dict) else 5
            display_names = [cap["display_name"] for cap in capabilities[:max_items]]
            
            if not display_names:
                return None
            
            # LLM으로 자연어 요약
            items_text = ", ".join(display_names)
            prompt = (
                f"다음 서비스 항목들을 자연어 한 문장으로 안내하세요.\n"
                f"항목: {items_text}\n"
                f"형식 예시: '저는 A, B, C를 안내해 드릴 수 있어요. 어떤 것이 궁금하신가요?'"
            )
            
            guide_text = await self.llm.generate_response(
                user_text=prompt,
                context_docs=[],
                call_id=self.call_id,
                system_prompt="전화 상담 안내 멘트를 간결하게 한 문장으로 생성하세요. 존댓말을 사용하세요."
            )
            
            # 캐시 저장
            import time
            AIOrchestrator._capability_guide_cache[cache_key] = {
                "text": guide_text,
                "ts": time.time(),
            }
            
            return guide_text
            
        except Exception as e:
            logger.error("capability_guide_generation_error", error=str(e), exc_info=True)
            return None
    
    # ==================== Transfer Methods ====================
    
    # TransferManager 참조 (SIPEndpoint에서 설정)
    transfer_manager = None
    
    # ── Outbound 모드 지원 ──
    _outbound_context: dict = None
    _outbound_task_tracker = None
    _outbound_transcript: list = None
    _outbound_complete_cb = None
    _outbound_turns: int = 0
    _outbound_max_turns: int = 20
    _outbound_call_start_time: float = 0
    
    def set_outbound_complete_callback(self, callback):
        """아웃바운드 완료 콜백 설정"""
        self._outbound_complete_cb = callback
    
    async def handle_outbound_call(
        self,
        call_id: str,
        outbound_context: dict,
    ):
        """아웃바운드 콜 AI 대화 시작
        
        기존 handle_call과 유사하지만 아웃바운드 전용 컨텍스트로 작동합니다.
        
        Args:
            call_id: SIP Call-ID
            outbound_context: {outbound_id, purpose, questions, caller_display_name, callee_number}
        """
        import time as _time
        try:
            self.call_id = call_id
            self.caller = outbound_context.get('callee_number', '')  # 착신자(고객)
            self.callee = 'AI'  # AI가 발신자
            self.total_calls += 1
            self._outbound_context = outbound_context
            self._outbound_turns = 0
            self._outbound_max_turns = self.config.get('outbound', {}).get('ai', {}).get('max_turns', 20) if isinstance(self.config.get('outbound'), dict) else 20
            self._outbound_call_start_time = _time.time()
            self._outbound_transcript = []
            
            # TaskTracker 초기화
            from src.ai_voicebot.orchestrator.task_tracker import TaskTracker
            self._outbound_task_tracker = TaskTracker(outbound_context.get('questions', []))
            
            # 대화 세션 생성
            from datetime import datetime
            self.conversation = AIConversation(
                session_id=f"ob_{call_id}",
                call_id=call_id,
                caller='AI',
                callee=self.caller,
                started_at=datetime.now()
            )
            
            # 녹음 시작
            self.recorder.start_recording(call_id)
            
            # 오디오 버퍼 시작
            await self.audio_buffer.start()
            
            # STT 스트리밍 시작
            await self.stt.start_stream(self._on_outbound_stt_result)
            
            # 첫 인사말 + 목적 전달
            self.state = ConversationState.GREETING
            greeting = self._build_outbound_greeting(outbound_context)
            
            if self.conversation:
                self.conversation.add_message("assistant", greeting)
            self._outbound_transcript.append(TranscriptEntry(
                timestamp=round(_time.time() - self._outbound_call_start_time, 1),
                speaker="ai",
                text=greeting,
            ))
            self._outbound_turns += 1
            
            await self.speak(greeting)
            
            # 대화 루프 시작
            self.state = ConversationState.LISTENING
            
            logger.info("outbound_ai_call_started",
                       call_id=call_id,
                       outbound_id=outbound_context.get('outbound_id'),
                       purpose=outbound_context.get('purpose', '')[:50],
                       questions_count=len(outbound_context.get('questions', [])))
            
        except Exception as e:
            logger.error("outbound_handle_call_error", error=str(e), exc_info=True)
            self.state = ConversationState.ENDED
    
    def _build_outbound_greeting(self, context: dict) -> str:
        """아웃바운드 인사말 생성 (템플릿 기반)"""
        display_name = context.get('caller_display_name', '')
        purpose = context.get('purpose', '')
        
        # config에서 템플릿 가져오기
        template = "안녕하세요, {display_name} AI 비서입니다. {purpose} 관련하여 연락드렸습니다."
        outbound_ai_config = self.config.get('outbound', {}).get('ai', {}) if isinstance(self.config.get('outbound'), dict) else {}
        if outbound_ai_config:
            template = outbound_ai_config.get('greeting_template', template)
        
        greeting = template.format(
            display_name=display_name or "회사",
            purpose=purpose,
        )
        return greeting.strip()
    
    def _build_outbound_system_prompt(self) -> str:
        """아웃바운드 전용 시스템 프롬프트 생성"""
        context = self._outbound_context
        questions_text = "\n".join(
            f"  {i+1}. {q}" for i, q in enumerate(context.get('questions', []))
        )
        
        display_name = context.get('caller_display_name', '회사')
        
        return f"""당신은 {display_name}의 AI 비서입니다.
고객에게 전화를 걸어 아래 목적과 확인 사항을 처리해야 합니다.

## 통화 목적
{context.get('purpose', '')}

## 확인해야 할 사항
{questions_text}

## 대화 규칙
1. 이미 자기소개와 통화 목적은 전달되었습니다. 바로 확인 사항을 질문하세요.
2. 확인 사항을 하나씩 자연스럽게 질문하세요.
3. 답변이 불명확하면 정중하게 다시 한번 확인하세요.
4. 모든 확인 사항에 대한 답변을 받으면 감사 인사를 하고 통화를 마무리하세요.
5. 고객이 바쁘거나 거부하면 양해를 구하고 통화를 종료하세요.
6. 반드시 한국어로 대화하세요. 존댓말을 사용하세요.
7. 1~2문장으로 간결하게 답변하세요.

## 응답 시 내부 태스크 상태 추적
매 응답 마지막에 아래 JSON 형식으로 현재 상태를 [TASK_STATE] 태그로 출력하세요:
[TASK_STATE]{{"questions": [{{"id": "q1", "status": "answered|pending|unclear|refused", "answer": "고객 답변 요약"}}], "all_completed": false, "should_end_call": false}}[/TASK_STATE]

status 값:
- pending: 아직 질문하지 않았거나 답변을 받지 못함
- answered: 명확한 답변을 받음
- unclear: 불명확한 답변 (재질문 필요)
- refused: 고객이 답변을 거부함

should_end_call: 고객이 통화를 원하지 않거나 바쁘다고 하면 true로 설정하세요.
"""

    async def _on_outbound_stt_result(self, text: str, is_final: bool):
        """아웃바운드 모드 STT 결과 콜백"""
        import time as _time
        
        if not self.barge_in_controller.should_process_speech(is_final):
            return
        
        self.barge_in_controller.on_speech_detected(text, is_final)
        
        if not is_final:
            self.current_user_speech = text
            return
        
        await asyncio.sleep(2.0)
        
        if self.barge_in_controller.check_silence():
            user_text = self.barge_in_controller.get_and_reset_utterance()
            if not user_text:
                return
            
            logger.info("outbound_stt_final", text=user_text)
            
            # 대화 기록
            if self.conversation:
                self.conversation.add_message("user", user_text)
            self._outbound_transcript.append(TranscriptEntry(
                timestamp=round(_time.time() - self._outbound_call_start_time, 1),
                speaker="customer",
                text=user_text,
            ))
            
            self.total_turns += 1
            self._outbound_turns += 1
            
            # 최대 턴 수 확인
            if self._outbound_turns >= self._outbound_max_turns:
                logger.warning("outbound_max_turns_reached",
                              turns=self._outbound_turns)
                closing = "죄송합니다. 통화가 길어졌네요. 감사합니다. 좋은 하루 되세요."
                await self.speak(closing)
                await self._finalize_outbound()
                return
            
            # 아웃바운드 전용 응답 생성
            await self._generate_outbound_response(user_text)
    
    async def _generate_outbound_response(self, user_text: str):
        """아웃바운드 모드 전용 응답 생성"""
        import time as _time
        from src.ai_voicebot.orchestrator.task_tracker import TaskTracker
        
        try:
            self.state = ConversationState.THINKING
            
            # 시스템 프롬프트 생성
            system_prompt = self._build_outbound_system_prompt()
            
            # LLM 응답 생성
            response_text = await self.llm.generate_response(
                user_text=user_text,
                context_docs=[],
                call_id=self.call_id,
                system_prompt=system_prompt,
            )
            
            # 태스크 상태 파싱
            task_state = TaskTracker.parse_task_state(response_text)
            if task_state and self._outbound_task_tracker:
                self._outbound_task_tracker.update(task_state)
                
                progress = self._outbound_task_tracker.get_progress()
                logger.info("outbound_task_progress",
                           progress=progress,
                           call_id=self.call_id)
            
            # 태그 제거 후 TTS
            clean_response = TaskTracker.strip_task_tags(response_text)
            
            if self.conversation:
                self.conversation.add_message("assistant", clean_response)
            self._outbound_transcript.append(TranscriptEntry(
                timestamp=round(_time.time() - self._outbound_call_start_time, 1),
                speaker="ai",
                text=clean_response,
            ))
            self._outbound_turns += 1
            
            await self.speak(clean_response)
            
            # 태스크 완료 확인
            if self._outbound_task_tracker and self._outbound_task_tracker.is_all_completed():
                logger.info("outbound_all_tasks_completed",
                           call_id=self.call_id)
                await self._finalize_outbound()
            
        except Exception as e:
            logger.error("outbound_response_error", error=str(e), exc_info=True)
            await self.speak("죄송합니다. 잠시 오류가 발생했습니다.")
    
    async def _finalize_outbound(self):
        """아웃바운드 콜 완료 처리 (결과 생성 + 콜백)"""
        import time as _time
        
        try:
            # 통화 시간 계산
            duration = int(_time.time() - self._outbound_call_start_time) if self._outbound_call_start_time else 0
            
            # 요약 생성
            summary = ""
            try:
                transcript_text = "\n".join(
                    f"{'AI' if t.speaker == 'ai' else '고객'}: {t.text}"
                    for t in self._outbound_transcript
                )
                summary_prompt = f"다음 통화 내용을 2-3문장으로 요약해주세요:\n\n{transcript_text}"
                summary = await self.llm.generate_response(
                    user_text=summary_prompt,
                    context_docs=[],
                    call_id=self.call_id,
                    system_prompt="통화 내용을 간결하게 요약하세요.",
                )
            except Exception as e:
                logger.warning("outbound_summary_error", error=str(e))
                summary = "요약 생성 실패"
            
            # 결과 생성
            answers = self._outbound_task_tracker.to_answers() if self._outbound_task_tracker else []
            ai_turns = sum(1 for t in self._outbound_transcript if t.speaker == "ai")
            customer_turns = sum(1 for t in self._outbound_transcript if t.speaker == "customer")
            
            result = OutboundCallResult(
                answers=answers,
                summary=summary,
                task_completed=self._outbound_task_tracker.is_all_completed() if self._outbound_task_tracker else False,
                transcript=self._outbound_transcript or [],
                duration_seconds=duration,
                ai_turns=ai_turns,
                customer_turns=customer_turns,
            )
            
            logger.info("outbound_result_generated",
                       call_id=self.call_id,
                       task_completed=result.task_completed,
                       duration=duration,
                       answers_count=len(answers))
            
            # OutboundCallManager에 완료 통보
            if self._outbound_complete_cb:
                await self._outbound_complete_cb(self.call_id, result)
            
        except Exception as e:
            logger.error("outbound_finalize_error", error=str(e), exc_info=True)
    
    async def get_partial_outbound_result(self) -> 'OutboundCallResult':
        """현재까지의 부분 결과 수집 (상대방이 먼저 끊었을 때)"""
        import time as _time
        
        duration = int(_time.time() - self._outbound_call_start_time) if self._outbound_call_start_time else 0
        answers = self._outbound_task_tracker.to_answers() if self._outbound_task_tracker else []
        ai_turns = sum(1 for t in (self._outbound_transcript or []) if t.speaker == "ai")
        customer_turns = sum(1 for t in (self._outbound_transcript or []) if t.speaker == "customer")
        
        return OutboundCallResult(
            answers=answers,
            summary="통화 중 상대방이 종료함",
            task_completed=self._outbound_task_tracker.is_all_completed() if self._outbound_task_tracker else False,
            transcript=self._outbound_transcript or [],
            duration_seconds=duration,
            ai_turns=ai_turns,
            customer_turns=customer_turns,
        )
    
    def set_transfer_manager(self, transfer_manager):
        """TransferManager 설정"""
        self.transfer_manager = transfer_manager
        logger.info("TransferManager configured", call_id=self.call_id)
    
    async def _handle_transfer_intent(self, user_text: str, rag_result):
        """호 전환 의도 처리
        
        RAG에서 response_type=="transfer" 결과를 감지했을 때 호출됩니다.
        TransferManager에 전환 요청을 위임합니다.
        
        Args:
            user_text: 사용자의 원래 요청 텍스트
            rag_result: RAG 검색 결과 (상위 1건, transfer 타입)
        """
        metadata = getattr(rag_result, 'metadata', {}) if hasattr(rag_result, 'metadata') else {}
        department_name = metadata.get('display_name', '담당부서')
        transfer_to = metadata.get('transfer_to', '')
        phone_display = metadata.get('phone_display', transfer_to)
        
        if not transfer_to:
            logger.warning("transfer_no_target",
                          call_id=self.call_id,
                          department=department_name)
            await self.speak("죄송합니다. 해당 부서의 연결 정보를 찾을 수 없습니다.")
            return
        
        logger.info("transfer_request",
                    call_id=self.call_id,
                    department=department_name,
                    transfer_to=transfer_to,
                    phone_display=phone_display)
        
        # 대화 메시지에 기록
        if self.conversation:
            self.conversation.add_message("system", f"[Transfer] {department_name} ({phone_display})")
        
        if self.transfer_manager:
            # TransferManager에 전환 위임
            record = await self.transfer_manager.initiate_transfer(
                call_id=self.call_id,
                transfer_to=transfer_to,
                department_name=department_name,
                phone_display=phone_display,
                user_request_text=user_text,
                caller_uri=self.caller or "",
                caller_display=self.caller or "",
            )
            
            if not record:
                await self.speak("죄송합니다. 현재 전화 연결을 처리할 수 없습니다.")
        else:
            # TransferManager가 없으면 안내만 제공
            logger.warning("transfer_manager_not_available", call_id=self.call_id)
            await self.speak(
                f"{department_name}의 전화번호는 {phone_display}입니다. "
                f"직접 연락해 주시면 감사하겠습니다."
            )
    
    async def end_call(self):
        """통화 종료 처리"""
        try:
            self.state = ConversationState.ENDED
            
            # STT 중지
            await self.stt.stop_stream()
            
            # 오디오 버퍼 중지
            await self.audio_buffer.stop()
            
            # 녹음 저장
            metadata = await self.recorder.stop_recording()
            
            # 대화 종료 시간 설정
            if self.conversation:
                from datetime import datetime
                self.conversation.ended_at = datetime.now()
            
            # 전사 텍스트 저장
            if self.conversation:
                transcript = self._build_transcript()
                await self.recorder.save_transcript(self.call_id, transcript)
                
                # 지식 추출 (비동기, 백그라운드)
                if transcript:
                    asyncio.create_task(
                        self.extractor.extract_from_call(
                            call_id=self.call_id,
                            transcript_path=metadata.get("files", {}).get("transcript", ""),
                            owner_id=self.callee,
                            speaker="callee"
                        )
                    )
            
            logger.info("AI call ended",
                       call_id=self.call_id,
                       total_turns=self.total_turns,
                       duration=self.conversation.get_duration_seconds() if self.conversation else 0)
            
        except Exception as e:
            logger.error("End call error", error=str(e), exc_info=True)
    
    def _build_transcript(self) -> str:
        """대화 전사 텍스트 생성"""
        if not self.conversation:
            return ""
        
        lines = []
        for msg in self.conversation.messages:
            if msg.role == "user":
                lines.append(f"발신자: {msg.content}")
            elif msg.role == "assistant":
                lines.append(f"착신자(AI): {msg.content}")
        
        return "\n".join(lines)
    
    def get_stats(self) -> dict:
        """통계 반환"""
        return {
            "total_calls": self.total_calls,
            "total_turns": self.total_turns,
            "current_state": self.state.value if self.state else "unknown",
            "is_speaking": self.is_speaking,
            "current_call_id": self.call_id,
        }
    
    # ==================== HITL Methods (추가) ====================
    
    def set_hitl_service(self, hitl_service):
        """HITL Service 설정"""
        self.hitl_service = hitl_service
        logger.info("HITL Service configured", call_id=self.call_id)
    
    async def request_human_help(self, user_text: str, rag_results: list, confidence: float):
        """
        사람의 도움 요청 (운영자 부재중 모드 지원)
        
        Args:
            user_text: 사용자 질문
            rag_results: RAG 검색 결과
            confidence: AI 신뢰도
            
        Returns:
            True: HITL 요청 성공 (운영자 대기 중)
            False: HITL 요청 거절 (운영자 부재중)
        """
        if not self.hitl_enabled or not self.hitl_service:
            logger.warning("HITL not enabled or service not available")
            return False
        
        logger.info("Requesting human help",
                   call_id=self.call_id,
                   question=user_text,
                   confidence=confidence)
        
        # HITL 요청 컨텍스트 생성
        context = {
            'caller_id': self.caller,
            'callee_id': self.callee,
            'conversation_history': [
                {'role': msg.role, 'content': msg.content, 'timestamp': msg.timestamp.isoformat()}
                for msg in (self.conversation.messages[-5:] if self.conversation else [])
            ],
            'rag_results': [
                {'text': doc.text, 'score': doc.score}
                for doc in rag_results
            ],
            'ai_confidence': confidence
        }
        
        # HITLService에 요청 (운영자 상태 확인 포함)
        hitl_accepted = await self.hitl_service.request_human_help(
            call_id=self.call_id,
            question=user_text,
            context=context,
            urgency='high' if confidence < 0.3 else 'medium'
        )
        
        if not hitl_accepted:
            # 운영자 부재중 - 자동 fallback 응답
            logger.info("HITL rejected - operator away, using fallback message",
                       call_id=self.call_id)
            
            # 부재중 메시지 가져오기 (Redis에서 커스텀 메시지 또는 기본 메시지)
            away_message = await self._get_away_message()
            
            # 즉시 응답 (대기 음악 없음)
            if self.tts:
                audio = await self.tts.synthesize(away_message)
                if audio and self.rtp_send_callback:
                    await self.rtp_send_callback(audio)
            
            return False
        
        # 운영자 대기 중 - 기존 HITL 로직
        # 대화 상태 업데이트
        self.state = ConversationState.WAITING_HUMAN
        self.is_waiting_for_human = True
        
        # 대기 멘트 재생
        await self._play_hold_message()
        
        return True
    
    async def _get_away_message(self) -> str:
        """
        운영자 부재중 메시지 가져오기
        
        Returns:
            부재중 메시지
        """
        # Redis에서 커스텀 메시지 조회
        if self.hitl_service and self.hitl_service.redis_client:
            try:
                custom_message = await self.hitl_service.redis_client.get("operator:away_message")
                if custom_message:
                    return custom_message.decode() if isinstance(custom_message, bytes) else custom_message
            except Exception as e:
                logger.error("Failed to get away message from Redis", error=str(e))
        
        # 기본 메시지
        return self.config.get('hitl', {}).get(
            'away_message',
            "죄송합니다. 해당 부분은 잘 모르는 내용이라 확인 후 별도로 안내드리겠습니다."
        )
    
    async def _play_hold_message(self):
        """대기 멘트 재생"""
        hold_message = self.config.get('hitl', {}).get(
            'hold_message',
            "잠시만 확인 중이니 기다려 주세요. 곧 답변 드리겠습니다."
        )
        
        logger.info("Playing hold message", call_id=self.call_id)
        
        # TTS로 대기 멘트 생성 및 재생
        if self.tts:
            audio = await self.tts.synthesize(hold_message)
            if audio and self.rtp_send_callback:
                await self.rtp_send_callback(audio)
        
        # TODO: 대기 음악 재생 (선택 사항)
        # await self._play_hold_music()
    
    async def wait_for_human_response(self, timeout: int = 60) -> Optional[str]:
        """
        운영자 응답 대기
        
        Args:
            timeout: 타임아웃 (초)
            
        Returns:
            운영자 응답 텍스트 또는 None (타임아웃)
        """
        self.hitl_response_event = asyncio.Event()
        self.hitl_response_text = None
        
        try:
            await asyncio.wait_for(
                self.hitl_response_event.wait(),
                timeout=timeout
            )
            return self.hitl_response_text
        except asyncio.TimeoutError:
            logger.warning("HITL response timeout", call_id=self.call_id)
            self.is_waiting_for_human = False
            self.state = ConversationState.LISTENING
            return None
    
    async def handle_human_response(self, response_text: str, operator_id: str):
        """
        Frontend에서 받은 운영자 응답 처리
        
        Args:
            response_text: 운영자가 작성한 답변
            operator_id: 운영자 ID
        """
        logger.info("Human response received",
                   call_id=self.call_id,
                   operator_id=operator_id,
                   response_length=len(response_text))
        
        self.hitl_response_text = response_text
        self.is_waiting_for_human = False
        
        # 이벤트 트리거
        if self.hitl_response_event:
            self.hitl_response_event.set()
        
        # 대화 상태 복원
        self.state = ConversationState.THINKING
    
    def _is_sensitive_topic(self, text: str) -> bool:
        """민감한 주제인지 확인"""
        sensitive_keywords = self.config.get('hitl', {}).get('sensitive_keywords', [
            '계약', '결제', '환불', '클레임', '불만', '취소', 
            'contract', 'payment', 'refund', 'complaint'
        ])
        
        return any(keyword in text.lower() for keyword in sensitive_keywords)
