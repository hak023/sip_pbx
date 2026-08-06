"""
AI Voicebot Unit Tests - 도메인 비종속 지식베이스 문서 lifecycle DB (Story 1.26, FR32-A)

docs/stories/1.26.knowledge-base-document-crud-and-upload.story.md 참고
"""

import sqlite3
from contextlib import contextmanager

import pytest

from src.common import knowledge_documents_db as docs_db


@pytest.fixture
def temp_db(tmp_path, monkeypatch):
    db_path = tmp_path / "test_knowledge_documents.db"
    conn = sqlite3.connect(str(db_path))
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS knowledge_documents (
            id                   INTEGER PRIMARY KEY AUTOINCREMENT,
            document_id          TEXT    NOT NULL UNIQUE,
            owner                TEXT    NOT NULL,
            title                TEXT    NOT NULL DEFAULT '',
            domain_tags_json     TEXT    NOT NULL DEFAULT '[]',
            source_type          TEXT    NOT NULL,
            chunk_doc_ids_json   TEXT    NOT NULL DEFAULT '[]',
            approved_methods_json TEXT   NOT NULL DEFAULT '["GET"]',
            base_url             TEXT    NOT NULL DEFAULT '',
            auth_header_name     TEXT    NOT NULL DEFAULT '',
            auth_header_value    TEXT    NOT NULL DEFAULT '',
            version_no           INTEGER NOT NULL DEFAULT 1,
            is_active            INTEGER NOT NULL DEFAULT 1,
            uploaded_by          TEXT    NOT NULL DEFAULT '',
            uploaded_at          TEXT    NOT NULL DEFAULT (datetime('now','localtime')),
            updated_at           TEXT    NOT NULL DEFAULT (datetime('now','localtime'))
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS knowledge_document_endpoints (
            id                INTEGER PRIMARY KEY AUTOINCREMENT,
            document_id       TEXT    NOT NULL,
            method            TEXT    NOT NULL,
            endpoint_path     TEXT    NOT NULL,
            parameters_json   TEXT    NOT NULL DEFAULT '[]',
            request_body_json TEXT,
            created_at        TEXT    NOT NULL DEFAULT (datetime('now','localtime'))
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


class TestCreateAndGetDocument:
    def test_create_document_returns_record(self, temp_db):
        record = docs_db.create_document(
            owner="9001",
            title="예약 API 문서",
            domain_tags=["api-docs"],
            source_type="openapi",
            chunk_doc_ids=["kb_1", "kb_2"],
            uploaded_by="tester",
        )
        assert record is not None
        assert record["owner"] == "9001"
        assert record["title"] == "예약 API 문서"
        assert record["domain_tags"] == ["api-docs"]
        assert record["chunk_doc_ids"] == ["kb_1", "kb_2"]
        assert record["is_active"] is True
        assert record["version_no"] == 1

    def test_get_document_enforces_owner_isolation(self, temp_db):
        record = docs_db.create_document(
            owner="9001", title="t", domain_tags=[], source_type="markdown", chunk_doc_ids=["k1"],
        )
        assert docs_db.get_document(record["document_id"], owner="9001") is not None
        assert docs_db.get_document(record["document_id"], owner="9002") is None

    def test_get_document_not_found_returns_none(self, temp_db):
        assert docs_db.get_document("nonexistent", owner="9001") is None


class TestListDocuments:
    def test_list_documents_filters_by_owner(self, temp_db):
        docs_db.create_document(owner="9001", title="a", domain_tags=[], source_type="markdown", chunk_doc_ids=["k1"])
        docs_db.create_document(owner="9002", title="b", domain_tags=[], source_type="markdown", chunk_doc_ids=["k2"])
        items = docs_db.list_documents(owner="9001")
        assert len(items) == 1
        assert items[0]["title"] == "a"

    def test_list_documents_filters_by_domain_tag(self, temp_db):
        docs_db.create_document(owner="9001", title="a", domain_tags=["billing"], source_type="markdown", chunk_doc_ids=["k1"])
        docs_db.create_document(owner="9001", title="b", domain_tags=["support"], source_type="markdown", chunk_doc_ids=["k2"])
        items = docs_db.list_documents(owner="9001", domain_tag="billing")
        assert len(items) == 1
        assert items[0]["title"] == "a"

    def test_list_documents_filters_by_source_type(self, temp_db):
        docs_db.create_document(owner="9001", title="a", domain_tags=[], source_type="pdf", chunk_doc_ids=["k1"])
        docs_db.create_document(owner="9001", title="b", domain_tags=[], source_type="markdown", chunk_doc_ids=["k2"])
        items = docs_db.list_documents(owner="9001", source_type="pdf")
        assert len(items) == 1
        assert items[0]["source_type"] == "pdf"


class TestUpdateDocument:
    def test_update_title_and_tags(self, temp_db):
        record = docs_db.create_document(owner="9001", title="old", domain_tags=["a"], source_type="markdown", chunk_doc_ids=["k1"])
        updated = docs_db.update_document(
            record["document_id"], owner="9001", title="new", domain_tags=["b", "c"],
        )
        assert updated is not None
        assert updated["title"] == "new"
        assert updated["domain_tags"] == ["b", "c"]
        assert updated["version_no"] == 2

    def test_update_chunk_doc_ids(self, temp_db):
        record = docs_db.create_document(owner="9001", title="t", domain_tags=[], source_type="markdown", chunk_doc_ids=["k1"])
        updated = docs_db.update_document(record["document_id"], owner="9001", chunk_doc_ids=["k2", "k3"])
        assert updated["chunk_doc_ids"] == ["k2", "k3"]

    def test_update_nonexistent_document_returns_none(self, temp_db):
        assert docs_db.update_document("nonexistent", owner="9001", title="x") is None


class TestDeactivateDocument:
    def test_deactivate_removes_from_list(self, temp_db):
        record = docs_db.create_document(owner="9001", title="t", domain_tags=[], source_type="markdown", chunk_doc_ids=["k1"])
        ok = docs_db.deactivate_document(record["document_id"], owner="9001")
        assert ok is True
        assert docs_db.get_document(record["document_id"], owner="9001") is None
        assert docs_db.list_documents(owner="9001") == []

    def test_deactivate_nonexistent_returns_false(self, temp_db):
        assert docs_db.deactivate_document("nonexistent", owner="9001") is False


class TestBaseUrlAndAuthPersistence:
    """Story 1.35 재개(FR34-A): base_url/인증 정보 저장 검증."""

    def test_create_with_base_url_persists(self, temp_db):
        record = docs_db.create_document(
            owner="9001", title="x", domain_tags=[], source_type="openapi", chunk_doc_ids=[],
            base_url="https://api.example.com", auth_header_name="Authorization", auth_header_value="Bearer tok",
        )
        assert record is not None
        assert record["base_url"] == "https://api.example.com"
        assert record["auth_header_value"] == "Bearer tok"

    def test_create_without_base_url_defaults_empty(self, temp_db):
        record = docs_db.create_document(owner="9001", title="x", domain_tags=[], source_type="markdown", chunk_doc_ids=[])
        assert record["base_url"] == ""
        assert record["auth_header_value"] == ""


class TestEndpointMetaPersistence:
    """Story 1.35 재개(FR34-A): 엔드포인트 실행 메타 영속화 검증."""

    def test_save_and_list_endpoints(self, temp_db):
        doc = docs_db.create_document(owner="9001", title="x", domain_tags=[], source_type="openapi", chunk_doc_ids=[])
        doc_id = doc["document_id"]
        endpoints = [
            {"_method": "GET", "_endpoint_path": "/orders", "_parameters": [{"name": "limit"}], "_request_body": None},
            {"_method": "POST", "_endpoint_path": "/orders", "_parameters": [], "_request_body": {"type": "object"}},
        ]
        ok = docs_db.save_document_endpoints(doc_id, endpoints)
        assert ok is True
        listed = docs_db.list_document_endpoints(doc_id)
        assert len(listed) == 2
        assert listed[0]["method"] == "GET"
        assert listed[1]["method"] == "POST"
        assert listed[0]["parameters"] == [{"name": "limit"}]
        assert listed[1]["request_body"] == {"type": "object"}

    def test_get_specific_endpoint(self, temp_db):
        doc = docs_db.create_document(owner="9001", title="x", domain_tags=[], source_type="openapi", chunk_doc_ids=[])
        docs_db.save_document_endpoints(doc["document_id"], [
            {"_method": "DELETE", "_endpoint_path": "/orders/{id}", "_parameters": [], "_request_body": None},
        ])
        ep = docs_db.get_document_endpoint(doc["document_id"], method="DELETE", endpoint_path="/orders/{id}")
        assert ep is not None
        assert ep["method"] == "DELETE"

    def test_empty_endpoints_saves_nothing(self, temp_db):
        doc = docs_db.create_document(owner="9001", title="x", domain_tags=[], source_type="openapi", chunk_doc_ids=[])
        ok = docs_db.save_document_endpoints(doc["document_id"], [])
        assert ok is False  # empty list → False 반환, 저장 없음


class TestOpenApiSpecAdapterExtractBaseUrl:
    """Story 1.35 재개: servers[0].url 자동 추출 검증."""

    def test_extracts_from_servers_json(self):
        from src.ai_voicebot.self_service.document_adapters import OpenApiSpecAdapter
        import json

        spec = {"openapi": "3.0.0", "info": {"title": "x", "version": "1"},
                "servers": [{"url": "https://api.example.com/v1"}], "paths": {}}
        adapter = OpenApiSpecAdapter(json.dumps(spec))
        assert adapter.extract_base_url() == "https://api.example.com/v1"

    def test_returns_empty_when_no_servers(self):
        from src.ai_voicebot.self_service.document_adapters import OpenApiSpecAdapter
        import json

        spec = {"openapi": "3.0.0", "paths": {}}
        adapter = OpenApiSpecAdapter(json.dumps(spec))
        assert adapter.extract_base_url() == ""

