"""
Pipecat Voice Pipeline 조립.

SIP PBX RTP Worker와 연동해 통화당 Voice AI 파이프라인을 구성·실행한다.
- callee(착신번호) → owner로 테넌트 식별, OrganizationInfoManager 생성
- 레코딩: create_recording_processors(call_id)로 rec_input/rec_output 삽입
- 파이프라인: input → rec_input → vad → stt → rag_llm → tts → rec_output → output

사용:
  from src.websocket import manager as ws_manager
  from src.ai_voicebot.pipecat.pipeline_builder import PipelineBuilder  # 또는 VoiceAIPipelineBuilder (동일 클래스)

  builder = PipelineBuilder(on_call_ended=ws_manager.emit_call_ended)
  await builder.build_and_run(
      callee="1003",
      rtp_worker=rtp_worker,
      vad=vad, stt=stt, tts=tts, llm_client=llm_client,
      knowledge_service=knowledge_service,
      hitl_on_alert=...,
  )

  (VAD/STT/TTS/llm_client는 호출 측에서 생성해 전달. pipecat 또는 pipecat-services-* 패키지 사용.)
"""

import asyncio
from typing import Any, Callable, Dict, List, Optional

import structlog

from src.common.call_data_record_logger import log_call_data
from src.ai_voicebot.pipecat.rtp_transport import SIPPBXTransport
from src.ai_voicebot.pipecat.processors.recording_processor import create_recording_processors
from src.ai_voicebot.pipecat.processors.rag_processor import RAGLLMProcessor

logger = structlog.get_logger(__name__)

# Graceful shutdown: Pipeline 취소 대기 타임아웃 (초)
# Pipecat PipelineTask의 cancel_timeout(기본 20초)을 고려해 여유 있게 설정
PIPELINE_SHUTDOWN_TIMEOUT_SECS = 25.0

# Pipecat Pipeline / Task / Runner (선택 의존성)
try:
    from pipecat.pipeline.pipeline import Pipeline
    from pipecat.pipeline.task import PipelineTask, PipelineParams
    from pipecat.pipeline.runner import PipelineRunner
    _PIPECAT_AVAILABLE = True
except ImportError:
    Pipeline = None
    PipelineTask = None
    PipelineParams = None
    PipelineRunner = None
    _PIPECAT_AVAILABLE = False

# 바지인 제어: 새 API 사용 (DeprecationWarning 제거). 최소 N단어 말했을 때만 TTS 중단.
try:
    from pipecat.turns.user_start import MinWordsUserTurnStartStrategy
    from pipecat.turns.user_turn_strategies import UserTurnStrategies
    _USER_TURN_STRATEGIES_AVAILABLE = True
except ImportError:
    MinWordsUserTurnStartStrategy = None
    UserTurnStrategies = None
    _USER_TURN_STRATEGIES_AVAILABLE = False


class PipelineBuilder:
    """
    Voice AI 파이프라인 조립 및 실행.

    callee(착신번호)를 owner로 사용해 테넌트별 org_manager·RAGLLMProcessor를 구성하고,
    레코딩 프로세서를 포함한 Pipecat Pipeline을 빌드·실행한다.
    """

    def __init__(
        self,
        *,
        on_call_ended: Optional[Callable[[str], Any]] = None,
    ):
        """
        Args:
            on_call_ended: 통화 종료 시 호출할 콜백 (call_id). 예: emit_call_ended(call_id)
        """
        self._on_call_ended = on_call_ended
        self._greeting_tasks: Dict[str, asyncio.Task] = {}  # call_id -> greeting task

    def build_pipeline(
        self,
        rtp_worker: Any,
        *,
        vad: Any,
        stt: Any,
        tts: Any,
        llm_client: Any,
        rag_engine: Optional[Any] = None,
        org_manager: Optional[Any] = None,
        embedder: Optional[Any] = None,
        vector_db: Optional[Any] = None,
        knowledge_service: Optional[Any] = None,
        system_prompt: str = "",
        max_history_turns: int = 10,
        owner: Optional[str] = None,
        call_id: Optional[str] = None,
        hitl_on_alert: Optional[Callable[..., Any]] = None,
        stt_post_filter_config: Optional[Dict[str, Any]] = None,
        tts_sync_context: Optional[Dict[str, Any]] = None,
    ) -> Any:
        """
        Voice 파이프라인 인스턴스 생성 (실행하지 않음).

        Args:
            rtp_worker: RTP Worker (media_session.call_id, get_caller_audio_stream, send_audio_to_caller 제공)
            vad, stt, tts: Pipecat VAD/STT/TTS 프로세서
            llm_client: LLM 클라이언트 (RAGLLMProcessor용)
            rag_engine, org_manager, embedder, vector_db, knowledge_service: RAG/테넌트 옵션
            owner: 테넌트 ID (미지정 시 rtp_worker.media_session에서 추출 시도)
            call_id: 통화 ID (미지정 시 rtp_worker.media_session.call_id)
            hitl_on_alert: HITL 알림 콜백
            stt_post_filter_config, tts_sync_context: RAGLLMProcessor 옵션

        Returns:
            Pipeline 인스턴스 (pipecat.pipeline.Pipeline)
        """
        if not _PIPECAT_AVAILABLE:
            raise RuntimeError("pipecat.pipeline not available. Install pipecat-ai.")

        call_id = call_id or getattr(getattr(rtp_worker, "media_session", None), "call_id", "") or ""
        owner = owner or getattr(getattr(rtp_worker, "media_session", None), "callee", None) or call_id
        try:
            from src.common.sip_owner import normalize_owner_username
            owner = normalize_owner_username(owner) or owner
        except Exception:
            pass

        tts_sync_context = tts_sync_context or {}
        tts_sync_context["_call_id"] = call_id  # Notifier/Output 로그용 (Phase1→Phase2 연동)

        transport = SIPPBXTransport(rtp_worker, tts_sync_context=tts_sync_context)
        _, rec_input, rec_output = create_recording_processors(call_id)

        rag_llm = RAGLLMProcessor(
            llm_client=llm_client,
            rag_engine=rag_engine,
            org_manager=org_manager,
            embedder=embedder,
            vector_db=vector_db,
            system_prompt=system_prompt,
            max_history_turns=max_history_turns,
            owner=owner,
            call_id=call_id or None,
            hitl_on_alert=hitl_on_alert,
            tts_sync_context=tts_sync_context,
            stt_post_filter_config=stt_post_filter_config,
        )

        # TTS 완료 감지 프로세서 (Phase 1/2 인사말 동기화용)
        from src.ai_voicebot.pipecat.processors.tts_complete_notifier import TTSCompleteNotifier
        tts_complete_notifier = TTSCompleteNotifier(sync_context=tts_sync_context)

        # VAD 래퍼 추가 (로깅 및 모니터링)
        from src.ai_voicebot.pipecat.processors.vad_wrapper import wrap_vad_with_logging
        # 바지인 켬: 3단어 이상 시 AI 말 멈춤 (allow_interruptions=True + user_turn_strategies와 연동)
        vad_wrapped = wrap_vad_with_logging(vad, call_id=call_id, enable_barge_in=True)

        # 바지인 켬: Interruption* 프레임을 TTS까지 전달 (3단어 조건은 user_turn_strategies에서 MinWordsUserTurnStartStrategy로 시도)
        # LLMUserAggregator 미사용 시 VAD 기준으로 동작할 수 있음 — 필요 시 BargeInSuppressProcessor 재도입 가능
        processor_names = [
            "transport.input()",
            "rec_input",
            "vad_wrapped",
            "stt",
            "rag_llm",
            "tts",
            "tts_complete_notifier",
            "rec_output",
            "transport.output()",
        ]
        pipeline = Pipeline([
            transport.input(),
            rec_input,
            vad_wrapped,
            stt,
            rag_llm,
            tts,
            tts_complete_notifier,
            rec_output,
            transport.output(),
        ])
        logger.info(
            "pipeline_built",
            call_id=call_id,
            owner=owner,
            has_rag=rag_engine is not None,
            has_org_manager=org_manager is not None,
            processor_chain=processor_names,
            note="바지인 활성화 (allow_interruptions=True, enable_barge_in=True)",
        )
        
        # rag_llm 인스턴스를 반환하기 위해 pipeline에 속성으로 저장
        pipeline._rag_llm = rag_llm
        
        return pipeline

    async def build_and_run(
        self,
        callee: str,
        rtp_worker: Any,
        *,
        vad: Any,
        stt: Any,
        tts: Any,
        llm_client: Any,
        rag_engine: Optional[Any] = None,
        org_manager: Optional[Any] = None,
        embedder: Optional[Any] = None,
        vector_db: Optional[Any] = None,
        knowledge_service: Optional[Any] = None,
        system_prompt: str = "",
        max_history_turns: int = 10,
        hitl_on_alert: Optional[Callable[..., Any]] = None,
        stt_post_filter_config: Optional[Dict[str, Any]] = None,
        **kwargs: Any,
    ) -> None:
        """
        파이프라인 빌드 후 실행. 종료 시 on_call_ended(call_id) 호출.

        Args:
            callee: 착신번호 (owner로 사용)
            rtp_worker: RTP Worker
            vad, stt, tts, llm_client: 필수 Voice/AI 컴포넌트
            나머지: build_pipeline와 동일 (rag_engine, org_manager 등)
        """
        call_id = getattr(getattr(rtp_worker, "media_session", None), "call_id", "") or ""

        if not org_manager and knowledge_service:
            try:
                from src.ai_voicebot.knowledge.organization_info import OrganizationInfoManager
                org_manager = OrganizationInfoManager(owner=callee, knowledge_service=knowledge_service)
                await org_manager.load()
            except Exception as e:
                logger.warning("org_manager_load_failed", callee=callee, error=str(e))
                org_manager = None

        tts_sync_context: Dict[str, Any] = {}
        pipeline = self.build_pipeline(
            rtp_worker,
            vad=vad,
            stt=stt,
            tts=tts,
            llm_client=llm_client,
            rag_engine=rag_engine,
            org_manager=org_manager,
            embedder=embedder,
            vector_db=vector_db,
            knowledge_service=knowledge_service,
            system_prompt=system_prompt,
            max_history_turns=max_history_turns,
            owner=callee,
            call_id=call_id or None,
            hitl_on_alert=hitl_on_alert,
            stt_post_filter_config=stt_post_filter_config,
            tts_sync_context=tts_sync_context,
            **kwargs,
        )

        # HITL 응답 큐는 RAGLLMProcessor.__init__(동기)에서 등록되어 루프가 비어 있을 수 있음 →
        # WebSocket 스레드에서 enqueue 시 run_coroutine_threadsafe 하려면 여기(파이프라인 루프)에서 루프 고정
        if call_id:
            try:
                from src.services.hitl import get_hitl_service

                get_hitl_service().ensure_queue_loop(call_id)
            except Exception as e:
                logger.debug("hitl_ensure_queue_loop_failed", call_id=call_id, error=str(e))

        # 바지인 켬: 3단어 이상 말했을 때만 TTS 중단 (새 API: user_turn_strategies, DeprecationWarning 없음)
        if PipelineParams is None:
            _params = None
            task = PipelineTask(pipeline)
        else:
            _user_turn_strategies = None
            if _USER_TURN_STRATEGIES_AVAILABLE and MinWordsUserTurnStartStrategy is not None and UserTurnStrategies is not None:
                try:
                    _user_turn_strategies = UserTurnStrategies(
                        start=[MinWordsUserTurnStartStrategy(min_words=3)],
                    )
                except Exception as e:
                    logger.debug("user_turn_strategies_init_skip", error=str(e))
            # PipelineParams: allow_interruptions=True로 바지인 활성화 (interruption_strategies는 deprecated, 사용 안 함)
            _params = PipelineParams(allow_interruptions=True)
            try:
                if _user_turn_strategies is not None:
                    task = PipelineTask(pipeline, params=_params, user_turn_strategies=_user_turn_strategies)
                else:
                    task = PipelineTask(pipeline, params=_params)
            except TypeError:
                task = PipelineTask(pipeline, params=_params)
        logger.info(
            "pipecat_task_created",
            call_id=call_id,
            allow_interruptions=getattr(_params, "allow_interruptions", None) if _params else None,
            note="Task 생성 — 프레임은 processor_chain 순서로 흐름",
        )
        # StartFrame 미수신 시 STT 큐 백업 방지: 2초 후 Input Transport에서 오디오 루프 강제 시작
        # Pipecat Pipeline은 _processors = [source] + processors + [sink] 이므로,
        # 우리가 넘긴 첫 프로세서(transport.input())는 procs[1] (procs[0]=PipelineSource)
        async def _input_consumption_fallback():
            await asyncio.sleep(2.0)
            procs = getattr(pipeline, "processors", None)
            if not procs or len(procs) < 2:
                logger.warning("input_fallback_skipped",
                              call_id=call_id,
                              procs_len=len(procs) if procs else 0,
                              note="Pipeline processors 수 부족 — Input Transport 폴백 미실행")
                return
            # procs[1] = 우리가 넘긴 첫 번째 프로세서 = SIPPBXInputTransport
            input_proc = procs[1]
            has_ensure = hasattr(input_proc, "ensure_audio_loop_started")
            logger.info("input_fallback_check",
                       call_id=call_id,
                       proc_index=1,
                       proc_type=type(input_proc).__name__,
                       has_ensure_audio_loop_started=has_ensure,
                       note="2초 폴백: Input Transport 오디오 루프 강제 시작 시도")
            if has_ensure:
                input_proc.ensure_audio_loop_started()
                logger.info("input_fallback_applied",
                            call_id=call_id,
                            note="Input Transport ensure_audio_loop_started() 호출 완료 — 큐 소비 시작 예상")
            else:
                logger.warning("input_fallback_no_method",
                               call_id=call_id,
                               proc_type=type(input_proc).__name__,
                               note="ensure_audio_loop_started 없음 — STT 큐 백업 가능성")
        asyncio.create_task(_input_consumption_fallback())
        # handle_sigint=False: 서버에서 여러 통화가 동시에 있으면 각 PipelineRunner가
        # 자체 SIGINT 핸들러를 등록해 서로 덮어쓰므로, 앱 레벨에서 shutdown 처리
        runner = PipelineRunner(handle_sigint=False)

        # 인사말 자동 전송 (Pipeline 시작 후) - 취소 가능하도록 Task 보관
        greeting_task: Optional[asyncio.Task] = None

        async def _send_initial_greeting():
            """Pipeline 시작 후 초기 인사말 자동 전송"""
            await asyncio.sleep(0.5)  # Pipeline 초기화 대기
            try:
                if hasattr(pipeline, 'processors'):
                    for proc in pipeline.processors:
                        if hasattr(proc, 'send_greeting'):
                            await proc.send_greeting()
                            logger.info("initial_greeting_sent", call_id=call_id)
                            break
            except asyncio.CancelledError:
                pass
            except Exception as e:
                logger.warning("initial_greeting_failed", call_id=call_id, error=str(e))

        greeting_task = asyncio.create_task(_send_initial_greeting())
        self._greeting_tasks[call_id] = greeting_task

        procs = getattr(pipeline, "processors", None)
        logger.info("pipeline_runner_about_to_start",
                    call_id=call_id,
                    processor_count=len(procs) if procs else 0,
                    first_user_proc=type(procs[1]).__name__ if procs and len(procs) > 1 else None,
                    note="PipelineRunner.run() 진입 — StartFrame은 procs[0](Source)에서 procs[1](Input)으로 전달 예상")
        if call_id:
            log_call_data(call_id, "call_event", "call_connected", callee=callee or "")
            try:
                from src.api.routers.calls import register_active_call
                register_active_call(call_id, callee=callee or "", is_ai_handled=True)
            except Exception:
                pass
        try:
            await runner.run(task)
        except asyncio.CancelledError:
            # PipelineRunner.run()이 CancelledError를 흡수하므로 여기 도달하지 않을 수 있음.
            # 외부에서 task.cancel() 시 runner가 내부적으로 정리 후 정상 반환.
            logger.info("pipeline_cancelled", call_id=call_id)
        except Exception as e:
            logger.exception("pipeline_run_error", call_id=call_id, error=str(e))
        finally:
            # Greeting task 정리 (취소 시 즉시 종료)
            greeting_task = self._greeting_tasks.pop(call_id, None)
            if greeting_task and not greeting_task.done():
                greeting_task.cancel()
                try:
                    await greeting_task
                except asyncio.CancelledError:
                    pass

            # 프로세서 cleanup (VADWrapperProcessor 등 __input_frame_task_handler 정리로 dangling task 방지)
            procs = getattr(pipeline, "processors", None)
            if procs:
                for proc in procs:
                    cleanup = getattr(proc, "cleanup", None)
                    if callable(cleanup):
                        try:
                            await cleanup()
                        except asyncio.CancelledError:
                            pass
                        except Exception as e:
                            try:
                                logger.warning("processor_cleanup_failed",
                                               call_id=call_id,
                                               proc_type=type(proc).__name__,
                                               error=str(e))
                            except (ValueError, OSError):
                                pass

            stop_pipecat = getattr(rtp_worker, "stop_pipecat_mode", None)
            if callable(stop_pipecat):
                try:
                    stop_pipecat()
                except Exception as e:
                    try:
                        logger.warning("stop_pipecat_mode_failed", call_id=call_id, error=str(e))
                    except (ValueError, OSError):
                        pass  # 서버 종료 시 로그가 이미 닫혀 있을 수 있음
            if call_id:
                log_call_data(call_id, "call_event", "call_ended", callee=callee or "")
                try:
                    from src.api.routers.calls import unregister_active_call
                    unregister_active_call(call_id)
                except Exception:
                    pass
                # BYE/cleanup 시 해당 통화의 HITL 타임아웃 타이머 취소 (통화 종료 후 타임아웃 메시지 방지)
                try:
                    from src.services.hitl import get_hitl_service
                    get_hitl_service().cancel_timer(call_id)
                    get_hitl_service().unregister_call(call_id)
                except Exception:
                    pass
            if call_id and self._on_call_ended:
                try:
                    if asyncio.iscoroutinefunction(self._on_call_ended):
                        await self._on_call_ended(call_id)
                    else:
                        self._on_call_ended(call_id)
                except Exception as e:
                    logger.warning("on_call_ended_failed", call_id=call_id, error=str(e))


# 호출부에서 사용하는 이름 호환용 (import VoiceAIPipelineBuilder 시 동일 클래스 참조)
VoiceAIPipelineBuilder = PipelineBuilder


def build_pipeline(
    rtp_worker: Any,
    *,
    vad: Any,
    stt: Any,
    tts: Any,
    llm_client: Any,
    callee: Optional[str] = None,
    call_id: Optional[str] = None,
    **kwargs: Any,
) -> Any:
    """
    편의 함수: Pipeline만 빌드해 반환 (실행하지 않음).

    owner/callee 미지정 시 rtp_worker.media_session에서 추출 시도.
    """
    builder = PipelineBuilder()
    return builder.build_pipeline(
        rtp_worker,
        vad=vad,
        stt=stt,
        tts=tts,
        llm_client=llm_client,
        owner=callee,
        call_id=call_id,
        **kwargs,
    )
