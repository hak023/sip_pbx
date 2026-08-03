"""
셀프서비스 매뉴얼 → ChromaDB 색인 파이프라인 (Story 1.3 Task 2).

`docs/product/self-service-manual-content.md` 의 Q&A 쌍을 파싱해
knowledge 컬렉션에 doc_type="self_service_manual" 로 색인한다.

- category: "question" (VALID_CATEGORIES에 정의된 기존 카테고리 재사용,
  self_service_manual 여부는 doc_type 메타데이터로 구분한다)
- owner: 테넌트별로 색인한다(owner 필터 기반 RAG 격리, Story 1.3 AC2).
  매뉴얼 내용 자체는 테넌트 공통이지만, RAGEngine.search()가 항상
  owner_filter를 적용하므로 색인도 owner 단위로 이루어져야 검색이 된다.
- 멱등성: 이미 해당 owner에 self_service_manual 문서가 색인되어 있으면
  force=True 가 아닌 한 재색인을 건너뛴다(add_knowledge는 매 호출마다
  새 doc_id를 발급하므로 무조건 재실행 시 중복이 발생한다).
- 섹션/도메인 메타데이터: 각 Q&A에 소속 섹션 제목(section_title)과
  settings_catalog 도메인명(related_domain)을 저장한다. 이 정보로
  프론트엔드에서 도메인별 그룹핑·도움말 표시가 가능하고,
  AI가 RAG 결과에서 어떤 settings_catalog 도메인을 써야 하는지 파악할 수 있다.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Protocol, Tuple

import structlog

from src.ai_voicebot.knowledge.knowledge_service import add_knowledge, list_knowledge
from src.common.sip_owner import normalize_owner_username

logger = structlog.get_logger(__name__)

# self_service_agent.py에서도 doc_type 필터 값으로 재사용
SELF_SERVICE_MANUAL_DOC_TYPE = "self_service_manual"

_DEFAULT_MANUAL_PATH = (
    Path(__file__).resolve().parents[3] / "docs" / "product" / "self-service-manual-content.md"
)

# "**Q: ...**" 다음 줄부터 "A: ..." — 다음 "**Q:" 또는 "---" 구분선 전까지를 answer로 캡처.
_QA_PATTERN = re.compile(
    r"\*\*Q:\s*(?P<question>.+?)\*\*\s*\n"
    r"A:\s*(?P<answer>.+?)"
    r"(?=\n\*\*Q:|\n---|\Z)",
    re.DOTALL,
)

# "## N. 섹션 제목" 패턴. 셀션 제목 끝에 명시적 도메인 태그(예: "{domain: ai-escalation}")가 있으면
# 함께 캡처한다(Story 2.8 — 매뉴얼 작성자가 코드를 모르더라도 정확한 도메인 연결을 보장할 수 있도록).
# 태그가 없는 기존 섹션은 여전히 정상 동작한다(점진적 마이그레이션 허용, IV1).
_SECTION_PATTERN = re.compile(
    r"^## \d+\.\s*(?P<title>.+?)(?:\s*\{domain:\s*(?P<domain_tag>[\w-]+)\s*\})?\s*$",
    re.MULTILINE,
)

# 섹션 제목 키워드 → settings_catalog 도메인 매핑
# 매뉴얼 섹션명에서 핵심 키워드로 판별한다.
_SECTION_TO_DOMAIN: List[Tuple[str, str]] = [
    ("에스컬레이션", "ai-escalation"),
    ("착신 제어", "call-control"),
    ("착신규칙", "call-control"),
    ("채팅", "chat-relay"),
    ("SIP 문자", "chat-relay"),
    ("예약", "booking"),
    ("페르소나", "persona"),
    ("Calendar", "integrations"),
    ("캘린더", "integrations"),
    ("초기 설정", "onboarding"),
    ("셀프서비스", "self-service"),
    ("서비스 소개", "intro"),
    ("통화 이력", "call-history"),
    ("운영자", "operator-status"),
]


def _section_title_to_domain(title: str) -> str:
    """섹션 제목에서 settings_catalog 도메인명을 유추한다(키워드 매칭 폴백). 매핑 없으면 빈 문자열.

    명시적 `{domain: xxx}` 태그가 있으면 이 함수는 호출되지 않고 태그 값이 그대로 사용된다
    (`parse_manual_qa_with_meta` 참고, Story 2.8).
    """
    for keyword, domain in _SECTION_TO_DOMAIN:
        if keyword in title:
            return domain
    return ""


def parse_manual_qa_pairs(markdown_text: str) -> List[Tuple[str, str]]:
    """매뉴얼 마크다운에서 (question, answer) 쌍 목록을 추출한다.

    형식: "**Q: 질문**\\nA: 답변"(A는 여러 줄·목록 가능),
    다음 "**Q:" 또는 섹션 구분선("---") 전까지가 answer.
    """
    pairs: List[Tuple[str, str]] = []
    for m in _QA_PATTERN.finditer(markdown_text):
        question = m.group("question").strip()
        answer = m.group("answer").strip()
        if question and answer:
            pairs.append((question, answer))
    return pairs


def parse_manual_qa_with_meta(markdown_text: str) -> List[Dict[str, str]]:
    """매뉴얼 마크다운에서 Q&A 쌍을 섹션·도메인 메타데이터와 함께 추출한다.

    섹션 제목에 명시적 `{domain: xxx}` 태그가 있으면 그 값을 그대로 사용하고(Story 2.8),
    태그가 없으면 기존 키워드 매칭(`_section_title_to_domain`)으로 폴백한다(점진적 마이그레이션
    허용 — 매뉴얼 전체를 한 번에 바꿀 필요 없음, IV1).

    Returns:
        [{"question": ..., "answer": ..., "section_title": ..., "related_domain": ...}, ...]
    """
    # 섹션 경계 파악: 각 섹션의 (시작 위치, 제목, 태그 도메인) 목록
    sections: List[Tuple[int, str, str]] = []
    for m in _SECTION_PATTERN.finditer(markdown_text):
        sections.append((m.start(), m.group("title").strip(), (m.group("domain_tag") or "").strip()))

    result: List[Dict[str, str]] = []
    for qa_match in _QA_PATTERN.finditer(markdown_text):
        question = qa_match.group("question").strip()
        answer = qa_match.group("answer").strip()
        if not question or not answer:
            continue

        # Q&A가 속한 섹션 결정: Q&A 시작 위치보다 작은 마지막 섹션
        qa_pos = qa_match.start()
        section_title = ""
        section_domain_tag = ""
        for sec_pos, sec_title, sec_domain_tag in sections:
            if sec_pos <= qa_pos:
                section_title = sec_title
                section_domain_tag = sec_domain_tag
            else:
                break

        related_domain = section_domain_tag or _section_title_to_domain(section_title)
        result.append({
            "question": question,
            "answer": answer,
            "section_title": section_title,
            "related_domain": related_domain,
        })
    return result


def load_manual_qa_pairs(manual_path: Optional[Path] = None) -> List[Tuple[str, str]]:
    """디스크에서 매뉴얼 파일을 읽어 Q&A 쌍을 반환한다."""
    path = manual_path or _DEFAULT_MANUAL_PATH
    text = path.read_text(encoding="utf-8")
    return parse_manual_qa_pairs(text)


def load_manual_qa_with_meta(manual_path: Optional[Path] = None) -> List[Dict[str, str]]:
    """디스크에서 매뉴얼 파일을 읽어 Q&A + 섹션/도메인 메타데이터를 반환한다."""
    path = manual_path or _DEFAULT_MANUAL_PATH
    text = path.read_text(encoding="utf-8")
    return parse_manual_qa_with_meta(text)


class SourceAdapter(Protocol):
    """색인 소스 어댑터 인터페이스 (Story 1.25, FR31-C).

    소스 종류(마크다운 Q&A, 향후 OpenAPI/Tool docstring 등)마다 다른 파싱 로직을
    이 인터페이스 뒤에 감춰, `index_self_service_manual()`이 소스 종류를 몰라도 되게 한다.
    """

    def load_pairs(self, path: Optional[Path] = None) -> List[Tuple[str, str]]: ...

    def load_pairs_with_meta(self, path: Optional[Path] = None) -> List[Dict[str, str]]: ...


class MarkdownManualAdapter:
    """기존 마크다운 Q&A 파서를 그대로 감싼 기본 어댑터(회귀 없음, 동작 100% 동일)."""

    def load_pairs(self, path: Optional[Path] = None) -> List[Tuple[str, str]]:
        return load_manual_qa_pairs(path)

    def load_pairs_with_meta(self, path: Optional[Path] = None) -> List[Dict[str, str]]:
        return load_manual_qa_with_meta(path)


_DEFAULT_ADAPTER = MarkdownManualAdapter()


def index_self_service_manual(
    owner: str,
    vector_db: Any,
    embedder: Any,
    *,
    manual_path: Optional[Path] = None,
    force: bool = False,
    adapter: Optional[SourceAdapter] = None,
) -> dict:
    """지정 owner에 셀프서비스 매뉴얼 Q&A를 색인한다.

    Returns:
        {"ok": bool, "indexed": int, "skipped": bool, "existing": int, "errors": [...]}
    """
    adapter = adapter or _DEFAULT_ADAPTER
    normalized_owner = normalize_owner_username(owner)
    if not normalized_owner:
        return {"ok": False, "error": "owner가 비었거나 정규화 후 비어 있습니다", "indexed": 0}
    if vector_db is None or embedder is None:
        return {"ok": False, "error": "vector_db/embedder가 필요합니다", "indexed": 0}

    existing = list_knowledge(
        vector_db, owner=normalized_owner, doc_type=SELF_SERVICE_MANUAL_DOC_TYPE, limit=1
    )
    existing_count = existing.get("total", 0)
    if existing_count and not force:
        logger.info(
            "self_service_manual_index_skip_existing",
            owner=normalized_owner,
            existing_count=existing_count,
        )
        return {"ok": True, "indexed": 0, "skipped": True, "existing": existing_count, "errors": []}

    pairs = adapter.load_pairs(manual_path)
    if not pairs:
        return {"ok": False, "error": "매뉴얼에서 Q&A 쌍을 추출하지 못했습니다", "indexed": 0}

    # 섹션/도메인 메타데이터도 함께 파싱 (프론트엔드 도움말 API용)
    items_with_meta = adapter.load_pairs_with_meta(manual_path)
    meta_by_qa: Dict[Tuple[str, str], Dict[str, str]] = {
        (it["question"], it["answer"]): it for it in items_with_meta
    }

    indexed = 0
    errors: List[str] = []
    for question, answer in pairs:
        # Q+A를 함께 임베딩/저장해야 RAG 검색 결과(Document.text)에 답변까지 포함된다
        # (기존 manual_to_faq_extractor.py 패턴과 동일하게 "Q: ...\nA: ..." 결합).
        doc_content = f"Q: {question}\nA: {answer}"
        result = add_knowledge(
            vector_db=vector_db,
            embedder=embedder,
            text=doc_content,
            owner=normalized_owner,
            category="question",
            doc_type=SELF_SERVICE_MANUAL_DOC_TYPE,
            source="seed",
            answer=answer,
        )
        if result.get("ok"):
            doc_id = result.get("doc_id")
            # 섹션/도메인 메타데이터를 ChromaDB에 추가 저장
            extra = meta_by_qa.get((question, answer), {})
            if doc_id and (extra.get("section_title") or extra.get("related_domain")):
                try:
                    current = vector_db.collection.get(
                        ids=[doc_id], include=["metadatas"]
                    )
                    cur_meta = ((current.get("metadatas") or [{}])[0]) or {}
                    cur_meta["section_title"] = extra.get("section_title", "")
                    cur_meta["related_domain"] = extra.get("related_domain", "")
                    vector_db.collection.update(ids=[doc_id], metadatas=[cur_meta])
                except Exception as e:
                    logger.warning(
                        "manual_index_meta_update_failed",
                        doc_id=doc_id,
                        error=str(e),
                    )
            indexed += 1
        else:
            errors.append(result.get("error", "unknown_error"))

    logger.info(
        "self_service_manual_indexed",
        owner=normalized_owner,
        indexed=indexed,
        total_pairs=len(pairs),
        error_count=len(errors),
    )
    return {
        "ok": len(errors) == 0,
        "indexed": indexed,
        "skipped": False,
        "existing": existing_count,
        "errors": errors,
    }
