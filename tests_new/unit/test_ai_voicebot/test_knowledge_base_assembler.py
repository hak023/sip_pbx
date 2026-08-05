"""Story 1.31(FR33-B) 업로드 데이터 기반 지식베이스 자동 구성 집계 단위테스트."""

from __future__ import annotations

from src.ai_voicebot.self_service.document_adapters import OpenApiSpecAdapter
from src.ai_voicebot.self_service.knowledge_base_assembler import (
    classify_setting_item,
    summarize_auto_assembled_knowledge_base,
)


def _kb_item(owner: str, question: str, answer: str) -> dict:
    return {
        "id": f"kb_{question}",
        "text": f"Q: {question}\nA: {answer}",
        "metadata": {"owner": owner, "doc_type": "knowledge_document", "category": "question"},
    }


class TestClassifySettingItem:
    def test_write_method_classified_as_writable_setting_item(self):
        item = classify_setting_item("POST /orders 엔드포인트는 무엇을 하나요?", "주문을 생성합니다")
        assert item is not None
        assert item["method"] == "POST"
        assert item["label"] == "/orders"
        assert item["writable"] is True

    def test_read_method_classified_as_readonly_setting_item(self):
        item = classify_setting_item("GET /orders 엔드포인트는 무엇을 하나요?", "주문 목록을 조회합니다")
        assert item is not None
        assert item["writable"] is False

    def test_non_endpoint_question_returns_none(self):
        assert classify_setting_item("영업 시간이 어떻게 되나요?", "평일 9시~18시입니다") is None

    def test_empty_question_returns_none(self):
        assert classify_setting_item("", "") is None


class TestSummarizeAutoAssembledKnowledgeBase:
    def test_mixed_manual_qa_and_setting_items_classified_correctly(self):
        raw_items = [
            _kb_item("9001", "영업 시간이 어떻게 되나요?", "평일 9시~18시입니다"),
            _kb_item("9001", "POST /orders 엔드포인트는 무엇을 하나요?", "주문을 생성합니다"),
            _kb_item("9001", "GET /orders 엔드포인트는 무엇을 하나요?", "주문 목록을 조회합니다"),
        ]
        result = summarize_auto_assembled_knowledge_base(raw_items, owner="9001")
        assert result["manual_qa_count"] == 1
        assert result["setting_item_count"] == 2
        assert result["writable_setting_item_count"] == 1

    def test_owner_isolation(self):
        raw_items = [
            _kb_item("9001", "POST /orders 엔드포인트는 무엇을 하나요?", "주문을 생성합니다"),
            _kb_item("9003", "POST /invoices 엔드포인트는 무엇을 하나요?", "청구서를 생성합니다"),
        ]
        result = summarize_auto_assembled_knowledge_base(raw_items, owner="9001")
        assert result["setting_item_count"] == 1
        assert result["setting_items"][0]["label"] == "/orders"

    def test_non_knowledge_document_doc_type_ignored(self):
        raw_items = [
            {
                "id": "manual_1",
                "text": "Q: 영업 시간?\nA: 9~18시",
                "metadata": {"owner": "9001", "doc_type": "self_service_manual"},
            }
        ]
        result = summarize_auto_assembled_knowledge_base(raw_items, owner="9001")
        assert result["manual_qa_count"] == 0
        assert result["setting_item_count"] == 0

    def test_empty_raw_items_returns_zero_counts(self):
        result = summarize_auto_assembled_knowledge_base([], owner="9001")
        assert result["manual_qa_count"] == 0
        assert result["setting_item_count"] == 0
        assert result["screen_node_count"] == 0

    def test_document_records_counted_as_screen_node_count(self):
        result = summarize_auto_assembled_knowledge_base(
            [], owner="9001", document_records=[{"document_id": "a"}, {"document_id": "b"}]
        )
        assert result["screen_node_count"] == 2


class TestDomainAgnosticEndToEnd:
    """AC2(도메인 비종속) 실증 — SIP PBX와 전혀 무관한 이커머스 주문 API 샘플로 검증한다."""

    _ECOMMERCE_OPENAPI_SPEC = """
    {
      "paths": {
        "/orders": {
          "get": {"summary": "주문 목록 조회", "description": "고객의 주문 이력을 반환합니다."},
          "post": {"summary": "주문 생성", "description": "신규 주문을 생성합니다."}
        },
        "/orders/{id}/cancel": {
          "delete": {"summary": "주문 취소", "description": "지정된 주문을 취소합니다."}
        }
      }
    }
    """

    def test_ecommerce_spec_produces_qa_and_setting_items_without_sip_pbx_coupling(self):
        adapter = OpenApiSpecAdapter(self._ECOMMERCE_OPENAPI_SPEC, title="이커머스 주문 API")
        pairs = adapter.load_pairs_with_meta()
        assert len(pairs) == 3

        raw_items = [_kb_item("tenant-a", p["question"], p["answer"]) for p in pairs]
        result = summarize_auto_assembled_knowledge_base(raw_items, owner="tenant-a")

        assert result["setting_item_count"] == 3
        assert result["writable_setting_item_count"] == 2  # POST + DELETE
        labels = {s["label"] for s in result["setting_items"]}
        assert labels == {"/orders", "/orders/{id}/cancel"}
