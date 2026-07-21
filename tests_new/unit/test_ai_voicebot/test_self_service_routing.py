"""
AI Voicebot Unit Tests - 셀프서비스 대화 레인 라우팅(Self-Service Conversation Lane)

Story 1.2: 셀프서비스 전용 대화 레인 및 페르소나
docs/stories/1.2.self-service-conversation-lane.story.md §Testing 참고
"""

import pytest

from src.ai_voicebot.langgraph.agent import (
    _route_after_classify,
    _build_state_graph,
    _LANGGRAPH_SCHEMA_VERSION,
)
from src.ai_voicebot.langgraph.nodes.self_service_agent import self_service_agent_node


class TestRouteAfterClassify:
    """_route_after_classify() 분기 테스트"""

    def test_self_service_intent_routes_to_self_service_agent(self):
        """intent="self_service" → self_service_agent"""
        assert _route_after_classify({"intent": "self_service"}) == "self_service_agent"

    def test_outbound_purpose_takes_priority_over_self_service(self):
        """방어적 테스트: outbound_purpose + self_service 동시 True 시 outbound가 우선(기존 동작 유지, CR1)"""
        state = {"outbound_purpose": "설문조사", "intent": "self_service"}
        assert _route_after_classify(state) == "generate_response"

    def test_outbound_purpose_only(self):
        """outbound_purpose만 있으면 generate_response (기존 동작 회귀 없음)"""
        assert _route_after_classify({"outbound_purpose": "설문조사"}) == "generate_response"

    @pytest.mark.parametrize("intent", ["question", "chitchat", "booking", "greeting", "farewell"])
    def test_existing_intents_still_route_to_route_utterance(self, intent):
        """기존 booking/question/chitchat 등 intent가 self-service 분기 추가 후에도 동일하게 route_utterance로 감(회귀 없음)"""
        assert _route_after_classify({"intent": intent}) == "route_utterance"

    def test_no_intent_defaults_to_route_utterance(self):
        assert _route_after_classify({}) == "route_utterance"


class TestGraphCompilation:
    """그래프 컴파일 회귀 테스트"""

    def test_build_state_graph_succeeds_with_new_node(self):
        graph = _build_state_graph()
        assert graph is not None

    def test_schema_version_incremented(self):
        assert _LANGGRAPH_SCHEMA_VERSION == 9


class TestSelfServiceAgentNode:
    """self_service_agent_node() 단위 테스트"""

    @pytest.mark.asyncio
    async def test_returns_self_service_intent_and_business_state(self, monkeypatch):
        """AC2/AC3: intent="self_service", business_state="self_service_handled" 반환"""

        class _FakeLLM:
            async def generate_response(self, **kwargs):
                return "안녕하세요! 무엇을 도와드릴까요?"

        monkeypatch.setattr(
            "src.ai_voicebot.langgraph.nodes.self_service_agent.get_llm_client",
            lambda: _FakeLLM(),
        )

        state = {
            "user_query": "안녕하세요",
            "_owner": "1003",
            "_call_id": "test-call-1",
            "_caller_number": "1003",
            "messages": [],
        }
        result = await self_service_agent_node(state)

        assert result["intent"] == "self_service"
        assert result["business_state"] == "self_service_handled"
        assert result["response"]
        assert len(result["messages"]) == 2

    @pytest.mark.asyncio
    async def test_no_llm_client_returns_fallback(self, monkeypatch):
        monkeypatch.setattr(
            "src.ai_voicebot.langgraph.nodes.self_service_agent.get_llm_client",
            lambda: None,
        )
        state = {"user_query": "안녕하세요", "_call_id": "test-call-2"}
        result = await self_service_agent_node(state)

        assert result["intent"] == "self_service"
        assert result["response"]
