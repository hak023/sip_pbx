"""
LangGraph Agentic RAG Agent.

ConversationState를 공유하는 StateGraph 워크플로우.
설계서 Phase 2의 핵심: 모든 RAG/LLM 흐름을 LangGraph로 오케스트레이션.

워크플로우:
  classify_intent → check_cache ─(hit)─→ update_state → END
                                  │
                              (miss)
                                  ↓
                           rewrite_query → adaptive_rag → step_back →
                           generate_response → hitl_alert → update_cache →
                           update_state → END
"""

import asyncio
from typing import Optional

import structlog

from src.ai_voicebot.langgraph.state import ConversationState
from src.ai_voicebot.langgraph.nodes.classify_intent import classify_intent_node
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
    fallback_response_node,
)

logger = structlog.get_logger(__name__)


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
    if intent in ("out_of_scope", "nlu_fallback"):
        return "fallback_response"
    # 잡담: RAG/semantic cache 없이 LLM만으로 짧게 응답
    if intent == "chitchat":
        return "generate_response"
    # question, complaint, transfer, unknown → 캐시·RAG 경로
    return "check_cache"


def _route_after_rag(state: ConversationState) -> str:
    """RAG confidence에 따라 분기"""
    confidence = state.get("confidence", 0.0)
    if confidence < 0.4:
        return "step_back"
    return "generate_response"


def _route_after_greeting_farewell_cache(state: ConversationState) -> str:
    """캐시 히트 시 update_state. 미스 시 knowledge RAG(인사/종료 category)로 폴백."""
    if state.get("rag_cache_hit"):
        return "update_state"
    if state.get("intent") in ("greeting", "farewell"):
        return "rewrite_query"
    return "update_state"


_compiled_graph_cache = None  # 전역 캐시: 서버 라이프사이클 동안 재사용


def build_conversation_graph():
    """
    LangGraph StateGraph 워크플로우 빌드.
    
    컴파일된 그래프는 전역 캐시에 저장하여 재사용한다.
    매 통화마다 컴파일하면 ~7초 지연이 발생하므로 반드시 캐싱해야 한다.
    
    Returns:
        compiled StateGraph (invoke/ainvoke 가능)
    """
    global _compiled_graph_cache
    if _compiled_graph_cache is not None:
        logger.info("langgraph_graph_cache_hit", message="기존 컴파일된 그래프 재사용")
        return _compiled_graph_cache

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
    graph.add_node("fallback_response", fallback_response_node)
    graph.add_node("check_greeting_farewell_cache", check_greeting_farewell_cache_node)

    # ── 엣지 정의 ──
    graph.set_entry_point("classify_intent")

    # classify_intent → 의도별 분기 (greeting/farewell은 캐시 선검색)
    graph.add_conditional_edges(
        "classify_intent",
        _route_after_intent,
        {
            "update_state": "update_state",
            "generate_response": "generate_response",
            "check_cache": "check_cache",
            "check_greeting_farewell_cache": "check_greeting_farewell_cache",
            "template_response": "template_response",
            "repeat_response": "repeat_response",
            "clarification_response": "clarification_response",
            "help_response": "help_response",
            "fallback_response": "fallback_response",
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
    for node_name in ("template_response", "repeat_response", "clarification_response", "help_response", "fallback_response"):
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
               nodes=9, edges="conditional+linear",
               compile_time=f"{compile_elapsed:.3f}s")

    _compiled_graph_cache = compiled
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

    async def process_utterance(self, user_text: str, call_id: Optional[str] = None) -> dict:
        """
        사용자 발화 처리 (메인 API).

        Args:
            user_text: STT 결과 텍스트
            call_id: 통화 ID (로그/DB 연계용, call 키로 필터 가능)

        Returns:
            dict with keys: response, confidence, intent, needs_human, hitl_reason,
                           business_state, response_chunks, rag_cache_hit
        """
        import time
        utterance_start = time.time()

        if not self.graph:
            logger.error("conversation_agent_no_graph")
            return {"response": "시스템 오류가 발생했습니다.", "confidence": 0.0}

        # 기관 정보 로드
        org_context = ""
        system_prompt = ""
        if self.org_manager:
            org_context = self.org_manager.get_organization_context()
            system_prompt = self.org_manager.get_system_prompt()

        # 현재 상태 + 새 입력 병합
        invoke_state = {
            **self._state,
            "user_query": user_text,
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
            result = await self.graph.ainvoke(invoke_state)
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
            
            # ✅ 구간별 타이밍 로그 (6.2 지연 구간 점검: classify_intent(LLM), generate_response(LLM) 로그 참고)
            logger.info("process_utterance_complete",
                       user_text=user_text[:50],
                       total_elapsed=f"{total_elapsed:.3f}s",
                       langgraph_elapsed=f"{graph_elapsed:.3f}s",
                       intent=result.get("intent", "unknown"),
                       confidence=f"{result.get('confidence', 0.0):.3f}",
                       cache_hit=result.get("rag_cache_hit", False),
                       response_len=len(result.get("response", "")),
                       note="지연 시 ⏱️ [TIMING] classify_intent (LLM) / generate_response (LLM) 로그로 구간 확인")

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
            }

    async def generate_greeting(self) -> str:
        """
        1차 인사 메시지 생성 (통화 시작 시 호출).

        우선순위:
        1) 지식베이스 `knowledge` 컬렉션 category=greeting_phase1 (owner 일치)
        2) tenant_config `greeting_templates` (OrganizationInfoManager)
        3) 기본 문구

        LLM 호출 없이 즉시 반환.
        """
        # 1) 지식베이스 greeting_phase1 (CHROMADB_CATEGORY_DESIGN)
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
                        preview=kb_text[:120],
                        note="지식베이스 greeting_phase1 문서 본문 사용",
                    )
                    return kb_text.strip()
            except Exception as e:
                logger.debug("greeting_kb_phase1_lookup_failed", owner=self.owner, error=str(e))

        org_name = "AI 비서"
        if self.org_manager:
            org_name = self.org_manager.get_organization_name()
            try:
                template = self.org_manager.get_random_greeting_template()
                if template and len(template.strip()) >= 5:
                    # tenant_config greeting_templates — 짧은 멘트·다양한 표현 허용
                    return template.strip()
            except Exception:
                pass
        full = f"안녕하세요. {org_name} AI 통화 비서입니다. 무엇을 도와드릴까요?"
        return full

    async def generate_capability_guide(self) -> str:
        """
        2차 인사말: 업무 안내 메시지 생성.

        우선순위:
        1) 지식베이스 category=greeting_phase2
        2) capabilities 기반 자동 문장
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
                        preview=kb_text[:120],
                        note="지식베이스 greeting_phase2 문서 본문 사용",
                    )
                    return kb_text.strip()
            except Exception as e:
                logger.debug("greeting_kb_phase2_lookup_failed", owner=self.owner, error=str(e))

        capabilities = []
        org_name = "AI 비서"

        if self.org_manager:
            org_name = self.org_manager.get_organization_name()
            try:
                await self.org_manager.load_capabilities()
                capabilities = self.org_manager.get_capabilities()
            except Exception:
                pass

        if not capabilities:
            return "어떤 내용이 궁금하시면 편하게 말씀해 주세요."

        cap_text = ", ".join(capabilities[:7])
        return f"저는 {cap_text}을 도와드릴 수 있어요. 어떤 것이 궁금하신가요?"

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
