"""경량 지식 그래프 — Screen Graph 다중 홉 확장 (Story 1.18, 축 B).

설계 근거: docs/design/SELF_SERVICE_INTELLIDECISION_KNOWLEDGE_STRUCTURING_RESEARCH.md §4 축 B

기존 `self_service_agent.py::_format_screen_guidance()`는 RAG 히트의 `related_domain`
메타데이터로 `screen_graph`를 1-hop만 조회했다(GraphRAG "Local Search" 정신의 일부만 구현).
이 모듈은 동일 철학(그래프 DB 불필요, 파이썬 dict 기반 정적 순회로 충분한 규모)을 유지한 채
순회를 2-hop으로 확장한다:

    manual_qa --relates_to--> catalog_domain --rendered_by--> frontend_screen   (기존 1-hop)
    catalog_domain --writable--> intellidecision_type (B/D/E/G 중 실제 적용 가능한 유형)  (신규 2-hop)

**핵심 목적(사용자 요청 반영)**: 단순히 화면 정보만 보여주는 데 그치지 않고, 이 2-hop이
"이 도메인에서 실제로 어떤 IntelliDecision 유형이 성립 가능한가"까지 시스템 프롬프트에
명시적으로 드러내(Anthropic "투명성" 원칙) LLM이 더 스마트하게 판단하도록 돕는다 — 예를 들어
쓰기 불가능한 도메인(`contacts`, `general` 등 update_fn 미등록)에서는 유형 E(실행 취소)/B(실행)
가능성을 애초에 프롬프트에서 배제해, LLM이 존재하지 않는 변경 능력을 안내하는 환각을 구조적으로
줄인다.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

import structlog

from src.ai_voicebot.self_service import intellidecision_policy, settings_catalog
from src.ai_voicebot.self_service.screen_graph import ScreenEntry, get_screen_for_domain

logger = structlog.get_logger(__name__)


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
    """
    result: Dict[str, Any] = {
        "domain": domain, "screen": None, "writable": False, "applicable_intent_types": [],
    }

    try:
        result["screen"] = get_screen_for_domain(domain)
    except Exception as e:
        logger.warning("knowledge_graph_traverse_screen_failed", domain=domain, error=str(e))

    if max_hops < 2:
        return result

    try:
        result["writable"] = bool(settings_catalog.domain_writable_fields(domain))
    except Exception as e:
        logger.warning("knowledge_graph_traverse_writable_failed", domain=domain, error=str(e))

    try:
        result["applicable_intent_types"] = intellidecision_policy.applicable_types_for_domain(
            domain, writable=result["writable"],
        )
    except Exception as e:
        logger.warning("knowledge_graph_traverse_intent_types_failed", domain=domain, error=str(e))

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
