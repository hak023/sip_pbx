"""
AI Voicebot Unit Tests - IntelliDecision 설명 매뉴얼 (Story 1.40, FR34-D)

`src/ai_voicebot/self_service/intellidecision_manual.py` — 실시간 LLM 호출 없이 임베딩
검색+지식 그래프 조회만으로 유형별 정적 사례를 산출하는지 검증한다.
"""

from dataclasses import dataclass, field
from typing import Any, Dict, List

import pytest

from src.ai_voicebot.self_service import intellidecision_manual as manual


@dataclass
class _FakeSpec:
    code: str
    rag_enabled: bool = True
    trigger_examples: List[str] = field(default_factory=list)


@dataclass
class _FakeDoc:
    id: str
    score: float
    metadata: Dict[str, Any]
    text: str = "Q: 예시 질문\nA: 예시 답변입니다."


@dataclass
class _FakeSearchResult:
    documents: List[_FakeDoc]


class TestBuildCaseExampleForType:
    @pytest.mark.asyncio
    async def test_rag_disabled_type_returns_no_case_without_search(self, monkeypatch):
        called = {"search": False}

        class _FakeEngine:
            async def search(self, *a, **kw):
                called["search"] = True
                return _FakeSearchResult(documents=[])

        monkeypatch.setattr(manual, "get_self_service_rag_engine", lambda: _FakeEngine())

        spec = _FakeSpec(code="D", rag_enabled=False, trigger_examples=["아니 그거 말고"])
        result = await manual.build_case_example_for_type(spec, owner="9001")

        assert result.has_case is False
        assert result.code == "D"
        assert called["search"] is False

    @pytest.mark.asyncio
    async def test_no_trigger_examples_returns_no_case(self, monkeypatch):
        spec = _FakeSpec(code="A", rag_enabled=True, trigger_examples=[])
        result = await manual.build_case_example_for_type(spec, owner="9001")
        assert result.has_case is False
        assert result.trigger_example is None

    @pytest.mark.asyncio
    async def test_rag_engine_unavailable_returns_no_case(self, monkeypatch):
        monkeypatch.setattr(manual, "get_self_service_rag_engine", lambda: None)
        spec = _FakeSpec(code="A", rag_enabled=True, trigger_examples=["뭘 할 수 있어?"])
        result = await manual.build_case_example_for_type(spec, owner="9001")
        assert result.has_case is False
        assert result.trigger_example == "뭘 할 수 있어?"

    @pytest.mark.asyncio
    async def test_no_matched_documents_returns_no_case(self, monkeypatch):
        class _FakeEngine:
            async def search(self, *a, **kw):
                return _FakeSearchResult(documents=[])

        monkeypatch.setattr(manual, "get_self_service_rag_engine", lambda: _FakeEngine())
        spec = _FakeSpec(code="A", rag_enabled=True, trigger_examples=["뭘 할 수 있어?"])
        result = await manual.build_case_example_for_type(spec, owner="9001")
        assert result.has_case is False

    @pytest.mark.asyncio
    async def test_matched_documents_and_hop_path_populate_case(self, monkeypatch):
        class _FakeEngine:
            async def search(self, *a, **kw):
                return _FakeSearchResult(
                    documents=[
                        _FakeDoc(id="doc-1", score=0.9, metadata={"related_domain": "booking"}),
                    ]
                )

        monkeypatch.setattr(manual, "get_self_service_rag_engine", lambda: _FakeEngine())
        monkeypatch.setattr(
            "src.ai_voicebot.self_service.knowledge_graph.traverse_graph",
            lambda source_type, source_id, max_hops, owner: [
                {
                    "hop": 1, "edge_type": "has_screen", "source_type": "catalog_domain",
                    "source_id": "booking", "target_type": "screen", "target_id": "/booking",
                }
            ],
        )

        spec = _FakeSpec(code="A", rag_enabled=True, trigger_examples=["뭘 할 수 있어?"])
        result = await manual.build_case_example_for_type(spec, owner="9001")

        assert result.has_case is True
        assert result.trigger_example == "뭘 할 수 있어?"
        assert len(result.matched_documents) == 1
        assert result.matched_documents[0].doc_id == "doc-1"
        assert result.matched_documents[0].related_domain == "booking"
        assert "예시 답변" in result.matched_documents[0].excerpt
        assert len(result.hop_path) == 1
        assert result.hop_path[0].target_id == "/booking"

    @pytest.mark.asyncio
    async def test_search_exception_returns_no_case(self, monkeypatch):
        class _FakeEngine:
            async def search(self, *a, **kw):
                raise RuntimeError("boom")

        monkeypatch.setattr(manual, "get_self_service_rag_engine", lambda: _FakeEngine())
        spec = _FakeSpec(code="A", rag_enabled=True, trigger_examples=["뭘 할 수 있어?"])
        result = await manual.build_case_example_for_type(spec, owner="9001")
        assert result.has_case is False


class TestCollectHopPath:
    def test_deduplicates_and_caps_edges(self, monkeypatch):
        monkeypatch.setattr(
            "src.ai_voicebot.self_service.knowledge_graph.traverse_graph",
            lambda source_type, source_id, max_hops, owner: [
                {
                    "hop": 1, "edge_type": "has_screen", "source_type": "catalog_domain",
                    "source_id": source_id, "target_type": "screen", "target_id": f"/{source_id}",
                }
            ],
        )
        edges = manual._collect_hop_path(["booking", "booking", "persona"], owner="9001")
        assert len(edges) == 2  # booking 중복 제거 + persona

    def test_domain_failure_does_not_block_others(self, monkeypatch):
        def fake_traverse(source_type, source_id, max_hops, owner):
            if source_id == "boom":
                raise RuntimeError("boom")
            return [
                {
                    "hop": 1, "edge_type": "has_screen", "source_type": "catalog_domain",
                    "source_id": source_id, "target_type": "screen", "target_id": f"/{source_id}",
                }
            ]

        monkeypatch.setattr("src.ai_voicebot.self_service.knowledge_graph.traverse_graph", fake_traverse)
        edges = manual._collect_hop_path(["boom", "booking"], owner="9001")
        assert len(edges) == 1
        assert edges[0].source_id == "booking"
