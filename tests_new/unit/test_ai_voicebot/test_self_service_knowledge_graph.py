"""Story 1.18(축 B) — Screen Graph 다중 홉 지식 그래프(knowledge_graph.py) 단위 테스트."""

from src.ai_voicebot.self_service import knowledge_graph


def test_traverse_writable_domain_returns_screen_and_applicable_types():
    info = knowledge_graph.traverse("chat-relay", max_hops=2)
    assert info["domain"] == "chat-relay"
    assert info["screen"] is not None
    assert info["writable"] is True
    codes = {spec.code for spec in info["applicable_intent_types"]}
    assert "B" in codes and "E" in codes


def test_traverse_non_writable_domain_excludes_write_types():
    info = knowledge_graph.traverse("contacts", max_hops=2)
    assert info["writable"] is False
    codes = {spec.code for spec in info["applicable_intent_types"]}
    assert "B" not in codes
    assert "E" not in codes


def test_traverse_max_hops_1_skips_writable_and_intent_types():
    info = knowledge_graph.traverse("chat-relay", max_hops=1)
    assert info["screen"] is not None
    assert info["writable"] is False
    assert info["applicable_intent_types"] == []


def test_format_decision_hint_writable_domain():
    hint = knowledge_graph.format_decision_hint("chat-relay")
    assert "변경" in hint and "되돌리기" in hint


def test_format_decision_hint_readonly_domain():
    hint = knowledge_graph.format_decision_hint("contacts")
    assert "조회만" in hint


def test_format_decision_hint_unknown_domain_returns_empty():
    assert knowledge_graph.format_decision_hint("does-not-exist") == ""
