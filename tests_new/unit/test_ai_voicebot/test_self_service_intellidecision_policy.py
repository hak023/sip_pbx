"""Story 1.18(축 A) — IntelliDecision 정책 레지스트리 단위 테스트."""

from src.ai_voicebot.self_service import intellidecision_policy


def test_list_intent_types_has_all_nine_types():
    codes = {spec.code for spec in intellidecision_policy.list_intent_types()}
    assert codes == set("ABCDEFGHI")


def test_get_intent_type_known_code():
    spec = intellidecision_policy.get_intent_type("B")
    assert spec is not None
    assert spec.name == "실행성"
    assert spec.requires_tool is True
    assert spec.requires_writable_domain is True


def test_get_intent_type_unknown_code_returns_none():
    assert intellidecision_policy.get_intent_type("Z") is None


def test_applicable_types_for_domain_excludes_writable_only_types_when_not_writable():
    types = intellidecision_policy.applicable_types_for_domain("contacts", writable=False)
    codes = {spec.code for spec in types}
    assert "B" not in codes
    assert "D" not in codes
    assert "E" not in codes
    assert "G" not in codes
    # writable을 요구하지 않는 유형은 여전히 포함되어야 함
    assert "A" in codes
    assert "C" in codes


def test_applicable_types_for_domain_includes_all_when_writable():
    types = intellidecision_policy.applicable_types_for_domain("chat-relay", writable=True)
    codes = {spec.code for spec in types}
    assert codes == set("ABCDEFGHI")


def test_all_types_have_rag_matching_metadata_fields():
    """Story 1.24(FR31-B) — 유형별 RAG 매칭 사전예측 메타데이터 필드가 모두 채워져 있어야 한다."""
    for spec in intellidecision_policy.list_intent_types():
        assert isinstance(spec.rag_enabled, bool)
        assert spec.rag_source_scope
        assert spec.rag_strategy_hint in {"vector", "hybrid", "none"}


def test_type_a_and_c_are_rag_enabled_with_expected_strategy():
    """탐색성(A)/포괄적 도움 요청(C)은 매뉴얼 RAG 검색이 실제로 트리거되는 유형이다."""
    type_a = intellidecision_policy.get_intent_type("A")
    type_c = intellidecision_policy.get_intent_type("C")
    assert type_a.rag_enabled is True
    assert type_a.rag_strategy_hint == "vector"
    assert type_c.rag_enabled is True
    assert type_c.rag_strategy_hint == "hybrid"


def test_type_e_undo_is_not_rag_enabled():
    """실행 취소(E)는 RAG 검색 없이 변경 이력 테이블만으로 처리되는 유형이다."""
    type_e = intellidecision_policy.get_intent_type("E")
    assert type_e.rag_enabled is False
    assert type_e.rag_strategy_hint == "none"
