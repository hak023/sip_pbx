"""
셀프서비스 AI 도우미 — 도움말 문서 열람 API.

프론트엔드 `settings/ai-assistant/docs` 화면에서 관리자가 서비스 이용 매뉴얼을
구조화된 Q&A 형태로 열람할 수 있도록 제공한다.

매뉴얼 Q&A는 raw 마크다운이 아니라 ChromaDB에 `doc_type=self_service_manual`로
색인된 지식 베이스 데이터를 반환한다. 섹션 제목과 관련 settings_catalog 도메인 정보도
함께 제공해, 유저가 AI 도우미에게 어떤 설정 변경을 요청할 수 있는지 파악하기 쉽게 한다.

엔드포인트
-----------
  GET  /api/settings/ai-assistant/docs?owner=<owner>
       owner에 색인된 self_service_manual Q&A 목록 반환.
       색인 항목이 없으면 자동으로 색인 후 반환한다.

  POST /api/settings/ai-assistant/docs/index?owner=<owner>&force=false
       매뉴얼 Q&A를 (재)색인한다. force=true 이면 기존 항목과 무관하게 재색인.

  GET  /api/settings/ai-assistant/catalog
       settings_catalog에 등록된 도메인·필드·writable 정보를 반환한다.
       AI 도우미가 응대 시 어떤 설정을 변경할 수 있는지 유저가 확인할 수 있고,
       AI 자신도 이 정보를 참조해 필요한 정보를 유저에게 물어본다.

  GET  /api/settings/ai-assistant/screen-graph
       settings_catalog 도메인과 프론트엔드 화면(라우트·UI 요소)을 연결하는 경량
       지식 그래프(Screen Graph, Story 1.11)를 반환한다. AI 도우미가 대화 중 화면을
       설명할 때 참조하는 것과 동일한 데이터이며, 유저는 이 화면에서 AI가 안내할 수 있는
       화면 목록을 직접 확인할 수 있다(Story 1.12).

  GET  /api/settings/ai-assistant/catalog-config/export
       카탈로그/Screen Graph의 현재 활성 설정을 그대로 재업로드 가능한 원본 JSON으로
       내보낸다(Epic 2 Story 2.4). `/catalog`, `/screen-graph`가 읽기 전용 요약 뷰인 것과
       달리, 이 엔드포인트는 Story 2.5의 import가 그대로 입력으로 받는 원본 포맷이다.

  POST /api/settings/ai-assistant/catalog-config/import
       업로드된 카탈로그/Screen Graph 설정을 검증 후 새 **비활성** 버전으로 저장하고,
       현재 활성 버전과의 diff(무엇이 추가/삭제/변경되는지)를 미리보기로 반환한다
       (Epic 2 Story 2.5). 검증 실패 시 아무것도 저장하지 않는다(원자성).
       실제 반영(적용)은 별도로 `/catalog-config/activate`를 호출해야 한다.

  POST /api/settings/ai-assistant/catalog-config/activate
       지정한 버전을 활성화한다(신규 업로드 확정 적용과 과거 버전 롤백 모두 동일 엔드포인트
       재사용). 활성화 즉시 다음 대화부터 반영된다(서버 재시작 불필요, FR20).

  GET  /api/settings/ai-assistant/catalog-config/versions?config_kind=catalog
       지정 config_kind(catalog|screen_graph)의 버전 이력을 최신순으로 반환한다.

  GET  /api/settings/ai-assistant/intellidecision-policy
       IntelliDecision 유형(A~I) 정책 레지스트리(Story 1.18,
       `self_service/intellidecision_policy.py`)를 읽기 전용으로 반환한다. 프론트엔드가
       AI 도우미의 판단 기준을 표 형태로 열람할 수 있게 한다(리서치 축 C-1, 저비용 시각화).

  GET  /api/settings/ai-assistant/knowledge-base/inventory?owner=<owner>
       매뉴얼 RAG(ChromaDB, doc_type=self_service_manual)의 owner별 색인 현황(총 청크 수,
       도메인 분포, 소스 문서 수, 최근 색인 시각)을 읽기 전용으로 반환한다(Story 1.23, FR31-A).
       색인/검색 로직에는 어떤 영향도 주지 않는 순수 관측 엔드포인트다.

  GET  /api/settings/ai-assistant/intellidecision-manual?owner=<owner>
       유형(A~I) 각각에 대해 지식베이스 기반 정적 사례(트리거 예시 → 매칭 문서 → hop 경로)를
       반환한다(Story 1.40, FR34-D). 임베딩 벡터 검색과 지식 그래프 조회만 사용하며 실시간
       LLM 호출은 전혀 없다(응답 생성 없음). 매칭 문서가 없으면 has_case=false로 표시한다.
"""

from __future__ import annotations

import asyncio
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

router = APIRouter(prefix="/api/settings/ai-assistant", tags=["settings-ai-assistant"])

_SELF_SERVICE_DOC_TYPE = "self_service_manual"


# ---------------------------------------------------------------------------
# 응답 모델
# ---------------------------------------------------------------------------

class HelpDocItem(BaseModel):
    id: str
    question: str
    answer: str
    section_title: str
    related_domain: str
    created_at: str


class HelpDocsResponse(BaseModel):
    owner: str
    total: int
    items: List[HelpDocItem]
    indexed: bool  # True = 이미 색인 존재, False = 이번 호출에서 색인 실행


class IndexResponse(BaseModel):
    owner: str
    ok: bool
    indexed: int
    skipped: bool
    existing: int
    errors: List[str]
    detail: str


class CatalogDomainEntry(BaseModel):
    domain: str
    writable: bool
    writable_fields: List[str]
    destructive: bool
    optional_fields: List[str]
    related_manual_domains: List[str]


class CatalogResponse(BaseModel):
    domains: List[CatalogDomainEntry]


class ScreenUiFieldOut(BaseModel):
    field: str
    element_type: str
    label: str
    options: List[str] = []


class ScreenEntryOut(BaseModel):
    domain: str
    route: str
    title: str
    description: str
    fields: List[ScreenUiFieldOut] = []


class ScreenGraphResponse(BaseModel):
    screens: List[ScreenEntryOut]


class CatalogConfigExportResponse(BaseModel):
    catalog: Dict[str, Any]
    catalog_version: Optional[int]
    catalog_source: str  # "db" | "static_fallback"
    screen_graph: Dict[str, Any]
    screen_graph_version: Optional[int]
    screen_graph_source: str  # "db" | "static_fallback"
    exported_at: str


class CatalogConfigImportRequest(BaseModel):
    catalog: Dict[str, Any]
    screen_graph: Dict[str, Any]
    uploaded_by: str = ""
    note: str = ""


class IntentTypeOut(BaseModel):
    code: str
    name: str
    summary: str
    trigger_examples: List[str]
    requires_tool: bool
    requires_writable_domain: bool
    related_types: List[str]
    rag_enabled: bool
    rag_source_scope: str
    rag_strategy_hint: str


class IntelliDecisionPolicyResponse(BaseModel):
    types: List[IntentTypeOut]


class ManualCaseDocumentOut(BaseModel):
    doc_id: str
    score: float
    related_domain: str
    excerpt: str


class ManualHopEdgeOut(BaseModel):
    hop: int
    edge_type: str
    source_type: str
    source_id: str
    target_type: str
    target_id: str


class IntelliDecisionManualCaseOut(BaseModel):
    code: str
    has_case: bool
    trigger_example: Optional[str] = None
    matched_documents: List[ManualCaseDocumentOut] = []
    hop_path: List[ManualHopEdgeOut] = []


class IntelliDecisionManualResponse(BaseModel):
    cases: List[IntelliDecisionManualCaseOut]


class KnowledgeBaseDomainCount(BaseModel):
    domain: str
    count: int


class AutoAssembledSettingItem(BaseModel):
    label: str
    method: str
    writable: bool
    description: str


class AutoAssembledSummary(BaseModel):
    """Story 1.31(FR33-B) 업로드 데이터 기반 지식베이스 자동 구성 집계."""

    manual_qa_count: int
    setting_item_count: int
    writable_setting_item_count: int
    setting_items: List[AutoAssembledSettingItem]
    screen_node_count: int


class KnowledgeBaseInventoryResponse(BaseModel):
    owner: str
    total_chunks: int
    source_document_count: int
    domain_distribution: List[KnowledgeBaseDomainCount]
    last_indexed_at: str
    doc_type: str
    auto_assembled: Optional[AutoAssembledSummary] = None


class CatalogConfigDiff(BaseModel):
    added: List[str] = []
    removed: List[str] = []
    changed: List[str] = []


class CatalogConfigImportResponse(BaseModel):
    ok: bool
    catalog_errors: List[str] = []
    screen_graph_errors: List[str] = []
    catalog_version: Optional[int] = None
    screen_graph_version: Optional[int] = None
    catalog_diff: Optional[CatalogConfigDiff] = None
    screen_graph_diff: Optional[CatalogConfigDiff] = None


class CatalogConfigActivateRequest(BaseModel):
    config_kind: str
    version_no: int
    activated_by: str = ""


class CatalogConfigActivateResponse(BaseModel):
    ok: bool
    config_kind: str
    version_no: int
    error: Optional[str] = None


class CatalogConfigVersionItem(BaseModel):
    version_no: int
    is_active: bool
    uploaded_by: str
    note: str
    created_at: str
    activated_at: Optional[str] = None
    activated_by: str = ""


class CatalogConfigVersionsResponse(BaseModel):
    config_kind: str
    versions: List[CatalogConfigVersionItem]


# ---------------------------------------------------------------------------
# 헬퍼
# ---------------------------------------------------------------------------

def _knowledge_service():
    """전역 KnowledgeService 반환. 없으면 503."""
    try:
        from src.services.knowledge_service import get_knowledge_service
        ks = get_knowledge_service()
        if ks is None:
            raise HTTPException(
                status_code=503,
                detail="KnowledgeService가 초기화되지 않았습니다. AI 서버가 기동 중인지 확인하세요.",
            )
        return ks
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=503, detail=f"KnowledgeService 접근 실패: {e}") from e


def _parse_item(raw: Dict[str, Any]) -> Optional[HelpDocItem]:
    """ChromaDB raw 항목을 HelpDocItem으로 변환한다. 파싱 불가 시 None."""
    doc_id = raw.get("id") or ""
    text = (raw.get("text") or "").strip()
    meta = raw.get("metadata") or {}

    if not text or not doc_id:
        return None

    # "Q: ...\nA: ..." 형식에서 분리
    question = ""
    answer = ""
    if text.startswith("Q:"):
        parts = text.split("\nA:", 1)
        question = parts[0][2:].strip()
        answer = parts[1].strip() if len(parts) > 1 else ""
    else:
        question = text[:120]
        answer = text

    return HelpDocItem(
        id=doc_id,
        question=question,
        answer=answer,
        section_title=str(meta.get("section_title") or ""),
        related_domain=str(meta.get("related_domain") or ""),
        created_at=str(meta.get("created_at") or ""),
    )


# ---------------------------------------------------------------------------
# 엔드포인트
# ---------------------------------------------------------------------------

@router.get("/docs", response_model=HelpDocsResponse, summary="도움말 Q&A 목록")
async def list_help_docs(
    owner: str = Query(..., description="테넌트 owner"),
) -> HelpDocsResponse:
    """
    owner에 색인된 self_service_manual Q&A 항목을 반환한다.
    색인 항목이 없으면 매뉴얼 파일에서 자동 색인 후 반환한다.
    """
    ks = _knowledge_service()

    # 기존 항목 조회 — doc_type=self_service_manual, owner 필터
    try:
        raw_all = await ks.get_all_knowledge(limit=2000)
    except Exception as e:
        raise HTTPException(status_code=503, detail=f"ChromaDB 조회 실패: {e}") from e

    owner_f = (owner or "").strip()
    items_raw = [
        r for r in raw_all
        if str((r.get("metadata") or {}).get("doc_type") or "").strip() == _SELF_SERVICE_DOC_TYPE
        and str((r.get("metadata") or {}).get("owner") or "").strip() == owner_f
    ]

    already_indexed = len(items_raw) > 0

    # 색인 없으면 자동 색인
    if not already_indexed:
        try:
            from src.ai_voicebot.self_service.manual_indexer import index_self_service_manual
            idx_result = index_self_service_manual(
                owner=owner_f,
                vector_db=ks.vector_db,
                embedder=ks.embedder,
            )
        except Exception as e:
            raise HTTPException(status_code=503, detail=f"매뉴얼 색인 실패: {e}") from e

        if not idx_result.get("ok"):
            raise HTTPException(
                status_code=503,
                detail=f"매뉴얼 색인 오류: {idx_result.get('error', '알 수 없는 오류')}",
            )

        # 재조회
        try:
            raw_all2 = await ks.get_all_knowledge(limit=2000)
        except Exception as e:
            raise HTTPException(status_code=503, detail=f"ChromaDB 재조회 실패: {e}") from e
        items_raw = [
            r for r in raw_all2
            if str((r.get("metadata") or {}).get("doc_type") or "").strip() == _SELF_SERVICE_DOC_TYPE
            and str((r.get("metadata") or {}).get("owner") or "").strip() == owner_f
        ]

    items = [it for r in items_raw if (it := _parse_item(r)) is not None]

    # section_title → related_domain → question 순 정렬
    items.sort(key=lambda x: (x.section_title, x.related_domain, x.question))

    return HelpDocsResponse(
        owner=owner_f,
        total=len(items),
        items=items,
        indexed=already_indexed,
    )


@router.post("/docs/index", response_model=IndexResponse, summary="도움말 Q&A 재색인")
def trigger_index(
    owner: str = Query(..., description="테넌트 owner"),
    force: bool = Query(False, description="기존 항목 무관하게 강제 재색인"),
) -> IndexResponse:
    """
    self-service-manual-content.md를 파싱해 ChromaDB에 색인한다.
    force=true 이면 이미 색인된 항목이 있어도 재실행한다(중복 주의).
    """
    ks = _knowledge_service()
    try:
        from src.ai_voicebot.self_service.manual_indexer import index_self_service_manual
        result = index_self_service_manual(
            owner=owner.strip(),
            vector_db=ks.vector_db,
            embedder=ks.embedder,
            force=force,
        )
    except Exception as e:
        raise HTTPException(status_code=503, detail=f"색인 실패: {e}") from e

    detail = (
        f"{result.get('indexed', 0)}건 색인 완료"
        if result.get("ok")
        else f"오류: {result.get('error', '알 수 없는 오류')}"
    )
    return IndexResponse(
        owner=owner.strip(),
        ok=bool(result.get("ok")),
        indexed=int(result.get("indexed") or 0),
        skipped=bool(result.get("skipped")),
        existing=int(result.get("existing") or 0),
        errors=list(result.get("errors") or []),
        detail=detail,
    )


@router.get("/catalog", response_model=CatalogResponse, summary="설정 카탈로그 (AI 변경 가능 도메인)")
def get_catalog() -> CatalogResponse:
    """
    settings_catalog에 등록된 도메인별 메타데이터를 반환한다.

    반환 정보:
    - domain: 도메인 식별자 (tools.py update_self_service_setting 호출 시 사용)
    - writable: update_fn이 있어 AI 도우미가 대화로 설정 변경 가능한지 여부
    - writable_fields: 실제로 변경 허용된 필드 목록
    - destructive: True 이면 변경 시 고객 응대에 영향을 줄 수 있음 (AI가 신중히 확인)
    - optional_fields: 조회 시 반환되는 부가 필드 목록
    - related_manual_domains: 매뉴얼에서 이 도메인을 다루는 섹션의 related_domain 값
    """
    from src.ai_voicebot.self_service import settings_catalog

    # 매뉴얼 섹션 도메인과 catalog 도메인 매핑 (같은 이름인 경우 자동 연결)
    _catalog_to_manual: Dict[str, List[str]] = {
        "persona": ["persona"],
        "ai-escalation": ["ai-escalation"],
        "call-control": ["call-control"],
        "chat-relay": ["chat-relay"],
        "contacts": ["contacts"],
        "general": ["intro"],
        "integrations": ["integrations"],
    }

    entries: List[CatalogDomainEntry] = []
    for domain in settings_catalog.list_domains():
        schema = settings_catalog.get_domain_schema(domain)
        wf = settings_catalog.domain_writable_fields(domain)
        entries.append(
            CatalogDomainEntry(
                domain=domain,
                writable=wf is not None,
                writable_fields=sorted(wf) if wf else [],
                destructive=bool(schema.get("destructive", True)),
                optional_fields=list(schema.get("optional", [])),
                related_manual_domains=_catalog_to_manual.get(domain, []),
            )
        )

    return CatalogResponse(domains=entries)


@router.get("/screen-graph", response_model=ScreenGraphResponse, summary="Screen Graph (화면 안내 정보)")
def get_screen_graph() -> ScreenGraphResponse:
    """
    settings_catalog 도메인과 프론트엔드 화면(라우트·UI 요소)을 연결하는 Screen Graph를
    반환한다(Story 1.11/1.12). AI 도우미가 대화 중 화면을 설명할 때 참조하는 것과
    동일한 데이터이며, 유저는 이 화면에서 AI가 안내할 수 있는 화면 목록을 직접 확인할 수 있다.

    프론트엔드 전용 화면이 없는 도메인(예: persona)은 이 목록에 포함되지 않는다
    (존재하지 않는 화면을 안내하지 않는다는 원칙, screen_graph.py 참고).
    """
    from src.ai_voicebot.self_service import screen_graph

    out: List[ScreenEntryOut] = []
    for entry in screen_graph.list_all_screens():
        out.append(
            ScreenEntryOut(
                domain=entry.domain,
                route=entry.route,
                title=entry.title,
                description=entry.description,
                fields=[
                    ScreenUiFieldOut(
                        field=f.field, element_type=f.element_type, label=f.label,
                        options=list(f.options or []),
                    )
                    for f in entry.fields
                ],
            )
        )
    return ScreenGraphResponse(screens=out)


@router.get(
    "/intellidecision-policy", response_model=IntelliDecisionPolicyResponse,
    summary="IntelliDecision 정책 레지스트리(유형 A~I)",
)
def get_intellidecision_policy() -> IntelliDecisionPolicyResponse:
    """
    IntelliDecision 유형(A~I) 정책 레지스트리를 반환한다(Story 1.18,
    `self_service/intellidecision_policy.py`). 프론트엔드가 AI 도우미의 판단 기준을
    표 형태로 열람할 수 있게 하는 읽기 전용 시각화 용도이며(리서치 축 C-1), 이 응답을 바꿔도
    실제 응대 로직(프롬프트)에는 영향이 없다(단방향 조회).
    """
    from src.ai_voicebot.self_service import intellidecision_policy

    types = [
        IntentTypeOut(
            code=spec.code, name=spec.name, summary=spec.summary,
            trigger_examples=list(spec.trigger_examples),
            requires_tool=spec.requires_tool,
            requires_writable_domain=spec.requires_writable_domain,
            related_types=list(spec.related_types),
            rag_enabled=spec.rag_enabled,
            rag_source_scope=spec.rag_source_scope,
            rag_strategy_hint=spec.rag_strategy_hint,
        )
        for spec in intellidecision_policy.list_intent_types()
    ]
    return IntelliDecisionPolicyResponse(types=types)


@router.get(
    "/intellidecision-manual", response_model=IntelliDecisionManualResponse,
    summary="IntelliDecision 설명 매뉴얼(유형별 지식베이스 기반 정적 사례)",
)
async def get_intellidecision_manual(
    owner: str = Query(..., description="테넌트 owner"),
) -> IntelliDecisionManualResponse:
    """
    유형(A~I) 각각에 대해, 실제 업로드된 지식베이스를 임베딩 검색해 "이 질문 → 이 문서가
    매칭 → 이 hop이 확장" 정적 사례를 반환한다(Story 1.40, FR34-D). 실시간 LLM 호출(응답
    생성)은 전혀 발생하지 않는다 — 벡터 검색과 지식 그래프 조회만 사용한다. 매칭 문서가
    없으면 `has_case=false`로 표시하고 임의로 사례를 지어내지 않는다(AC4).
    """
    from src.ai_voicebot.self_service import intellidecision_policy
    from src.ai_voicebot.self_service.intellidecision_manual import build_case_example_for_type

    # `get_self_service_rag_engine()`는 call_context(ContextVar, agent.py::process_utterance
    # 진입 시에만 채워짐)에서 embedder/vector_db를 읽는다 — 이 엔드포인트는 실제 대화 턴 밖에서
    # 호출되므로, 전역 AI Orchestrator의 인스턴스를 그대로 주입해 검색이 실제로 동작하게 한다
    # (knowledge_base_simulate.py::_get_isolated_agent와 동일한 재사용 패턴, LLM 클라이언트는
    # 필요 없으므로 주입하지 않는다).
    from src.ai_voicebot.factory import get_ai_orchestrator
    from src.ai_voicebot.langgraph.call_context import clear_call_context, set_call_context

    orch = get_ai_orchestrator()
    rag = getattr(orch, "rag", None)
    set_call_context(
        embedder=getattr(rag, "embedder", None) if rag else None,
        vector_db=getattr(rag, "vector_db", None) if rag else None,
    )
    try:
        specs = intellidecision_policy.list_intent_types()
        cases = await asyncio.gather(*[build_case_example_for_type(spec, owner) for spec in specs])
    finally:
        clear_call_context()

    return IntelliDecisionManualResponse(
        cases=[
            IntelliDecisionManualCaseOut(
                code=c.code, has_case=c.has_case, trigger_example=c.trigger_example,
                matched_documents=[
                    ManualCaseDocumentOut(
                        doc_id=d.doc_id, score=d.score, related_domain=d.related_domain, excerpt=d.excerpt,
                    )
                    for d in c.matched_documents
                ],
                hop_path=[
                    ManualHopEdgeOut(
                        hop=e.hop, edge_type=e.edge_type, source_type=e.source_type, source_id=e.source_id,
                        target_type=e.target_type, target_id=e.target_id,
                    )
                    for e in c.hop_path
                ],
            )
            for c in cases
        ]
    )


# Story 1.37(FR34-C) — 문서별 hop 경로 조회 (신규 API, 최소 범위)
class DocumentHopEdgeOut(BaseModel):
    hop: int
    edge_type: str
    source_type: str
    source_id: str
    target_type: str
    target_id: str


class DocumentHopPathResponse(BaseModel):
    document_id: str
    domain_tags: List[str]
    hop_path: List[DocumentHopEdgeOut]


@router.get(
    "/knowledge-base/documents/{document_id}/hop-path",
    response_model=DocumentHopPathResponse,
    summary="지식 문서의 지식 그래프 hop 경로(Story 1.37, FR34-C)",
)
def get_document_hop_path(
    document_id: str,
    owner: str = Query(..., description="테넌트 owner"),
) -> DocumentHopPathResponse:
    """업로드된 문서의 domain_tags를 시작점으로 knowledge_graph.traverse_graph()를 호출해
    해당 문서가 어떤 도메인·화면·IntelliDecision 유형과 연결되는지 반환한다(Story 1.37, FR34-C).
    LLM 호출 없음, 순수 그래프 조회 전용.
    """
    from src.common.knowledge_documents_db import get_document
    from src.ai_voicebot.self_service.knowledge_graph import traverse_graph

    doc = get_document(document_id, owner=owner)
    if doc is None:
        raise HTTPException(status_code=404, detail="문서를 찾을 수 없거나 owner가 일치하지 않습니다.")

    domain_tags = doc.get("domain_tags") or []
    edges: List[DocumentHopEdgeOut] = []
    seen: set = set()
    _MAX = 30
    for domain in sorted({t for t in domain_tags if t}):
        try:
            raw = traverse_graph("catalog_domain", domain, max_hops=3, owner=owner)
        except Exception as exc:
            import logging; logging.getLogger(__name__).warning(
                "knowledge_document_hop_path_failed domain=%s err=%s", domain, exc
            )
            continue
        for e in raw:
            key = (e["hop"], e["edge_type"], str(e["source_id"]), str(e["target_id"]))
            if key in seen:
                continue
            seen.add(key)
            edges.append(DocumentHopEdgeOut(
                hop=e["hop"], edge_type=e["edge_type"],
                source_type=e["source_type"], source_id=str(e["source_id"]),
                target_type=e["target_type"], target_id=str(e["target_id"]),
            ))
            if len(edges) >= _MAX:
                break

    return DocumentHopPathResponse(
        document_id=document_id, domain_tags=domain_tags, hop_path=edges,
    )


@router.get(
    "/knowledge-base/inventory", response_model=KnowledgeBaseInventoryResponse,
    summary="지식베이스(매뉴얼 RAG) 색인 현황",
)
async def get_knowledge_base_inventory(
    owner: str = Query(..., description="테넌트 owner"),
) -> KnowledgeBaseInventoryResponse:
    """
    매뉴얼 RAG(ChromaDB, doc_type=self_service_manual)의 owner별 색인 현황을 반환한다
    (Story 1.23, FR31-A). 색인/검색 로직을 전혀 건드리지 않는 순수 읽기 전용 집계이며,
    색인이 없는 신규 테넌트에서도 예외 없이 0건 결과를 반환한다.
    """
    from src.ai_voicebot.self_service.knowledge_base_inventory import summarize_inventory
    from src.ai_voicebot.self_service.knowledge_base_assembler import (
        summarize_auto_assembled_knowledge_base,
    )

    ks = _knowledge_service()
    try:
        raw_all = await ks.get_all_knowledge(limit=2000)
    except Exception as e:
        raise HTTPException(status_code=503, detail=f"ChromaDB 조회 실패: {e}") from e

    inventory = summarize_inventory(raw_all, owner=owner)

    from src.common import knowledge_documents_db

    document_records = knowledge_documents_db.list_documents(owner=owner)
    auto_assembled = summarize_auto_assembled_knowledge_base(
        raw_all, owner=owner, document_records=document_records
    )

    return KnowledgeBaseInventoryResponse(
        owner=inventory["owner"],
        total_chunks=inventory["total_chunks"],
        source_document_count=inventory["source_document_count"],
        domain_distribution=[
            KnowledgeBaseDomainCount(**d) for d in inventory["domain_distribution"]
        ],
        last_indexed_at=inventory["last_indexed_at"],
        doc_type=inventory["doc_type"],
        auto_assembled=AutoAssembledSummary(
            manual_qa_count=auto_assembled["manual_qa_count"],
            setting_item_count=auto_assembled["setting_item_count"],
            writable_setting_item_count=auto_assembled["writable_setting_item_count"],
            setting_items=[
                AutoAssembledSettingItem(**s) for s in auto_assembled["setting_items"]
            ],
            screen_node_count=auto_assembled["screen_node_count"],
        ),
    )


@router.get(
    "/catalog-config/export", response_model=CatalogConfigExportResponse,
    summary="카탈로그/Screen Graph 설정 내보내기 (Epic 2 Story 2.4)",
)
def export_catalog_config() -> CatalogConfigExportResponse:
    """
    현재 활성 카탈로그/Screen Graph 설정을 그대로 재업로드 가능한 원본 JSON으로 내보낸다.

    위 `/catalog`, `/screen-graph`는 AI/유저가 참고하는 **읽기 전용 요약 뷰**이고, 이
    엔드포인트는 **그대로 편집해서 재업로드할 수 있는 원본 포맷**이라는 점에서 목적이 다르다
    (Story 2.5의 import가 이 포맷을 그대로 입력으로 받는다).

    DB(Story 2.1)에 활성 버전이 있으면 그 값을 그대로 반환하고(`*_source="db"`), 아직 한 번도
    마이그레이션되지 않았다면 현재 코드에 하드코딩된 값을 즉석에서 직렬화해 반환한다
    (`*_source="static_fallback"`) — 어느 경우든 다운로드 자체는 항상 성공한다.

    보안: 함수 화이트리스트 이름(get_fn_ref/update_fn_ref) **문자열만** 포함되며, 실제 Python
    콜러블 참조는 절대 포함되지 않는다(RCE 방지 — Epic 2 아키텍처 §핵심 설계 결정 참고).
    """
    from datetime import datetime, timezone

    from src.ai_voicebot.self_service import screen_graph, settings_catalog
    from src.common import self_service_catalog_config_db as config_db

    catalog_active = config_db.get_active_config(config_db.CATALOG_KIND)
    if catalog_active is not None:
        catalog_json = catalog_active["config_json"]
        catalog_version: Optional[int] = catalog_active["version_no"]
        catalog_source = "db"
    else:
        catalog_json = settings_catalog.export_static_snapshot()
        catalog_version = None
        catalog_source = "static_fallback"

    screen_graph_active = config_db.get_active_config(config_db.SCREEN_GRAPH_KIND)
    if screen_graph_active is not None:
        screen_graph_json = screen_graph_active["config_json"]
        screen_graph_version: Optional[int] = screen_graph_active["version_no"]
        screen_graph_source = "db"
    else:
        screen_graph_json = screen_graph.export_static_snapshot()
        screen_graph_version = None
        screen_graph_source = "static_fallback"

    return CatalogConfigExportResponse(
        catalog=catalog_json,
        catalog_version=catalog_version,
        catalog_source=catalog_source,
        screen_graph=screen_graph_json,
        screen_graph_version=screen_graph_version,
        screen_graph_source=screen_graph_source,
        exported_at=datetime.now(timezone.utc).isoformat(),
    )


@router.post(
    "/catalog-config/import", response_model=CatalogConfigImportResponse,
    summary="카탈로그/Screen Graph 설정 업로드(검증+미리보기) (Epic 2 Story 2.5)",
)
def import_catalog_config(payload: CatalogConfigImportRequest) -> CatalogConfigImportResponse:
    """
    업로드된 설정을 검증하고, 통과하면 새 **비활성** 버전으로 저장한 뒤 현재 활성 버전과의
    diff(미리보기)를 반환한다. 실제 반영은 이 호출만으로는 일어나지 않으며, 반드시
    `/catalog-config/activate`를 별도로 호출해야 확정 적용된다(2단계 흐름 — AC1).

    **원자성(IV1, 보안 핵심)**: 카탈로그·Screen Graph 둘 중 하나라도 검증에 실패하면 어느 쪽도
    저장하지 않는다(둘 다 통과해야만 둘 다 저장). 화이트리스트에 없는 함수명을 참조하는 설정을
    업로드해도 실제 카탈로그 동작은 전혀 바뀌지 않는다.
    """
    from src.ai_voicebot.self_service import catalog_config_loader, settings_catalog
    from src.common import self_service_catalog_config_db as config_db

    catalog_errors = catalog_config_loader.validate_config(
        config_db.CATALOG_KIND, payload.catalog,
        get_fn_names=settings_catalog.get_fn_whitelist_names(),
        update_fn_names=settings_catalog.update_fn_whitelist_names(),
    )
    screen_graph_errors = catalog_config_loader.validate_config(config_db.SCREEN_GRAPH_KIND, payload.screen_graph)

    if catalog_errors or screen_graph_errors:
        return CatalogConfigImportResponse(
            ok=False, catalog_errors=catalog_errors, screen_graph_errors=screen_graph_errors,
        )

    catalog_active = config_db.get_active_config(config_db.CATALOG_KIND)
    screen_graph_active = config_db.get_active_config(config_db.SCREEN_GRAPH_KIND)
    catalog_diff = catalog_config_loader.diff_configs(
        config_db.CATALOG_KIND,
        catalog_active["config_json"] if catalog_active else None,
        payload.catalog,
    )
    screen_graph_diff = catalog_config_loader.diff_configs(
        config_db.SCREEN_GRAPH_KIND,
        screen_graph_active["config_json"] if screen_graph_active else None,
        payload.screen_graph,
    )

    catalog_version = config_db.save_new_version(
        config_db.CATALOG_KIND, payload.catalog, uploaded_by=payload.uploaded_by, note=payload.note,
    )
    screen_graph_version = config_db.save_new_version(
        config_db.SCREEN_GRAPH_KIND, payload.screen_graph, uploaded_by=payload.uploaded_by, note=payload.note,
    )
    if catalog_version is None or screen_graph_version is None:
        raise HTTPException(status_code=500, detail="설정 저장에 실패했습니다. 서버 로그를 확인하세요.")

    return CatalogConfigImportResponse(
        ok=True,
        catalog_version=catalog_version,
        screen_graph_version=screen_graph_version,
        catalog_diff=CatalogConfigDiff(**catalog_diff),
        screen_graph_diff=CatalogConfigDiff(**screen_graph_diff),
    )


@router.post(
    "/catalog-config/activate", response_model=CatalogConfigActivateResponse,
    summary="카탈로그/Screen Graph 설정 버전 활성화(적용/롤백 겸용) (Epic 2 Story 2.5)",
)
def activate_catalog_config(payload: CatalogConfigActivateRequest) -> CatalogConfigActivateResponse:
    """
    지정한 버전을 활성화한다 — 신규 업로드를 확정 적용하는 경우와 과거 버전으로 롤백하는
    경우 모두 이 엔드포인트 하나로 처리한다(`activate_version()`이 원래 이 두 용도를 겸하도록
    설계됨, Story 2.1). 활성화 즉시 다음 대화부터 반영되며 서버 재시작이 필요 없다(FR20 —
    `catalog_config_loader.get_cached_config()`가 활성 버전 번호 변경을 자동 감지해 캐시를
    갱신하므로 별도 무효화 호출이 없어도 즉시 반영된다).
    """
    from src.common import self_service_catalog_config_db as config_db

    if payload.config_kind not in (config_db.CATALOG_KIND, config_db.SCREEN_GRAPH_KIND):
        return CatalogConfigActivateResponse(
            ok=False, config_kind=payload.config_kind, version_no=payload.version_no,
            error=f"알 수 없는 config_kind입니다: {payload.config_kind}",
        )

    ok = config_db.activate_version(payload.config_kind, payload.version_no, activated_by=payload.activated_by)
    return CatalogConfigActivateResponse(
        ok=ok, config_kind=payload.config_kind, version_no=payload.version_no,
        error=None if ok else f"버전을 찾을 수 없거나 활성화에 실패했습니다: v{payload.version_no}",
    )


@router.get(
    "/catalog-config/versions", response_model=CatalogConfigVersionsResponse,
    summary="카탈로그/Screen Graph 설정 버전 이력 (Epic 2 Story 2.5)",
)
def get_catalog_config_versions(
    config_kind: str = Query(..., description="'catalog' 또는 'screen_graph'"),
    limit: int = Query(20, ge=1, le=100),
) -> CatalogConfigVersionsResponse:
    """지정 config_kind의 버전 이력을 최신순으로 반환한다. `is_active`인 항목이 현재 적용 버전이다."""
    from src.common import self_service_catalog_config_db as config_db

    if config_kind not in (config_db.CATALOG_KIND, config_db.SCREEN_GRAPH_KIND):
        raise HTTPException(status_code=400, detail=f"알 수 없는 config_kind입니다: {config_kind}")

    rows = config_db.list_versions(config_kind, limit=limit)
    versions = [
        CatalogConfigVersionItem(
            version_no=r["version_no"],
            is_active=r["is_active"],
            uploaded_by=r.get("uploaded_by", ""),
            note=r.get("note", ""),
            created_at=r.get("created_at", ""),
            activated_at=r.get("activated_at"),
            activated_by=r.get("activated_by", ""),
        )
        for r in rows
    ]
    return CatalogConfigVersionsResponse(config_kind=config_kind, versions=versions)

