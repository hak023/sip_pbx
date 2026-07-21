"""
AI Voicebot Unit Tests - settings_ai_assistant.py 카탈로그/Screen Graph 설정 내보내기 (Epic 2 Story 2.4)

docs/stories/2.4.frontend-catalog-export.story.md §AC/Testing 참고
"""

import pytest

from src.api.routers.settings_ai_assistant import export_catalog_config
from src.common import self_service_catalog_config_db as config_db


class TestExportCatalogConfig:
    def test_uses_db_source_when_active_version_exists(self, monkeypatch):
        fake_catalog = {"version_no": 3, "config_json": {"domains": {"persona": {}}}}
        fake_screen_graph = {"version_no": 5, "config_json": {"screens": {"chat-relay": {}}}}

        def fake_get_active_config(kind):
            return fake_catalog if kind == config_db.CATALOG_KIND else fake_screen_graph

        monkeypatch.setattr(config_db, "get_active_config", fake_get_active_config)

        result = export_catalog_config()

        assert result.catalog_source == "db"
        assert result.catalog_version == 3
        assert result.catalog == {"domains": {"persona": {}}}
        assert result.screen_graph_source == "db"
        assert result.screen_graph_version == 5
        assert result.screen_graph == {"screens": {"chat-relay": {}}}
        assert result.exported_at  # ISO 타임스탬프 문자열

    def test_falls_back_to_static_snapshot_when_no_active_version(self, monkeypatch):
        monkeypatch.setattr(config_db, "get_active_config", lambda kind: None)

        result = export_catalog_config()

        assert result.catalog_source == "static_fallback"
        assert result.catalog_version is None
        assert "persona" in result.catalog["domains"]
        assert result.screen_graph_source == "static_fallback"
        assert result.screen_graph_version is None
        assert "chat-relay" in result.screen_graph["screens"]

    def test_mixed_sources_are_independent_per_kind(self, monkeypatch):
        fake_catalog = {"version_no": 1, "config_json": {"domains": {"persona": {}}}}

        def fake_get_active_config(kind):
            return fake_catalog if kind == config_db.CATALOG_KIND else None

        monkeypatch.setattr(config_db, "get_active_config", fake_get_active_config)

        result = export_catalog_config()

        assert result.catalog_source == "db"
        assert result.screen_graph_source == "static_fallback"

    def test_export_contains_only_string_function_references(self, monkeypatch):
        """AC2: 함수 화이트리스트 이름(문자열)만 포함되고 실제 콜러블은 포함되지 않는다."""
        monkeypatch.setattr(config_db, "get_active_config", lambda kind: None)

        result = export_catalog_config()

        for domain, entry in result.catalog["domains"].items():
            get_ref = entry.get("get_fn_ref")
            update_ref = entry.get("update_fn_ref")
            assert get_ref is None or isinstance(get_ref, str)
            assert update_ref is None or isinstance(update_ref, str)
