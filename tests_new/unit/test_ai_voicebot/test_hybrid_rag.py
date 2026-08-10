"""Story 1.33(FR33-E) 유형 C 하이브리드 다중 도메인 RAG 단위테스트."""

from __future__ import annotations

import pytest

from src.ai_voicebot.self_service.hybrid_rag import (
    looks_like_broad_help_query,
    search_hybrid_multi_domain,
)


class TestLooksLikeBroadHelpQuery:
    def test_matches_known_trigger_phrases(self):
        assert looks_like_broad_help_query("뭘 할 수 있어?") is True
        assert looks_like_broad_help_query("사용법 알려줘") is True
        assert looks_like_broad_help_query("어떤 도움을 줄 수 있어?") is True

    def test_does_not_match_specific_domain_question(self):
        assert looks_like_broad_help_query("착신 규칙 바꾸고 싶어요") is False

    def test_empty_query_returns_false(self):
        assert looks_like_broad_help_query("") is False
        assert looks_like_broad_help_query("   ") is False


class _FakeEmbedder:
    def embed_text(self, text: str):
        return [0.1, 0.2, 0.3]


class _FakeVectorDB:
    def __init__(self, per_domain_ids: dict):
        self._per_domain_ids = per_domain_ids
        self.calls = []

    def query(self, query_embeddings, n_results, where):
        domain = where["$and"][2]["related_domain"]
        self.calls.append(domain)
        ids = self._per_domain_ids.get(domain, [])
        return {
            "ids": [ids],
            "documents": [[f"Q: {i}\nA: ans-{i}" for i in ids]],
            "metadatas": [[{"related_domain": domain} for _ in ids]],
            "distances": [[0.1] * len(ids)],
        }


class TestSearchHybridMultiDomain:
    @pytest.mark.asyncio
    async def test_queries_all_catalog_domains_in_parallel(self, monkeypatch):
        from src.ai_voicebot.self_service import settings_catalog

        monkeypatch.setattr(settings_catalog, "list_domains", lambda *_: ["booking", "chat-relay"])
        vector_db = _FakeVectorDB({"booking": ["b1"], "chat-relay": ["c1", "c2"]})
        docs = await search_hybrid_multi_domain(
            "뭘 할 수 있어?", owner="9001", vector_db=vector_db, embedder=_FakeEmbedder()
        )
        assert sorted(vector_db.calls) == ["booking", "chat-relay"]
        assert {d.id for d in docs} == {"b1", "c1", "c2"}

    @pytest.mark.asyncio
    async def test_deduplicates_by_doc_id_across_domains(self, monkeypatch):
        from src.ai_voicebot.self_service import settings_catalog

        monkeypatch.setattr(settings_catalog, "list_domains", lambda *_: ["booking", "chat-relay"])
        vector_db = _FakeVectorDB({"booking": ["shared"], "chat-relay": ["shared"]})
        docs = await search_hybrid_multi_domain(
            "뭘 할 수 있어?", owner="9001", vector_db=vector_db, embedder=_FakeEmbedder()
        )
        assert len(docs) == 1

    @pytest.mark.asyncio
    async def test_single_domain_failure_does_not_break_others(self, monkeypatch):
        from src.ai_voicebot.self_service import settings_catalog

        monkeypatch.setattr(settings_catalog, "list_domains", lambda *_: ["booking", "broken"])

        class _PartlyBrokenVectorDB(_FakeVectorDB):
            def query(self, query_embeddings, n_results, where):
                domain = where["$and"][2]["related_domain"]
                if domain == "broken":
                    raise RuntimeError("boom")
                return super().query(query_embeddings, n_results, where)

        vector_db = _PartlyBrokenVectorDB({"booking": ["b1"]})
        docs = await search_hybrid_multi_domain(
            "뭘 할 수 있어?", owner="9001", vector_db=vector_db, embedder=_FakeEmbedder()
        )
        assert {d.id for d in docs} == {"b1"}

    @pytest.mark.asyncio
    async def test_no_vector_db_returns_empty(self):
        docs = await search_hybrid_multi_domain(
            "뭘 할 수 있어?", owner="9001", vector_db=None, embedder=_FakeEmbedder()
        )
        assert docs == []

    @pytest.mark.asyncio
    async def test_no_domains_returns_empty(self, monkeypatch):
        from src.ai_voicebot.self_service import settings_catalog

        monkeypatch.setattr(settings_catalog, "list_domains", lambda *_: [])
        vector_db = _FakeVectorDB({})
        docs = await search_hybrid_multi_domain(
            "뭘 할 수 있어?", owner="9001", vector_db=vector_db, embedder=_FakeEmbedder()
        )
        assert docs == []
