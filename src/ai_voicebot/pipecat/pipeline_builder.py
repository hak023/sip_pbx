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
      owner="1003",
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
        is_outbound: bool = False,
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

        _ms_c = getattr(rtp_worker, "media_session", None)
        _caller_for_sms = ""
        if _ms_c is not None:
            _raw_c = getattr(_ms_c, "caller_identity", None) or getattr(_ms_c, "caller", None) or ""
            if isinstance(_raw_c, dict):
                _caller_for_sms = str(_raw_c.get("number") or _raw_c.get("uri") or "").strip()
            else:
                _caller_for_sms = str(_raw_c).strip()

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
            caller_id=_caller_for_sms or None,
            call_id=call_id or None,
            hitl_on_alert=hitl_on_alert,
            tts_sync_context=tts_sync_context,
            stt_post_filter_config=stt_post_filter_config,
            # 개선안 3: Debounce 비활성화 → 즉시 처리 + Supersede 방식으로 분할 STT 병합
            stt_final_debounce_sec=0.0,
            rtp_worker=rtp_worker,
        )

        # TTS 완료 감지 프로세서 (Phase 1/2 인사말 동기화용)
        from src.ai_voicebot.pipecat.processors.tts_complete_notifier import TTSCompleteNotifier
        tts_complete_notifier = TTSCompleteNotifier(sync_context=tts_sync_context)

        from src.ai_voicebot.pipecat.processors.korean_tts_number_processor import KoreanTTSNumberProcessor
        korean_tts_numbers = KoreanTTSNumberProcessor(call_id=call_id)

        # VAD 래퍼 추가 (로깅 및 모니터링)
        from src.ai_voicebot.pipecat.processors.vad_wrapper import wrap_vad_with_logging
        # TTS 재생 중 STT 입력 억제 — 임시 비활성화 (에코 원인 재검토 중)
        # 실제 에코가 아닌 두 턴 발화 얽힘으로 판단, 스피커폰 미사용 환경에서 에코 없음 확인 필요
        vad_wrapped = wrap_vad_with_logging(
            vad,
            call_id=call_id,
            enable_barge_in=True,
            suppress_stt_during_tts=False,
            tts_sync_context=None,
        )
        logger.info(
            "vad_wrapper_suppress_stt_configured",
            call_id=call_id,
            is_outbound=is_outbound,
            suppress_stt_during_tts=False,
            note="TTS 중 STT 억제 임시 비활성화 (에코 원인 재검토 중)",
        )

        # 바지인 켬: Interruption* 프레임을 TTS까지 전달 (3단어 조건은 user_turn_strategies에서 MinWordsUserTurnStartStrategy로 시도)
        # LLMUserAggregator 미사용 시 VAD 기준으로 동작할 수 있음 — 필요 시 BargeInSuppressProcessor 재도입 가능
        processor_names = [
            "transport.input()",
            "rec_input",
            "vad_wrapped",
            "stt",
            "rag_llm",
            "korean_tts_numbers",
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
            korean_tts_numbers,
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
        owner: str,
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
        outbound_purpose: str = "",
        outbound_questions: Optional[list] = None,
        hangup_callback: Optional[Callable[..., Any]] = None,
        greeting_override: Optional[str] = None,
        **kwargs: Any,
    ) -> None:
        """
        파이프라인 빌드 후 실행. 종료 시 on_call_ended(call_id) 호출.

        Args:
            owner: KB/페르소나 로드 기준 테넌트 ID.
                   인바운드: callee(착신번호), 아웃바운드: caller_number(AI봇 발신번호).
            rtp_worker: RTP Worker
            vad, stt, tts, llm_client: 필수 Voice/AI 컴포넌트
            outbound_purpose: 아웃바운드 통화 목적 (미션 완료 감지용)
            outbound_questions: 아웃바운드 확인 질문 목록 (모두 답변 시 자동 BYE)
            hangup_callback: 미션 완료 시 호출할 BYE 콜백 async def cb(call_id: str)
            나머지: build_pipeline와 동일 (rag_engine, org_manager 등)
        """
        call_id = getattr(getattr(rtp_worker, "media_session", None), "call_id", "") or ""

        if not org_manager and knowledge_service:
            try:
                from src.ai_voicebot.knowledge.organization_info import OrganizationInfoManager
                org_manager = OrganizationInfoManager(owner=owner, knowledge_service=knowledge_service)
                await org_manager.load()
            except Exception as e:
                logger.warning("org_manager_load_failed", owner=owner, error=str(e))
                org_manager = None

        tts_sync_context: Dict[str, Any] = {}
        _is_outbound = bool(outbound_purpose or outbound_questions)
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
            owner=owner,
            call_id=call_id or None,
            hitl_on_alert=hitl_on_alert,
            stt_post_filter_config=stt_post_filter_config,
            tts_sync_context=tts_sync_context,
            is_outbound=_is_outbound,
            **kwargs,
        )

        # 아웃바운드 미션 설정: pipeline._rag_llm에 purpose/questions/hangup_callback 주입
        if outbound_purpose or outbound_questions:
            rag_llm = getattr(pipeline, "_rag_llm", None)
            if rag_llm is not None and hasattr(rag_llm, "set_outbound_mission"):
                rag_llm.set_outbound_mission(
                    purpose=outbound_purpose,
                    questions=outbound_questions or [],
                    hangup_callback=hangup_callback,
                )
                logger.info("outbound_mission_injected",
                            call_id=call_id,
                            purpose=outbound_purpose[:50] if outbound_purpose else "",
                            question_count=len(outbound_questions or []))
            else:
                logger.warning("outbound_mission_inject_failed",
                               call_id=call_id,
                               note="pipeline._rag_llm 없음 또는 set_outbound_mission 미지원")

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
                    # Story 5.4 (2026-07-29): 옵트인 스마트 barge-in 판단 전략.
                    # config.yaml의 ai_voicebot.barge_in.smart_judge_enabled=true일 때만
                    # SmartBargeInUserTurnStartStrategy로 교체(기본 False → 기존 MinWords 그대로,
                    # 회귀 위험 없음). 두 전략을 동시에 넣지 않는다 — user_turn_strategies의
                    # 다중 start 전략은 OR로 동작해 나란히 두면 오히려 더 민감해지기만 하기 때문.
                    _smart_judge_enabled = False
                    try:
                        from src.config.config_loader import load_config
                        _cfg = load_config()
                        _barge_in_cfg = (
                            getattr(getattr(_cfg, "ai_voicebot", None), "barge_in", None) or {}
                        )
                        _smart_judge_enabled = bool(_barge_in_cfg.get("smart_judge_enabled", False))
                    except Exception as e:
                        logger.debug("smart_barge_in_config_load_skip", error=str(e))

                    if _smart_judge_enabled:
                        from src.ai_voicebot.pipecat.smart_barge_in_turn_strategy import (
                            SmartBargeInUserTurnStartStrategy,
                        )
                        _min_words = int((_barge_in_cfg or {}).get("min_words", 3))
                        _start_strategy = SmartBargeInUserTurnStartStrategy(
                            min_words=_min_words, llm_client=llm_client,
                        )
                        logger.info(
                            "smart_barge_in_enabled",
                            call_id=call_id,
                            min_words=_min_words,
                            note="Story 5.4 스마트 barge-in 판단 전략 활성화(config 옵트인)",
                        )
                    else:
                        _start_strategy = MinWordsUserTurnStartStrategy(min_words=3)

                    # Story 7.1 Task 4 (2026-07-29): pipecat 기본값으로 암묵 적용되던 Smart Turn
                    # v3.2 stop 전략(TurnAnalyzerUserTurnStopStrategy+LocalSmartTurnAnalyzerV3)을
                    # 명시적으로 구성하고, 순수 관측용 이벤트 핸들러만 추가한다. 판단 로직은
                    # 전혀 건드리지 않는다(핸들러는 `on_user_turn_stopped` 발생 시 로깅만 수행,
                    # 기존 내부 처리와 별개로 병렬 실행되어 회귀 위험 없음). 이 관측 로그로
                    # Story 7.2(개선 방안 설계 결정)에 필요한 실제 판정 시각·빈도 데이터를 쌓는다.
                    _stop_strategies = None
                    try:
                        from src.ai_voicebot.pipecat.smart_turn_stop_observer import (
                            build_observed_smart_turn_stop_strategy,
                        )
                        _stop_strategy = build_observed_smart_turn_stop_strategy(call_id=call_id)
                        if _stop_strategy is not None:
                            _stop_strategies = [_stop_strategy]
                    except Exception as e:
                        logger.debug("smart_turn_stop_observer_init_skip", error=str(e))

                    if _stop_strategies is not None:
                        _user_turn_strategies = UserTurnStrategies(
                            start=[_start_strategy], stop=_stop_strategies
                        )
                    else:
                        # 관측 전략 구성 실패 시 pipecat 기본값(stop 미지정)으로 폴백 —
                        # 기존 동작과 동일하게 유지(회귀 없음).
                        _user_turn_strategies = UserTurnStrategies(start=[_start_strategy])
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
            """Pipeline 시작 후 초기 인사말 자동 전송.

            greeting_override가 있으면 Call Control 안내멘트 텍스트를 우선 사용한다.
            """
            await asyncio.sleep(0.5)  # Pipeline 초기화 대기
            try:
                rag_llm = getattr(pipeline, "_rag_llm", None)
                if greeting_override:
                    # Call Control 안내멘트 텍스트 우선 재생
                    send_custom = getattr(rag_llm, "send_greeting", None) if rag_llm is not None else None
                    if callable(send_custom):
                        await send_custom(text=greeting_override)
                        logger.info(
                            "initial_greeting_sent_override",
                            call_id=call_id,
                            source="call_control_announcement",
                        )
                    else:
                        logger.warning(
                            "initial_greeting_override_skipped_no_send",
                            call_id=call_id,
                            note="send_greeting 없음 — greeting_override 미적용",
                        )
                else:
                    send = getattr(rag_llm, "send_greeting", None) if rag_llm is not None else None
                    if callable(send):
                        await send()
                        logger.info("initial_greeting_sent", call_id=call_id, via="pipeline._rag_llm")
                    else:
                        logger.warning(
                            "initial_greeting_skipped_no_rag_llm",
                            call_id=call_id,
                            has_attr=rag_llm is not None,
                            note="build_pipeline이 pipeline._rag_llm을 설정하지 않았거나 send_greeting 없음",
                        )
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
            log_call_data(call_id, "call_event", "call_connected", callee=owner or "")
            try:
                from src.api.routers.calls import register_active_call
                register_active_call(call_id, callee=owner or "", is_ai_handled=True)
            except Exception:
                pass
            # P3: 통화 시작 시 call_records DB upsert
            try:
                from src.common.call_record_db import upsert_call_record
                from datetime import datetime as _dt, timezone as _tz
                _ms = getattr(rtp_worker, "media_session", None)
                _caller = ""
                if _ms is not None:
                    _caller = (
                        getattr(_ms, "caller_identity", None)
                        or getattr(_ms, "caller", None)
                        or ""
                    )
                if isinstance(_caller, dict):
                    _caller = _caller.get("number", "") or _caller.get("uri", "") or ""
                _callee_for_row = owner or ""
                if _ms is not None and (getattr(_ms, "callee_identity", None) or "").strip():
                    _callee_for_row = (getattr(_ms, "callee_identity", "") or "").strip()
                _direction = "outbound" if (call_id or "").startswith("outbound-") else "inbound"
                upsert_call_record(
                    call_id=call_id,
                    owner=owner or "",
                    caller_id=str(_caller).strip(),
                    callee_id=_callee_for_row,
                    direction=_direction,
                    start_time=_dt.now(_tz.utc).isoformat().replace("+00:00", "Z"),
                    is_ai_handled=True,
                )
            except Exception as _e:
                logger.debug("call_record_start_upsert_failed", call_id=call_id, error=str(_e))
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
                log_call_data(call_id, "call_event", "call_ended", callee=owner or "")
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
                # P3: 통화 종료 시 call_records DB upsert (종료 시각·녹음·대본 갱신)
                try:
                    from src.common.call_record_db import upsert_call_record
                    from datetime import datetime as _dt, timezone as _tz
                    from src.api.routers.call_history import _find_call_dir, _recordings_root
                    _end_now = _dt.now(_tz.utc).isoformat().replace("+00:00", "Z")
                    _call_dir = _find_call_dir(call_id)
                    _has_rec = (_call_dir / "mixed.wav").is_file() if _call_dir else False
                    _has_ts = (_call_dir / "transcript.txt").is_file() if _call_dir else False
                    _rec_dir = str(_call_dir) if _call_dir else ""
                    # call_insights.json에서 요약·AI 미처리 건수 읽기
                    _summary = None
                    _ai_unhandled = 0
                    _is_ai = True
                    if _call_dir:
                        try:
                            from src.common.call_insights_buffer import load_call_insights_for_directory
                            _ins = load_call_insights_for_directory(_call_dir)
                            if _ins:
                                _summary = _ins.get("call_summary") or None
                                _ai_unhandled = int(_ins.get("ai_unhandled_count") or 0)
                                _is_ai = bool(_ins.get("is_ai_handled_call", True))
                        except Exception:
                            pass
                    _ms_end = getattr(rtp_worker, "media_session", None)
                    _cid_fill = (
                        (getattr(_ms_end, "caller_identity", None) or "").strip()
                        if _ms_end is not None
                        else ""
                    )
                    _callee_fill = (
                        (getattr(_ms_end, "callee_identity", None) or "").strip()
                        if _ms_end is not None
                        else ""
                    )
                    _end_kw: dict = dict(
                        call_id=call_id,
                        end_time=_end_now,
                        call_summary=_summary,
                        is_ai_handled=_is_ai,
                        ai_unhandled_count=_ai_unhandled,
                        has_recording=_has_rec,
                        has_transcript=_has_ts,
                        recordings_dir=_rec_dir,
                    )
                    if _cid_fill:
                        _end_kw["caller_id"] = _cid_fill
                    if _callee_fill:
                        _end_kw["callee_id"] = _callee_fill
                    upsert_call_record(**_end_kw)
                    # 발신자 연락처 자동 생성 (수동 없을 때만) — LLM·예약 힌트
                    _excerpt = ""
                    if _call_dir and (_call_dir / "transcript.txt").is_file():
                        try:
                            _excerpt = (_call_dir / "transcript.txt").read_text(
                                encoding="utf-8", errors="ignore"
                            )[:4000]
                        except OSError:
                            _excerpt = ""
                    _rag_llm = getattr(pipeline, "_rag_llm", None)
                    _llm_for_contact = getattr(_rag_llm, "_llm", None) if _rag_llm is not None else None
                    if (
                        call_id
                        and _llm_for_contact is not None
                        and (owner or "").strip()
                        and (_cid_fill or "").strip()
                    ):
                        try:
                            from src.services.caller_contact_autofill import (
                                schedule_caller_contact_autofill,
                            )

                            schedule_caller_contact_autofill(
                                llm=_llm_for_contact,
                                owner=owner or "",
                                caller_raw=_cid_fill,
                                call_id=call_id,
                                call_summary=_summary,
                                transcript_excerpt=_excerpt,
                            )
                        except Exception as _acf_e:
                            logger.debug(
                                "caller_contact_autofill_schedule_failed",
                                call_id=call_id,
                                error=str(_acf_e),
                            )
                except Exception as _e:
                    logger.debug("call_record_end_upsert_failed", call_id=call_id, error=str(_e))
            # 통화 종료 SIP MESSAGE(RCS) 요약 — WS(emit_call_ended) 지연 방지를 위해 백그라운드 태스크
            rag_llm = getattr(pipeline, "_rag_llm", None)
            if call_id and rag_llm is not None and hasattr(rag_llm, "send_end_call_summary_sms_async"):
                async def _pipecat_end_call_sms_bg() -> None:
                    try:
                        await asyncio.wait_for(rag_llm.send_end_call_summary_sms_async(), timeout=120.0)
                    except asyncio.TimeoutError:
                        logger.warning("pipecat_end_call_sms_timeout", call_id=call_id)
                    except Exception as _sms_e:
                        logger.warning(
                            "pipecat_end_call_sms_failed",
                            call_id=call_id,
                            error=str(_sms_e),
                        )

                try:
                    asyncio.create_task(_pipecat_end_call_sms_bg())
                except Exception as _sched_e:
                    logger.warning(
                        "pipecat_end_call_sms_task_failed",
                        call_id=call_id,
                        error=str(_sched_e),
                    )
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
