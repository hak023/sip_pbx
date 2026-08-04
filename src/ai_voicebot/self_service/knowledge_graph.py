"""경량 지식 그래프 — 노드/엣지 타입 레지스트리 기반 n-hop 순회 (Story 1.18 축 B → Story 1.28 일반화).

설계 근거: docs/architecture/self-service-ai-assistant-architecture.md §RAG·IntelliDecision 고도화
           → Story 1.28, docs/design/SELF_SERVICE_RAG_INTELLIDECISION_ADVANCEMENT_RESEARCH.md §5.1

Story 1.18은 `traverse(domain)`을 아래 고정 2단 체인으로 하드코딩했다:

    manual_qa --relates_to--> catalog_domain --rendered_by--> frontend_screen   (1-hop)
    catalog_domain --writable--> intellidecision_type                          (2-hop)

Story 1.28은 이 고정 체인을 **노드 타입/엣지 타입 등록 테이블**로 일반화한다 — 신규 지식 유형
(업로드 문서 `document`, API 엔드포인트 `api_endpoint`, 절차 단계 `procedure_step`)이 늘어나도
그래프 순회 엔진(`traverse_graph()`) 자체는 다시 작성하지 않고, `register_edge_type()` 호출만
추가하면 확장되도록 한다.

⚠️ 회귀 없음 원칙: 기존 공개 API `traverse(domain, *, max_hops=2)`/`format_decision_hint(domain)`은
내부적으로 `traverse_graph()`를 사용하도록 재작성했을 뿐, 반환 값의 형태·내용은 리팩터링 전과
1바이트도 다르지 않다(직접 비교 테스트로 검증, Story 1.25/2.3과 동일한 회귀 검증 패턴).

Non-Goal: Full GraphRAG 수준의 자동 엔터티 추출·Leiden 클러스터링은 다루지 않는다 — 그래프 DB
없이 파이썬 dict 기반 정적 순회로 충분한 소규모 명시적 스키마를 유지한다.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Dict, List, Optional, Tuple

import structlog

from src.ai_voicebot.self_service import intellidecision_policy, settings_catalog
from src.ai_voicebot.self_service.screen_graph import ScreenEntry, get_screen_for_domain

logger = structlog.get_logger(__name__)

# 엣지 리졸버 시그니처: (source_node_id, owner) -> [(target_node_type, target_node_id, data), ...]
EdgeResolver = Callable[[Any, Optional[str]], List[Tuple[str, Any, Any]]]


@dataclass
class NodeTypeSpec:
    """노드 타입 메타데이터(순수 등록 정보, 실제 인스턴스 저장소는 각 도메인 모듈이 소유)."""

    type_id: str
    description: str


@dataclass
class EdgeTypeSpec:
    """엣지 타입 메타데이터 + 실제 순회에 쓰이는 리졸버."""

    type_id: str
    description: str
    source_type: str
    target_type: str
    resolver: EdgeResolver


_NODE_TYPES: Dict[str, NodeTypeSpec] = {}
_EDGE_TYPES: Dict[str, EdgeTypeSpec] = {}
# (source_node_type, edge_type) -> EdgeTypeSpec — traverse_graph()가 hop마다 조회하는 실제 인덱스
_EDGE_INDEX: Dict[Tuple[str, str], EdgeTypeSpec] = {}


def register_node_type(type_id: str, description: str) -> None:
    _NODE_TYPES[type_id] = NodeTypeSpec(type_id=type_id, description=description)


def register_edge_type(
    type_id: str, description: str, *, source_type: str, target_type: str, resolver: EdgeResolver,
) -> None:
    spec = EdgeTypeSpec(
        type_id=type_id, description=description,
        source_type=source_type, target_type=target_type, resolver=resolver,
    )
    _EDGE_TYPES[type_id] = spec
    _EDGE_INDEX[(source_type, type_id)] = spec


def list_node_types() -> List[NodeTypeSpec]:
    return list(_NODE_TYPES.values())


def list_edge_types() -> List[EdgeTypeSpec]:
    return list(_EDGE_TYPES.values())


def traverse_graph(
    start_type: str, start_id: Any, *, max_hops: int = 2, owner: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """등록된 노드/엣지 타입 테이블을 실제로 순회하는 범용 n-hop 그래프 탐색(AC3).

    `max_hops`를 3~4단계로 늘려도 신규 엣지 타입만 등록하면 코드 수정 없이 동작한다 — 어떤
    소스 노드 타입에 등록된 엣지든 자동으로 탐색 대상이 된다(하드코딩된 호출 순서 없음).

    Returns:
        [{"hop": int, "edge_type": str, "source_type": str, "source_id": Any,
          "target_type": str, "target_id": Any, "data": Any}, ...]
        개별 리졸버 실패는 해당 엣지만 건너뛴다(best-effort, 전체 순회를 중단하지 않음).
    """
    edges: List[Dict[str, Any]] = []
    frontier: List[Tuple[str, Any]] = [(start_type, start_id)]
    visited: set[Tuple[str, Any]] = {(start_type, start_id)}

    for hop in range(1, max_hops + 1):
        next_frontier: List[Tuple[str, Any]] = []
        for node_type, node_id in frontier:
            for (src_type, edge_type), spec in _EDGE_INDEX.items():
                if src_type != node_type:
                    continue
                try:
                    targets = spec.resolver(node_id, owner)
                except Exception as e:
                    logger.warning(
                        "knowledge_graph_edge_resolver_failed",
                        edge_type=edge_type, source_type=node_type, source_id=node_id, error=str(e),
                    )
                    continue
                for target_type, target_id, data in targets or []:
                    edges.append({
                        "hop": hop, "edge_type": edge_type,
                        "source_type": node_type, "source_id": node_id,
                        "target_type": target_type, "target_id": target_id, "data": data,
                    })
                    key = (target_type, target_id)
                    if key not in visited:
                        visited.add(key)
                        next_frontier.append(key)
        frontier = next_frontier
        if not frontier:
            break

    return edges


# ---------------------------------------------------------------------------
# 노드 타입 등록 — 기존 4종(Story 1.18) + 신규 3종 예약(Story 1.28, AC1)
# ---------------------------------------------------------------------------
register_node_type("manual_qa", "셀프서비스 매뉴얼 Q&A 청크(ChromaDB, self_service_manual)")
register_node_type("catalog_domain", "설정 카탈로그 도메인(settings_catalog.py)")
register_node_type("frontend_screen", "프론트엔드 화면 안내(screen_graph.py)")
register_node_type("intent_type", "IntelliDecision 유형 A~I(intellidecision_policy.py)")
register_node_type("document", "업로드 지식 문서(Story 1.26, knowledge_documents_db.py)")
register_node_type("api_endpoint", "OpenAPI 스펙 엔드포인트(Story 1.26, OpenApiSpecAdapter)")
register_node_type("procedure_step", "다단계 절차 단위(예약, 실제 데이터 소스는 후속 Story)")


# ---------------------------------------------------------------------------
# 엣지 타입 등록 — 기존 2종(Story 1.18) + 신규 3종(Story 1.28, AC2)
# ---------------------------------------------------------------------------
def _resolve_rendered_by(domain: Any, _owner: Optional[str]) -> List[Tuple[str, Any, Any]]:
    screen = get_screen_for_domain(str(domain))
    if screen is None:
        return []
    return [("frontend_screen", screen.route, screen)]


def _resolve_writable(domain: Any, _owner: Optional[str]) -> List[Tuple[str, Any, Any]]:
    writable = bool(settings_catalog.domain_writable_fields(str(domain)))
    specs = intellidecision_policy.applicable_types_for_domain(str(domain), writable=writable)
    return [("intent_type", spec.code, {"spec": spec, "writable": writable}) for spec in specs]


def _resolve_documents_for_domain(domain: Any, owner: Optional[str]) -> List[Tuple[str, Any, Any]]:
    """catalog_domain --relates_to--> document(Story 1.26 업로드 문서, domain_tags 매칭).

    owner가 없으면(예: 로그인 컨텍스트 밖 조회) 빈 목록을 반환한다 — 문서는 owner 스코프
    테넌트 격리 대상이므로, owner 없이는 어떤 문서도 노출하지 않는다(NFR2).
    """
    if not owner:
        return []
    try:
        from src.common import knowledge_documents_db
    except Exception:
        return []
    try:
        items = knowledge_documents_db.list_documents(owner=owner, domain_tag=str(domain))
    except Exception as e:
        logger.warning("knowledge_graph_documents_edge_failed", domain=domain, owner=owner, error=str(e))
        return []
    return [("document", it.get("document_id"), it) for it in items]


def _resolve_depends_on(_step_id: Any, _owner: Optional[str]) -> List[Tuple[str, Any, Any]]:
    """procedure_step --depends_on--> procedure_step(예약, AC2) — 실제 절차 데이터 소스는 후속 Story."""
    return []


def _resolve_api_endpoint_documents(_endpoint_id: Any, _owner: Optional[str]) -> List[Tuple[str, Any, Any]]:
    """api_endpoint --documents--> document(예약, AC2) — OpenAPI 엔드포인트 노드 소스는 후속 Story."""
    return []


register_edge_type(
    "rendered_by", "catalog_domain -> frontend_screen(1-hop, 화면 안내)",
    source_type="catalog_domain", target_type="frontend_screen", resolver=_resolve_rendered_by,
)
register_edge_type(
    "writable", "catalog_domain -> intent_type(2-hop, 적용 가능한 IntelliDecision 유형)",
    source_type="catalog_domain", target_type="intent_type", resolver=_resolve_writable,
)
register_edge_type(
    "relates_to", "catalog_domain -> document(Story 1.26 업로드 문서, domain_tags 매칭)",
    source_type="catalog_domain", target_type="document", resolver=_resolve_documents_for_domain,
)
register_edge_type(
    "depends_on", "procedure_step -> procedure_step(예약, 절차 단계 순서)",
    source_type="procedure_step", target_type="procedure_step", resolver=_resolve_depends_on,
)
register_edge_type(
    "documents", "api_endpoint -> document(예약, API 문서 ↔ Tool/엔드포인트 매핑)",
    source_type="api_endpoint", target_type="document", resolver=_resolve_api_endpoint_documents,
)


def traverse(domain: str, *, max_hops: int = 2) -> Dict[str, Any]:
    """도메인 하나에서 시작해 관련 지식을 다중 홉으로 수집한다.

    Returns:
        {
          "domain": str,
          "screen": ScreenEntry | None,        # 1-hop: catalog_domain -> frontend_screen
          "writable": bool,                    # 2-hop 판단 근거: 쓰기 가능한 필드가 있는가
          "applicable_intent_types": [IntentTypeSpec, ...],  # 2-hop: writable -> 적용 가능 유형
        }
    best-effort — 개별 조회 실패 시 해당 필드만 빈 값으로 채운다(전체 실패시키지 않음).

    ⚠️ 내부적으로 `traverse_graph()`(등록 테이블 기반 범용 순회)를 사용하도록 재작성됐다
    (Story 1.28). 반환 값의 형태·내용은 Story 1.18 구현과 1바이트도 다르지 않다(AC5).
    """
    result: Dict[str, Any] = {
        "domain": domain, "screen": None, "writable": False, "applicable_intent_types": [],
    }

    edges = traverse_graph("catalog_domain", domain, max_hops=max_hops)

    for e in edges:
        if e["edge_type"] == "rendered_by":
            result["screen"] = e["data"]
            break

    if max_hops < 2:
        return result

    try:
        result["writable"] = bool(settings_catalog.domain_writable_fields(domain))
    except Exception as e:
        logger.warning("knowledge_graph_traverse_writable_failed", domain=domain, error=str(e))

    result["applicable_intent_types"] = [
        e["data"]["spec"] for e in edges if e["edge_type"] == "writable"
    ]

    return result


def format_decision_hint(domain: str) -> str:
    """`traverse()` 결과를 시스템 프롬프트에 주입할 한 줄짜리 한국어 힌트로 조립한다.

    화면 안내 문구(`describe_screen_for_conversation`, 1-hop)와 별도로, 이 도메인에서
    실제로 성립 가능한 IntelliDecision 유형(쓰기 가능 여부 기반)을 LLM에 명시적으로 알려줘
    "이 도메인은 조회만 가능하다/변경·되돌리기까지 가능하다"를 프롬프트 산문 판단에만
    맡기지 않고 데이터로 뒷받침한다.

    반환 예: "(참고: 이 설정은 조회만 가능하며 변경·되돌리기는 지원되지 않습니다)"
             "(참고: 이 설정은 조회·변경·되돌리기가 모두 가능합니다)"
    빈 문자열이면(도메인 미등록 등) 호출측에서 무시한다.
    """
    try:
        info = traverse(domain, max_hops=2)
        if info.get("screen") is None:
            return ""
        if info["writable"]:
            return "(참고: 이 설정은 조회·변경·되돌리기가 모두 가능합니다)"
        return "(참고: 이 설정은 조회만 가능하며 변경·되돌리기는 지원되지 않습니다)"
    except Exception as e:
        logger.warning("knowledge_graph_format_decision_hint_failed", domain=domain, error=str(e))
        return ""

