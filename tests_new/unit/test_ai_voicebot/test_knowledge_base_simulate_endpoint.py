"""
AI Voicebot Unit Tests - 응답 시뮬레이터 엔드포인트 (Story 1.27, FR32-B)

`src/api/routers/knowledge_base_simulate.py` — 실제 LLM/RAG 호출 없이 배선(격리 세션,
매칭 문서 조립, IntelliDecision 동기 판정 재사용)을 검증한다.
"""

import pytest
from fastapi import HTTPException

from src.api.routers import knowledge_base_simulate as kbs


class TestSimulateRequestValidation:
    @pytest.mark.asyncio
    async def test_rejects_empty_owner(self):
        body = kbs.SimulateRequest(owner="  ", query="안녕")
        with pytest.raises(HTTPException) as exc_info:
            await kbs.simulate(body)
        assert exc_info.value.status_code == 400

    @pytest.mark.asyncio
    async def test_rejects_empty_query(self):
        body = kbs.SimulateRequest(owner="1003", query="  ")
        with pytest.raises(HTTPException) as exc_info:
            await kbs.simulate(body)
        assert exc_info.value.status_code == 400

    @pytest.mark.asyncio
    async def test_raises_503_when_ai_not_ready(self, monkeypatch):
        async def fake_get_isolated_agent(owner):
            return None

        monkeypatch.setattr(kbs, "_get_isolated_agent", fake_get_isolated_agent)
        body = kbs.SimulateRequest(owner="1003", query="영업 시간 알려줘")
        with pytest.raises(HTTPException) as exc_info:
            await kbs.simulate(body)
        assert exc_info.value.status_code == 503


class TestExtractMatchedDocuments:
    def test_returns_documents_from_matching_event(self, monkeypatch):
        monkeypatch.setattr(
            "src.api.utils.call_data_record_reader.read_call_data_record_for_call",
            lambda call_id: [
                {"category": "timing", "event": "agent_graph_total"},
                {
                    "category": "self_service", "event": "self_service_rag_search",
                    "matched_doc_ids": ["d1", "d2"], "scores": [0.91, 0.4],
                    "related_domains": ["booking", ""],
                },
            ],
        )
        docs = kbs._extract_matched_documents("call-1")
        assert len(docs) == 2
        assert docs[0].doc_id == "d1" and docs[0].score == 0.91 and docs[0].related_domain == "booking"
        assert docs[1].doc_id == "d2" and docs[1].related_domain == ""

    def test_returns_empty_when_no_matching_event(self, monkeypatch):
        monkeypatch.setattr(
            "src.api.utils.call_data_record_reader.read_call_data_record_for_call",
            lambda call_id: [{"category": "timing", "event": "agent_graph_total"}],
        )
        assert kbs._extract_matched_documents("call-1") == []


class TestSimulateEndToEnd:
    """simulate()가 격리 세션으로 실행하고 3개 결과(응답/매칭 문서/유형·근거)를 조합하는지"""

    @pytest.mark.asyncio
    async def test_simulate_combines_all_three_results(self, monkeypatch):
        class _FakeAgent:
            async def process_utterance(self, text, call_id=None, caller_number=None):
                assert caller_number == "1003"  # self_service_agent 경로를 타려면 owner와 동일해야 함(AC2)
                return {"response": "네, 도와드릴게요.", "intent": "self_service", "confidence": 0.9}

        async def fake_get_isolated_agent(owner):
            assert owner == "1003"
            return _FakeAgent()

        async def fake_capture_and_log(*, user_query, ai_response, owner, call_id):
            return "A", "단순 조회형 발화로 판단"

        monkeypatch.setattr(kbs, "_get_isolated_agent", fake_get_isolated_agent)
        monkeypatch.setattr(
            "src.ai_voicebot.self_service.decision_rationale._capture_and_log",
            fake_capture_and_log,
        )
        monkeypatch.setattr(
            "src.api.utils.call_data_record_reader.read_call_data_record_for_call",
            lambda call_id: [
                {
                    "category": "self_service", "event": "self_service_rag_search",
                    "matched_doc_ids": ["doc-1"], "scores": [0.8], "related_domains": ["booking"],
                },
            ],
        )

        body = kbs.SimulateRequest(owner="1003", query="예약 취소하고 싶어요")
        result = await kbs.simulate(body)

        assert result.response == "네, 도와드릴게요."
        assert result.intellidecision_type == "A"
        assert result.reasoning_summary == "단순 조회형 발화로 판단"
        assert len(result.matched_documents) == 1
        assert result.matched_documents[0].doc_id == "doc-1"
        assert result.elapsed_sec >= 0
        assert len(result.hop_path) > 0


class TestCollectHopPath:
    def test_returns_edges_for_real_domain(self):
        docs = [kbs.MatchedDocument(doc_id="d1", score=0.9, related_domain="booking")]
        edges = kbs._collect_hop_path(docs, owner="1003")
        assert len(edges) > 0
        assert all(e.hop >= 1 for e in edges)

    def test_empty_related_domain_yields_no_edges(self):
        docs = [kbs.MatchedDocument(doc_id="d1", score=0.9, related_domain="")]
        assert kbs._collect_hop_path(docs, owner="1003") == []

    def test_deduplicates_across_documents_with_same_domain(self):
        docs = [
            kbs.MatchedDocument(doc_id="d1", score=0.9, related_domain="booking"),
            kbs.MatchedDocument(doc_id="d2", score=0.5, related_domain="booking"),
        ]
        edges = kbs._collect_hop_path(docs, owner="1003")
        keys = [(e.hop, e.edge_type, e.source_id, e.target_id) for e in edges]
        assert len(keys) == len(set(keys))

    def test_resolver_failure_does_not_raise(self, monkeypatch):
        def fake_traverse_graph(*args, **kwargs):
            raise RuntimeError("boom")

        monkeypatch.setattr(
            "src.ai_voicebot.self_service.knowledge_graph.traverse_graph", fake_traverse_graph
        )
        docs = [kbs.MatchedDocument(doc_id="d1", score=0.9, related_domain="booking")]
        assert kbs._collect_hop_path(docs, owner="1003") == []
