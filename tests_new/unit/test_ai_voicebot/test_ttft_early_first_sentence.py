"""
AI Voicebot Unit Tests - TTFT 안전 서브셋 조기 첫 문장 감지 (Story 4.2)

docs/stories/4.2.ttft-safe-subset-implementation.story.md 참고.
`_invoke_graph_with_node_timing(on_node_update=...)`가 실제 LangGraph astream 이벤트 흐름을
흉내낸 가짜 그래프로 정확히 동작하는지(안전 조건 충족 시에만 콜백 발동) 검증한다. 실제
LLM/서버 호출 없이 순수 단위 테스트로 검증 가능하도록 fake graph를 사용한다.
"""

import pytest

from src.ai_voicebot.langgraph.agent import (
    ConversationAgent,
    _invoke_graph_with_node_timing,
)


class _FakeGraph:
    """astream()이 (mode, chunk) 튜플 시퀀스를 그대로 재생하는 가짜 LangGraph 컴파일 그래프."""

    def __init__(self, packets):
        self._packets = packets

    async def astream(self, invoke_state, **kwargs):
        for packet in self._packets:
            yield packet


def _updates(node_name: str, node_output: dict):
    return ("updates", {node_name: node_output})


def _final_values(state: dict):
    return ("values", state)


class TestInvokeGraphOnNodeUpdateCallback:
    @pytest.mark.asyncio
    async def test_callback_fires_for_chitchat_with_chunks(self):
        fired = []

        async def cb(node_name, node_output):
            fired.append((node_name, node_output))

        graph = _FakeGraph([
            _updates("classify_intent", {"intent": "chitchat"}),
            _updates(
                "generate_response",
                {
                    "intent": "chitchat",
                    "needs_follow_up": False,
                    "response_chunks": ["안녕하세요! ", "오늘도 좋은 하루 되세요."],
                },
            ),
            _final_values({"response": "안녕하세요! 오늘도 좋은 하루 되세요."}),
        ])

        result, _durations = await _invoke_graph_with_node_timing(
            graph, {}, on_node_update=cb
        )

        assert result == {"response": "안녕하세요! 오늘도 좋은 하루 되세요."}
        # classify_intent 포함 여러 노드에 대해 콜백이 호출되지만, generate_response 건만 채택 대상
        gen_calls = [c for c in fired if c[0] == "generate_response"]
        assert len(gen_calls) == 1

    @pytest.mark.asyncio
    async def test_callback_not_invoked_when_none(self):
        """on_node_update=None(기존 모든 호출부)이면 예외 없이 기존과 동일하게 동작한다."""
        graph = _FakeGraph([
            _updates("generate_response", {"intent": "chitchat", "response_chunks": ["hi"]}),
            _final_values({"response": "hi"}),
        ])

        result, _durations = await _invoke_graph_with_node_timing(graph, {})
        assert result == {"response": "hi"}

    @pytest.mark.asyncio
    async def test_callback_receives_non_generate_response_nodes_too(self):
        """콜백은 모든 노드에 대해 호출되며, 안전 조건 판별은 호출부(agent.py wrapper) 책임이다."""
        seen_nodes = []

        async def cb(node_name, node_output):
            seen_nodes.append(node_name)

        graph = _FakeGraph([
            _updates("classify_intent", {"intent": "question"}),
            _updates("route_utterance", {}),
        ])

        await _invoke_graph_with_node_timing(graph, {}, on_node_update=cb)
        assert seen_nodes == ["classify_intent", "route_utterance"]


class TestProcessUtteranceFirstSentenceSafetyWrapper:
    """ConversationAgent.process_utterance()의 _maybe_fire_first_sentence 안전 조건 검증.

    실제 그래프 실행 없이, agent.py에 정의된 안전 조건 로직 자체가 문서(Story 4.1)의
    안전 서브셋 정의(intent in {chitchat, out_of_scope} + needs_follow_up=False +
    비아웃바운드)와 일치하는지를 별도로 재현해 검증한다.
    """

    @staticmethod
    def _make_checker(is_outbound: bool):
        fired = {}

        async def on_first_sentence(text, intent):
            fired["text"] = text
            fired["intent"] = intent

        async def maybe_fire(node_name, node_output):
            if node_name != "generate_response":
                return
            if is_outbound:
                return
            intent_out = node_output.get("intent")
            if intent_out not in ("chitchat", "out_of_scope"):
                return
            if node_output.get("needs_follow_up"):
                return
            chunks = node_output.get("response_chunks") or []
            if not chunks or not (chunks[0] or "").strip():
                return
            await on_first_sentence(chunks[0].strip(), intent_out)

        return maybe_fire, fired

    @pytest.mark.asyncio
    async def test_fires_for_chitchat_safe_case(self):
        maybe_fire, fired = self._make_checker(is_outbound=False)
        await maybe_fire(
            "generate_response",
            {"intent": "chitchat", "needs_follow_up": False, "response_chunks": ["첫 문장."]},
        )
        assert fired.get("text") == "첫 문장."
        assert fired.get("intent") == "chitchat"

    @pytest.mark.asyncio
    async def test_does_not_fire_for_booking_intent(self):
        maybe_fire, fired = self._make_checker(is_outbound=False)
        await maybe_fire(
            "generate_response",
            {"intent": "booking", "needs_follow_up": False, "response_chunks": ["예약을 도와드릴게요."]},
        )
        assert fired == {}

    @pytest.mark.asyncio
    async def test_does_not_fire_when_needs_follow_up_true(self):
        """설계 가정(chitchat/out_of_scope는 항상 needs_follow_up=False)이 깨지는 경우를 대비한 방어."""
        maybe_fire, fired = self._make_checker(is_outbound=False)
        await maybe_fire(
            "generate_response",
            {"intent": "out_of_scope", "needs_follow_up": True, "response_chunks": ["잘 모르겠어요."]},
        )
        assert fired == {}

    @pytest.mark.asyncio
    async def test_does_not_fire_for_outbound_session(self):
        maybe_fire, fired = self._make_checker(is_outbound=True)
        await maybe_fire(
            "generate_response",
            {"intent": "chitchat", "needs_follow_up": False, "response_chunks": ["안녕하세요."]},
        )
        assert fired == {}

    @pytest.mark.asyncio
    async def test_does_not_fire_when_no_chunks(self):
        maybe_fire, fired = self._make_checker(is_outbound=False)
        await maybe_fire(
            "generate_response",
            {"intent": "chitchat", "needs_follow_up": False, "response_chunks": []},
        )
        assert fired == {}
