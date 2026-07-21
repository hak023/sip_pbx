"""
셀프서비스 AI 도우미 QA 자동 테스트 엔드포인트 (BMAD QA 단계 전용).

실제 운영 파이프라인의 진입점(`ConversationAgent.process_utterance` — STT 결과 텍스트
입력 직후, TTS 변환 직전)을 그대로 재사용한다. 음성(rag_processor.py)·문자
(sip_message_ai_reply.py) 두 채널이 공통으로 거치는 지점과 동일한 함수이므로,
여기서 실행되는 RAG 검색·온보딩 체크리스트·Tool-calling(bind_tools, 실제 LLM 호출
포함)은 실제 통화·문자에서 일어나는 것과 100% 동일하다(모의 객체 없음).

⚠️ 테스트 전용: 실제 LLM·RAG·DB에 대해 부작용(설정 실제 변경 등)을 일으킬 수 있다.
   - `SELF_SERVICE_QA_TEST_MODE` 환경변수가 명시적으로 truthy일 때만 라우트가 동작한다
     (기본 비활성화 — 운영 환경에서 실수로 열려 있는 것을 방지).
   - 반드시 실 서비스 테넌트가 아닌 QA 전용 owner로 테스트할 것을 권장한다
     (자동설정 Tool이 실제로 persona/chat-relay 값을 변경할 수 있음).

세션(대화 맥락) 유지: owner+caller_number(또는 session_id) 조합별로
ConversationAgent 인스턴스를 캐싱해 멀티턴 시나리오(확인 발화 → 긍정 응답 등)를
테스트할 수 있다(`sip_message_ai_reply.py`의 `_agent_cache` 패턴과 동일).
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

router = APIRouter(prefix="/api/self-service/test", tags=["self-service-qa-test"])

_MAX_CACHED_AGENTS = 32
_agent_cache: "OrderedDict[str, Any]" = OrderedDict()


def _test_mode_enabled() -> bool:
    raw = (os.environ.get("SELF_SERVICE_QA_TEST_MODE") or "").strip().lower()
    return raw in ("1", "true", "yes", "on")


def _require_test_mode() -> None:
    if not _test_mode_enabled():
        raise HTTPException(
            status_code=403,
            detail=(
                "셀프서비스 QA 테스트 모드가 비활성화되어 있습니다. "
                "환경변수 SELF_SERVICE_QA_TEST_MODE=1 설정 후 서버를 재시작하세요."
            ),
        )


class ConverseRequest(BaseModel):
    owner: str = Field(..., description="테스트할 테넌트 owner(착신 내선번호)")
    text: str = Field(..., min_length=1, description="STT 결과라고 가정할 자연어 입력")
    caller_number: Optional[str] = Field(
        None, description="발신자 번호. 생략 시 owner와 동일(셀프서비스 세션 트리거)."
    )
    session_id: Optional[str] = Field(
        None, description="멀티턴 유지용 세션 키. 생략 시 owner+caller_number로 자동 생성."
    )
    reset_session: bool = Field(False, description="true면 기존 세션(에이전트·대화 맥락)을 폐기하고 새로 시작")


class ConverseResponse(BaseModel):
    response: str
    intent: Optional[str] = None
    business_state: Optional[str] = None
    confidence: Optional[float] = None
    is_self_service_session: bool
    call_id: str
    session_key: str
    elapsed_sec: float
    tool_trace: List[Dict[str, Any]]


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
    STT 직후 ~ TTS 직전 구간을 그대로 재현하는 QA 자동 테스트 엔드포인트.

    실제 `ConversationAgent.process_utterance()`(음성·채팅 파이프라인과 동일 함수)를
    호출해 RAG 검색·온보딩 체크리스트·Tool-calling(조회/통계/자동설정, 실제 LLM
    function-calling 포함)을 실행하고, 최종 응답 텍스트와 내부 Tool 호출 트레이스를
    반환한다.
    """
    _require_test_mode()

    owner = body.owner.strip()
    if not owner:
        raise HTTPException(status_code=400, detail="owner가 비어 있습니다.")
    caller_number = (body.caller_number or owner).strip()
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

    call_id = f"qatest-{uuid.uuid4().hex[:12]}"
    start = time.time()
    result = await agent.process_utterance(
        body.text,
        call_id=call_id,
        caller_number=caller_number,
    )
    elapsed = time.time() - start

    from src.api.utils.call_data_record_reader import read_call_data_record_for_call

    rows = read_call_data_record_for_call(call_id)
    tool_trace = [
        {k: v for k, v in r.items() if k != "call_id"}
        for r in rows
        if r.get("category") == "self_service"
    ]

    logger.info(
        "self_service_qa_test_converse",
        owner=owner, caller_number=caller_number, call_id=call_id, session_key=key,
        elapsed_sec=round(elapsed, 3), response_len=len(result.get("response") or ""),
        tool_trace_events=len(tool_trace),
    )

    return ConverseResponse(
        response=result.get("response") or "",
        intent=result.get("intent"),
        business_state=result.get("business_state"),
        confidence=result.get("confidence"),
        is_self_service_session=is_self_service_session(caller_number, owner),
        call_id=call_id,
        session_key=key,
        elapsed_sec=round(elapsed, 3),
        tool_trace=tool_trace,
    )


@router.post("/reset")
def reset_session(
    owner: str, caller_number: Optional[str] = None, session_id: Optional[str] = None,
) -> Dict[str, Any]:
    """캐시된 QA 테스트 세션(에이전트 인스턴스·대화 맥락)을 폐기한다."""
    _require_test_mode()
    key = _cache_key(owner.strip(), (caller_number or owner).strip(), session_id)
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
