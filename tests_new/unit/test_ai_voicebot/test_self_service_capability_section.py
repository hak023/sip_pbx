"""
AI Voicebot Unit Tests - 유형 C(도움 요청) 능력 섹션 동적 생성 (Story 1.17)

docs/stories/1.17.capability-registry-rag-plan.story.md 참고.
"""

import pytest

from src.ai_voicebot.langgraph.nodes.self_service_agent import (
    _STATIC_CAPABILITY_FALLBACK,
    _format_capability_section,
)


class TestFormatCapabilitySection:
    def test_includes_queryable_and_writable_domains_with_labels(self, monkeypatch):
        monkeypatch.setattr(
            "src.ai_voicebot.langgraph.nodes.self_service_agent.settings_catalog.list_domains",
            lambda: ["persona", "chat-relay", "contacts"],
        )

        def fake_writable(domain):
            return frozenset({"enabled"}) if domain == "chat-relay" else None

        monkeypatch.setattr(
            "src.ai_voicebot.langgraph.nodes.self_service_agent.settings_catalog.domain_writable_fields",
            fake_writable,
        )
        result = _format_capability_section()
        assert "페르소나" in result
        assert "채팅 자동응답" in result
        assert "연락처" in result
        # writable 라인에는 chat-relay(채팅 자동응답)만 포함되고 persona/contacts는 없어야 함
        writable_line = next(line for line in result.split("\n") if "설정 변경" in line)
        assert "채팅 자동응답" in writable_line
        assert "페르소나" not in writable_line
        assert "연락처" not in writable_line

    def test_includes_tool_based_capabilities(self, monkeypatch):
        monkeypatch.setattr(
            "src.ai_voicebot.langgraph.nodes.self_service_agent.settings_catalog.list_domains",
            lambda: ["persona"],
        )
        monkeypatch.setattr(
            "src.ai_voicebot.langgraph.nodes.self_service_agent.settings_catalog.domain_writable_fields",
            lambda domain: None,
        )
        result = _format_capability_section()
        assert "이용 통계 조회" in result
        assert "통화 이력 자연어 조회" in result
        assert "방금 바꾼 설정 되돌리기" in result

    def test_falls_back_to_static_when_no_domains(self, monkeypatch):
        monkeypatch.setattr(
            "src.ai_voicebot.langgraph.nodes.self_service_agent.settings_catalog.list_domains",
            lambda: [],
        )
        result = _format_capability_section()
        assert result == _STATIC_CAPABILITY_FALLBACK

    def test_falls_back_to_static_on_exception(self, monkeypatch):
        def boom():
            raise RuntimeError("catalog unavailable")

        monkeypatch.setattr(
            "src.ai_voicebot.langgraph.nodes.self_service_agent.settings_catalog.list_domains", boom,
        )
        result = _format_capability_section()
        assert result == _STATIC_CAPABILITY_FALLBACK

    def test_unknown_domain_falls_back_to_raw_identifier(self, monkeypatch):
        """_DOMAIN_LABELS에 없는 도메인명은 그대로 노출(존재하지 않는 라벨을 지어내지 않음)."""
        monkeypatch.setattr(
            "src.ai_voicebot.langgraph.nodes.self_service_agent.settings_catalog.list_domains",
            lambda: ["some-new-domain"],
        )
        monkeypatch.setattr(
            "src.ai_voicebot.langgraph.nodes.self_service_agent.settings_catalog.domain_writable_fields",
            lambda domain: None,
        )
        result = _format_capability_section()
        assert "some-new-domain" in result
