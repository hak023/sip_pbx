"""
AI Voicebot Unit Tests - 셀프서비스 온보딩 체크리스트 (Story 1.5)

Story 1.5: 온보딩 체크리스트 안내
docs/stories/1.5.onboarding-checklist.story.md §Testing 참고
"""

import pytest

from src.ai_voicebot.self_service import onboarding
from src.ai_voicebot.self_service.tools import get_onboarding_checklist_tool
from src.ai_voicebot.langgraph.nodes.self_service_agent import self_service_agent_node


class TestPersonaIncomplete:
    def test_missing_persona_is_incomplete(self):
        assert onboarding._persona_incomplete({"exists": False}) is True

    def test_empty_name_and_description_is_incomplete(self):
        assert onboarding._persona_incomplete({"exists": True, "name": "", "description": ""}) is True

    def test_filled_persona_is_complete(self):
        value = {"exists": True, "name": "이탈리안 비스트로", "description": "레스토랑"}
        assert onboarding._persona_incomplete(value) is False

    def test_error_value_is_not_incomplete(self):
        assert onboarding._persona_incomplete({"error": "boom"}) is False


class TestAiEscalationIncomplete:
    def test_persona_not_exists_is_incomplete(self):
        assert onboarding._ai_escalation_incomplete({"escalation_mode": "hitl", "persona_exists": False}) is True

    def test_persona_exists_is_complete(self):
        assert onboarding._ai_escalation_incomplete({"escalation_mode": "transfer", "persona_exists": True}) is False

    def test_error_value_is_not_incomplete(self):
        assert onboarding._ai_escalation_incomplete({"error": "boom"}) is False


class TestCallControlIncomplete:
    def test_no_rules_is_incomplete(self):
        assert onboarding._call_control_incomplete({"rules": []}) is True

    def test_has_rules_is_complete(self):
        assert onboarding._call_control_incomplete({"rules": [{"id": "r1"}]}) is False

    def test_error_value_is_not_incomplete(self):
        assert onboarding._call_control_incomplete({"error": "boom"}) is False


class TestGetOnboardingChecklist:
    """settings_catalog.get_domain_value()만 사용하는지(IV1), 완료/미완료 목록 왕복 검증"""

    @pytest.mark.asyncio
    async def test_all_incomplete_returns_all_three_items(self, monkeypatch):
        async def fake_get_domain_value(domain, owner):
            return {
                "persona": {"exists": False},
                "ai-escalation": {"escalation_mode": "hitl", "persona_exists": False},
                "call-control": {"rules": []},
            }[domain]

        monkeypatch.setattr(
            "src.ai_voicebot.self_service.onboarding.settings_catalog.get_domain_value",
            fake_get_domain_value,
        )
        items = await onboarding.get_onboarding_checklist("1003")
        assert {i["domain"] for i in items} == {"persona", "ai-escalation", "call-control"}

    @pytest.mark.asyncio
    async def test_all_complete_returns_empty_list(self, monkeypatch):
        async def fake_get_domain_value(domain, owner):
            return {
                "persona": {"exists": True, "name": "이탈리안 비스트로", "description": "레스토랑"},
                "ai-escalation": {"escalation_mode": "hitl", "persona_exists": True},
                "call-control": {"rules": [{"id": "r1"}]},
            }[domain]

        monkeypatch.setattr(
            "src.ai_voicebot.self_service.onboarding.settings_catalog.get_domain_value",
            fake_get_domain_value,
        )
        items = await onboarding.get_onboarding_checklist("1003")
        assert items == []

    @pytest.mark.asyncio
    async def test_catalog_error_dicts_do_not_produce_incomplete_items(self, monkeypatch):
        """settings_catalog.get_domain_value()가 {"error": ...}를 반환해도(카탈로그 자체 조회 실패)
        온보딩 체크리스트는 크래시하지 않고 해당 항목을 미완료로 오판하지 않는다."""

        async def fake_get_domain_value(domain, owner):
            return {"error": "persona_service_unavailable"}

        monkeypatch.setattr(
            "src.ai_voicebot.self_service.onboarding.settings_catalog.get_domain_value",
            fake_get_domain_value,
        )
        items = await onboarding.get_onboarding_checklist("1003")
        assert items == []


class TestGetOnboardingChecklistTool:
    @pytest.mark.asyncio
    async def test_tool_returns_json_with_items(self, monkeypatch):
        async def fake_checklist(owner):
            return [{"domain": "persona", "message": "안내문"}]

        monkeypatch.setattr(
            "src.ai_voicebot.self_service.tools._get_onboarding_checklist_impl",
            fake_checklist,
        )
        # langchain 미설치/설치 여부와 무관하게 원본 async 함수 또는 Tool 래퍼 모두
        # ainvoke 가능한 형태여야 하므로, 원본 함수 참조로 직접 호출해 검증한다.
        from src.ai_voicebot.self_service.tools import _get_onboarding_checklist

        result = await _get_onboarding_checklist("1003")
        assert "persona" in result
        assert "incomplete_count" in result


class TestSelfServiceAgentNodeOnboardingIntegration:
    """self_service_agent_node의 온보딩 체크리스트 통합 동작 검증 (Task 3)"""

    @pytest.mark.asyncio
    async def test_first_turn_with_incomplete_items_injects_checklist(self, monkeypatch):
        captured = {}

        class _FakeLLM:
            async def generate_response(self, **kwargs):
                captured["system_prompt"] = kwargs.get("system_prompt", "")
                return "안녕하세요! 몇 가지 설정을 도와드릴게요."

        async def fake_checklist(owner):
            return [{"domain": "call-control", "message": "착신 규칙이 없어요."}]

        monkeypatch.setattr(
            "src.ai_voicebot.langgraph.nodes.self_service_agent.get_llm_client",
            lambda: _FakeLLM(),
        )
        monkeypatch.setattr(
            "src.ai_voicebot.langgraph.nodes.self_service_agent.get_self_service_rag_engine",
            lambda: None,
        )
        monkeypatch.setattr(
            "src.ai_voicebot.langgraph.nodes.self_service_agent.get_onboarding_checklist",
            fake_checklist,
        )

        state = {"user_query": "안녕하세요", "_owner": "1003", "_call_id": "test-onb-1", "messages": []}
        result = await self_service_agent_node(state)

        assert "착신 규칙이 없어요" in captured["system_prompt"]
        assert result["intent"] == "self_service"

    @pytest.mark.asyncio
    async def test_first_turn_all_complete_does_not_mention_checklist(self, monkeypatch):
        captured = {}

        class _FakeLLM:
            async def generate_response(self, **kwargs):
                captured["system_prompt"] = kwargs.get("system_prompt", "")
                return "안녕하세요!"

        async def fake_checklist(owner):
            return []

        monkeypatch.setattr(
            "src.ai_voicebot.langgraph.nodes.self_service_agent.get_llm_client",
            lambda: _FakeLLM(),
        )
        monkeypatch.setattr(
            "src.ai_voicebot.langgraph.nodes.self_service_agent.get_self_service_rag_engine",
            lambda: None,
        )
        monkeypatch.setattr(
            "src.ai_voicebot.langgraph.nodes.self_service_agent.get_onboarding_checklist",
            fake_checklist,
        )

        state = {"user_query": "안녕하세요", "_owner": "1003", "_call_id": "test-onb-2", "messages": []}
        await self_service_agent_node(state)

        assert "모든 초기 설정이 완료됨" in captured["system_prompt"]

    @pytest.mark.asyncio
    async def test_non_first_turn_does_not_call_checklist(self, monkeypatch):
        checklist_called = {"count": 0}

        class _FakeLLM:
            async def generate_response(self, **kwargs):
                return "네, 이어서 도와드릴게요."

        async def fake_checklist(owner):
            checklist_called["count"] += 1
            return [{"domain": "persona", "message": "안내"}]

        monkeypatch.setattr(
            "src.ai_voicebot.langgraph.nodes.self_service_agent.get_llm_client",
            lambda: _FakeLLM(),
        )
        monkeypatch.setattr(
            "src.ai_voicebot.langgraph.nodes.self_service_agent.get_self_service_rag_engine",
            lambda: None,
        )
        monkeypatch.setattr(
            "src.ai_voicebot.langgraph.nodes.self_service_agent.get_onboarding_checklist",
            fake_checklist,
        )

        state = {
            "user_query": "다른 질문이요",
            "_owner": "1003",
            "_call_id": "test-onb-3",
            "messages": [{"role": "user", "content": "이전 질문"}, {"role": "assistant", "content": "이전 답변"}],
        }
        await self_service_agent_node(state)

        assert checklist_called["count"] == 0

    @pytest.mark.asyncio
    async def test_onboarding_checklist_error_does_not_break_response(self, monkeypatch):
        class _FakeLLM:
            async def generate_response(self, **kwargs):
                return "안녕하세요!"

        async def fake_checklist_raises(owner):
            raise RuntimeError("catalog down")

        monkeypatch.setattr(
            "src.ai_voicebot.langgraph.nodes.self_service_agent.get_llm_client",
            lambda: _FakeLLM(),
        )
        monkeypatch.setattr(
            "src.ai_voicebot.langgraph.nodes.self_service_agent.get_self_service_rag_engine",
            lambda: None,
        )
        monkeypatch.setattr(
            "src.ai_voicebot.langgraph.nodes.self_service_agent.get_onboarding_checklist",
            fake_checklist_raises,
        )

        state = {"user_query": "안녕하세요", "_owner": "1003", "_call_id": "test-onb-4", "messages": []}
        result = await self_service_agent_node(state)

        assert result["response"]
        assert result["intent"] == "self_service"
