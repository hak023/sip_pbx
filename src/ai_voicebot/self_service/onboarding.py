"""
셀프서비스 온보딩 체크리스트 판정 로직 (Story 1.5).

설정 카탈로그(Story 1.4, `settings_catalog.get_domain_value()`)의 조회 결과만
사용해 "아직 하지 않은 초기 설정"을 판별한다. 완료 여부를 별도 DB/캐시에 저장하지
않는다 — 항상 카탈로그를 통해 실시간으로 다시 계산한다(IV1, 단일 진실 소스 원칙).

판정 대상은 매뉴얼(`docs/product/self-service-manual-content.md` §2 초기 설정
체크리스트)의 **필수** 항목만 다룬다. 다음은 의도적으로 제외한다:
  - 예약 도메인/슬롯 설정 — 설정 카탈로그(Story 1.4)에 `booking` 도메인이 아직
    없음(업종에 따라 선택적이라 카탈로그 범위 밖으로 남겨둠).
  - 채팅 자동응답(chat-relay), Google 캘린더 연동(integrations) — 매뉴얼에서
    "문자 문의도 받는다면"/"필요하다면"으로 명시된 선택 항목이라 미완료로 취급하지 않음.

신규 필수 온보딩 항목을 추가하려면 `_CHECKS`에 (domain, 판정 함수, 안내 문구)를
추가한다. 판정 함수는 `settings_catalog.get_domain_value()`가 반환한 dict만
검사해야 하며, 새로운 저장소나 캐시를 만들어서는 안 된다.
"""

from __future__ import annotations

from typing import Any, Callable, Dict, List, Tuple

import structlog

from src.ai_voicebot.self_service import settings_catalog

logger = structlog.get_logger(__name__)


def _persona_incomplete(value: Dict[str, Any]) -> bool:
    """페르소나(조직 소개)가 아예 없거나 이름·설명이 비어 있으면 미완료."""
    if value.get("error"):
        return False  # 조회 실패는 미완료로 오판하지 않음(안전측: 침묵)
    if not value.get("exists", True):
        return True
    return not (value.get("name") or "").strip() and not (value.get("description") or "").strip()


def _ai_escalation_incomplete(value: Dict[str, Any]) -> bool:
    """persona 자체가 없으면 escalation_mode="hitl"은 코드 기본값일 뿐 관리자가
    의식적으로 선택한 값이 아니므로 미결정으로 간주한다."""
    if value.get("error"):
        return False
    return not value.get("persona_exists", True)


def _call_control_incomplete(value: Dict[str, Any]) -> bool:
    """착신 규칙이 하나도 없으면 미완료."""
    if value.get("error"):
        return False
    return not value.get("rules")


_CHECKS: List[Tuple[str, Callable[[Dict[str, Any]], bool], str]] = [
    (
        "persona",
        _persona_incomplete,
        "아직 서비스 소개(페르소나)가 등록되지 않았어요. 조직 이름과 설명을 알려주시면 등록해 드릴게요.",
    ),
    (
        "ai-escalation",
        _ai_escalation_incomplete,
        "AI가 모르는 질문을 받았을 때 어떻게 처리할지(운영자 알림/상담원 연결/미사용)를 아직 정하지 않았어요.",
    ),
    (
        "call-control",
        _call_control_incomplete,
        "착신 규칙이 하나도 없어요. 전화를 어떻게 받을지 규칙을 최소 1개 만들어야 정상적으로 응대할 수 있어요.",
    ),
]


async def get_onboarding_checklist(owner: str) -> List[Dict[str, str]]:
    """미완료 초기 설정 항목 목록을 반환한다. 모두 완료면 빈 리스트(AC3)."""
    incomplete: List[Dict[str, str]] = []
    for domain, check_fn, message in _CHECKS:
        value = await settings_catalog.get_domain_value(domain, owner)
        try:
            if check_fn(value):
                incomplete.append({"domain": domain, "message": message})
        except Exception as e:
            logger.warning(
                "onboarding_checklist_check_error", domain=domain, owner=owner, error=str(e),
            )
    return incomplete
