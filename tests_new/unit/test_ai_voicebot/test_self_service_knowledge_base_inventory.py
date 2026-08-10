"""Story 1.23(FR31-A) — 지식베이스 인벤토리 투명성 단위 테스트."""

from src.ai_voicebot.self_service.knowledge_base_inventory import summarize_inventory


def _item(owner: str, doc_type: str, domain: str = "", section: str = "", created_at: str = ""):
    return {
        "id": f"kb_{owner}_{domain}_{created_at}",
        "text": "Q: dummy\nA: dummy",
        "metadata": {
            "owner": owner,
            "doc_type": doc_type,
            "related_domain": domain,
            "section_title": section,
            "created_at": created_at,
        },
    }


def test_summarize_inventory_aggregates_owner_matching_manual_items():
    raw_items = [
        _item("9001", "self_service_manual", domain="persona", section="섹션1", created_at="2026-07-30T10:00:00"),
        _item("9001", "self_service_manual", domain="persona", section="섹션1", created_at="2026-07-29T09:00:00"),
        _item("9001", "self_service_manual", domain="chat-relay", section="섹션2", created_at="2026-07-28T08:00:00"),
    ]

    result = summarize_inventory(raw_items, owner="9001")

    assert result["owner"] == "9001"
    assert result["total_chunks"] == 3
    assert result["source_document_count"] == 2  # 섹션1/섹션2
    assert result["last_indexed_at"] == "2026-07-30T10:00:00"
    assert result["doc_type"] == "knowledge_document,self_service_manual"

    domain_counts = {d["domain"]: d["count"] for d in result["domain_distribution"]}
    assert domain_counts == {"persona": 2, "chat-relay": 1}


def test_summarize_inventory_empty_collection_returns_zero_without_error():
    result = summarize_inventory([], owner="9001")

    assert result["total_chunks"] == 0
    assert result["source_document_count"] == 0
    assert result["domain_distribution"] == []
    assert result["last_indexed_at"] == ""


def test_summarize_inventory_isolates_other_owner_data():
    raw_items = [
        _item("9001", "self_service_manual", domain="persona", created_at="2026-07-30T10:00:00"),
        _item("9003", "self_service_manual", domain="persona", created_at="2026-07-30T11:00:00"),
    ]

    result = summarize_inventory(raw_items, owner="9001")

    assert result["total_chunks"] == 1
    assert result["last_indexed_at"] == "2026-07-30T10:00:00"


def test_summarize_inventory_ignores_non_manual_doc_type():
    raw_items = [
        _item("9001", "self_service_manual", domain="persona", created_at="2026-07-30T10:00:00"),
        _item("9001", "knowledge", domain="unrelated", created_at="2026-07-30T12:00:00"),
    ]

    result = summarize_inventory(raw_items, owner="9001")

    assert result["total_chunks"] == 1
    assert result["last_indexed_at"] == "2026-07-30T10:00:00"


def test_summarize_inventory_includes_uploaded_knowledge_document_chunks():
    """(2026-08-07 버그수정) Story 1.26 업로드 문서(doc_type=knowledge_document)도 집계에
    포함되어야 한다 — 이전에는 self_service_manual만 세어 업로드 직후에도 총 청크 수가
    바뀌지 않는 것처럼 보이는 버그가 있었다."""
    raw_items = [
        _item("9001", "self_service_manual", domain="persona", created_at="2026-07-30T10:00:00"),
        _item("9001", "knowledge_document", domain="", created_at="2026-08-07T11:14:00"),
        _item("9001", "knowledge_document", domain="", created_at="2026-08-07T11:14:01"),
    ]

    result = summarize_inventory(raw_items, owner="9001")

    assert result["total_chunks"] == 3
    assert result["last_indexed_at"] == "2026-08-07T11:14:01"


def test_summarize_inventory_untagged_domain_falls_back_to_unclassified_bucket():
    raw_items = [
        _item("9001", "self_service_manual", domain="", created_at="2026-07-30T10:00:00"),
    ]

    result = summarize_inventory(raw_items, owner="9001")

    assert result["domain_distribution"] == [{"domain": "(미분류)", "count": 1}]
