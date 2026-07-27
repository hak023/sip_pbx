"""
AI Voicebot Unit Tests - booking_gemini_fc.py의 JSON Schema → genai_types.Schema 변환
(Story 1.14 근본 원인 수정, Story 6.2에서 google-genai 기준으로 이식)

docs/stories/1.14.empty-candidate-string-field-mitigation.story.md,
docs/stories/6.2.booking-gemini-fc-genai-migration.story.md 참고

핵심 회귀 방지 대상: Python `Any` 타입 파라미터(예: `self_service/tools.py::_update_self_service_setting`의
`value: Any`)가 생성하는 JSON Schema(`{"title": "Value"}` — `type` 키 없음)를 예전 코드는
"타입 정보 없음"과 "명시적 object 선언"을 동일하게 취급해 빈 OBJECT로 잘못 변환했다. 이로 인해
Gemini function-calling이 실제로는 문자열/불리언 값을 받아야 하는 필드를 "프로퍼티 0개짜리 OBJECT"로
알고 있어, 특히 자유 문자열 값(짧은 불리언/enum 값과 다르게)을 채워야 할 때 스키마를 만족시키지 못해
완전히 빈 응답(candidate)을 반환하는 현상으로 이어졌다(결함③).
"""

from google.genai import types as genai_types

from src.ai_voicebot.langgraph.booking_gemini_fc import _json_schema_to_genai_schema


class TestUnconstrainedAnyTypeField:
    """Python `Any` 타입(= JSON Schema에 `type` 키 자신이 없음)의 변환 검증"""

    def test_schema_without_type_key_becomes_string_not_object(self):
        """회귀 방지 핵심 테스트 — 예전에는 OBJECT(속성 0개)로 잘묻 변환되었다."""
        schema = {"title": "Value"}
        result = _json_schema_to_genai_schema(schema)
        assert result.type == genai_types.Type.STRING
        assert result.type != genai_types.Type.OBJECT

    def test_schema_with_only_title_no_type_or_description(self):
        schema = {"title": "SomeField"}
        result = _json_schema_to_genai_schema(schema)
        assert result.type == genai_types.Type.STRING


class TestExplicitObjectStillWorks:
    """명시적으로 object로 선언되거나 properties가 있는 가우는 여전히 OBJECT로 변환되어야 함"""

    def test_explicit_object_type_is_preserved(self):
        schema = {"type": "object", "properties": {"a": {"type": "string"}}}
        result = _json_schema_to_genai_schema(schema)
        assert result.type == genai_types.Type.OBJECT
        assert "a" in result.properties

    def test_properties_without_explicit_type_is_treated_as_object(self):
        """type 키가 없어도 properties가 있으면 여전히 object로 이급함(회귀 방지)."""
        schema = {"properties": {"a": {"type": "string"}}}
        result = _json_schema_to_genai_schema(schema)
        assert result.type == genai_types.Type.OBJECT
        assert "a" in result.properties


class TestExplicitPrimitiveTypesUnaffected:
    """명시적 타입이 있는 필럈은 이변 수정과 부관하게 그대로 동작해야 함"""

    def test_explicit_string_type(self):
        schema = {"type": "string", "description": "설명"}
        result = _json_schema_to_genai_schema(schema)
        assert result.type == genai_types.Type.STRING

    def test_explicit_boolean_type(self):
        schema = {"type": "boolean"}
        result = _json_schema_to_genai_schema(schema)
        assert result.type == genai_types.Type.BOOLEAN

    def test_explicit_enum_values_preserved(self):
        schema = {"type": "string", "enum": ["hitl", "transfer", "none"]}
        result = _json_schema_to_genai_schema(schema)
        assert result.type == genai_types.Type.STRING
        assert list(result.enum) == ["hitl", "transfer", "none"]

    def test_array_type_unaffected(self):
        schema = {"type": "array", "items": {"type": "string"}}
        result = _json_schema_to_genai_schema(schema)
        assert result.type == genai_types.Type.ARRAY


class TestAnyOfStillTakesFirstOption:
    def test_any_of_uses_first_branch(self):
        schema = {"anyOf": [{"type": "string"}, {"type": "null"}]}
        result = _json_schema_to_genai_schema(schema)
        assert result.type == genai_types.Type.STRING


class TestRealUpdateSelfServiceSettingToolSchema:
    """실제 update_self_service_setting_tool의 args_schema로 종단 검증(회귀 방지)."""

    def test_value_field_is_string_not_object(self):
        from src.ai_voicebot.self_service.tools import update_self_service_setting_tool
        from src.ai_voicebot.langgraph.booking_gemini_fc import _langchain_tools_to_glm_tool

        tool = _langchain_tools_to_glm_tool([update_self_service_setting_tool])
        decl = tool.function_declarations[0]
        assert decl.parameters.properties["value"].type == genai_types.Type.STRING

    def test_owner_domain_field_fields_still_string(self):
        from src.ai_voicebot.self_service.tools import update_self_service_setting_tool
        from src.ai_voicebot.langgraph.booking_gemini_fc import _langchain_tools_to_glm_tool

        tool = _langchain_tools_to_glm_tool([update_self_service_setting_tool])
        decl = tool.function_declarations[0]
        for field in ("owner", "domain", "field", "call_id"):
            assert decl.parameters.properties[field].type == genai_types.Type.STRING
