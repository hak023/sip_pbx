"""
AI Voicebot Unit Tests - 도메인 비종속 지식베이스 문서 CRUD 서비스 (Story 1.26, FR32-A)

docs/stories/1.26.knowledge-base-document-crud-and-upload.story.md 참고
ChromaDB(add_knowledge/delete_knowledge)와 SQLite(knowledge_documents_db)는 모두 monkeypatch로
대체해, 순수 오케스트레이션 로직(어댑터 선택 → 색인 → 메타데이터 저장 → 정합성 롤백)만 검증한다.
"""

import json

import pytest

from src.ai_voicebot.self_service import knowledge_documents as kd


@pytest.fixture
def fake_vector_db_and_embedder():
    return object(), object()


class _FakeAddKnowledgeCounter:
    def __init__(self):
        self.calls = 0

    def __call__(self, **kwargs):
        self.calls += 1
        return {"ok": True, "doc_id": f"kb_{self.calls}"}


class TestRegisterDocumentMarkdown:
    def test_register_markdown_document_uses_manual_adapter(self, monkeypatch, fake_vector_db_and_embedder):
        """MarkdownManualAdapter는 실제 매뉴얼 파일(docs/product/self-service-manual-content.md)을
        읽으므로 content 인자와 무관하게 동작한다 — 이 경로가 실제로 호출되는지만 확인한다."""
        vector_db, embedder = fake_vector_db_and_embedder
        add_counter = _FakeAddKnowledgeCounter()
        monkeypatch.setattr(kd, "add_knowledge", add_counter)
        monkeypatch.setattr(
            kd.db, "create_document",
            lambda **kw: {**kw, "document_id": "doc-1", "uploaded_at": "now", "updated_at": "now"},
        )

        result = kd.register_document(
            owner="9001",
            title="테스트 매뉴얼",
            domain_tags=["persona"],
            source_type="markdown",
            content=None,
            vector_db=vector_db,
            embedder=embedder,
        )
        assert result["ok"] is True
        assert result["indexed_chunks"] == add_counter.calls

    def test_register_invalid_source_type_returns_error(self, fake_vector_db_and_embedder):
        vector_db, embedder = fake_vector_db_and_embedder
        result = kd.register_document(
            owner="9001", title="t", domain_tags=[], source_type="unknown",
            content="x", vector_db=vector_db, embedder=embedder,
        )
        assert result["ok"] is False
        assert "source_type" in result["error"]

    def test_register_missing_owner_returns_error(self, fake_vector_db_and_embedder):
        vector_db, embedder = fake_vector_db_and_embedder
        result = kd.register_document(
            owner="", title="t", domain_tags=[], source_type="openapi",
            content="{}", vector_db=vector_db, embedder=embedder,
        )
        assert result["ok"] is False


class TestRegisterDocumentOpenApi:
    def test_register_openapi_document_indexes_chunks_and_saves_record(
        self, monkeypatch, fake_vector_db_and_embedder
    ):
        vector_db, embedder = fake_vector_db_and_embedder
        add_counter = _FakeAddKnowledgeCounter()
        monkeypatch.setattr(kd, "add_knowledge", add_counter)

        saved = {}

        def fake_create_document(**kwargs):
            saved.update(kwargs)
            return {
                **kwargs,
                "document_id": "doc-abc",
                "uploaded_at": "now",
                "updated_at": "now",
            }

        monkeypatch.setattr(kd.db, "create_document", fake_create_document)

        spec = json.dumps({"paths": {"/x": {"get": {"summary": "x 조회"}}}})
        result = kd.register_document(
            owner="9001",
            title="API 문서",
            domain_tags=["api-docs"],
            source_type="openapi",
            content=spec,
            vector_db=vector_db,
            embedder=embedder,
        )
        assert result["ok"] is True
        assert result["document_id"] == "doc-abc"
        assert result["indexed_chunks"] == 1
        assert saved["chunk_doc_ids"] == ["kb_1"]

    def test_register_rolls_back_chunks_when_db_save_fails(
        self, monkeypatch, fake_vector_db_and_embedder
    ):
        vector_db, embedder = fake_vector_db_and_embedder
        add_counter = _FakeAddKnowledgeCounter()
        monkeypatch.setattr(kd, "add_knowledge", add_counter)
        monkeypatch.setattr(kd.db, "create_document", lambda **kw: None)

        deleted_ids = []
        monkeypatch.setattr(
            kd, "delete_knowledge",
            lambda vdb, doc_id: deleted_ids.append(doc_id) or {"ok": True},
        )

        spec = json.dumps({"paths": {"/x": {"get": {"summary": "x"}}}})
        result = kd.register_document(
            owner="9001", title="t", domain_tags=[], source_type="openapi",
            content=spec, vector_db=vector_db, embedder=embedder,
        )
        assert result["ok"] is False
        assert deleted_ids == ["kb_1"]

    def test_register_empty_spec_returns_error(self, monkeypatch, fake_vector_db_and_embedder):
        vector_db, embedder = fake_vector_db_and_embedder
        result = kd.register_document(
            owner="9001", title="t", domain_tags=[], source_type="openapi",
            content=json.dumps({"paths": {}}), vector_db=vector_db, embedder=embedder,
        )
        assert result["ok"] is False


class TestDeleteDocument:
    def test_delete_document_removes_all_chunks(self, monkeypatch, fake_vector_db_and_embedder):
        vector_db, _ = fake_vector_db_and_embedder
        monkeypatch.setattr(
            kd.db, "get_document",
            lambda doc_id, owner=None: {"chunk_doc_ids": ["k1", "k2"]},
        )
        monkeypatch.setattr(kd.db, "deactivate_document", lambda doc_id, owner: True)
        deleted = []
        monkeypatch.setattr(
            kd, "delete_knowledge",
            lambda vdb, doc_id: deleted.append(doc_id) or {"ok": True},
        )

        result = kd.delete_document(document_id="doc-1", owner="9001", vector_db=vector_db)
        assert result["ok"] is True
        assert result["deleted_chunks"] == 2
        assert deleted == ["k1", "k2"]

    def test_delete_nonexistent_document_returns_error(self, monkeypatch, fake_vector_db_and_embedder):
        vector_db, _ = fake_vector_db_and_embedder
        monkeypatch.setattr(kd.db, "get_document", lambda doc_id, owner=None: None)
        result = kd.delete_document(document_id="nonexistent", owner="9001", vector_db=vector_db)
        assert result["ok"] is False
