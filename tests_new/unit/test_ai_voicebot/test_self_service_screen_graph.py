"""
AI Voicebot Unit Tests - Screen Graph (화면 안내 경량 지식 그래프, Story 1.11)

Story 1.11: Screen Graph 구축 및 화면 안내형 응대
docs/stories/1.11.screen-graph-guided-assistance.story.md §Testing 참고
"""

import pytest

from src.ai_voicebot.self_service import screen_graph


class TestGetScreenForDomain:
    @pytest.mark.parametrize("domain", [
        "ai-escalation", "chat-relay", "call-control", "general", "integrations", "contacts",
    ])
    def test_registered_domains_return_entry(self, domain):
        entry = screen_graph.get_screen_for_domain(domain)
        assert entry is not None
        assert entry.domain == domain
        assert entry.route.startswith("/")

    def test_persona_has_no_dedicated_screen(self):
        """persona는 name/description/scope_keywords가 지식베이스 관리 영역으로 이전되어
        전용 설정 폼이 없다 — 존재하지 않는 화면을 안내하지 않기 위해 의도적으로 미등록."""
        assert screen_graph.get_screen_for_domain("persona") is None

    def test_unknown_domain_returns_none(self):
        assert screen_graph.get_screen_for_domain("does-not-exist") is None


class TestListAllScreens:
    def test_returns_all_registered_screens(self):
        screens = screen_graph.list_all_screens()
        domains = {s.domain for s in screens}
        assert "ai-escalation" in domains
        assert "chat-relay" in domains
        assert "persona" not in domains  # 의도적으로 미등록


class TestDescribeScreenForConversation:
    def test_registered_domain_returns_nonempty_guidance(self):
        text = screen_graph.describe_screen_for_conversation("ai-escalation")
        assert text
        # 2026-07-20: 사용자는 API 경로/URL을 알 수도, 알 필요도 없으므로(전화 대화 중)
        # 대화체 안내는 raw route가 아니라 메인화면 기준 클릭 경로(nav_hint)를 사용해야 한다.
        assert "/settings/ai-escalation" not in text
        assert "설정" in text and "AI 에스컬레이션" in text

    def test_unregistered_domain_returns_empty_string(self):
        assert screen_graph.describe_screen_for_conversation("persona") == ""
        assert screen_graph.describe_screen_for_conversation("does-not-exist") == ""

    def test_never_raises_on_bad_input(self):
        """best-effort 계약 — 어떤 입력에도 예외를 던지지 않는다."""
        assert screen_graph.describe_screen_for_conversation(None) == ""  # type: ignore[arg-type]
        assert screen_graph.describe_screen_for_conversation(12345) == ""  # type: ignore[arg-type]

    def test_call_control_lists_all_tabs(self):
        text = screen_graph.describe_screen_for_conversation("call-control")
        assert "rules" in text.lower() or "규칙" in text
