"""
AI Voicebot Unit Tests - settings_ai_assistant.py IntelliDecision 정책 레지스트리 API (Story 1.18, 축 C-1)

docs/stories/1.18.intellidecision-policy-registry-and-knowledge-graph.story.md 참고
"""

from src.api.routers.settings_ai_assistant import get_intellidecision_policy


class TestGetIntelliDecisionPolicy:
    def test_returns_all_nine_types(self):
        result = get_intellidecision_policy()
        codes = {t.code for t in result.types}
        assert codes == set("ABCDEFGHI")

    def test_type_b_marks_tool_and_writable_requirements(self):
        result = get_intellidecision_policy()
        type_b = next(t for t in result.types if t.code == "B")
        assert type_b.name == "실행성"
        assert type_b.requires_tool is True
        assert type_b.requires_writable_domain is True
        assert len(type_b.trigger_examples) > 0

    def test_type_c_does_not_require_tool(self):
        result = get_intellidecision_policy()
        type_c = next(t for t in result.types if t.code == "C")
        assert type_c.requires_tool is False
