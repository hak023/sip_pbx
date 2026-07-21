"""
LangGraph Agentic RAG Agent.

ConversationState를 공유하는 StateGraph 워크플로우.
설계서 Phase 2의 핵심: 모든 RAG/LLM 흐름을 LangGraph로 오케스트레이션.

워크플로우:
  classify_intent → route_utterance
       → (rag_mode=skip: chitchat/out_of_scope) generate_response → hitl_alert → update_cache → update_state → END
       → (knowledge) check_cache ─(hit)─→ update_state → END
                     (miss) → rewrite_query → adaptive_rag → generate_response
                     → hitl_alert → update_cache → update_state → END

[2026-04-03] step_back 제거:
  - RAG 0건 → step_back(LLM+재검색, ~2.6s) → 결과 0건의 반복 패턴이 관측됨
  - RAG_MIN_USEFUL_SCORE 필터와 이중 모순: 필터 통과 실패 문서를 동일 DB에서 재검색
  - generate_response가 rag_results=[] 상태에서 LLM fallback 응답을 자체 생성
  - 분석 리포트: docs/reports/2026-04/2026-04-03_1500_STEP_BACK_REMOVAL_ANALYSIS.md
"""

import asyncio
import time
from collections import defaultdict
from typing import Any, Dict, Optional, Tuple

import structlog

from src.ai_voicebot.langgraph.state import ConversationState
from src.ai_voicebot.langgraph.nodes.classify_intent import classify_intent_node
from src.ai_voicebot.langgraph.nodes.route_utterance import route_utterance_node
from src.ai_voicebot.langgraph.nodes.semantic_cache import check_cache_node, update_cache_node
from src.ai_voicebot.langgraph.nodes.rewrite_query import rewrite_query_node
from src.ai_voicebot.langgraph.nodes.adaptive_rag import adaptive_rag_node
from src.ai_voicebot.langgraph.nodes.generate_response import generate_response_node
from src.ai_voicebot.langgraph.nodes.hitl_alert import hitl_alert_node
from src.ai_voicebot.langgraph.nodes.update_state import update_state_node
from src.ai_voicebot.langgraph.nodes.greeting_farewell_cache import check_greeting_farewell_cache_node
from src.ai_voicebot.langgraph.nodes.greeting_farewell_kb import greeting_farewell_kb_node
from src.ai_voicebot.langgraph.nodes.response_shortcuts import (
    template_response_node,
    repeat_response_node,
    clarification_response_node,
    help_response_node,
)
from src.ai_voicebot.langgraph.nodes.booking_agent import booking_agent_node
from src.ai_voicebot.langgraph.nodes.self_service_agent import self_service_agent_node
from src.common.call_data_record_logger import log_call_data

logger = structlog.get_logger(__name__)

# build_conversation_graph() 노드명과 동기화 (astream_events에서 구간 시간 집계용)
_LANGGRAPH_NODE_NAMES = frozenset(
    {
        "classify_intent",
        "route_utterance",
        "check_cache",
        "rewrite_query",
        "adaptive_rag",
        "generate_response",
        "hitl_alert",
        "update_cache",
        "update_state",
        "template_response",
        "repeat_response",
        "clarification_response",
        "help_response",
        "check_greeting_farewell_cache",
        "greeting_farewell_kb",
        "booking_agent",  # 예약 에이전트 노드
    }
)


async def _invoke_graph_with_node_timing(
    graph: Any, invoke_state: Dict[str, Any], config: Optional[Dict[str, Any]] = None
) -> Tuple[Optional[Dict[str, Any]], Dict[str, float]]:
    """
    단일 그래프 실행으로 최종 state + 노드별 wall 시간을 수집한다.

    우선 stream_mode=["updates","values"] (한 번의 실행)로 updates 키=노드명,
    마지막 values 청크=병합된 전체 state.
    미지원 시 values만으로 최종 state만 수집하거나 (None, {}) 로 ainvoke 폴백.
    config: Checkpointer thread_id 등 LangGraph config 딕셔너리
    """
    ast = getattr(graph, "astream", None)
    if not callable(ast):
        return None, {}

    stream_kwargs: Dict[str, Any] = {"stream_mode": ["updates", "values"]}
    if config:
        stream_kwargs["config"] = config

    node_sec: Dict[str, float] = defaultdict(float)
    last_values: Optional[Dict[str, Any]] = None
    prev_wall = time.perf_counter()

    try:
        async for packet in ast(invoke_state, **stream_kwargs):
            if not isinstance(packet, tuple) or len(packet) != 2:
                continue
            mode, chunk = packet
            now = time.perf_counter()
            if mode == "updates" and isinstance(chunk, dict):
                dt = max(0.0, now - prev_wall)
                prev_wall = now
                named = [k for k in chunk if k in _LANGGRAPH_NODE_NAMES]
                if named:
                    share = dt / len(named)
                    for k in named:
                        node_sec[k] += share
            elif mode == "values" and isinstance(chunk, dict):
                last_values = chunk
                prev_wall = time.perf_counter()
    except Exception as e:
        # [2026-07-15] 원인 규명: astream(stream_mode=["updates","values"])가 스트림 도중
        # 예외(TypeError 등)를 던지면, 과거에는 무조건 stream_mode="values" 단일 모드로
        # 그래프를 처음부터 다시 실행했다. 이 때문에 Tool-calling이 있는 노드(RAG 검색·LLM
        # 호출·쓰기 Tool 실행 등 부작용 있는 작업)가 한 번의 API 호출 안에서 2회 실행되고,
        # 최종 응답이 1차 실행의 정상 응답이 아니라 2차 실행 결과로 덮어써지는 버그가 있었다
        # (QA 자동 테스트에서 발견, docs/reports/2026-07/2026-07-15_self_service_bmad_qa_step3_execution_result.md §7).
        # 이미 최소 1개의 values 청크(= 그래프가 실제로 진행되어 부작용이 발생했을 가능성)를
        # 받은 상태라면, 절대 처음부터 다시 실행하지 않고 지금까지의 결과를 그대로 반환한다.
        logger.warning(
            "langgraph_astream_updates_values_failed",
            error=str(e), error_type=type(e).__name__,
            has_partial_result=last_values is not None,
            note="values 청크 수신 후 실패 시 재실행 없이 부분 결과 사용(부작용 중복 방지)",
        )
        if last_values is not None:
            rounded = {k: round(v, 4) for k, v in sorted(node_sec.items(), key=lambda x: -x[1])}
            return last_values, rounded
        if node_sec:
            # values 청크는 없지만 updates 청크(노드 실행 흔적)는 이미 있었다 — 부작용이 이미
            # 발생했을 가능성이 있으므로 재실행하지 않고 실패로 처리한다(호출부의 ainvoke
            # 폴백이 1회만 발생하도록 — 여기서 재시도까지 하면 최악의 경우 3회 실행됨).
            return None, {}
        # 아직 values/updates 청크를 하나도 못 받은 경우에만(=부작용 발생 가능성이 낮음) 단일
        # 모드로 한 번 더 시도한다.
        try:
            values_kwargs: Dict[str, Any] = {"stream_mode": "values"}
            if config:
                values_kwargs["config"] = config
            prev = time.perf_counter()
            async for chunk in ast(invoke_state, **values_kwargs):
                if isinstance(chunk, dict):
                    last_values = chunk
                    _ = time.perf_counter() - prev
                    prev = time.perf_counter()
        except Exception as e2:
            logger.warning(
                "langgraph_astream_values_only_failed", error=str(e2), error_type=type(e2).__name__,
            )
            return None, {}

    rounded = {k: round(v, 4) for k, v in sorted(node_sec.items(), key=lambda x: -x[1])}
    return last_values, rounded


def _route_after_cache(state: ConversationState) -> str:
    """캐시 히트 여부에 따라 분기.

    - 히트: update_state (즉시 응답)
    - 미스 + intent=help: help_response (RAG+LLM 폴백)
    - 미스 + 그 외: rewrite_query (RAG 경로)
    """
    if state.get("rag_cache_hit"):
        return "update_state"
    if state.get("intent") == "help":
        return "help_response"
    return "rewrite_query"


def _route_after_intent(state: ConversationState) -> str:
    """의도에 따라 분기. 설계: AI_RESPONSE_HUMANLIKE_DESIGN.md §3.2, CHROMADB_CATEGORY_DESIGN §4.2"""
    intent = state.get("intent", "")
    if intent in ("farewell", "greeting"):
        return "greeting_farewell_kb"
    # 예약 의도 → booking_agent 직행 (RAG/캐시 불필요)
    if intent == "booking":
        return "booking_agent"
    # B 그룹 반응/피드백 → 템플릿 응답
    if intent in ("affirm", "deny", "gratitude", "doubt", "positive_reaction", "negative_reaction"):
        return "template_response"
    if intent == "repeat":
        return "repeat_response"
    if intent == "clarification":
        return "clarification_response"
    # help: 먼저 check_cache에서 FAQ 캐시 히트 시도, 미스 시 help_response(RAG+LLM)로 폴백
    if intent == "help":
        return "check_cache"
    # question / complaint / transfer / nlu_fallback 등 — 캐시·RAG 경로
    # chitchat·out_of_scope 는 route_utterance 에서 rag_mode=skip 으로 generate 직행
    return "check_cache"


def _route_after_utterance(state: ConversationState) -> str:
    """검색 전 레인: 일상 직행 vs 지식 경로."""
    # 아웃바운드 모드: classify/cache/rewrite/RAG 전체 스킵 → generate_response 직행
    if state.get("outbound_purpose"):
        return "generate_response"
    # 예약 의도: utterance_lane="booking"이면 booking_agent 직행 (rag_mode 체크보다 선행)
    if state.get("utterance_lane") == "booking":
        return "booking_agent"
    if state.get("rag_mode") == "skip":
        return "generate_response"
    return _route_after_intent(state)


def _route_after_rag(state: ConversationState) -> str:
    """adaptive_rag 이후 항상 generate_response로 진행.

    [2026-04-03] step_back 제거: RAG 0건일 때 step_back(LLM+재검색, ~2.6s) 실행했으나
    실제 관측에서 모두 재검색 0건 → generate_response fallback과 결과 동일.
    generate_response가 rag_results=[] 상태에서 LLM fallback 응답을 직접 생성하므로 충분.
    """
    return "generate_response"


def _route_after_greeting_farewell_cache(state: ConversationState) -> str:
    """캐시 히트 시 update_state. 미스 시 knowledge RAG(인사/종료 category)로 폴백."""
    if state.get("rag_cache_hit"):
        return "update_state"
    if state.get("intent") in ("greeting", "farewell"):
        return "rewrite_query"
    return "update_state"


def _route_after_classify(state: ConversationState) -> str:
    """classify_intent 이후 분기.

    아웃바운드 모드(outbound_purpose 존재)이면 route_utterance·classify 전체 스킵하고
    generate_response 로 직행한다. classify_intent LLM 호출 비용(~1.5초)은 이미 소요됐지만
    이후 route→cache→rewrite→RAG(~10초)를 완전 제거한다.

    셀프서비스 모드(intent=="self_service")이면 self_service_agent로 직행한다
    (booking과 동일한 우회 레인 패턴 — 캐시/RAG/HITL 생략).
    """
    if state.get("outbound_purpose"):
        return "generate_response"
    if state.get("intent") == "self_service":
        return "self_service_agent"
    return "route_utterance"


# 토폴로지 변경 시 버전 증가 → 기존 프로세스 내 캐시 무효화
_LANGGRAPH_SCHEMA_VERSION = 9  # 2026-07-14: self_service_agent 노드/엣지 추가 (Story 1.2)
_compiled_graph_entry = None  # (version, compiled_graph) — 동기 MemorySaver 캐시(레거시)
_compiled_async_entry = None  # (version, compiled_graph) — AsyncSqliteSaver + ainvoke
_async_graph_compile_lock = asyncio.Lock()


def _build_state_graph():
    """StateGraph 구성만 수행(컴파일 전)."""
    try:
        from langgraph.graph import StateGraph, END
    except ImportError:
        logger.error("langgraph_not_installed",
                    message="pip install langgraph langchain-core 를 실행하세요.")
        return None

    graph = StateGraph(ConversationState)

    # ── 노드 등록 ──
    graph.add_node("classify_intent", classify_intent_node)
    graph.add_node("route_utterance", route_utterance_node)
    graph.add_node("check_cache", check_cache_node)
    graph.add_node("rewrite_query", rewrite_query_node)
    graph.add_node("adaptive_rag", adaptive_rag_node)
    graph.add_node("generate_response", generate_response_node)
    graph.add_node("hitl_alert", hitl_alert_node)
    graph.add_node("update_cache", update_cache_node)
    graph.add_node("update_state", update_state_node)
    # 단축 응답 노드 (설계 §3.3)
    graph.add_node("template_response", template_response_node)
    graph.add_node("repeat_response", repeat_response_node)
    graph.add_node("clarification_response", clarification_response_node)
    graph.add_node("help_response", help_response_node)
    graph.add_node("check_greeting_farewell_cache", check_greeting_farewell_cache_node)
    graph.add_node("greeting_farewell_kb", greeting_farewell_kb_node)
    graph.add_node("booking_agent", booking_agent_node)
    graph.add_node("self_service_agent", self_service_agent_node)

    # ── 엣지 정의 ──
    graph.set_entry_point("classify_intent")

    # classify_intent → 아웃바운드이면 generate_response 직행, 인바운드면 route_utterance
    graph.add_conditional_edges(
        "classify_intent",
        _route_after_classify,
        {
            "generate_response": "generate_response",
            "route_utterance": "route_utterance",
            "self_service_agent": "self_service_agent",
        },
    )

    # route_utterance → 일상 직행(generate) 또는 기존 의도별 분기
    graph.add_conditional_edges(
        "route_utterance",
        _route_after_utterance,
        {
            "generate_response": "generate_response",
            "check_cache": "check_cache",
            "check_greeting_farewell_cache": "check_greeting_farewell_cache",
            "greeting_farewell_kb": "greeting_farewell_kb",
            "template_response": "template_response",
            "repeat_response": "repeat_response",
            "clarification_response": "clarification_response",
            "help_response": "help_response",
            "booking_agent": "booking_agent",
        },
    )

    # booking_agent → update_state → END (캐시/RAG/HITL 스킵)
    graph.add_edge("booking_agent", "update_state")

    # self_service_agent → update_state → END (캐시/RAG/HITL 스킵, booking_agent와 동일 우회 패턴)
    graph.add_edge("self_service_agent", "update_state")

    # greeting/farewell 캐시 검색 후 분기
    graph.add_conditional_edges(
        "check_greeting_farewell_cache",
        _route_after_greeting_farewell_cache,
        {
            "update_state": "update_state",
            "rewrite_query": "rewrite_query",
        },
    )

    # 단축 응답 노드 → update_state → END (캐시/RAG/hitl_alert 스킵)
    for node_name in ("template_response", "repeat_response", "clarification_response", "help_response", "greeting_farewell_kb"):
        graph.add_edge(node_name, "update_state")

    # check_cache → (hit → update_state, miss+help → help_response, miss+other → rewrite_query)
    graph.add_conditional_edges(
        "check_cache",
        _route_after_cache,
        {
            "update_state": "update_state",
            "rewrite_query": "rewrite_query",
            "help_response": "help_response",
        },
    )

    # rewrite_query → adaptive_rag
    graph.add_edge("rewrite_query", "adaptive_rag")

    # adaptive_rag → generate_response (step_back 제거: 2026-04-03)
    graph.add_edge("adaptive_rag", "generate_response")

    # generate_response → hitl_alert
    graph.add_edge("generate_response", "hitl_alert")

    # hitl_alert → update_cache
    graph.add_edge("hitl_alert", "update_cache")

    # update_cache → update_state
    graph.add_edge("update_cache", "update_state")

    # update_state → END
    graph.add_edge("update_state", END)

    return graph


def build_conversation_graph():
    """
    동기 경로: MemorySaver 체크포인터로 컴파일(레거시·테스트).

    PBX·실통화는 ``await get_or_build_compiled_graph_async()`` 가 AsyncSqliteSaver 를 사용한다.
    """
    global _compiled_graph_entry
    if _compiled_graph_entry is not None:
        ver, cached = _compiled_graph_entry
        if ver == _LANGGRAPH_SCHEMA_VERSION and cached is not None:
            logger.info("langgraph_graph_cache_hit", message="기존 동기 컴파일 그래프 재사용")
            return cached

    compile_start = time.time()
    graph = _build_state_graph()
    if graph is None:
        return None

    try:
        from langgraph.checkpoint.memory import MemorySaver

        checkpointer = MemorySaver()
    except ImportError:
        checkpointer = None

    compiled = graph.compile(checkpointer=checkpointer) if checkpointer else graph.compile()
    compile_elapsed = time.time() - compile_start
    logger.info(
        "langgraph_conversation_graph_compiled_sync",
        nodes=10,
        edges="conditional+linear",
        checkpointer=type(checkpointer).__name__ if checkpointer else "none",
        compile_time=f"{compile_elapsed:.3f}s",
    )

    _compiled_graph_entry = (_LANGGRAPH_SCHEMA_VERSION, compiled)
    return compiled


async def get_or_build_compiled_graph_async():
    """비동기 SQLite(또는 Memory) 체크포인터로 컴파일 — ``ainvoke``/``astream`` 용."""
    global _compiled_async_entry
    if _compiled_async_entry is not None:
        ver, cached = _compiled_async_entry
        if ver == _LANGGRAPH_SCHEMA_VERSION and cached is not None:
            logger.info("langgraph_graph_async_cache_hit", message="기존 Async 컴파일 그래프 재사용")
            return cached

    async with _async_graph_compile_lock:
        if _compiled_async_entry is not None:
            ver, cached = _compiled_async_entry
            if ver == _LANGGRAPH_SCHEMA_VERSION and cached is not None:
                return cached

        compile_start = time.time()
        graph = _build_state_graph()
        if graph is None:
            return None

        try:
            from src.ai_voicebot.langgraph.checkpointer import get_async_sqlite_checkpointer

            checkpointer = await get_async_sqlite_checkpointer()
        except Exception as e:
            logger.warning("langgraph_async_checkpointer_resolve_failed", error=str(e))
            checkpointer = None

        if checkpointer is None:
            try:
                from langgraph.checkpoint.memory import MemorySaver

                checkpointer = MemorySaver()
            except ImportError:
                checkpointer = None

        compiled = graph.compile(checkpointer=checkpointer) if checkpointer else graph.compile()
        compile_elapsed = time.time() - compile_start
        logger.info(
            "langgraph_conversation_graph_compiled_async",
            nodes=10,
            edges="conditional+linear",
            checkpointer=type(checkpointer).__name__ if checkpointer else "none",
            compile_time=f"{compile_elapsed:.3f}s",
        )

        _compiled_async_entry = (_LANGGRAPH_SCHEMA_VERSION, compiled)
        return compiled


class ConversationAgent:
    """
    LangGraph 기반 대화 에이전트.
    
    Phase 1의 RAGLLMProcessor를 대체할 수 있는 인터페이스 제공.
    """

    def __init__(
        self,
        llm_client,
        rag_engine=None,
        embedder=None,
        vector_db=None,
        org_manager=None,
        owner: str = "",
    ):
        self.llm_client = llm_client
        self.rag_engine = rag_engine
        self.embedder = embedder
        self.vector_db = vector_db
        self.org_manager = org_manager
        self.owner = owner  # 착신번호 (테넌트 ID)

        # 그래프는 첫 process_utterance 에서 AsyncSqliteSaver 로 컴파일(이벤트 루프 필요)
        self.graph = None
        self._state: ConversationState = {
            "messages": [],
            "turn_count": 0,
            "business_state": "initial",
            "rag_cache_hit": False,
            "needs_human": False,
            "confidence": 0.0,
        }

        logger.info(
            "conversation_agent_initialized",
            has_rag=rag_engine is not None,
            has_cache=(vector_db is not None and embedder is not None),
            note="그래프는 첫 발화 시 get_or_build_compiled_graph_async 로 로드",
        )

    async def _ensure_graph(self) -> None:
        if self.graph is not None:
            return
        self.graph = await get_or_build_compiled_graph_async()
        if not self.graph:
            logger.error("conversation_agent_graph_build_failed")

    async def process_utterance(self, user_text: str, call_id: Optional[str] = None, **kwargs) -> dict:
        """
        사용자 발화 처리 (메인 API).

        Args:
            user_text: STT 결과 텍스트
            call_id: 통화 ID (로그/DB 연계용, call 키로 필터 가능)

        Returns:
            dict with keys: response, confidence, intent, needs_human, hitl_reason,
                           business_state, response_chunks, rag_cache_hit
        """
        utterance_start = time.time()

        await self._ensure_graph()

        if not self.graph:
            logger.error("conversation_agent_no_graph")
            return {
                "response": "시스템 오류가 발생했습니다.",
                "confidence": 0.0,
                "llm_rag_applied": [],
                "llm_rag_context_source": "no_graph",
                "rag_search_trace": {},
            }

        # 기관 정보 로드
        org_context = ""
        system_prompt = ""
        if self.org_manager:
            org_context = self.org_manager.get_organization_context()
            system_prompt = self.org_manager.get_system_prompt()

        # STT 원문(시간 정규화 전) — RAG 이중 검색용. 미전달 시 user_text와 동일로 간주.
        user_query_raw = (kwargs.get("user_query_raw") or user_text or "").strip()

        # 아웃바운드 컨텍스트 (rag_processor가 전달한 경우에만 주입)
        outbound_purpose = (kwargs.get("outbound_purpose") or "").strip()
        outbound_questions = kwargs.get("outbound_questions") or []
        if not isinstance(outbound_questions, list):
            outbound_questions = []
        outbound_answers = kwargs.get("outbound_answers")
        if not isinstance(outbound_answers, dict):
            outbound_answers = {}
        outbound_mission_done = bool(kwargs.get("outbound_mission_done", False))
        hangup_callback = kwargs.get("_hangup_callback", None)

        is_outbound_session = bool(outbound_purpose or outbound_questions)

        # 아웃바운드 전용 시스템 프롬프트: org system_prompt 대신 목적/질문 기반으로 덮어씀
        if outbound_purpose:
            qs_text = "\n".join(f"- {q}" for q in outbound_questions) if outbound_questions else ""
            system_prompt = (
                "당신은 아웃바운드 AI 통화 어시스턴트입니다.\n"
                f"[통화 목적] {outbound_purpose}\n"
                + (f"[확인 질문]\n{qs_text}\n" if qs_text else "")
                + "상대방의 답변을 자연스럽게 수집하세요. "
                "질문과 무관한 내용을 묻더라도 간결하게 답하고 목적 달성에 집중하세요. "
                "모든 정보를 확인하면 정중히 마무리하세요."
            )
        elif outbound_questions:
            qs_text = "\n".join(f"- {q}" for q in outbound_questions)
            system_prompt = (
                "당신은 아웃바운드 AI 통화 어시스턴트입니다.\n"
                f"[확인 질문]\n{qs_text}\n"
                "상대방의 답변을 자연스럽게 수집하세요. "
                "질문과 무관한 내용을 묻더라도 간결하게 답하고 목적 달성에 집중하세요. "
                "모든 정보를 확인하면 정중히 마무리하세요."
            )

        # 페르소나 owner 결정:
        #   inbound  → callee(착신번호) = self.owner  (KB 테넌트 ID와 동일)
        #   outbound → callee(상대방번호)을 호출부에서 kwargs["callee"]로 전달해야 함.
        #              미전달 시 self.owner(AI봇 발신번호)를 그대로 사용 (기존 동작 유지)
        _persona_owner: str = kwargs.get("callee") or self.owner

        # 발신자 전화번호 (kwargs로 전달, 없으면 빈 문자열)
        caller_number: str = kwargs.get("caller_number") or kwargs.get("_caller_number") or ""

        # ── 셀프서비스 AI 도우미: 발신측=착신측(자기 자신에게 연락) 판별 ──
        # 설계: docs/architecture/self-service-ai-assistant-architecture.md
        #       음성(rag_processor.py)·문자(sip_message_ai_reply.py) 두 채널이
        #       공통으로 거치는 이 지점에서만 판별 — SIP 프로토콜 레이어는 수정하지 않는다.
        from src.ai_voicebot.self_service.detection import is_self_service_session
        from src.common.sip_owner import normalize_owner_username

        _is_self_service = is_self_service_session(caller_number, _persona_owner)
        if call_id:
            log_call_data(
                call_id,
                "self_service",
                "self_service_session_detected",
                caller_number_normalized=normalize_owner_username(caller_number),
                owner_normalized=normalize_owner_username(_persona_owner),
                is_self_service=_is_self_service,
            )

        # ── call_context ContextVar 레지스트리에 직렬화 불가 객체 등록 ──
        # checkpointer(AsyncSqliteSaver/MemorySaver)가 state를 msgpack 직렬화할 때
        # LLMClient 등이 포함되면 "Type is not msgpack serializable" 오류가 발생.
        # 해결: 직렬화 불가 객체는 state 대신 ContextVar(asyncio Task 스코프)로 전달.
        from src.ai_voicebot.langgraph.call_context import set_call_context
        set_call_context(
            llm_client=self.llm_client,
            rag_engine=self.rag_engine,
            embedder=self.embedder,
            vector_db=self.vector_db,
            org_manager=self.org_manager,
            hangup_callback=hangup_callback if is_outbound_session else None,
        )
        logger.debug(
            "call_context_registered",
            call_id=call_id or "",
            has_llm=self.llm_client is not None,
            has_rag=self.rag_engine is not None,
            is_outbound=is_outbound_session,
        )

        # 현재 상태 + 새 입력 병합 (직렬화 가능 값만)
        invoke_state = {
            **self._state,
            "user_query": user_text,
            "user_query_raw": user_query_raw,
            "org_context": org_context,
            "system_prompt": system_prompt,
            "_owner": self.owner,              # 테넌트 ID (RAG owner_filter, KB 격리)
            "_caller_number": caller_number,   # 발신자 전화번호 (예약 검색·SMS용)
            "_persona_owner": _persona_owner,  # 페르소나 조회 owner
            "_call_id": call_id or "",         # 통화 ID → RAG/로그 call 키
            "is_self_service_session": _is_self_service,  # 발신측=착신측 판별 결과 (Story 1.1)
        }
        if is_outbound_session:
            invoke_state["outbound_purpose"] = outbound_purpose
            invoke_state["outbound_questions"] = list(outbound_questions)
            invoke_state["outbound_answers"] = dict(outbound_answers)
            invoke_state["outbound_mission_done"] = outbound_mission_done

        # Checkpointer thread config (call_id 기반)
        try:
            from src.ai_voicebot.langgraph.checkpointer import get_thread_config
            thread_config = get_thread_config(call_id or "")
        except Exception:
            thread_config = {}

        try:
            graph_start = time.time()
            timed_result, node_durations_sec = await _invoke_graph_with_node_timing(
                self.graph, invoke_state, config=thread_config
            )
            if timed_result is not None:
                result = timed_result
            else:
                logger.debug(
                    "langgraph_ainvoke_no_astream_events_or_empty",
                    call_id=call_id or "",
                    note="astream_events 미수신 시 단일 ainvoke",
                )
                result = await self.graph.ainvoke(invoke_state, config=thread_config)
                node_durations_sec = {}
            graph_elapsed = time.time() - graph_start

            # 단축 경로/캐시 히트 경로는 messages를 반환하지 않음 → 이 턴의 user+assistant 보강
            messages_before = invoke_state.get("messages", [])
            messages_after = result.get("messages", [])
            response_text = result.get("response", "")
            if response_text and len(messages_after) <= len(messages_before):
                from datetime import datetime
                repaired = list(messages_after)
                repaired.append({"role": "user", "content": user_text, "timestamp": datetime.now().isoformat()})
                repaired.append({"role": "assistant", "content": response_text, "timestamp": datetime.now().isoformat()})
                result = {**result, "messages": repaired}

            # 결과에서 지속 상태 추출
            self._state["messages"] = result.get("messages", self._state["messages"])
            self._state["turn_count"] = result.get("turn_count", self._state["turn_count"])
            self._state["business_state"] = result.get("business_state", self._state["business_state"])
            # 예약 컨텍스트 (발화 간 히스토리) 보존
            if "booking_context" in result:
                self._state["booking_context"] = result["booking_context"]
            # 셀프서비스 Tool-calling 대화 기억 (발화 간 히스토리) 보존 — 2026-07-15 수정.
            # 없으면 booking_context와 달리 매 턴 사라져서 "확인 발화 → 긍정 응답" 2턴
            # 쓰기 플로우(Story 1.8)가 항상 처음부터 다시 시작하는 문제가 있었다.
            if "self_service_tool_messages" in result:
                self._state["self_service_tool_messages"] = result["self_service_tool_messages"]

            total_elapsed = time.time() - utterance_start

            cid = call_id or ""
            if cid:
                log_call_data(
                    cid,
                    "timing",
                    "agent_graph_total",
                    graph_elapsed_sec=round(graph_elapsed, 3),
                    total_elapsed_sec=round(total_elapsed, 3),
                    intent=result.get("intent", "unknown"),
                    rag_cache_hit=result.get("rag_cache_hit", False),
                    agent_graph_node_durations_sec=node_durations_sec or None,
                )
            if node_durations_sec:
                logger.info(
                    "langgraph_node_durations_sec",
                    call_id=cid,
                    progress="timing",
                    node_durations_sec=node_durations_sec,
                    graph_elapsed_sec=round(graph_elapsed, 3),
                    note="astream_events v2/v1 on_chain_* 로 집계; 노드명은 StateGraph 노드와 일치",
                )

            # ✅ 구간별 타이밍 로그 (6.2 지연 구간 점검: classify_intent(LLM), generate_response(LLM) 로그 참고)
            logger.info("process_utterance_complete",
                       user_text=user_text,
                       total_elapsed=f"{total_elapsed:.3f}s",
                       langgraph_elapsed=f"{graph_elapsed:.3f}s",
                       intent=result.get("intent", "unknown"),
                       confidence=f"{result.get('confidence', 0.0):.3f}",
                       cache_hit=result.get("rag_cache_hit", False),
                       response_len=len(result.get("response", "")),
                       node_durations_sec=node_durations_sec or {},
                       note="노드별: langgraph_node_durations_sec / call_data agent_graph_node_durations_sec; 지연 시 generate_response·classify_intent 등 상위 항목 확인")

            return {
                "response": result.get("response", ""),
                "confidence": result.get("confidence", 0.0),
                "intent": result.get("intent", "unknown"),
                "needs_human": result.get("needs_human", False),
                "hitl_reason": result.get("hitl_reason", ""),
                "business_state": result.get("business_state", "initial"),
                "response_chunks": result.get("response_chunks", []),
                "rag_cache_hit": result.get("rag_cache_hit", False),
                "needs_follow_up": result.get("needs_follow_up", False),
                "follow_up_user_query": result.get("follow_up_user_query", ""),
                "llm_rag_applied": result.get("llm_rag_applied") or [],
                "llm_rag_context_source": result.get("llm_rag_context_source") or "",
                "rag_search_trace": result.get("rag_search_trace") or {},
                "llm_gen_elapsed_sec": result.get("llm_gen_elapsed_sec"),
                "llm_first_sentence_elapsed_sec": result.get("llm_first_sentence_elapsed_sec"),
                "llm_first_sentence_preview": result.get("llm_first_sentence_preview") or "",
                "llm_first_sentence_source": result.get("llm_first_sentence_source") or "",
                "semantic_cache_score": result.get("semantic_cache_score"),
                "greeting_farewell_cache_score": result.get("greeting_farewell_cache_score"),
                # 아웃바운드 전용: LLM이 추출한 답변 목록 + 유효 답변 여부
                # generate_response_node → agent → rag_processor 전달 경로
                "outbound_answered": result.get("outbound_answered") or [],
                "outbound_is_answer": result.get("outbound_is_answer", True),
            }

        except Exception as e:
            logger.error("conversation_agent_invoke_error",
                       error=str(e), exc_info=True)
            return {
                "response": "죄송합니다. 일시적인 오류가 발생했습니다.",
                "confidence": 0.0,
                "intent": "unknown",
                "needs_human": False,
                "needs_follow_up": False,
                "follow_up_user_query": "",
                "llm_rag_applied": [],
                "llm_rag_context_source": "invoke_error",
                "rag_search_trace": {},
            }

    async def generate_greeting(self) -> str:
        """
        1차 인사 (통화 시작, LLM 없음).

        지식베이스 `documents` 본문 category=greeting_phase1 (owner 일치) 우선.
        없거나 조회 실패 시 기본 문구로 TTS.
        """
        if self.vector_db and self.owner:
            try:
                from src.ai_voicebot.knowledge.knowledge_service import get_knowledge_greeting_text

                loop = asyncio.get_event_loop()
                kb_text = await loop.run_in_executor(
                    None,
                    lambda: get_knowledge_greeting_text(
                        self.vector_db, self.owner, "greeting_phase1"
                    ),
                )
                if kb_text and len(kb_text.strip()) >= 2:
                    logger.info(
                        "greeting_from_kb_greeting_phase1",
                        owner=self.owner,
                        text_len=len(kb_text),
                        text=kb_text,
                        note="지식베이스 greeting_phase1 문서 본문 → TTS",
                    )
                    return kb_text.strip()
            except Exception as e:
                logger.debug("greeting_kb_phase1_lookup_failed", owner=self.owner, error=str(e))

        from src.ai_voicebot.greeting_defaults import DEFAULT_GREETING_PHASE1

        logger.info(
            "greeting_phase1_default_tts_fallback",
            owner=self.owner or "",
            reason="kb_empty_or_no_owner_or_lookup_failed",
            text_len=len(DEFAULT_GREETING_PHASE1),
            note="Chroma/지식 greeting_phase1 없음 → 기본 문구 TTS",
        )
        return DEFAULT_GREETING_PHASE1

    async def generate_capability_guide(self) -> str:
        """
        2차 인사 (LLM 없음).

        지식베이스 category=greeting_phase2 본문 우선. 없거나 조회 실패 시 기본 문구로 TTS.
        """
        if self.vector_db and self.owner:
            try:
                from src.ai_voicebot.knowledge.knowledge_service import get_knowledge_greeting_text

                loop = asyncio.get_event_loop()
                kb_text = await loop.run_in_executor(
                    None,
                    lambda: get_knowledge_greeting_text(
                        self.vector_db, self.owner, "greeting_phase2"
                    ),
                )
                if kb_text and len(kb_text.strip()) >= 2:
                    logger.info(
                        "greeting_phase2_from_kb",
                        owner=self.owner,
                        text_len=len(kb_text),
                        text=kb_text,
                        note="지식베이스 greeting_phase2 문서 본문 → TTS",
                    )
                    return kb_text.strip()
            except Exception as e:
                logger.debug("greeting_kb_phase2_lookup_failed", owner=self.owner, error=str(e))

        from src.ai_voicebot.greeting_defaults import DEFAULT_GREETING_PHASE2

        logger.info(
            "greeting_phase2_default_tts_fallback",
            owner=self.owner or "",
            reason="kb_empty_or_no_owner_or_lookup_failed",
            text_len=len(DEFAULT_GREETING_PHASE2),
            note="Chroma/지식 greeting_phase2 없음 → 기본 문구 TTS",
        )
        return DEFAULT_GREETING_PHASE2

    async def generate_farewell(self) -> str:
        """
        종료 멘트 (LLM 없음, 아웃바운드 미션 완료 시 사용).

        지식베이스 category=farewell 본문 우선. 없거나 조회 실패 시 빈 문자열 반환
        (호출부에서 하드코딩 폴백 처리).
        """
        if self.vector_db and self.owner:
            try:
                from src.ai_voicebot.knowledge.knowledge_service import get_knowledge_greeting_text

                loop = asyncio.get_event_loop()
                kb_text = await loop.run_in_executor(
                    None,
                    lambda: get_knowledge_greeting_text(
                        self.vector_db, self.owner, "farewell"
                    ),
                )
                if kb_text and len(kb_text.strip()) >= 2:
                    logger.info(
                        "farewell_from_kb",
                        owner=self.owner,
                        text_len=len(kb_text),
                        text=kb_text,
                        note="지식베이스 farewell 문서 본문 → TTS",
                    )
                    return kb_text.strip()
            except Exception as e:
                logger.debug("farewell_kb_lookup_failed", owner=self.owner, error=str(e))

        logger.info(
            "farewell_kb_not_found",
            owner=self.owner or "",
            note="farewell 카테고리 지식 없음 → 호출부 하드코딩 폴백",
        )
        return ""

    def reset(self):
        """상태 초기화 (새 통화 시작)"""
        self._state = {
            "messages": [],
            "turn_count": 0,
            "business_state": "initial",
            "rag_cache_hit": False,
            "needs_human": False,
            "confidence": 0.0,
        }
        logger.info("conversation_agent_state_reset")
