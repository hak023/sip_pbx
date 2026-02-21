"""
Voice AI Pipeline Builder for SIP PBX (Phase 3 + Smart Turn).

Pipecat 파이프라인을 구성하여 AI 통화 응대를 수행.

Pipeline 구조 (완성):
    RTPInput → SileroVAD(stop_secs=config) → [SmartTurn] → GoogleSTT → [SmartBargeIn] → RAG-LLM → [StreamingTTS] → GoogleTTS → RTPOutput

주요 프로세서:
  - Smart Turn v3.2 (발화 종료 판단: 문법/억양/속도 분석, 10ms CPU)
  - SmartBargeInProcessor (3단계 필터: 키워드 + 단어수 + LLM)
  - StreamingTTSGateway (첫 문장 즉시 TTS 발화)
"""

import asyncio
import os
from typing import Optional

import structlog

from pipecat.audio.vad.silero import SileroVADAnalyzer
from pipecat.audio.vad.vad_analyzer import VADParams
from pipecat.pipeline.pipeline import Pipeline
from pipecat.pipeline.runner import PipelineRunner
from pipecat.pipeline.task import PipelineParams, PipelineTask
from pipecat.processors.audio.vad_processor import VADProcessor
from pipecat.services.google.stt import GoogleSTTService
from pipecat.services.google.tts import GoogleTTSService

from src.ai_voicebot.pipecat.rtp_transport import SIPPBXTransport
from src.ai_voicebot.pipecat.processors.rag_processor import RAGLLMProcessor
from src.ai_voicebot.pipecat.processors.tts_complete_notifier import TTSCompleteNotifier
from src.ai_voicebot.pipecat.processors.tts_end_frame_forwarder import TTSEndFrameForwarder

logger = structlog.get_logger(__name__)


class VoiceAIPipelineBuilder:
    """
    AI 통화 응대를 위한 Pipecat Pipeline 생성 및 실행.
    
    Phase 1: 기본 파이프라인 (VAD + STT + RAG-LLM + TTS)
    Phase 2: LangGraph Agent 통합
    Phase 3: Smart Barge-in + Streaming TTS + Smart Turn v3.2
    """
    
    def __init__(self, config: dict):
        """
        Args:
            config: AI 설정 딕셔너리 (config.yaml의 ai_voicebot 섹션)
        """
        self.config = config
        self._runner: Optional[PipelineRunner] = None
    
    async def build_and_run(
        self,
        rtp_worker,
        call_context: dict,
        llm_client=None,
        rag_engine=None,
        org_manager=None,
        embedder=None,
        vector_db=None,
    ) -> Optional[PipelineTask]:
        """
        파이프라인 구축 및 실행.
        
        Args:
            rtp_worker: RTPRelayWorker 인스턴스
            call_context: 통화 컨텍스트 {call_id, caller, callee, system_prompt}
            llm_client: LLM 클라이언트 (기존 llm_client.py)
            rag_engine: RAG 엔진 (기존 rag_engine.py)
            org_manager: 기관 정보 관리자
            embedder: TextEmbedder 인스턴스 (Phase 2: Semantic Cache용)
            vector_db: VectorDB 인스턴스 (Phase 2: Semantic Cache용)
        
        Returns:
            실행 중인 PipelineTask
        """
        import time
        build_start = time.time()
        call_id = call_context.get("call_id", "unknown")
        callee = call_context.get("callee", "")  # 착신번호 = owner
        
        try:
            # 0. 착신번호 기반 OrganizationInfoManager 생성 (VectorDB에서 로드)
            if callee:
                try:
                    from src.ai_voicebot.knowledge.organization_info import create_org_manager
                    from src.services.knowledge_service import get_knowledge_service
                    ks = get_knowledge_service()
                    if ks:
                        org_manager = await create_org_manager(owner=callee, knowledge_service=ks)
                        logger.info("pipecat_org_manager_created_from_vectordb",
                                   call_id=call_id, owner=callee,
                                   tenant_name=org_manager.get_organization_name())
                    else:
                        logger.warning("pipecat_knowledge_service_unavailable",
                                     call_id=call_id)
                except Exception as e:
                    logger.warning("pipecat_org_manager_creation_failed",
                                 call_id=call_id, owner=callee, error=str(e))
            
            # 1. RTP Relay를 Pipecat 모드로 전환
            rtp_worker.enable_pipecat_mode()
            
            # Phase1/Phase2 인사말 + TTS 완료 시그널 공유 컨텍스트 (Notifier·Output 불일치 경고용)
            tts_sync_context = {"_call_id": call_id or ""}
            
            # 2. Transport 생성 (tts_sync_context 전달 → TTS vs RTP 전송량 불일치 시 경고)
            transport = SIPPBXTransport(rtp_worker, tts_sync_context=tts_sync_context)
            
            # 3. VAD 프로세서 (Silero VAD)
            #    stop_secs: 침묵 이 길어져야 "발화 종료". 사람-AI 대화에서는 0.5~0.8초 권장 (config: silero_vad)
            vad_cfg = self.config.get("silero_vad", {})
            vad_stop_secs = vad_cfg.get("stop_secs", 0.7)
            vad_start_secs = vad_cfg.get("start_secs", 0.25)
            vad_confidence = vad_cfg.get("confidence", 0.6)
            vad_min_volume = vad_cfg.get("min_volume", 0.5)
            
            vad_analyzer = SileroVADAnalyzer(
                params=VADParams(
                    confidence=vad_confidence,
                    start_secs=vad_start_secs,
                    stop_secs=vad_stop_secs,
                    min_volume=vad_min_volume,
                )
            )
            vad_processor = VADProcessor(vad_analyzer=vad_analyzer)
            
            # 3.5. Smart Turn Processor (설계서 Phase 1: Smart Turn v3.2)
            smart_turn_processor = self._create_smart_turn_processor()
            
            # 4. Google STT
            stt = self._create_stt_service()
            
            # 5. Smart Barge-in Processor (Phase 3)
            barge_in_processor = self._create_barge_in_processor(llm_client)
            
            # HITL: 운영자 응답을 해당 통화 TTS로 넣기 위한 큐 + on_alert 콜백
            hitl_response_queue: Optional[asyncio.Queue] = None
            hitl_on_alert = None
            try:
                from src.services.hitl import get_hitl_service
                hitl_svc = get_hitl_service()
                hitl_response_queue = asyncio.Queue()
                hitl_svc.register_hitl_response_queue(call_id, hitl_response_queue)

                def _make_on_alert(ctx: dict):
                    async def _on_hitl_alert(cid: str, alert_data: dict):
                        await hitl_svc.request_human_help(
                            call_id=cid,
                            question=alert_data.get("question", ""),
                            context={
                                "caller_id": ctx.get("caller", ""),
                                "callee_id": ctx.get("callee", ""),
                                "conversation_history": [],
                                "rag_results": [],
                                "ai_confidence": alert_data.get("confidence", 0.0),
                            },
                            urgency="high" if (alert_data.get("confidence", 1.0) < 0.3) else "medium",
                        )
                    return _on_hitl_alert

                hitl_on_alert = _make_on_alert(call_context)
            except Exception as e:
                logger.warning("hitl_callbacks_not_attached", call_id=call_id, error=str(e))
            
            # 6. RAG + LLM 프로세서 (Phase 2: LangGraph Agent)
            rag_llm = RAGLLMProcessor(
                llm_client=llm_client,
                rag_engine=rag_engine,
                org_manager=org_manager,
                embedder=embedder,
                vector_db=vector_db,
                system_prompt=call_context.get("system_prompt", ""),
                owner=callee,
                tts_sync_context=tts_sync_context,
                call_id=call_id,  # 통화 ID 전달 (WebSocket 이벤트용)
                hitl_on_alert=hitl_on_alert,
                hitl_response_queue=hitl_response_queue,
                name="RAG-LLM",
            )
            
            # 7. Streaming TTS Gateway (Phase 3)
            streaming_gateway = self._create_streaming_gateway()
            
            # 8. Google TTS
            tts = self._create_tts_service()
            
            # 9. Pipeline 조립 (Phase 3 + Smart Turn)
            pipeline_components = [
                transport.input(),       # RTP → PCM 16kHz
                vad_processor,           # Silero VAD (음성 감지, 0.2s)
            ]
            
            # Smart Turn (VAD 뒤, STT 앞에 삽입)
            if smart_turn_processor:
                pipeline_components.append(smart_turn_processor)
            
            pipeline_components.append(
                stt,                     # Google STT (Streaming)
            )
            
            # Smart Barge-in (Phase 3) - 있으면 추가
            if barge_in_processor:
                pipeline_components.append(barge_in_processor)
            
            pipeline_components.extend([
                rag_llm,                 # RAG + LLM (LangGraph Agent)
            ])
            
            # Streaming TTS Gateway (Phase 3) - 있으면 추가
            if streaming_gateway:
                pipeline_components.append(streaming_gateway)
            
            pipeline_components.extend([
                tts,                     # Google TTS (음성 합성)
                TTSEndFrameForwarder(    # Pipecat TTS가 EndFrame 미전달 시 TTSStopped 후 synthetic EndFrame 전달
                    name="TTSEndFrameForwarder",
                ),
                TTSCompleteNotifier(     # Phase1 TTS 완료 시그널 (인사말 순차 재생)
                    sync_context=tts_sync_context,
                    name="TTSCompleteNotifier",
                ),
                transport.output(),      # PCM → RTP → Caller
            ])
            
            pipeline = Pipeline(pipeline_components)
            
            # 10. PipelineTask 생성
            task = PipelineTask(
                pipeline,
                params=PipelineParams(
                    allow_interruptions=True,
                    enable_metrics=False,
                    enable_usage_metrics=False,
                ),
            )
            
            component_names = [
                "SIPPBXTransport", f"SileroVAD(stop={vad_stop_secs}s)",
            ]
            if smart_turn_processor:
                component_names.append("SmartTurnV3")
            component_names.append("GoogleSTT")
            if barge_in_processor:
                component_names.append("SmartBargeIn")
            component_names.append("RAG-LLM(LangGraph)")
            if streaming_gateway:
                component_names.append("StreamingTTSGateway")
            component_names.extend(["GoogleTTS", "TTSEndFrameForwarder", "TTSCompleteNotifier", "SIPPBXOutput"])
            
            build_elapsed = time.time() - build_start
            logger.info("⏱️ [TIMING] pipecat_pipeline_built",
                       call_id=call_id,
                       phase=3,
                       components=component_names,
                       build_elapsed=f"{build_elapsed:.3f}s")
            
            # 11. 인사말 전송 예약
            async def _send_greeting_after_start():
                """파이프라인 시작 후 인사말 전송 (최소 대기)"""
                # ✅ 0.5초 → 0.1초로 단축 (LangGraph 그래프는 이미 캐싱됨)
                await asyncio.sleep(0.1)
                greeting_start = time.time()
                await rag_llm.send_greeting()
                greeting_elapsed = time.time() - greeting_start
                logger.info("⏱️ [TIMING] greeting_total",
                           call_id=call_id,
                           elapsed=f"{greeting_elapsed:.3f}s")
            
            # 12. 파이프라인 실행
            self._runner = PipelineRunner(handle_sigint=False)
            
            asyncio.create_task(_send_greeting_after_start())
            
            try:
                await self._runner.run(task)
            finally:
                # HITL 응답 큐 해제 (통화 종료 시)
                if hitl_response_queue is not None:
                    try:
                        from src.services.hitl import get_hitl_service
                        get_hitl_service().unregister_hitl_response_queue(call_id)
                    except Exception as ex:
                        logger.debug("hitl_unregister_failed", call_id=call_id, error=str(ex))
            
            logger.info("pipecat_pipeline_completed", call_id=call_id)
            return task
            
        except Exception as e:
            logger.error("pipecat_pipeline_error",
                        call_id=call_id,
                        error=str(e),
                        exc_info=True)
            try:
                rtp_worker.stop_pipecat_mode()
            except Exception:
                pass
            return None
    
    def _create_barge_in_processor(self, llm_client=None):
        """
        Smart Barge-in Processor 생성 (Phase 3).
        
        pipecat-ai가 설치되지 않았거나 비활성화 시 None 반환 (graceful fallback).
        """
        barge_in_config = self.config.get("barge_in", {})
        if not barge_in_config.get("enabled", True):
            logger.info("smart_barge_in_disabled_by_config")
            return None
        
        try:
            from src.ai_voicebot.pipecat.barge_in_strategy import (
                SmartBargeInStrategy,
                SmartBargeInProcessor,
            )
            
            strategy = SmartBargeInStrategy(
                min_words=barge_in_config.get("min_words", 3),
                keywords=barge_in_config.get("keywords", None),
                llm_client=llm_client,
            )
            
            processor = SmartBargeInProcessor(
                strategy=strategy,
                name="SmartBargeIn",
            )
            
            logger.info("smart_barge_in_processor_created",
                       min_words=barge_in_config.get("min_words", 3),
                       has_llm=llm_client is not None)
            return processor
            
        except Exception as e:
            logger.warning("smart_barge_in_creation_failed",
                          error=str(e),
                          message="Falling back to Pipecat default interruption")
            return None
    
    def _create_streaming_gateway(self):
        """
        Streaming TTS Gateway 생성 (Phase 3).
        
        비활성화 시 None 반환 (TextFrame이 바로 TTS로 전달됨).
        """
        streaming_config = self.config.get("streaming_tts", {})
        if not streaming_config.get("enabled", True):
            logger.info("streaming_tts_gateway_disabled_by_config")
            return None
        
        try:
            from src.ai_voicebot.pipecat.processors.streaming_tts_processor import (
                StreamingTTSGateway,
            )
            
            gateway = StreamingTTSGateway(
                min_chunk_chars=streaming_config.get("min_chunk_chars", 15),
                max_buffer_chars=streaming_config.get("max_buffer_chars", 200),
                flush_timeout=streaming_config.get("flush_timeout", 1.0),
                name="StreamingTTSGateway",
            )
            
            logger.info("streaming_tts_gateway_created",
                       min_chars=streaming_config.get("min_chunk_chars", 15),
                       max_buffer=streaming_config.get("max_buffer_chars", 200))
            return gateway
            
        except Exception as e:
            logger.warning("streaming_tts_gateway_creation_failed",
                          error=str(e))
            return None
    
    def _is_smart_turn_enabled(self) -> bool:
        """Smart Turn 활성화 여부 확인"""
        smart_turn_config = self.config.get("smart_turn", {})
        return smart_turn_config.get("enabled", True)
    
    def _create_smart_turn_processor(self):
        """
        Smart Turn v3.2 Processor 생성.
        
        Pipecat의 LocalSmartTurnAnalyzerV3를 사용하여 발화 종료를 판단.
        VAD stop_secs(설정) 침묵 후 모델이 문법/억양/속도를 분석하여 진짜 발화 완료인지 판단.
        
        미설치/비활성화 시 None 반환 (VAD-only fallback, config.silero_vad.stop_secs 사용).
        """
        smart_turn_config = self.config.get("smart_turn", {})
        if not smart_turn_config.get("enabled", True):
            logger.info("smart_turn_disabled_by_config")
            return None
        
        try:
            from pipecat.audio.turn.smart_turn.local_smart_turn_v3 import (
                LocalSmartTurnAnalyzerV3,
            )
            from src.ai_voicebot.pipecat.processors.smart_turn_processor import (
                SmartTurnProcessor,
            )
            
            # Smart Turn 모델 초기화
            model_path = smart_turn_config.get("model_path", None)
            if model_path:
                analyzer = LocalSmartTurnAnalyzerV3(
                    smart_turn_model_path=model_path
                )
            else:
                # Pipecat 번들 모델 사용 (기본)
                analyzer = LocalSmartTurnAnalyzerV3()
            
            processor = SmartTurnProcessor(
                turn_analyzer=analyzer,
                max_hold_secs=smart_turn_config.get("max_hold_secs", 2.0),
                name="SmartTurnV3",
            )
            
            logger.info("smart_turn_processor_created",
                       model="LocalSmartTurnAnalyzerV3",
                       max_hold_secs=smart_turn_config.get("max_hold_secs", 2.0),
                       custom_model=model_path is not None)
            return processor
            
        except ImportError as e:
            logger.warning("smart_turn_import_failed",
                          error=str(e),
                          message="Smart Turn v3.2 not available. "
                                  "Falling back to VAD-only (stop_secs=0.5). "
                                  "Install: pip install pipecat-ai[smart-turn]")
            return None
        except Exception as e:
            logger.warning("smart_turn_creation_failed",
                          error=str(e),
                          message="Falling back to VAD-only")
            return None
    
    def _create_stt_service(self) -> GoogleSTTService:
        """Google STT 서비스 생성"""
        stt_config = self.config.get("google_cloud", {}).get("stt", {})
        
        # 언어 코드 설정 (Language enum 사용 필수)
        from pipecat.frames.frames import Language
        language_code = stt_config.get("language_code", "ko-KR")
        lang_map = {
            "ko-KR": Language.KO_KR,
            "ko": Language.KO,
            "en-US": Language.EN_US,
            "en": Language.EN,
        }
        stt_language = lang_map.get(language_code, Language.KO_KR)
        
        # STT 모델 설정
        stt_model = stt_config.get("model", "telephony")
        
        return GoogleSTTService(
            credentials_path=stt_config.get(
                "credentials_path",
                os.environ.get("GOOGLE_APPLICATION_CREDENTIALS", "")
            ),
            sample_rate=16000,
            params=GoogleSTTService.InputParams(
                languages=[stt_language],
                model=stt_model,
                enable_automatic_punctuation=stt_config.get("enable_automatic_punctuation", True),
                enable_interim_results=True,
            ),
        )
    
    def _create_tts_service(self) -> GoogleTTSService:
        """Google TTS 서비스 생성"""
        tts_config = self.config.get("google_cloud", {}).get("tts", {})
        
        # 언어 코드 설정 (voice와 language가 일치해야 함)
        from pipecat.frames.frames import Language
        language_code = tts_config.get("language_code", "ko")
        # language_code → Language enum 매핑
        lang_map = {
            "ko": Language.KO,
            "ko-KR": Language.KO_KR,
            "en": Language.EN,
        }
        language = lang_map.get(language_code, Language.KO)
        
        return GoogleTTSService(
            credentials_path=tts_config.get(
                "credentials_path",
                os.environ.get("GOOGLE_APPLICATION_CREDENTIALS", "")
            ),
            voice_id=tts_config.get("voice_name", "ko-KR-Chirp3-HD-Kore"),
            sample_rate=16000,
            # 문장 단위 재분할 방지: Gateway에서 넘어온 청크를 그대로 한 덩어리로 합성 (인사말 Phase1 잘림 방지)
            aggregate_sentences=False,
            push_text_frames=True,  # LLMFullResponseEndFrame을 하류(TTSCompleteNotifier)로 전달
            params=GoogleTTSService.InputParams(
                language=language,
                speaking_rate=tts_config.get("speaking_rate", 1.0),
            ),
        )
    
    async def stop(self):
        """파이프라인 중지"""
        if self._runner:
            try:
                await self._runner.stop_when_done()
            except Exception as e:
                logger.warning("pipecat_runner_stop_error", error=str(e))
