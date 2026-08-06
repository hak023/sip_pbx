"""
Story 1.35(FR34-A) 단위테스트 — 동적 API 실행기(실제 HTTP 호출 없음).

승인 검사 → 스냅샷 → 실행 → 로그 기록 → Undo 경로를 httpx 모킹으로 검증한다.
"""

from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager

import pytest

from src.ai_voicebot.self_service import dynamic_api_tool as dat


@pytest.fixture
def temp_db(tmp_path, monkeypatch):
    db_path = tmp_path / "test.db"
    conn = sqlite3.connect(str(db_path))
    conn.execute(
        """
        CREATE TABLE tool_execution_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            owner TEXT, document_id TEXT, method TEXT, endpoint_path TEXT,
            request_json TEXT, pre_state_json TEXT,
            response_status INTEGER, response_json TEXT,
            undo_attempted INTEGER NOT NULL DEFAULT 0, undo_ok INTEGER,
            created_at TEXT NOT NULL DEFAULT (datetime('now','localtime'))
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


def _stub_http(status: int, data: any):
    async def _stub(**kwargs):
        return status, data
    return _stub


class TestExecuteApiEndpoint:
    @pytest.mark.asyncio
    async def test_unapproved_method_rejected_without_http_call(self, monkeypatch, temp_db):
        called = {"http": False}

        async def fake_http(**kwargs):
            called["http"] = True
            return 200, {}

        monkeypatch.setattr(dat, "_do_http_request", fake_http)
        result = await dat.execute_api_endpoint(
            base_url="https://api.example.com", endpoint_path="/orders", method="POST",
            headers={}, approved_methods=["GET"],
            document_id="doc-1", owner="9001",
        )
        assert result["ok"] is False
        assert result["status"] == 403
        assert called["http"] is False

    @pytest.mark.asyncio
    async def test_get_always_executes_without_snapshot(self, monkeypatch, temp_db):
        calls = []

        async def fake_http(*, method, **kwargs):
            calls.append(method)
            return 200, {"items": [1, 2]}

        monkeypatch.setattr(dat, "_do_http_request", fake_http)
        result = await dat.execute_api_endpoint(
            base_url="https://api.example.com", endpoint_path="/orders", method="GET",
            headers={}, approved_methods=["GET"],
            document_id="doc-1", owner="9001",
        )
        assert result["ok"] is True
        assert calls == ["GET"]  # 스냅샷 GET 없음 — 단 1회만

    @pytest.mark.asyncio
    async def test_write_method_takes_snapshot_first(self, monkeypatch, temp_db):
        calls = []

        async def fake_http(*, method, url, **kwargs):
            calls.append(method)
            return 200, {"id": 42}

        monkeypatch.setattr(dat, "_do_http_request", fake_http)
        result = await dat.execute_api_endpoint(
            base_url="https://api.example.com", endpoint_path="/orders/1", method="DELETE",
            headers={}, approved_methods=["GET", "DELETE"],
            document_id="doc-1", owner="9001",
        )
        assert result["ok"] is True
        assert calls[0] == "GET"  # 스냅샷
        assert calls[1] == "DELETE"  # 실제 실행

    @pytest.mark.asyncio
    async def test_5xx_retried_once(self, monkeypatch, temp_db):
        attempts = {"n": 0}

        async def fake_http(*, method, **kwargs):
            if method != "GET":
                attempts["n"] += 1
                return 500, {"error": "internal"} if attempts["n"] < 2 else 200, {"ok": True}
            return 200, {}

        monkeypatch.setattr(dat, "_do_http_request", fake_http)
        monkeypatch.setattr(dat, "asyncio", __import__("asyncio"))
        import asyncio

        async def no_sleep(*a, **kw):
            pass

        monkeypatch.setattr(asyncio, "sleep", no_sleep)
        # 2nd try succeeds — first 500 then 200
        calls = []

        async def counting_http(*, method, **kwargs):
            if method == "GET":
                return 200, {}
            calls.append(1)
            if len(calls) == 1:
                return 500, {"error": "first"}
            return 200, {"ok": True}

        monkeypatch.setattr(dat, "_do_http_request", counting_http)
        result = await dat.execute_api_endpoint(
            base_url="https://api.example.com", endpoint_path="/resource", method="POST",
            headers={}, approved_methods=["GET", "POST"],
            document_id="doc-1", owner="9001",
        )
        assert len(calls) == 2

    @pytest.mark.asyncio
    async def test_4xx_not_retried(self, monkeypatch, temp_db):
        calls = []

        async def fake_http(*, method, **kwargs):
            if method != "GET":
                calls.append(1)
                return 404, {"detail": "not found"}
            return 200, {}

        monkeypatch.setattr(dat, "_do_http_request", fake_http)
        result = await dat.execute_api_endpoint(
            base_url="https://api.example.com", endpoint_path="/resource/99", method="DELETE",
            headers={}, approved_methods=["GET", "DELETE"],
            document_id="doc-1", owner="9001",
        )
        assert result["ok"] is False
        assert len(calls) == 1  # 재시도 없음

    @pytest.mark.asyncio
    async def test_timeout_returns_error(self, monkeypatch, temp_db):
        async def fake_http(*, method, **kwargs):
            if method == "GET":
                return 200, {}
            return 408, {"error": "timeout"}

        monkeypatch.setattr(dat, "_do_http_request", fake_http)
        result = await dat.execute_api_endpoint(
            base_url="https://api.example.com", endpoint_path="/slow", method="POST",
            headers={}, approved_methods=["GET", "POST"],
            document_id="doc-1", owner="9001",
        )
        assert result["ok"] is False
        assert "초과" in result["error"]


class TestUndoLastExecution:
    @pytest.mark.asyncio
    async def test_no_log_returns_error(self, monkeypatch, temp_db):
        result = await dat.undo_last_execution(owner="9001", document_id="doc-none")
        assert result["ok"] is False

    @pytest.mark.asyncio
    async def test_log_with_pre_state_returns_state(self, monkeypatch, temp_db):
        from src.booking.database import get_db

        with get_db() as conn:
            conn.execute(
                "INSERT INTO tool_execution_log"
                " (owner, document_id, method, endpoint_path, request_json,"
                "  pre_state_json, response_status, response_json)"
                " VALUES (?,?,?,?,?,?,?,?)",
                ("9001", "doc-1", "DELETE", "/orders/1", "{}", '{"id":1,"qty":5}', 200, "null"),
            )

        monkeypatch.setattr(
            dat, "build_execution_context",
            lambda document_id, owner: {
                "base_url": "https://api.example.com", "headers": {}, "approved_methods": ["GET", "PUT", "DELETE"],
            },
        )

        async def fake_http(*, method, **kwargs):
            return 200, {"restored": True}

        monkeypatch.setattr(dat, "_do_http_request", fake_http)

        result = await dat.undo_last_execution(owner="9001", document_id="doc-1")
        assert result["ok"] is True
        assert result["pre_state"] == {"id": 1, "qty": 5}

    @pytest.mark.asyncio
    async def test_log_without_pre_state_returns_error(self, monkeypatch, temp_db):
        from src.booking.database import get_db

        with get_db() as conn:
            conn.execute(
                "INSERT INTO tool_execution_log"
                " (owner, document_id, method, endpoint_path, request_json,"
                "  pre_state_json, response_status, response_json)"
                " VALUES (?,?,?,?,?,?,?,?)",
                ("9001", "doc-1", "POST", "/items", "{}", "null", 201, "null"),
            )
        result = await dat.undo_last_execution(owner="9001", document_id="doc-1")
        assert result["ok"] is False

    @pytest.mark.asyncio
    async def test_missing_base_url_returns_error(self, monkeypatch, temp_db):
        from src.booking.database import get_db

        with get_db() as conn:
            conn.execute(
                "INSERT INTO tool_execution_log"
                " (owner, document_id, method, endpoint_path, request_json,"
                "  pre_state_json, response_status, response_json)"
                " VALUES (?,?,?,?,?,?,?,?)",
                ("9001", "doc-2", "DELETE", "/orders/1", "{}", '{"id":1}', 200, "null"),
            )
        monkeypatch.setattr(dat, "build_execution_context", lambda document_id, owner: None)
        result = await dat.undo_last_execution(owner="9001", document_id="doc-2")
        assert result["ok"] is False

    @pytest.mark.asyncio
    async def test_put_not_approved_returns_error(self, monkeypatch, temp_db):
        from src.booking.database import get_db

        with get_db() as conn:
            conn.execute(
                "INSERT INTO tool_execution_log"
                " (owner, document_id, method, endpoint_path, request_json,"
                "  pre_state_json, response_status, response_json)"
                " VALUES (?,?,?,?,?,?,?,?)",
                ("9001", "doc-3", "DELETE", "/orders/1", "{}", '{"id":1}', 200, "null"),
            )
        monkeypatch.setattr(
            dat, "build_execution_context",
            lambda document_id, owner: {
                "base_url": "https://api.example.com", "headers": {}, "approved_methods": ["GET", "DELETE"],
            },
        )
        result = await dat.undo_last_execution(owner="9001", document_id="doc-3")
        assert result["ok"] is False
        assert "PUT" in result["error"]


class TestBuildExecutionContext:
    def test_returns_none_when_document_missing(self, monkeypatch, temp_db):
        monkeypatch.setattr("src.common.knowledge_documents_db.get_document", lambda document_id, owner: None)
        assert dat.build_execution_context("doc-x", owner="9001") is None

    def test_returns_none_when_base_url_empty(self, monkeypatch, temp_db):
        monkeypatch.setattr(
            "src.common.knowledge_documents_db.get_document",
            lambda document_id, owner: {"base_url": "", "auth_header_name": "", "auth_header_value": "", "approved_methods": ["GET"]},
        )
        assert dat.build_execution_context("doc-x", owner="9001") is None

    def test_builds_headers_when_auth_present(self, monkeypatch, temp_db):
        monkeypatch.setattr(
            "src.common.knowledge_documents_db.get_document",
            lambda document_id, owner: {
                "base_url": "https://api.example.com", "auth_header_name": "Authorization",
                "auth_header_value": "Bearer xyz", "approved_methods": ["GET", "POST"],
            },
        )
        ctx = dat.build_execution_context("doc-x", owner="9001")
        assert ctx["base_url"] == "https://api.example.com"
        assert ctx["headers"] == {"Authorization": "Bearer xyz"}
        assert ctx["approved_methods"] == ["GET", "POST"]

