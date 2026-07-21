"""
AI Voicebot Unit Tests - 셀프서비스 변경 이력 조회 API (Story 1.9)

Story 1.9: 자동설정 변경 이력 프론트엔드 페이지
docs/stories/1.9.config-change-history-page.story.md §Testing 참고
"""

import sqlite3
from contextlib import contextmanager

import pytest

from src.api.routers.self_service import get_config_changes
from src.common.self_service_config_change_db import record_config_change


@pytest.fixture
def temp_db(tmp_path, monkeypatch):
    db_path = tmp_path / "test_self_service.db"
    conn = sqlite3.connect(str(db_path))
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS self_service_config_changes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            owner TEXT NOT NULL,
            domain TEXT NOT NULL,
            field TEXT NOT NULL,
            old_value TEXT NOT NULL DEFAULT '',
            new_value TEXT NOT NULL DEFAULT '',
            call_id TEXT NOT NULL DEFAULT '',
            changed_at TEXT NOT NULL DEFAULT (datetime('now','localtime'))
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


class TestGetConfigChanges:
    """get_config_changes() 라우터 함수 — owner 필터/정렬/왕복 검증 (AC1/AC2, Testing #1~2)"""

    def test_owner_filter_isolates_other_tenants(self, temp_db):
        record_config_change(owner="owner-a", domain="persona", field="name", old_value="a1", new_value="a2")
        record_config_change(owner="owner-b", domain="persona", field="name", old_value="b1", new_value="b2")

        result = get_config_changes(owner="owner-a", limit=50)

        assert result["total"] == 1
        assert result["items"][0]["owner"] == "owner-a"

    def test_sorted_by_changed_at_desc(self, temp_db):
        import time

        record_config_change(owner="1003", domain="persona", field="name", old_value="1", new_value="2")
        time.sleep(1.1)  # changed_at 초 단위 해상도이므로 순서 보장을 위해 약간 대기
        record_config_change(owner="1003", domain="chat-relay", field="message_ai_reply_enabled", old_value="0", new_value="1")

        result = get_config_changes(owner="1003", limit=50)

        assert len(result["items"]) == 2
        # 가장 최근(chat-relay)이 첫 번째여야 함
        assert result["items"][0]["domain"] == "chat-relay"
        assert result["items"][1]["domain"] == "persona"

    def test_includes_expected_fields(self, temp_db):
        record_config_change(
            owner="1003", domain="ai-escalation", field="escalation_mode",
            old_value="hitl", new_value="transfer", call_id="call-123",
        )
        result = get_config_changes(owner="1003", limit=50)
        item = result["items"][0]
        assert item["domain"] == "ai-escalation"
        assert item["field"] == "escalation_mode"
        assert item["old_value"] == "hitl"
        assert item["new_value"] == "transfer"
        assert item["call_id"] == "call-123"
        assert "changed_at" in item

    def test_empty_history_returns_empty_list(self, temp_db):
        result = get_config_changes(owner="no-history-owner", limit=50)
        assert result == {"items": [], "total": 0}

    def test_limit_is_forwarded(self, temp_db, monkeypatch):
        captured = {}

        def fake_list_config_changes(owner, limit=100):
            captured["owner"] = owner
            captured["limit"] = limit
            return []

        monkeypatch.setattr(
            "src.api.routers.self_service.list_config_changes",
            fake_list_config_changes,
        )
        get_config_changes(owner="1003", limit=10)
        assert captured == {"owner": "1003", "limit": 10}
