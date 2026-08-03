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
    assert result["doc_type"] == "self_service_manual"

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


def test_summarize_inventory_untagged_domain_falls_back_to_unclassified_bucket():
    raw_items = [
        _item("9001", "self_service_manual", domain="", created_at="2026-07-30T10:00:00"),
    ]

    result = summarize_inventory(raw_items, owner="9001")

    assert result["domain_distribution"] == [{"domain": "(미분류)", "count": 1}]
