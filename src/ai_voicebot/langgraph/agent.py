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

logger = structlog.get_logger(__name__)


def _route_after_cache(state: ConversationState) -> str:
    """캐시 히트 여부에 따라 분기"""
    if state.get("rag_cache_hit"):
        return "update_state"
    return "rewrite_query"


def _route_after_intent(state: ConversationState) -> str:
    """의도에 따라 분기"""
    intent = state.get("intent", "")
    if intent == "farewell":
        return "update_state"
    if intent == "greeting":
        # 인사 의도는 캐시 스킵 → 바로 응답 생성
        return "generate_response"
    return "check_cache"


def _route_after_rag(state: ConversationState) -> str:
    """RAG confidence에 따라 분기"""
    confidence = state.get("confidence", 0.0)
    if confidence < 0.4:
        return "step_back"
    return "generate_response"


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

    # ── 엣지 정의 ──
    # 시작점
    graph.set_entry_point("classify_intent")

    # classify_intent → (farewell → update_state, greeting → generate, else → check_cache)
    graph.add_conditional_edges(
        "classify_intent",
        _route_after_intent,
        {
            "update_state": "update_state",
            "generate_response": "generate_response",
            "check_cache": "check_cache",
        },
    )

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

            # 결과에서 지속 상태 추출
            self._state["messages"] = result.get("messages", self._state["messages"])
            self._state["turn_count"] = result.get("turn_count", self._state["turn_count"])
            self._state["business_state"] = result.get("business_state", self._state["business_state"])

            total_elapsed = time.time() - utterance_start
            
            # ✅ 구간별 타이밍 로그 (디버깅용)
            logger.info("⏱️ [TIMING] process_utterance 완료",
                       user_text=user_text[:50],
                       total_elapsed=f"{total_elapsed:.3f}s",
                       langgraph_elapsed=f"{graph_elapsed:.3f}s",
                       intent=result.get("intent", "unknown"),
                       confidence=f"{result.get('confidence', 0.0):.3f}",
                       cache_hit=result.get("rag_cache_hit", False),
                       response_len=len(result.get("response", "")))

            return {
                "response": result.get("response", ""),
                "confidence": result.get("confidence", 0.0),
                "intent": result.get("intent", "unknown"),
                "needs_human": result.get("needs_human", False),
                "hitl_reason": result.get("hitl_reason", ""),
                "business_state": result.get("business_state", "initial"),
                "response_chunks": result.get("response_chunks", []),
                "rag_cache_hit": result.get("rag_cache_hit", False),
            }

        except Exception as e:
            logger.error("conversation_agent_invoke_error",
                       error=str(e), exc_info=True)
            return {
                "response": "죄송합니다. 일시적인 오류가 발생했습니다.",
                "confidence": 0.0,
                "intent": "unknown",
                "needs_human": False,
            }

    async def generate_greeting(self) -> str:
        """
        1차 인사 메시지 생성 (통화 시작 시 호출).
        
        고정 템플릿 기반으로 빠르게 인사합니다.
        LLM 호출 없이 즉시 반환하여 사용자 대기 시간을 최소화합니다.
        """
        if self.org_manager:
            org_name = self.org_manager.get_organization_name()
            # VectorDB tenant_config의 greeting_templates에서 랜덤 선택
            try:
                template = self.org_manager.get_random_greeting_template()
                if template:
                    return template
            except Exception:
                pass
        else:
            org_name = "AI 비서"

        return f"안녕하세요. {org_name} AI 통화 비서입니다. 무엇을 도와드릴까요?"

    async def generate_capability_guide(self) -> str:
        """
        2차 인사말: 업무 안내 메시지 생성.
        
        기관의 capabilities를 기반으로 "저는 ~을 도와드릴 수 있습니다" 형태의
        안내 메시지를 생성합니다. 캐시가 비어 있으면 load_capabilities()로 먼저 로드.
        """
        capabilities = []
        org_name = "AI 비서"
        
        if self.org_manager:
            org_name = self.org_manager.get_organization_name()
            try:
                # 캐시가 비어 있으면 VectorDB에서 먼저 로드 (실제 가이드 멘트가 TTS로 나가도록)
                await self.org_manager.load_capabilities()
                capabilities = self.org_manager.get_capabilities()
            except Exception:
                pass
        
        if not capabilities:
            return "어떤 내용이 궁금하시면 편하게 말씀해 주세요."
        
        # API 가이드 멘트 미리보기와 동일한 문장으로 통일 (캐시된 미리보기 = 실제 TTS 안내)
        cap_text = ", ".join(capabilities[:7])  # API와 동일 7개 제한
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
