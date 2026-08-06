"""
셀프서비스 자동설정 변경 이력 조회 REST API (Story 1.9).

Story 1.8에서 쌓이는 `self_service_config_changes` 테이블을 프론트엔드가 표시하기
위한 유일한 신규 엔드포인트다(Architecture 문서의 "이 Epic은 신규 REST 엔드포인트가
필요 없다" 원칙의 유일한 예외 — 다른 모든 Story는 LangGraph Tool이 서비스 레이어를
직접 호출해 별도 API가 필요 없었다).

읽기 전용이며 `src/common/self_service_config_change_db.py::list_config_changes()`만
호출한다(새 조회 로직을 만들지 않음).
"""

from __future__ import annotations

from typing import Any, Dict, List

from fastapi import APIRouter, Query

from src.api.utils.call_data_record_reader import read_call_data_record_for_call
from src.common.self_service_config_change_db import list_config_changes
from src.common.self_service_decision_log_db import (
    get_decision_log_session_detail,
    list_decision_log,
    list_decision_log_sessions,
)

router = APIRouter(prefix="/api/self-service", tags=["self-service"])


@router.get("/config-changes")
def get_config_changes(
    owner: str = Query(..., description="테넌트 owner"),
    limit: int = Query(50, ge=1, le=500, description="최대 조회 건수"),
) -> Dict[str, Any]:
    """owner의 최근 자동설정 변경 이력을 changed_at DESC 순으로 반환한다."""
    items = list_config_changes(owner, limit=limit)
    return {"items": items, "total": len(items)}


@router.get("/decision-log")
def get_decision_log(
    owner: str = Query(..., description="테넌트 owner"),
    limit: int = Query(20, ge=1, le=200, description="최대 조회 건수"),
) -> Dict[str, Any]:
    """owner의 최근 IntelliDecision 판단 근거 이력을 created_at DESC 순으로 반환한다(Story 1.21, FR30).

    읽기 전용이며 `src/common/self_service_decision_log_db.py::list_decision_log()`만
    호출한다(새 조회 로직을 만들지 않음, config-changes와 동일한 관례).
    """
    items = list_decision_log(owner, limit=limit)
    return {"items": items, "total": len(items)}


@router.get("/decision-log/sessions")
def get_decision_log_sessions(
    owner: str = Query(..., description="테넌트 owner"),
    limit: int = Query(20, ge=1, le=200, description="최대 세션 수"),
    related_domain: str | None = Query(
        None, description="Story 1.46(FR35-F): 이 도메인이 매칭된 턴이 있는 세션만 필터링"
    ),
    doc_id: str | None = Query(
        None, description="Story 1.46(FR35-F): 이 지식 문서(chunk) id가 매칭된 턴이 있는 세션만 필터링"
    ),
) -> Dict[str, Any]:
    """owner의 판단 이력을 세션(채널별 그룹핑) 단위 요약으로 반환한다(Story 1.38, FR34-F).

    음성 통화는 call_id 하나 = 세션 하나, 채팅/SIP MESSAGE는 (owner, caller_number)+시간 윈도우
    기준으로 그룹핑한다(`self_service_decision_log_db.py::list_decision_log_sessions()`).
    턴 상세는 포함하지 않는다(AC10 1단계 로딩) — 특정 세션의 턴 전체는
    `GET /decision-log/sessions/{session_key}`로 별도 조회한다.

    `related_domain`/`doc_id`가 주어지면(Story 1.46 지식베이스↔응대이력 교차 탐색), 세션 내
    최소 한 턴의 RAG 매칭 결과(`self_service_rag_search` call_data_record 이벤트)가 그 조건과
    일치하는 세션만 남긴다 — 신규 저장 로직 없이 기존 세션 상세 조회 경로를 재사용한다.
    """
    if not related_domain and not doc_id:
        items = list_decision_log_sessions(owner, limit=limit)
        return {"items": items, "total": len(items)}

    # 필터링을 위해서는 세션별 턴 상세(call_id)가 필요하므로 더 넓게 가져와 판별 후 자른다.
    candidates = list_decision_log_sessions(owner, limit=min(limit * 5, 200))
    matched: List[Dict[str, Any]] = []
    for summary in candidates:
        detail = get_decision_log_session_detail(owner, summary["session_key"])
        if detail is None:
            continue
        if _session_matches_filter(detail.get("turns", []), related_domain, doc_id):
            matched.append(summary)
        if len(matched) >= limit:
            break
    return {"items": matched, "total": len(matched)}


def _session_matches_filter(
    turns: List[Dict[str, Any]], related_domain: str | None, doc_id: str | None
) -> bool:
    """세션에 속한 턴 중 하나라도 주어진 related_domain/doc_id와 매칭되는 RAG 결과가 있으면 True."""
    for turn in turns:
        steps = _build_turn_steps(turn.get("call_id") or "")
        rag = steps.get("rag")
        if not rag:
            continue
        if related_domain and related_domain in (rag.get("related_domains") or []):
            return True
        if doc_id and doc_id in (rag.get("matched_doc_ids") or []):
            return True
    return False


@router.get("/decision-log/sessions/{session_key}")
def get_decision_log_session_detail_route(
    session_key: str,
    owner: str = Query(..., description="테넌트 owner"),
) -> Dict[str, Any]:
    """특정 세션에 속한 턴 전체를 시간순으로 반환한다(Story 1.38 AC10 2단계 로딩).

    각 턴에는 `call_data_record` 로그(`read_call_data_record_for_call`)에서 실제로 기록된
    5단계 서브플로우 데이터(①유형 판정은 matched_type 그대로 ②RAG ③화면안내/hop ④Tool
    ⑤응답 메타)를 `steps`로 덧붙인다(AC4/AC6/AC8/AC9). 로그에 없는 항목은 None으로 남겨
    프론트엔드가 "정보 없음"으로 표시하게 한다 — 추정으로 채우지 않는다.
    """
    session = get_decision_log_session_detail(owner, session_key)
    if session is None:
        return {"found": False}
    for turn in session.get("turns", []):
        turn["steps"] = _build_turn_steps(turn.get("call_id") or "")
    return {"found": True, "session": session}


def _build_turn_steps(call_id: str) -> Dict[str, Any]:
    """call_data_record 로그에서 해당 call_id의 서브플로우 데이터를 추출한다(Story 1.38).

    실제로 기록된 이벤트만 사용한다 — 없으면 각 필드를 None/빈 리스트로 남겨 프론트엔드가
    "정보 없음"으로 표시하게 한다(NFR10, AC6 — 추정으로 채우지 않음).
    """
    events = read_call_data_record_for_call(call_id) if call_id else []
    rag: Dict[str, Any] | None = None
    hybrid_rag: Dict[str, Any] | None = None
    screen_guidance: Dict[str, Any] | None = None
    tool_calls: List[Dict[str, Any]] = []
    response_meta: Dict[str, Any] | None = None

    for ev in events:
        event = ev.get("event")
        if event == "self_service_rag_search":
            rag = {
                "matched_doc_ids": ev.get("matched_doc_ids"),
                "scores": ev.get("scores"),
                "related_domains": ev.get("related_domains"),
            }
        elif event == "self_service_agent_hybrid_rag_merged":
            hybrid_rag = {
                "hybrid_doc_count": ev.get("hybrid_doc_count"),
                "merged_total": ev.get("merged_total"),
            }
        elif event == "self_service_screen_graph_hit":
            screen_guidance = {"has_screen_guidance": ev.get("has_screen_guidance")}
        elif event == "self_service_tool_start":
            tool_calls.append({"tool": ev.get("tool"), "result_preview": None})
        elif event == "self_service_tool_done":
            for tc in reversed(tool_calls):
                if tc.get("tool") == ev.get("tool") and tc.get("result_preview") is None:
                    tc["result_preview"] = ev.get("result_preview")
                    break
        elif event == "self_service_agent_response":
            response_meta = {
                "elapsed_sec": ev.get("elapsed_sec"),
                "response_len": ev.get("response_len"),
            }

    return {
        "rag": rag,
        "hybrid_rag": hybrid_rag,
        "screen_guidance": screen_guidance,
        "tool_calls": tool_calls,
        "response_meta": response_meta,
    }
