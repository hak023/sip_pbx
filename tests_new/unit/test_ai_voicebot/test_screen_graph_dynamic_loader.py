"""
AI Voicebot Unit Tests - screen_graph.py 동적(DB) Screen Graph 로딩 (Epic 2 Story 2.3)

docs/stories/2.3.screen-graph-dynamic.story.md §AC/Testing 참고

tests_new/unit/conftest.py의 오토유즈 픽스처가 기본적으로
`catalog_config_loader.get_cached_config()`를 None으로 고정해 하드코딩 폴백을 쓰도록
격리하므로, 이 파일의 테스트들은 그 위에서 `get_cached_config`를 원하는 값으로 다시
패치해 동적 로딩 자체를 검증한다.
"""

import pytest

from src.ai_voicebot.self_service import catalog_config_loader
from src.ai_voicebot.self_service import screen_graph


@pytest.fixture(autouse=True)
def _reset_effective_screens_cache():
    """모듈 전역 캐시(`_effective_screens_cache*`)가 테스트 간 오염되지 않도록 초기화."""
    screen_graph._effective_screens_cache = None
    screen_graph._effective_screens_cache_source_id = None
    yield
    screen_graph._effective_screens_cache = None
    screen_graph._effective_screens_cache_source_id = None


class TestEffectiveScreensFallback:
    def test_no_active_db_config_falls_back_to_static_registry(self, monkeypatch):
        monkeypatch.setattr(catalog_config_loader, "get_cached_config", lambda kind: None)
        assert screen_graph.list_all_screens() == list(screen_graph._SCREEN_REGISTRY.values())

    def test_empty_screens_dict_falls_back_to_static_registry(self, monkeypatch):
        monkeypatch.setattr(catalog_config_loader, "get_cached_config", lambda kind: {"screens": {}})
        assert screen_graph.list_all_screens() == list(screen_graph._SCREEN_REGISTRY.values())

    def test_malformed_config_missing_screens_key_falls_back(self, monkeypatch):
        monkeypatch.setattr(catalog_config_loader, "get_cached_config", lambda kind: {"oops": True})
        assert screen_graph.list_all_screens() == list(screen_graph._SCREEN_REGISTRY.values())


class TestEffectiveScreensDynamicOverride:
    def test_dynamic_config_replaces_static_registry(self, monkeypatch):
        dynamic_config = {
            "screens": {
                "chat-relay": {
                    "route": "/settings/chat-relay",
                    "title": "채팅 자동응답 설정(동적)",
                    "description": "동적 구성 테스트용 설명",
                    "nav_hint": "설정 > 조직·채팅 > 채팅·SIP MESSAGE(동적)",
                    "fields": [
                        {"field": "message_ai_reply_enabled", "element_type": "toggle", "label": "자동응답 사용"},
                    ],
                },
            },
        }
        monkeypatch.setattr(catalog_config_loader, "get_cached_config", lambda kind: dynamic_config)

        screens = screen_graph.list_all_screens()
        assert len(screens) == 1
        entry = screen_graph.get_screen_for_domain("chat-relay")
        assert entry.title == "채팅 자동응답 설정(동적)"
        assert entry.nav_hint == "설정 > 조직·채팅 > 채팅·SIP MESSAGE(동적)"
        assert entry.fields[0].field == "message_ai_reply_enabled"
        assert entry.fields[0].element_type == "toggle"

    def test_describe_screen_for_conversation_uses_dynamic_nav_hint(self, monkeypatch):
        dynamic_config = {
            "screens": {
                "ai-escalation": {
                    "route": "/settings/ai-escalation",
                    "title": "AI 에스컬레이션 설정",
                    "description": "설명",
                    "nav_hint": "동적으로 바뀐 안내 문구",
                    "fields": [],
                },
            },
        }
        monkeypatch.setattr(catalog_config_loader, "get_cached_config", lambda kind: dynamic_config)

        text = screen_graph.describe_screen_for_conversation("ai-escalation")
        assert "동적으로 바뀐 안내 문구" in text
        assert "/settings/ai-escalation" not in text  # nav_hint만 노출, route는 여전히 미노출

    def test_domain_absent_from_dynamic_config_returns_none(self, monkeypatch):
        monkeypatch.setattr(
            catalog_config_loader, "get_cached_config",
            lambda kind: {"screens": {"chat-relay": {"route": "/x", "title": "t", "description": "d", "nav_hint": "n"}}},
        )
        assert screen_graph.get_screen_for_domain("ai-escalation") is None

    def test_effective_screens_is_cached_by_raw_config_identity(self, monkeypatch):
        call_count = {"n": 0}
        dynamic_config = {
            "screens": {"chat-relay": {"route": "/x", "title": "t", "description": "d", "nav_hint": "n", "fields": []}},
        }

        def fake_get_cached_config(kind):
            call_count["n"] += 1
            return dynamic_config

        monkeypatch.setattr(catalog_config_loader, "get_cached_config", fake_get_cached_config)

        screen_graph.list_all_screens()
        screen_graph.list_all_screens()

        assert call_count["n"] == 2  # 로더 호출 자체는 매번 일어나지만
        first = screen_graph._get_effective_screens()
        second = screen_graph._get_effective_screens()
        assert first is second  # ScreenEntry 딕셔너리 재구성은 캐시되어 동일 인스턴스 재사용
