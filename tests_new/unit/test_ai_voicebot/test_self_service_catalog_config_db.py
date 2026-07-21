"""
AI Voicebot Unit Tests - 셀프서비스 카탈로그/Screen Graph 동적 구성 DB (Epic 2 Story 2.1)

docs/stories/2.1.catalog-config-storage.story.md 참고
"""

import sqlite3
from contextlib import contextmanager

import pytest

from src.common import self_service_catalog_config_db as config_db


@pytest.fixture
def temp_db(tmp_path, monkeypatch):
    db_path = tmp_path / "test_self_service_catalog.db"
    conn = sqlite3.connect(str(db_path))
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS self_service_catalog_config (
            id           INTEGER PRIMARY KEY AUTOINCREMENT,
            config_kind  TEXT    NOT NULL,
            version_no   INTEGER NOT NULL,
            config_json  TEXT    NOT NULL DEFAULT '{}',
            is_active    INTEGER NOT NULL DEFAULT 0,
            uploaded_by  TEXT    NOT NULL DEFAULT '',
            note         TEXT    NOT NULL DEFAULT '',
            created_at   TEXT    NOT NULL DEFAULT (datetime('now','localtime')),
            activated_at TEXT    DEFAULT NULL,
            activated_by TEXT    NOT NULL DEFAULT '',
            UNIQUE(config_kind, version_no)
        )
        """
    )
    conn.commit()
    conn.close()

    @contextmanager
    def fake_get_db():
        c = sqlite3.connect(str(db_path))
        c.row_factory = sqlite3.Row
        try:
            yield c
            c.commit()
        finally:
            c.close()

    monkeypatch.setattr("src.booking.database.get_db", fake_get_db)
    return db_path


class TestSaveAndGetActiveConfig:
    def test_save_new_version_starts_inactive(self, temp_db):
        version_no = config_db.save_new_version(
            config_db.CATALOG_KIND, {"domains": {"persona": {}}}, uploaded_by="tester",
        )
        assert version_no == 1
        assert config_db.get_active_config(config_db.CATALOG_KIND) is None

    def test_activate_version_makes_it_active(self, temp_db):
        version_no = config_db.save_new_version(config_db.CATALOG_KIND, {"domains": {}})
        ok = config_db.activate_version(config_db.CATALOG_KIND, version_no)
        assert ok is True

        active = config_db.get_active_config(config_db.CATALOG_KIND)
        assert active is not None
        assert active["version_no"] == version_no
        assert active["is_active"] is True
        assert active["config_json"] == {"domains": {}}

    def test_activate_nonexistent_version_returns_false(self, temp_db):
        assert config_db.activate_version(config_db.CATALOG_KIND, 999) is False

    def test_activate_version_records_activated_by_and_timestamp(self, temp_db):
        version_no = config_db.save_new_version(config_db.CATALOG_KIND, {"domains": {}})
        ok = config_db.activate_version(config_db.CATALOG_KIND, version_no, activated_by="admin@example.com")
        assert ok is True

        active = config_db.get_active_config(config_db.CATALOG_KIND)
        assert active["activated_by"] == "admin@example.com"
        assert active["activated_at"]  # 타임스탬프 문자열 존재

    def test_invalid_kind_returns_none_or_false(self, temp_db):
        assert config_db.get_active_config("bogus_kind") is None
        assert config_db.save_new_version("bogus_kind", {}) is None
        assert config_db.activate_version("bogus_kind", 1) is False


class TestVersioningAndRollback:
    def test_multiple_versions_increment_and_only_latest_activated_is_active(self, temp_db):
        v1 = config_db.save_new_version(config_db.CATALOG_KIND, {"v": 1})
        v2 = config_db.save_new_version(config_db.CATALOG_KIND, {"v": 2})
        assert v1 == 1 and v2 == 2

        config_db.activate_version(config_db.CATALOG_KIND, v1)
        config_db.activate_version(config_db.CATALOG_KIND, v2)

        active = config_db.get_active_config(config_db.CATALOG_KIND)
        assert active["version_no"] == v2
        assert active["config_json"] == {"v": 2}

    def test_rollback_reactivates_older_version(self, temp_db):
        v1 = config_db.save_new_version(config_db.CATALOG_KIND, {"label": "old"})
        v2 = config_db.save_new_version(config_db.CATALOG_KIND, {"label": "new"})
        config_db.activate_version(config_db.CATALOG_KIND, v2)
        assert config_db.get_active_config(config_db.CATALOG_KIND)["config_json"]["label"] == "new"

        # 롤백: v1을 다시 활성화
        ok = config_db.activate_version(config_db.CATALOG_KIND, v1)
        assert ok is True
        assert config_db.get_active_config(config_db.CATALOG_KIND)["config_json"]["label"] == "old"

    def test_rollback_updates_activated_by_to_rollback_actor(self, temp_db):
        v1 = config_db.save_new_version(config_db.CATALOG_KIND, {"label": "old"})
        v2 = config_db.save_new_version(config_db.CATALOG_KIND, {"label": "new"})
        config_db.activate_version(config_db.CATALOG_KIND, v2, activated_by="uploader@example.com")

        config_db.activate_version(config_db.CATALOG_KIND, v1, activated_by="rollback-admin@example.com")

        active = config_db.get_active_config(config_db.CATALOG_KIND)
        assert active["version_no"] == v1
        assert active["activated_by"] == "rollback-admin@example.com"

    def test_list_versions_returns_newest_first(self, temp_db):
        config_db.save_new_version(config_db.CATALOG_KIND, {"v": 1})
        config_db.save_new_version(config_db.CATALOG_KIND, {"v": 2})
        config_db.save_new_version(config_db.CATALOG_KIND, {"v": 3})

        versions = config_db.list_versions(config_db.CATALOG_KIND)
        assert [v["version_no"] for v in versions] == [3, 2, 1]

    def test_catalog_and_screen_graph_kinds_have_independent_version_sequences(self, temp_db):
        c1 = config_db.save_new_version(config_db.CATALOG_KIND, {"k": "catalog"})
        s1 = config_db.save_new_version(config_db.SCREEN_GRAPH_KIND, {"k": "screen_graph"})
        assert c1 == 1
        assert s1 == 1  # 서로 다른 kind는 독립적인 버전 번호를 가진다

        config_db.activate_version(config_db.CATALOG_KIND, c1)
        config_db.activate_version(config_db.SCREEN_GRAPH_KIND, s1)

        assert config_db.get_active_config(config_db.CATALOG_KIND)["config_json"] == {"k": "catalog"}
        assert config_db.get_active_config(config_db.SCREEN_GRAPH_KIND)["config_json"] == {"k": "screen_graph"}
