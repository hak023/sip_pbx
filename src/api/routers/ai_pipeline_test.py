"""
AI 음성 파이프라인(일반 경로) QA 자동 테스트 엔드포인트 — voice-latency-turn-taking Story 3.2/4.1/4.2 검증용.

`src/api/routers/self_service_test.py`와 동일한 원칙: 실제 운영 파이프라인의 진입점
(`ConversationAgent.process_utterance` — STT 결과 텍스트 입력 직후, TTS 변환 직전)을
그대로 재사용한다. 음성(rag_processor.py)·문자(sip_message_ai_reply.py) 두 채널이
공통으로 거치는 지점과 동일한 함수이므로, RAG 검색·LangGraph 오케스트레이션(캐시/HITL
판단 포함, 실제 LLM 호출)은 실제 통화·문자와 100% 동일하다(모의 객체 없음).

self_service_test.py와의 차이: `caller_number`를 `owner`와 다르게 지정해 일반(비셀프서비스)
질의응답·잡담·인사 경로(classify_intent → route_utterance → generate_response → hitl_alert)를
재현하고, 응답 지연 계측 필드(`llm_first_sentence_elapsed_sec` 등)를 그대로 노출한다.
`ai_response_latency_compare.py`의 RTP 레벨 계측(T0/T5 등, `rag_processor.py`/`rtp_transport.py`
전용)은 이 엔드포인트로 재현되지 않는다 — 어디까지나 "STT 직후 ~ TTS 직전" 텍스트 레벨
검증용이다(실제 오디오 왕복 지연은 실서버 통화로만 검증 가능, 별도 명시).

⚠️ 테스트 전용: 실제 LLM·RAG·DB에 대해 부작용을 일으킬 수 있다.
   - `AI_PIPELINE_QA_TEST_MODE` 환경변수가 명시적으로 truthy일 때만 라우트가 동작한다
     (기본 비활성화).
"""

from __future__ import annotations

import os
import time
import uuid
from collections import OrderedDict
from typing import Any, Dict, List, Optional

import structlog
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

logger = structlog.get_logger(__name__)

router = APIRouter(prefix="/api/ai-pipeline/test", tags=["ai-pipeline-qa-test"])

_MAX_CACHED_AGENTS = 32
_agent_cache: "OrderedDict[str, Any]" = OrderedDict()


def _test_mode_enabled() -> bool:
    raw = (os.environ.get("AI_PIPELINE_QA_TEST_MODE") or "").strip().lower()
    return raw in ("1", "true", "yes", "on")


def _require_test_mode() -> None:
    if not _test_mode_enabled():
        raise HTTPException(
            status_code=403,
            detail=(
                "AI 파이프라인 QA 테스트 모드가 비활성화되어 있습니다. "
                "환경변수 AI_PIPELINE_QA_TEST_MODE=1 설정 후 서버를 재시작하세요."
            ),
        )


class ConverseRequest(BaseModel):
    owner: str = Field(..., description="테스트할 테넌트 owner(착신 내선번호)")
    text: str = Field(..., min_length=1, description="STT 결과라고 가정할 자연어 입력")
    caller_number: Optional[str] = Field(
        None,
        description=(
            "발신자 번호. owner와 달라야 일반(비셀프서비스) 경로가 재현된다. "
            "생략 시 owner와 다른 고정 테스트 번호를 자동 사용."
        ),
    )
    session_id: Optional[str] = Field(
        None, description="멀티턴 유지용 세션 키. 생략 시 owner+caller_number로 자동 생성."
    )
    reset_session: bool = Field(False, description="true면 기존 세션(에이전트·대화 맥락)을 폐기하고 새로 시작")


class ConverseResponse(BaseModel):
    response: str
    response_chunk_count: int
    intent: Optional[str] = None
    confidence: Optional[float] = None
    needs_human: Optional[bool] = None
    needs_follow_up: Optional[bool] = None
    is_self_service_session: bool
    agent_elapsed_sec: float
    llm_first_sentence_elapsed_sec: Optional[float] = None
    llm_first_sentence_source: Optional[str] = None
    call_id: str
    session_key: str


def _cache_key(owner: str, caller_number: str, session_id: Optional[str]) -> str:
    if session_id:
        return f"sid:{session_id.strip()}"
    return f"{owner}:{caller_number}"


async def _get_or_create_agent(key: str, owner: str):
    from src.ai_voicebot.factory import get_ai_orchestrator, get_llm_client
    from src.ai_voicebot.langgraph.agent import ConversationAgent

    agent = _agent_cache.get(key)
    if agent is not None:
        return agent

    llm = get_llm_client()
    orch = get_ai_orchestrator()
    if llm is None or orch is None:
        return None

    rag = getattr(orch, "rag", None)
    embedder = getattr(rag, "embedder", None) if rag else None
    vector_db = getattr(rag, "vector_db", None) if rag else None
    org_manager = getattr(orch, "org_manager", None)

    agent = ConversationAgent(
        llm_client=llm,
        rag_engine=rag,
        embedder=embedder,
        vector_db=vector_db,
        org_manager=org_manager,
        owner=owner,
    )
    _agent_cache[key] = agent
    _agent_cache.move_to_end(key)
    while len(_agent_cache) > _MAX_CACHED_AGENTS:
        _agent_cache.popitem(last=False)
    return agent


@router.post("/converse", response_model=ConverseResponse)
async def converse(body: ConverseRequest) -> ConverseResponse:
    """
    STT 직후 ~ TTS 직전 구간을 그대로 재현하는 일반 경로 QA 테스트 엔드포인트.

    voice-latency-turn-taking Story 3.2(5초 SLA 원인 태깅)/4.1~4.2(TTFT)의 텍스트 레벨
    동작(intent 분류, needs_human/needs_follow_up 확정 시점, response_chunks 분할)을
    실제 통화 없이 검증하기 위한 용도.
    """
    _require_test_mode()

    owner = body.owner.strip()
    if not owner:
        raise HTTPException(status_code=400, detail="owner가 비어 있습니다.")
    # 기본값: owner와 다른 고정 테스트 번호 — 자기 자신에게 거는 셀프서비스 세션과
    # 혼동되지 않도록(is_self_service_session=False 보장).
    caller_number = (body.caller_number or f"{owner}-qa-caller").strip()
    key = _cache_key(owner, caller_number, body.session_id)

    if body.reset_session:
        _agent_cache.pop(key, None)

    agent = await _get_or_create_agent(key, owner)
    if agent is None:
        raise HTTPException(
            status_code=503,
            detail="AI 시스템(LLM/RAG)이 아직 초기화되지 않았습니다. 서버 기동 로그(AI Orchestrator initialized)를 확인하세요.",
        )

    from src.ai_voicebot.self_service.detection import is_self_service_session

    call_id = f"aiptest-{uuid.uuid4().hex[:12]}"
    start = time.time()
    result = await agent.process_utterance(
        body.text,
        call_id=call_id,
        caller_number=caller_number,
    )
    elapsed = time.time() - start

    response_chunks: List[str] = result.get("response_chunks") or []

    logger.info(
        "ai_pipeline_qa_test_converse",
        owner=owner, caller_number=caller_number, call_id=call_id, session_key=key,
        elapsed_sec=round(elapsed, 3),
        intent=result.get("intent"),
        response_len=len(result.get("response") or ""),
        response_chunk_count=len(response_chunks),
        needs_human=result.get("needs_human"),
    )

    return ConverseResponse(
        response=result.get("response") or "",
        response_chunk_count=len(response_chunks),
        intent=result.get("intent"),
        confidence=result.get("confidence"),
        needs_human=result.get("needs_human"),
        needs_follow_up=result.get("needs_follow_up"),
        is_self_service_session=is_self_service_session(caller_number, owner),
        agent_elapsed_sec=round(elapsed, 3),
        llm_first_sentence_elapsed_sec=result.get("llm_first_sentence_elapsed_sec"),
        llm_first_sentence_source=result.get("llm_first_sentence_source"),
        call_id=call_id,
        session_key=key,
    )


@router.post("/reset")
def reset_session(
    owner: str, caller_number: Optional[str] = None, session_id: Optional[str] = None,
) -> Dict[str, Any]:
    """캐시된 QA 테스트 세션(에이전트 인스턴스·대화 맥락)을 폐기한다."""
    _require_test_mode()
    key = _cache_key(owner.strip(), (caller_number or f"{owner}-qa-caller").strip(), session_id)
    existed = _agent_cache.pop(key, None) is not None
    return {"ok": True, "reset": existed, "session_key": key}


@router.get("/status")
def test_mode_status() -> Dict[str, Any]:
    """QA 테스트 모드 활성화 여부와 AI 시스템 준비 상태를 확인한다(가드 없이 조회 가능)."""
    from src.ai_voicebot.factory import get_ai_orchestrator, get_llm_client

    return {
        "test_mode_enabled": _test_mode_enabled(),
        "llm_ready": get_llm_client() is not None,
        "orchestrator_ready": get_ai_orchestrator() is not None,
        "cached_sessions": len(_agent_cache),
    }
