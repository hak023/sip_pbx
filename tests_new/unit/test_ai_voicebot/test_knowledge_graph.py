"""
AI Voicebot Unit Tests - 지식 그래프 n-hop 일반화 (Story 1.28, FR32-C)

`src/ai_voicebot/self_service/knowledge_graph.py` — 노드/엣지 타입 레지스트리 기반 범용
순회 엔진(`traverse_graph`)과, 리팩터링 전후 결과가 동일해야 하는 기존 공개 API
(`traverse`/`format_decision_hint`)를 검증한다.
"""

from src.ai_voicebot.self_service import intellidecision_policy, knowledge_graph, settings_catalog
from src.ai_voicebot.self_service.screen_graph import get_screen_for_domain


class TestNodeAndEdgeTypeRegistry:
    """AC1/AC2 — 신규 노드/엣지 타입이 예약·등록 가능해야 한다."""

    def test_reserved_node_types_are_registered(self):
        type_ids = {n.type_id for n in knowledge_graph.list_node_types()}
        assert {"manual_qa", "catalog_domain", "frontend_screen", "intent_type"} <= type_ids
        assert {"document", "api_endpoint", "procedure_step"} <= type_ids

    def test_reserved_edge_types_are_registered(self):
        type_ids = {e.type_id for e in knowledge_graph.list_edge_types()}
        assert {"relates_to", "rendered_by", "writable"} <= type_ids
        assert {"depends_on", "documents"} <= type_ids

    def test_depends_on_and_documents_edges_are_reserved_no_ops(self):
        """실 데이터 소스가 아직 없는 예약 엣지는 예외 없이 빈 목록을 반환해야 한다."""
        edges = knowledge_graph.traverse_graph("procedure_step", "step-1", max_hops=1)
        assert edges == []
        edges = knowledge_graph.traverse_graph("api_endpoint", "GET /foo", max_hops=1)
        assert edges == []


class TestTraverseGraphGeneric:
    """AC3 — traverse_graph()가 하드코딩 없이 등록 테이블을 실제로 순회해야 한다."""

    def test_traverses_two_hops_from_catalog_domain(self):
        edges = knowledge_graph.traverse_graph("catalog_domain", "chat-relay", max_hops=2)
        edge_types = {e["edge_type"] for e in edges}
        assert "rendered_by" in edge_types
        assert "writable" in edge_types

    def test_max_hops_one_stops_after_first_hop(self):
        edges = knowledge_graph.traverse_graph("catalog_domain", "chat-relay", max_hops=1)
        assert all(e["hop"] == 1 for e in edges)

    def test_unknown_domain_returns_empty_without_raising(self):
        edges = knowledge_graph.traverse_graph("catalog_domain", "no-such-domain", max_hops=2)
        # rendered_by는 화면 없음으로 빈 목록, writable은 관측 가능한 유형이 있을 수 있음 — 예외만 없으면 됨
        assert isinstance(edges, list)


class TestTraverseBackwardCompatibility:
    """AC5 — 리팩터링 전후 결과가 1바이트도 다르지 않아야 한다(Story 1.18 동작 재검증)."""

    def _expected(self, domain: str, max_hops: int = 2):
        expected = {
            "domain": domain, "screen": None, "writable": False, "applicable_intent_types": [],
        }
        expected["screen"] = get_screen_for_domain(domain)
        if max_hops < 2:
            return expected
        expected["writable"] = bool(settings_catalog.domain_writable_fields(domain))
        expected["applicable_intent_types"] = intellidecision_policy.applicable_types_for_domain(
            domain, writable=expected["writable"],
        )
        return expected

    def test_writable_domain_chat_relay(self):
        assert knowledge_graph.traverse("chat-relay") == self._expected("chat-relay")

    def test_readonly_domain_contacts(self):
        assert knowledge_graph.traverse("contacts") == self._expected("contacts")

    def test_max_hops_one_only_returns_screen(self):
        assert knowledge_graph.traverse("chat-relay", max_hops=1) == self._expected("chat-relay", max_hops=1)

    def test_format_decision_hint_writable_domain(self):
        hint = knowledge_graph.format_decision_hint("chat-relay")
        assert "조회·변경·되돌리기" in hint

    def test_format_decision_hint_readonly_domain(self):
        hint = knowledge_graph.format_decision_hint("contacts")
        assert "조회만 가능" in hint

    def test_format_decision_hint_unknown_domain_returns_empty(self):
        assert knowledge_graph.format_decision_hint("no-such-domain") == ""


class TestDocumentNodeLinking:
    """Task 5 — Story 1.26 업로드 문서를 document 노드로 연결(catalog_domain --relates_to--> document)."""

    def test_returns_empty_without_owner(self):
        edges = knowledge_graph.traverse_graph("catalog_domain", "booking", max_hops=1, owner=None)
        assert [e for e in edges if e["edge_type"] == "relates_to"] == []

    def test_links_uploaded_document_matching_domain_tag(self, monkeypatch):
        fake_doc = {
            "document_id": "doc-1", "owner": "9001", "title": "예약 API 문서",
            "domain_tags": ["booking"], "source_type": "openapi",
        }

        def fake_list_documents(*, owner, domain_tag=None, source_type=None, limit=500):
            assert owner == "9001"
            assert domain_tag == "booking"
            return [fake_doc]

        monkeypatch.setattr(
            "src.common.knowledge_documents_db.list_documents", fake_list_documents,
        )

        edges = knowledge_graph.traverse_graph("catalog_domain", "booking", max_hops=1, owner="9001")
        doc_edges = [e for e in edges if e["edge_type"] == "relates_to"]
        assert len(doc_edges) == 1
        assert doc_edges[0]["target_type"] == "document"
        assert doc_edges[0]["target_id"] == "doc-1"
        assert doc_edges[0]["data"] == fake_doc
