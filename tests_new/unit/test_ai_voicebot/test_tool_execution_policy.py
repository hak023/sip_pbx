"""
Story 1.34(FR34-A) 설계 스파이크 단위테스트.
tool_execution_policy.py 승인 검사 헬퍼 + knowledge_documents_db.update_approved_methods 경로.
"""

from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager

import pytest

from src.ai_voicebot.self_service.tool_execution_policy import (
    is_method_approved,
    validate_execution_request,
    ALLOWED_WRITE_METHODS,
)


class TestIsMethodApproved:
    def test_get_always_approved(self):
        assert is_method_approved("GET", [])
        assert is_method_approved("get", [])

    def test_unapproved_write_method_returns_false(self):
        assert not is_method_approved("POST", ["GET"])

    def test_approved_write_method_returns_true(self):
        assert is_method_approved("POST", ["GET", "POST"])

    def test_case_insensitive(self):
        assert is_method_approved("post", ["GET", "POST"])
        assert is_method_approved("DELETE", ["get", "delete"])


class TestValidateExecutionRequest:
    def test_get_always_ok(self):
        ok, reason = validate_execution_request(method="GET", approved_methods=[])
        assert ok is True
        assert reason == ""

    def test_unknown_method_rejected(self):
        ok, reason = validate_execution_request(method="CONNECT", approved_methods=["CONNECT"])
        assert ok is False
        assert "지원하지 않는" in reason

    def test_unapproved_write_rejected(self):
        ok, reason = validate_execution_request(method="POST", approved_methods=["GET"])
        assert ok is False
        assert "승인" in reason

    def test_approved_write_accepted(self):
        ok, reason = validate_execution_request(method="DELETE", approved_methods=["GET", "DELETE"])
        assert ok is True


class TestUpdateApprovedMethods:
    @pytest.fixture
    def temp_db(self, tmp_path, monkeypatch):
        db_path = tmp_path / "test_kd.db"
        conn = sqlite3.connect(str(db_path))
        conn.execute(
            """
            CREATE TABLE knowledge_documents (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                document_id TEXT NOT NULL UNIQUE,
                owner TEXT NOT NULL,
                title TEXT NOT NULL DEFAULT '',
                domain_tags_json TEXT NOT NULL DEFAULT '[]',
                source_type TEXT NOT NULL DEFAULT 'markdown',
                chunk_doc_ids_json TEXT NOT NULL DEFAULT '[]',
                approved_methods_json TEXT NOT NULL DEFAULT '["GET"]',
                version_no INTEGER NOT NULL DEFAULT 1,
                is_active INTEGER NOT NULL DEFAULT 1,
                uploaded_by TEXT NOT NULL DEFAULT '',
                uploaded_at TEXT NOT NULL DEFAULT (datetime('now','localtime')),
                updated_at TEXT NOT NULL DEFAULT (datetime('now','localtime'))
            )
            """
        )
        conn.execute(
            "INSERT INTO knowledge_documents (document_id, owner, source_type)"
            " VALUES (?, ?, ?)",
            ("doc-1", "9001", "openapi"),
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

    def test_approve_post_adds_to_list(self, temp_db):
        from src.common.knowledge_documents_db import update_approved_methods

        result = update_approved_methods("doc-1", owner="9001", approved_methods=["POST"])
        assert result is not None
        assert "POST" in result["approved_methods"]
        assert "GET" in result["approved_methods"]

    def test_unknown_method_ignored(self, temp_db):
        from src.common.knowledge_documents_db import update_approved_methods

        result = update_approved_methods("doc-1", owner="9001", approved_methods=["UNKNOWN", "POST"])
        assert result is not None
        assert "UNKNOWN" not in result["approved_methods"]
        assert "POST" in result["approved_methods"]

    def test_wrong_owner_returns_none(self, temp_db):
        from src.common.knowledge_documents_db import update_approved_methods

        result = update_approved_methods("doc-1", owner="other", approved_methods=["POST"])
        assert result is None

    def test_get_always_included(self, temp_db):
        from src.common.knowledge_documents_db import update_approved_methods

        result = update_approved_methods("doc-1", owner="9001", approved_methods=[])
        assert result is not None
        assert result["approved_methods"] == ["GET"]
