"""
LangGraph Agentic RAG Agent.

ConversationState를 공유하는 StateGraph 워크플로우.
설계서 Phase 2의 핵심: 모든 RAG/LLM 흐름을 LangGraph로 오케스트레이션.

워크플로우:
  classify_intent → route_utterance
       → (rag_mode=skip: chitchat/out_of_scope) generate_response → hitl_alert → update_cache → update_state → END
       → (knowledge) check_cache ─(hit)─→ update_state → END
                     (miss) → rewrite_query → adaptive_rag → (임계 분기) step_back → generate_response
                     → hitl_alert → update_cache → update_state → END
"""

import asyncio
import time
from collections import defaultdict
from typing import Any, Dict, Optional, Tuple

import structlog

from src.ai_voicebot.langgraph.state import ConversationState
from src.ai_voicebot.langgraph.nodes.classify_intent import classify_intent_node
from src.ai_voicebot.langgraph.nodes.route_utterance import (
    route_utterance_node,
    STEP_BACK_THRESHOLD_DOMAIN_QUESTION,
    STEP_BACK_THRESHOLD_LIGHT_QUESTION,
)
from src.ai_voicebot.langgraph.nodes.semantic_cache import check_cache_node, update_cache_node
from src.ai_voicebot.langgraph.nodes.rewrite_query import rewrite_query_node
from src.ai_voicebot.langgraph.nodes.adaptive_rag import adaptive_rag_node
from src.ai_voicebot.langgraph.nodes.generate_response import generate_response_node
from src.ai_voicebot.langgraph.nodes.step_back_prompt import step_back_node
from src.ai_voicebot.langgraph.nodes.hitl_alert import hitl_alert_node
from src.ai_voicebot.langgraph.nodes.update_state import update_state_node
from src.ai_voicebot.langgraph.nodes.greeting_farewell_cache import check_greeting_farewell_cache_node
from src.ai_voicebot.langgraph.nodes.response_shortcuts import (
    template_response_node,
    repeat_response_node,
    clarification_response_node,
    help_response_node,
)
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
        "step_back",
        "generate_response",
        "hitl_alert",
        "update_cache",
        "update_state",
        "template_response",
        "repeat_response",
        "clarification_response",
        "help_response",
        "check_greeting_farewell_cache",
    }
)


async def _invoke_graph_with_node_timing(
    graph: Any, invoke_state: Dict[str, Any]
) -> Tuple[Optional[Dict[str, Any]], Dict[str, float]]:
    """
    단일 그래프 실행으로 최종 state + 노드별 wall 시간을 수집한다.

    우선 stream_mode=["updates","values"] (한 번의 실행)로 updates 키=노드명,
    마지막 values 청크=병합된 전체 state.
    미지원 시 values만으로 최종 state만 수집하거나 (None, {}) 로 ainvoke 폴백.
    """
    ast = getattr(graph, "astream", None)
    if not callable(ast):
        return None, {}

    node_sec: Dict[str, float] = defaultdict(float)
    last_values: Optional[Dict[str, Any]] = None
    prev_wall = time.perf_counter()

    try:
        async for packet in ast(invoke_state, stream_mode=["updates", "values"]):
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
    except TypeError:
        try:
            prev = time.perf_counter()
            async for chunk in ast(invoke_state, stream_mode="values"):
                if isinstance(chunk, dict):
                    last_values = chunk
                    _ = time.perf_counter() - prev
                    prev = time.perf_counter()
        except Exception as e:
            logger.debug("langgraph_astream_values_only_failed", error=str(e))
            return None, {}
    except Exception as e:
        logger.debug("langgraph_astream_updates_values_failed", error=str(e))
        return None, {}

    rounded = {k: round(v, 4) for k, v in sorted(node_sec.items(), key=lambda x: -x[1])}
    return last_values, rounded


def _route_after_cache(state: ConversationState) -> str:
    """캐시 히트 여부에 따라 분기"""
    if state.get("rag_cache_hit"):
        return "update_state"
    return "rewrite_query"


def _route_after_intent(state: ConversationState) -> str:
    """의도에 따라 분기. 설계: AI_RESPONSE_HUMANLIKE_DESIGN.md §3.2, CHROMADB_CATEGORY_DESIGN §4.2"""
    intent = state.get("intent", "")
    if intent == "farewell":
        return "check_greeting_farewell_cache"
    if intent == "greeting":
        return "check_greeting_farewell_cache"
    # B 그룹 반응/피드백 → 템플릿 응답
    if intent in ("affirm", "deny", "gratitude", "doubt", "positive_reaction", "negative_reaction"):
        return "template_response"
    if intent == "repeat":
        return "repeat_response"
    if intent == "clarification":
        return "clarification_response"
    if intent == "help":
        return "help_response"
    # question / complaint / transfer / nlu_fallback 등 — 캐시·RAG 경로
    # chitchat·out_of_scope 는 route_utterance 에서 rag_mode=skip 으로 generate 직행
    return "check_cache"


def _route_after_utterance(state: ConversationState) -> str:
    """검색 전 레인: 일상 직행 vs 지식 경로."""
    if state.get("rag_mode") == "skip":
        return "generate_response"
    return _route_after_intent(state)


def _route_after_rag(state: ConversationState) -> str:
    """RAG confidence·도메인 질의 신호에 따라 step_back 분기 (이중 임계치)."""
    confidence = state.get("confidence", 0.0)
    intent = state.get("intent", "")
    domain = state.get("domain_question_signal", False)
    if intent == "question" and not domain:
        threshold = STEP_BACK_THRESHOLD_LIGHT_QUESTION
    else:
        threshold = STEP_BACK_THRESHOLD_DOMAIN_QUESTION
    if confidence < threshold:
        return "step_back"
    return "generate_response"


def _route_after_greeting_farewell_cache(state: ConversationState) -> str:
    """캐시 히트 시 update_state. 미스 시 knowledge RAG(인사/종료 category)로 폴백."""
    if state.get("rag_cache_hit"):
        return "update_state"
    if state.get("intent") in ("greeting", "farewell"):
        return "rewrite_query"
    return "update_state"


# 토폴로지 변경 시 버전 증가 → 기존 프로세스 내 캐시 무효화
_LANGGRAPH_SCHEMA_VERSION = 2
_compiled_graph_entry = None  # (version, compiled_graph)


def build_conversation_graph():
    """
    LangGraph StateGraph 워크플로우 빌드.
    
    컴파일된 그래프는 전역 캐시에 저장하여 재사용한다.
    매 통화마다 컴파일하면 ~7초 지연이 발생하므로 반드시 캐싱해야 한다.
    
    Returns:
        compiled StateGraph (invoke/ainvoke 가능)
    """
    global _compiled_graph_entry
    if _compiled_graph_entry is not None:
        ver, cached = _compiled_graph_entry
        if ver == _LANGGRAPH_SCHEMA_VERSION and cached is not None:
            logger.info("langgraph_graph_cache_hit", message="기존 컴파일된 그래프 재사용")
            return cached

    import time
    compile_start = time.time()

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
    graph.add_node("step_back", step_back_node)
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

    # ── 엣지 정의 ──
    graph.set_entry_point("classify_intent")
    graph.add_edge("classify_intent", "route_utterance")

    # route_utterance → 일상 직행(generate) 또는 기존 의도별 분기
    graph.add_conditional_edges(
        "route_utterance",
        _route_after_utterance,
        {
            "generate_response": "generate_response",
            "check_cache": "check_cache",
            "check_greeting_farewell_cache": "check_greeting_farewell_cache",
            "template_response": "template_response",
            "repeat_response": "repeat_response",
            "clarification_response": "clarification_response",
            "help_response": "help_response",
        },
    )

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
    for node_name in ("template_response", "repeat_response", "clarification_response", "help_response"):
        graph.add_edge(node_name, "update_state")

    # check_cache → (hit → update_state, miss → rewrite_query)
    graph.add_conditional_edges(
        "check_cache",
        _route_after_cache,
        {
            "update_state": "update_state",
            "rewrite_query": "rewrite_query",
        },
    )

    # rewrite_query → adaptive_rag
    graph.add_edge("rewrite_query", "adaptive_rag")

    # adaptive_rag → (low confidence → step_back, else → generate_response)
    graph.add_conditional_edges(
        "adaptive_rag",
        _route_after_rag,
        {
            "step_back": "step_back",
            "generate_response": "generate_response",
        },
    )

    # step_back → generate_response
    graph.add_edge("step_back", "generate_response")

    # generate_response → hitl_alert
    graph.add_edge("generate_response", "hitl_alert")

    # hitl_alert → update_cache
    graph.add_edge("hitl_alert", "update_cache")

    # update_cache → update_state
    graph.add_edge("update_cache", "update_state")

    # update_state → END
    graph.add_edge("update_state", END)

    compiled = graph.compile()
    compile_elapsed = time.time() - compile_start
    logger.info("langgraph_conversation_graph_compiled",
               nodes=10, edges="conditional+linear",
               compile_time=f"{compile_elapsed:.3f}s")

    _compiled_graph_entry = (_LANGGRAPH_SCHEMA_VERSION, compiled)
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

        self.graph = build_conversation_graph()
        self._state: ConversationState = {
            "messages": [],
            "turn_count": 0,
            "business_state": "initial",
            "rag_cache_hit": False,
            "needs_human": False,
            "confidence": 0.0,
        }

        if self.graph:
            logger.info("conversation_agent_initialized",
                       has_rag=rag_engine is not None,
                       has_cache=(vector_db is not None and embedder is not None))
        else:
            logger.warning("conversation_agent_graph_build_failed")

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

        # 현재 상태 + 새 입력 병합
        invoke_state = {
            **self._state,
            "user_query": user_text,
            "user_query_raw": user_query_raw,
            "org_context": org_context,
            "system_prompt": system_prompt,
            # 내부 참조 주입
            "_llm_client": self.llm_client,
            "_rag_engine": self.rag_engine,
            "_embedder": self.embedder,
            "_vector_db": self.vector_db,
            "_org_manager": self.org_manager,
            "_owner": self.owner,  # 착신번호 → RAG owner_filter
            "_call_id": call_id or "",  # 통화 ID → RAG/로그 call 키
        }

        try:
            graph_start = time.time()
            timed_result, node_durations_sec = await _invoke_graph_with_node_timing(
                self.graph, invoke_state
            )
            if timed_result is not None:
                result = timed_result
            else:
                logger.debug(
                    "langgraph_ainvoke_no_astream_events_or_empty",
                    call_id=call_id or "",
                    note="astream_events 미수신 시 단일 ainvoke",
                )
                result = await self.graph.ainvoke(invoke_state)
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
                "semantic_cache_score": result.get("semantic_cache_score"),
                "greeting_farewell_cache_score": result.get("greeting_farewell_cache_score"),
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
