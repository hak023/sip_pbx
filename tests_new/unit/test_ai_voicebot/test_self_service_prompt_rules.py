"""Story 1.19(축 A 완전판) — prompt_rules.py 자동 번호 렌더링 단위 테스트."""

from src.ai_voicebot.self_service import prompt_rules


class TestRenderBasePromptRules:
    def test_renders_all_base_rules_numbered_1_to_10(self):
        text = prompt_rules.render_base_prompt_rules()
        for i in range(1, 11):
            assert f"\n{i}. " in f"\n{text}"
        assert "11. " not in text

    def test_type_c_reference_resolved_to_actual_number(self):
        text = prompt_rules.render_base_prompt_rules()
        # type_c는 7번째로 등록되어 있어야 하고, 마지막 규칙이 이를 "7번"으로 참조해야 한다.
        assert "유형 C(7번)" in text
        assert "<<REF" not in text  # 센티널 토큰이 남아있지 않아야 함

    def test_fallback_message_placeholder_preserved_for_outer_format(self):
        text = prompt_rules.render_base_prompt_rules()
        assert "{fallback_message}" in text


class TestRenderToolPromptRules:
    def test_renders_all_tool_rules_numbered_continuing_from_base(self):
        text = prompt_rules.render_tool_prompt_rules()
        base_count = len(prompt_rules._BASE_RULES)
        assert f"{base_count + 1}. " in text
        assert f"{base_count + len(prompt_rules._TOOL_RULES)}. " in text

    def test_key_tool_names_present(self):
        text = prompt_rules.render_tool_prompt_rules()
        for tool_name in (
            "get_self_service_settings", "get_onboarding_checklist", "get_self_service_stats",
            "update_self_service_setting", "search_call_history", "get_top_caller",
            "get_missed_calls_today", "get_last_self_service_change",
            "undo_last_self_service_change",
        ):
            assert tool_name in text

    def test_no_sentinel_tokens_leak(self):
        text = prompt_rules.render_tool_prompt_rules()
        assert "<<REF" not in text


class TestRuleNumberComputation:
    def test_numbers_are_contiguous_and_unique(self):
        numbers = prompt_rules._compute_rule_numbers()
        values = sorted(numbers.values())
        assert values == list(range(1, len(values) + 1))
