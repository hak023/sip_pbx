"""
AI Voicebot Unit Tests - settings_ai_assistant.py 카탈로그/Screen Graph 설정 업로드·활성화·버전이력
(Epic 2 Story 2.5)

docs/stories/2.5.frontend-catalog-import.story.md §AC/IV1 참고
"""

import pytest
from fastapi import HTTPException

from src.api.routers.settings_ai_assistant import (
    CatalogConfigActivateRequest,
    CatalogConfigImportRequest,
    activate_catalog_config,
    get_catalog_config_versions,
    import_catalog_config,
)
from src.common import self_service_catalog_config_db as config_db


def _valid_catalog():
    return {
        "domains": {
            "persona": {
                "get_fn_ref": "get_persona",
                "update_fn_ref": "update_persona",
                "schema": {}, "destructive": False, "writable_fields": [], "field_allowed_values": {},
            },
        },
    }


def _valid_screen_graph():
    return {
        "screens": {
            "chat-relay": {
                "route": "/settings/chat-relay", "title": "t", "description": "d",
                "nav_hint": "n", "fields": [],
            },
        },
    }


class TestImportCatalogConfigValidationAtomicity:
    def test_invalid_catalog_rejects_without_saving(self, monkeypatch):
        save_calls = []
        monkeypatch.setattr(config_db, "get_active_config", lambda kind: None)
        monkeypatch.setattr(
            config_db, "save_new_version",
            lambda *a, **kw: save_calls.append((a, kw)) or 1,
        )

        bad_catalog = {"domains": {"persona": {"get_fn_ref": "os.system"}}}
        payload = CatalogConfigImportRequest(catalog=bad_catalog, screen_graph=_valid_screen_graph())

        result = import_catalog_config(payload)

        assert result.ok is False
        assert any("os.system" in e for e in result.catalog_errors)
        assert save_calls == []  # IV1: 검증 실패 시 아무것도 저장되지 않음

    def test_invalid_screen_graph_rejects_without_saving(self, monkeypatch):
        save_calls = []
        monkeypatch.setattr(config_db, "get_active_config", lambda kind: None)
        monkeypatch.setattr(
            config_db, "save_new_version",
            lambda *a, **kw: save_calls.append((a, kw)) or 1,
        )

        bad_screen_graph = {"screens": {"chat-relay": {"route": "/x"}}}  # title/description/nav_hint 누락
        payload = CatalogConfigImportRequest(catalog=_valid_catalog(), screen_graph=bad_screen_graph)

        result = import_catalog_config(payload)

        assert result.ok is False
        assert len(result.screen_graph_errors) > 0
        assert save_calls == []


class TestImportCatalogConfigSuccess:
    def test_valid_configs_are_saved_and_diff_is_returned(self, monkeypatch):
        active_catalog = {"config_json": {"domains": {}}}
        active_screen_graph = {"config_json": {"screens": {}}}

        monkeypatch.setattr(
            config_db, "get_active_config",
            lambda kind: active_catalog if kind == config_db.CATALOG_KIND else active_screen_graph,
        )

        saved = {}

        def fake_save(kind, config, *, uploaded_by="", note=""):
            saved[kind] = (config, uploaded_by, note)
            return 7 if kind == config_db.CATALOG_KIND else 9

        monkeypatch.setattr(config_db, "save_new_version", fake_save)

        payload = CatalogConfigImportRequest(
            catalog=_valid_catalog(), screen_graph=_valid_screen_graph(),
            uploaded_by="admin@example.com", note="테스트 업로드",
        )
        result = import_catalog_config(payload)

        assert result.ok is True
        assert result.catalog_version == 7
        assert result.screen_graph_version == 9
        assert result.catalog_diff.added == ["persona"]
        assert result.screen_graph_diff.added == ["chat-relay"]
        assert saved[config_db.CATALOG_KIND][1] == "admin@example.com"
        assert saved[config_db.CATALOG_KIND][2] == "테스트 업로드"


class TestActivateCatalogConfig:
    def test_successful_activation(self, monkeypatch):
        monkeypatch.setattr(
            config_db, "activate_version",
            lambda kind, version_no, *, activated_by="": True,
        )
        payload = CatalogConfigActivateRequest(config_kind=config_db.CATALOG_KIND, version_no=3, activated_by="a")
        result = activate_catalog_config(payload)
        assert result.ok is True
        assert result.version_no == 3
        assert result.error is None

    def test_failed_activation_returns_error(self, monkeypatch):
        monkeypatch.setattr(config_db, "activate_version", lambda kind, version_no, *, activated_by="": False)
        payload = CatalogConfigActivateRequest(config_kind=config_db.CATALOG_KIND, version_no=999)
        result = activate_catalog_config(payload)
        assert result.ok is False
        assert "999" in result.error

    def test_unknown_config_kind_rejected(self):
        payload = CatalogConfigActivateRequest(config_kind="bogus", version_no=1)
        result = activate_catalog_config(payload)
        assert result.ok is False
        assert "bogus" in result.error


class TestGetCatalogConfigVersions:
    def test_returns_mapped_version_list(self, monkeypatch):
        monkeypatch.setattr(
            config_db, "list_versions",
            lambda kind, limit=20: [
                {
                    "version_no": 2, "is_active": True, "uploaded_by": "a", "note": "n",
                    "created_at": "2026-07-20 10:00:00", "activated_at": "2026-07-20 10:05:00",
                    "activated_by": "a",
                },
                {
                    "version_no": 1, "is_active": False, "uploaded_by": "b", "note": "",
                    "created_at": "2026-07-19 09:00:00", "activated_at": None, "activated_by": "",
                },
            ],
        )
        result = get_catalog_config_versions(config_kind=config_db.CATALOG_KIND, limit=20)
        assert result.config_kind == config_db.CATALOG_KIND
        assert len(result.versions) == 2
        assert result.versions[0].is_active is True
        assert result.versions[1].activated_at is None

    def test_unknown_config_kind_raises_http_exception(self):
        with pytest.raises(HTTPException):
            get_catalog_config_versions(config_kind="bogus", limit=20)
