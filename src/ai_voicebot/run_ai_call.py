"""
AI 음성 통화 단일 진입점.

기존 AI 응대 로직을 파이프라인 한 번 실행으로 대체한다.
CallManager(또는 RTP Worker)는 "AI 통화 시작" 시 이 모듈의 run_ai_voice_pipeline 만 호출하면 된다.

사용:
  from src.ai_voicebot.run_ai_call import run_ai_voice_pipeline

  await run_ai_voice_pipeline(
      callee="1003",
      rtp_worker=rtp_worker,
      vad=vad, stt=stt, tts=tts, llm_client=llm_client,
      knowledge_service=knowledge_service,
  )
"""

import asyncio
from typing import Any, Callable, Optional

import structlog

from src.ai_voicebot.pipecat.pipeline_builder import PipelineBuilder

logger = structlog.get_logger(__name__)


def _get_call_id(rtp_worker: Any) -> str:
    return getattr(getattr(rtp_worker, "media_session", None), "call_id", "") or ""


async def run_ai_voice_pipeline(
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
    stt_post_filter_config: Optional[dict] = None,
    **kwargs: Any,
) -> None:
    """
    AI 음성 통화를 파이프라인으로 실행 (기존 AI 응대 코드 대체용 단일 진입점).

    - 통화 시작 시 emit_call_started 발송
    - PipelineBuilder.build_and_run 실행 (레코딩·RAG·HITL·통화 종료 정리 포함)
    - 통화 종료 시 emit_call_ended 발송 (build_and_run 내부에서 호출)

    Args:
        callee: 착신번호 (owner로 사용)
        rtp_worker: RTP Worker (media_session.call_id, get_caller_audio_stream, send_audio_to_caller)
        vad, stt, tts, llm_client: 필수 Voice/AI 컴포넌트
        knowledge_service: 있으면 OrganizationInfoManager 생성
        hitl_on_alert: 미지정 시 emit_hitl_requested 연동 콜백으로 설정
        나머지: PipelineBuilder.build_and_run 와 동일
    """
    call_id = _get_call_id(rtp_worker)

    # 통화 시작 이벤트
    try:
        from src.websocket import manager as ws_manager
        await ws_manager.emit_call_started(call_id, {
            "callee": callee,
            "is_ai_handled": True,
            "status": "AI 응대 중",
            "sip_phase": "ai_active"
        })
    except Exception as e:
        logger.warning("emit_call_started_failed", call_id=call_id, error=str(e))
    
    # API 레지스트리에도 등록 (REST API /api/calls/active에서 참조)
    try:
        from src.api.routers.calls import register_active_call
        register_active_call(
            call_id=call_id,
            callee=callee,
            caller="",
            is_ai_handled=True
        )
    except Exception as reg_err:
        logger.debug("register_active_call_failed", call_id=call_id, error=str(reg_err))

    # CallManager.ai_enabled_calls에도 등록 (REST 폴링에서 is_ai_handled 판정용)
    try:
        from src.api.routers.calls import _call_manager as _cm
        if _cm is not None and hasattr(_cm, "ai_enabled_calls"):
            _cm.ai_enabled_calls.add(call_id)
            logger.info("ai_enabled_calls_registered",
                        call_id=call_id,
                        note="run_ai_call에서 ai_enabled_calls에 추가 (호전환 버튼 표시용)")
    except Exception as ae_err:
        logger.debug("ai_enabled_calls_register_failed", call_id=call_id, error=str(ae_err))

    # HITL 알림 시 프론트로 전달 (미지정 시 기본 연동)
    if hitl_on_alert is None:
        try:
            from src.websocket import manager as ws_manager
            async def _default_hitl_alert(cid: str, question: str, context: dict, urgency: str = "medium"):
                await ws_manager.emit_hitl_requested(cid, question, context, urgency)
            hitl_on_alert = _default_hitl_alert
        except Exception as e:
            logger.debug("hitl_on_alert_default_failed", error=str(e))

    # 통화 종료 시 HITL 해제·이벤트 (파이프라인 내부에서 호출)
    async def _on_call_ended(cid: str) -> None:
        try:
            from src.websocket import manager as ws_manager
            await ws_manager.emit_call_ended(cid)
        except Exception as e:
            logger.warning("emit_call_ended_failed", call_id=cid, error=str(e))

    builder = PipelineBuilder(on_call_ended=_on_call_ended)
    await builder.build_and_run(
        callee=callee,
        rtp_worker=rtp_worker,
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
        hitl_on_alert=hitl_on_alert,
        stt_post_filter_config=stt_post_filter_config,
        **kwargs,
    )
