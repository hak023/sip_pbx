"""
도메인 비종속 지식베이스 업로드 소스 어댑터 (Story 1.26, FR32-A).

`manual_indexer.py::SourceAdapter` 프로토콜(Story 1.25)을 구현하는 신규 어댑터 2종.
디스크 파일이 아니라 API로 업로드된 바이트/텍스트를 감싸므로, 프로토콜의 `path` 인자는 사용하지
않는다(생성자로 주입된 콘텐츠를 그대로 파싱).
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import structlog
import yaml

logger = structlog.get_logger(__name__)

# 문단(청크) 최소 길이 — 너무 짧은 조각(빈 줄, 페이지 번호 등)은 청크로 만들지 않는다.
_MIN_PARAGRAPH_LEN = 20


class PdfDocumentAdapter:
    """PDF 바이트에서 텍스트를 추출해 문단 단위로 청킹하는 어댑터."""

    def __init__(self, pdf_bytes: bytes, *, title: str = "") -> None:
        self._pdf_bytes = pdf_bytes
        self._title = title or "PDF 문서"

    def load_pairs(self, path: Optional[Path] = None) -> List[Tuple[str, str]]:
        return [(it["question"], it["answer"]) for it in self.load_pairs_with_meta(path)]

    def load_pairs_with_meta(self, path: Optional[Path] = None) -> List[Dict[str, str]]:
        try:
            from pypdf import PdfReader
        except ImportError as exc:
            raise RuntimeError("pypdf가 설치되어 있지 않습니다(PDF 업로드 불가)") from exc
        import io

        reader = PdfReader(io.BytesIO(self._pdf_bytes))
        items: List[Dict[str, str]] = []
        for page_index, page in enumerate(reader.pages, start=1):
            text = (page.extract_text() or "").strip()
            if not text:
                continue
            for para_index, paragraph in enumerate(
                (p.strip() for p in text.split("\n\n") if p.strip()), start=1
            ):
                if len(paragraph) < _MIN_PARAGRAPH_LEN:
                    continue
                items.append(
                    {
                        "question": f"{self._title} (p.{page_index}-{para_index})",
                        "answer": paragraph,
                        "section_title": self._title,
                        "related_domain": "",
                    }
                )
        if not items:
            logger.warning("pdf_document_adapter_no_text_extracted", title=self._title)
        return items


class OpenApiSpecAdapter:
    """OpenAPI 스펙(JSON/YAML)의 각 엔드포인트를 Q&A 유사 페어로 변환하는 어댑터."""

    def __init__(self, spec_text: str, *, title: str = "") -> None:
        self._spec_text = spec_text
        self._title = title or "API 문서"

    def load_pairs(self, path: Optional[Path] = None) -> List[Tuple[str, str]]:
        return [(it["question"], it["answer"]) for it in self.load_pairs_with_meta(path)]

    def extract_base_url(self) -> str:
        """스펙의 `servers[0].url`을 추출한다(Story 1.35 재개, FR34-A). 없으면 빈 문자열.

        업로드 시 base_url 입력 필드의 기본값 제안용 — 테넌트가 직접 override 가능해야 한다
        (사설 IP·미기재 스펙 대비, 강제 사용 아님).
        """
        spec = self._parse_spec()
        servers = spec.get("servers") or []
        if isinstance(servers, list) and servers:
            first = servers[0]
            if isinstance(first, dict):
                return str(first.get("url") or "")
        return ""

    def load_pairs_with_meta(self, path: Optional[Path] = None) -> List[Dict[str, str]]:
        spec = self._parse_spec()
        paths = spec.get("paths") or {}
        items: List[Dict[str, str]] = []
        for endpoint_path, methods in paths.items():
            if not isinstance(methods, dict):
                continue
            for method, operation in methods.items():
                if method.lower() not in {
                    "get", "post", "put", "delete", "patch", "options", "head",
                }:
                    continue
                if not isinstance(operation, dict):
                    continue
                summary = operation.get("summary") or operation.get("operationId") or ""
                description = operation.get("description") or ""
                parameters = operation.get("parameters") or []
                param_lines = [
                    f"- {p.get('name', '?')}"
                    f"({'필수' if p.get('required') else '선택'}): {p.get('description', '')}"
                    for p in parameters
                    if isinstance(p, dict)
                ]
                answer_parts = [summary, description] + param_lines
                answer = "\n".join(part for part in answer_parts if part).strip()
                if not answer:
                    answer = f"{method.upper()} {endpoint_path} 엔드포인트입니다."
                question = f"{method.upper()} {endpoint_path} 엔드포인트는 무엇을 하나요?"
                items.append(
                    {
                        "question": question,
                        "answer": answer,
                        "section_title": self._title,
                        "related_domain": "",
                        # Story 1.35(FR34-A): 실행 메타데이터 보존 — 동적 Tool 생성 시 재사용
                        "_endpoint_path": endpoint_path,
                        "_method": method.upper(),
                        "_parameters": parameters,
                        "_request_body": operation.get("requestBody"),
                    }
                )
        if not items:
            logger.warning("openapi_spec_adapter_no_endpoints_found", title=self._title)
        return items

    def _parse_spec(self) -> dict:
        text = self._spec_text.strip()
        if not text:
            return {}
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            pass
        try:
            parsed = yaml.safe_load(text)
            return parsed if isinstance(parsed, dict) else {}
        except yaml.YAMLError as exc:
            raise RuntimeError(f"OpenAPI 스펙 파싱 실패(JSON/YAML 모두 아님): {exc}") from exc
