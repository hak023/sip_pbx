"""
AI Orchestrator

AI 보이스봇의 핵심 로직 - 모든 컴포넌트를 통합하고 대화 흐름을 제어합니다.
"""

import asyncio
from typing import Optional, Dict, Any
import structlog

from .models.conversation import AIConversation, ConversationState
from .audio_buffer import AudioBuffer
from .vad_detector import VADDetector
from .ai_pipeline.stt_client import STTClient
from .ai_pipeline.tts_client import TTSClient
from .ai_pipeline.llm_client import LLMClient
from .ai_pipeline.rag_engine import RAGEngine
from .recording.recorder import CallRecorder
from .knowledge.knowledge_extractor import KnowledgeExtractor

logger = structlog.get_logger(__name__)

# HITL 관련 import (추가)
try:
    from ..services.hitl import HITLService
    from ..websocket import manager as websocket_manager
except ImportError:
    logger.warning("HITL modules not available - HITL features disabled")
    HITLService = None
    websocket_manager = None


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
        STT 결과 수신 콜백
        
        Args:
            text: 인식된 텍스트
            is_final: 최종 결과 여부
        """
        if not is_final:
            # Interim result
            self.current_user_speech = text
            logger.debug("STT interim", text=text[:50])
            return
        
        # Final result
        user_text = text.strip()
        if not user_text:
            return
        
        logger.info("STT final result", text=user_text)
        
        # 대화 메시지 추가
        if self.conversation:
            self.conversation.add_message("user", user_text)
        
        self.total_turns += 1
        
        # 답변 생성 및 재생
        await self.generate_and_speak_response(user_text)
    
    async def generate_and_speak_response(self, user_text: str):
        """
        답변 생성 및 재생
        
        Args:
            user_text: 사용자 질문
        """
        try:
            self.state = ConversationState.THINKING
            
            # 1. RAG 검색
            documents = await self.rag.search(
                query=user_text,
                owner_filter=self.callee
            )
            context_docs = [doc.text for doc in documents]
            
            logger.info("RAG search completed", 
                       docs_count=len(context_docs))
            
            # 2. LLM 답변 생성
            response_text = await self.llm.generate_response(
                user_text=user_text,
                context_docs=context_docs
            )
            
            logger.info("LLM response generated", 
                       response_length=len(response_text))
            
            # 대화 메시지 추가
            if self.conversation:
                self.conversation.add_message("assistant", response_text)
            
            # 3. TTS 재생
            await self.speak(response_text)
            
        except Exception as e:
            logger.error("Response generation error", error=str(e), exc_info=True)
            # 오류 시 기본 응답
            await self.speak("죄송합니다, 답변을 생성하는 중 오류가 발생했습니다.")
    
    async def speak(self, text: str):
        """
        TTS 음성 재생
        
        Args:
            text: 재생할 텍스트
        """
        self.state = ConversationState.SPEAKING
        self.is_speaking = True
        
        try:
            # TTS 스트리밍 생성
            async for audio_chunk in self.tts.synthesize_stream(text):
                if not self.is_speaking:  # Barge-in 체크
                    logger.info("Speaking interrupted by barge-in")
                    break
                
                # RTP로 전송
                if self.rtp_send_callback:
                    await self.rtp_send_callback(audio_chunk)
                
                # 녹음
                self.recorder.add_callee_audio(audio_chunk)
            
        except Exception as e:
            logger.error("TTS playback error", error=str(e))
        finally:
            self.is_speaking = False
            if self.state == ConversationState.SPEAKING:
                self.state = ConversationState.LISTENING
    
    async def stop_speaking(self):
        """TTS 재생 중단 (Barge-in)"""
        self.is_speaking = False
        self.tts.stop()
        logger.info("TTS stopped")
    
    async def play_greeting(self):
        """고정 인사말 재생"""
        greeting_text = self.config.get(
            "greeting_message", 
            "안녕하세요, 저는 AI 비서입니다. 무엇을 도와드릴까요?"
        )
        
        # 대화 메시지 추가
        if self.conversation:
            self.conversation.add_message("assistant", greeting_text)
        
        await self.speak(greeting_text)
    
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

