"""
응답 시뮬레이터 API (Story 1.27, FR32-B).

설계: docs/architecture/self-service-ai-assistant-architecture.md §Story 1.27(v0.16) —
신규 로직은 이 파일뿐이며, 나머지는 모두 기존 검증된 구성요소를 재사용한다.

  1. 실행 경로: `self_service_test.py`와 동일하게 `ConversationAgent.process_utterance()`를
     직접 호출한다(격리 세션, `_agent_cache`에 등록하지 않는 1회성 실행 — AC3). caller_number는
     반드시 owner와 동일해야 `is_self_service_session()`이 True가 되어 실제 self_service_agent
     경로를 탄다(detection.py 판별 규칙, self_service_test.py의 기본 동작과 동일).
  2. RAG 매칭 근거: `self_service_agent.py`가 남기는 `self_service_rag_search` call_data_record
     이벤트(Story 1.27에서 matched_doc_ids/scores/related_domains 필드 추가)를 call_id로 조회한다.
  3. IntelliDecision 판정: `decision_rationale._capture_and_log()`를 fire-and-forget이 아니라
     직접 `await`해 `(matched_type, reasoning_summary)`를 그대로 응답에 싣는다.

엔드포인트
-----------
  POST /api/knowledge-base/simulate   owner+query -> 매칭 문서 + 유형/근거 + 응답 + 소요 시간
"""

from __future__ import annotations

import time
import uuid
from typing import Any, Dict, List

import structlog
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

logger = structlog.get_logger(__name__)

router = APIRouter(prefix="/api/knowledge-base", tags=["knowledge-base-simulate"])


class SimulateRequest(BaseModel):
    owner: str = Field(..., description="시뮬레이션할 테넌트 owner(착신 내선번호)")
    query: str = Field(..., min_length=1, description="예시 발화(질문)")


class MatchedDocument(BaseModel):
    doc_id: str
    score: float
    related_domain: str


class SimulateResponse(BaseModel):
    response: str
    matched_documents: List[MatchedDocument]
    intellidecision_type: str
    reasoning_summary: str
    elapsed_sec: float


async def _get_isolated_agent(owner: str):
    """`_agent_cache`에 등록하지 않는 1회성 격리 에이전트를 생성한다(AC3)."""
    from src.ai_voicebot.factory import get_ai_orchestrator, get_llm_client
    from src.ai_voicebot.langgraph.agent import ConversationAgent

    llm = get_llm_client()
    orch = get_ai_orchestrator()
    if llm is None or orch is None:
        return None

    rag = getattr(orch, "rag", None)
    embedder = getattr(rag, "embedder", None) if rag else None
    vector_db = getattr(rag, "vector_db", None) if rag else None
    org_manager = getattr(orch, "org_manager", None)

    return ConversationAgent(
        llm_client=llm,
        rag_engine=rag,
        embedder=embedder,
        vector_db=vector_db,
        org_manager=org_manager,
        owner=owner,
    )


def _extract_matched_documents(call_id: str) -> List[MatchedDocument]:
    from src.api.utils.call_data_record_reader import read_call_data_record_for_call

    rows = read_call_data_record_for_call(call_id)
    for row in rows:
        if row.get("category") == "self_service" and row.get("event") == "self_service_rag_search":
            doc_ids = row.get("matched_doc_ids") or []
            scores = row.get("scores") or []
            domains = row.get("related_domains") or []
            return [
                MatchedDocument(
                    doc_id=str(doc_ids[i]) if i < len(doc_ids) else "",
                    score=float(scores[i]) if i < len(scores) else 0.0,
                    related_domain=str(domains[i]) if i < len(domains) else "",
                )
                for i in range(len(doc_ids))
            ]
    return []


@router.post("/simulate", response_model=SimulateResponse)
async def simulate(body: SimulateRequest) -> SimulateResponse:
    """실제 통화/채팅 세션에 부수효과 없이 매칭 문서·IntelliDecision 유형·실제 응답을 미리 확인한다."""
    owner = body.owner.strip()
    if not owner:
        raise HTTPException(status_code=400, detail="owner가 비어 있습니다.")
    query = body.query.strip()
    if not query:
        raise HTTPException(status_code=400, detail="query가 비어 있습니다.")

    agent = await _get_isolated_agent(owner)
    if agent is None:
        raise HTTPException(
            status_code=503,
            detail="AI 시스템(LLM/RAG)이 아직 초기화되지 않았습니다. 서버 기동 로그(AI Orchestrator initialized)를 확인하세요.",
        )

    # 셀프서비스 세션 판정(detection.py::is_self_service_session)은 caller_number와 owner가
    # 정규화 후 동일해야 True가 된다 — 반드시 caller_number=owner로 호출해야 실제 self_service_agent
    # 경로를 그대로 재사용할 수 있다(AC2). 격리(AC3)는 caller_number가 아니라 매 호출마다 새로
    # 생성하는 call_id + `_agent_cache`에 등록하지 않는 1회성 에이전트 인스턴스로 보장한다.
    call_id = f"simtest-{uuid.uuid4().hex[:12]}"
    caller_number = owner

    start = time.time()
    result = await agent.process_utterance(query, call_id=call_id, caller_number=caller_number)
    ai_response = result.get("response") or ""

    from src.ai_voicebot.self_service.decision_rationale import _capture_and_log

    matched_type, reasoning_summary = await _capture_and_log(
        user_query=query, ai_response=ai_response, owner=owner, call_id=call_id,
    )

    matched_documents = _extract_matched_documents(call_id)
    elapsed = time.time() - start

    logger.info(
        "knowledge_base_simulate_done",
        owner=owner, call_id=call_id, elapsed_sec=round(elapsed, 3),
        matched_doc_count=len(matched_documents), intellidecision_type=matched_type,
    )

    return SimulateResponse(
        response=ai_response,
        matched_documents=matched_documents,
        intellidecision_type=matched_type,
        reasoning_summary=reasoning_summary,
        elapsed_sec=round(elapsed, 3),
    )
