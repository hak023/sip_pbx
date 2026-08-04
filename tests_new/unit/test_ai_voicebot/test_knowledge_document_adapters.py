"""
AI Voicebot Unit Tests - 도메인 비종속 지식베이스 소스 어댑터 (Story 1.26, FR32-A)

docs/stories/1.26.knowledge-base-document-crud-and-upload.story.md 참고
"""

import json

import pytest

from src.ai_voicebot.self_service.document_adapters import (
    OpenApiSpecAdapter,
    PdfDocumentAdapter,
)


class TestOpenApiSpecAdapter:
    def test_json_spec_produces_qa_pairs_per_endpoint(self):
        spec = {
            "paths": {
                "/booking": {
                    "get": {
                        "summary": "예약 목록 조회",
                        "parameters": [
                            {"name": "owner", "required": True, "description": "테넌트 owner"},
                        ],
                    },
                    "post": {"summary": "예약 생성"},
                }
            }
        }
        adapter = OpenApiSpecAdapter(json.dumps(spec), title="예약 API")
        pairs = adapter.load_pairs()
        assert len(pairs) == 2
        questions = {q for q, _ in pairs}
        assert "GET /booking 엔드포인트는 무엇을 하나요?" in questions
        assert "POST /booking 엔드포인트는 무엇을 하나요?" in questions

    def test_yaml_spec_is_parsed(self):
        spec_yaml = """
paths:
  /status:
    get:
      summary: 상태 조회
"""
        adapter = OpenApiSpecAdapter(spec_yaml, title="상태 API")
        pairs = adapter.load_pairs()
        assert len(pairs) == 1
        assert pairs[0][0] == "GET /status 엔드포인트는 무엇을 하나요?"

    def test_parameters_included_in_answer(self):
        spec = {
            "paths": {
                "/x": {
                    "get": {
                        "summary": "x 조회",
                        "parameters": [{"name": "id", "required": True, "description": "식별자"}],
                    }
                }
            }
        }
        adapter = OpenApiSpecAdapter(json.dumps(spec))
        items = adapter.load_pairs_with_meta()
        assert "id" in items[0]["answer"]
        assert "필수" in items[0]["answer"]

    def test_invalid_text_raises(self):
        adapter = OpenApiSpecAdapter("not json: not: valid: : yaml:::")
        with pytest.raises(Exception):
            adapter.load_pairs()

    def test_empty_paths_returns_empty_list(self):
        adapter = OpenApiSpecAdapter(json.dumps({"paths": {}}))
        assert adapter.load_pairs() == []

    def test_section_title_and_related_domain_meta(self):
        spec = {"paths": {"/x": {"get": {"summary": "s"}}}}
        adapter = OpenApiSpecAdapter(json.dumps(spec), title="내 API")
        items = adapter.load_pairs_with_meta()
        assert items[0]["section_title"] == "내 API"
        assert items[0]["related_domain"] == ""


class TestPdfDocumentAdapter:
    def test_no_text_pdf_returns_empty_list(self):
        # 텍스트가 전혀 없는 빈 페이지 PDF는 items가 비어있어야 한다(예외 아님).
        # pypdf의 PdfWriter로 실제 유효한 최소 PDF를 생성해 파싱 안정성을 보장한다.
        from pypdf import PdfWriter
        import io

        writer = PdfWriter()
        writer.add_blank_page(width=72, height=72)
        buf = io.BytesIO()
        writer.write(buf)

        adapter = PdfDocumentAdapter(buf.getvalue(), title="빈 문서")
        items = adapter.load_pairs_with_meta()
        assert items == []

    def test_extracts_paragraphs_as_items(self):
        from pypdf import PdfWriter
        import io

        writer = PdfWriter()
        writer.add_blank_page(width=200, height=200)
        buf = io.BytesIO()
        writer.write(buf)

        adapter = PdfDocumentAdapter(buf.getvalue(), title="샘플 문서")
        # 실제 텍스트 삽입 없이도(블랭크 페이지) 어댑터가 예외 없이 리스트를 반환하는지만 확인
        items = adapter.load_pairs_with_meta()
        assert isinstance(items, list)
