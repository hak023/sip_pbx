"""셀프콜/셀프문자(셀프서비스) 판별 순수 함수.

설계: docs/architecture/self-service-ai-assistant-architecture.md
      §Enhancement Scope and Integration Strategy — "PRD 가정 정정"

판별 규칙:
  발신측(caller_number)과 착신측(owner)을 각각
  ``src.common.sip_owner.normalize_owner_username()``으로 정규화한 뒤 값이
  동일하면 "본인이 자기 자신에게 연락"한 것으로 간주한다(셀프서비스 세션).

  normalize_owner_username()은 이미 sip_message_ai_reply.py 등에서 owner
  정규화에 쓰이는 기존 유틸리티를 그대로 재사용한다(신규 의존성 없음).

킬스위치:
  환경변수 ``SELF_SERVICE_ENABLED``(기본값 "1")가 "0"/"false"/"no"/"off"이면
  다른 조건과 무관하게 항상 False를 반환한다. 배포 후 문제가 발생해도 코드
  롤백 없이 즉시 기능을 끌 수 있어야 한다는 PO 검증(po-master-checklist
  §7 Risk Management) Must-fix 사항을 반영한다.
"""

from __future__ import annotations

import os

from src.common.sip_owner import normalize_owner_username


def self_service_enabled() -> bool:
    """긴급 킬스위치. 기본 on — 0/false/no/off 이면 비활성."""
    raw = (os.environ.get("SELF_SERVICE_ENABLED") or "1").strip().lower()
    return raw not in ("0", "false", "no", "off")


def is_self_service_session(caller_number: str, owner: str) -> bool:
    """발신측·착신측이 동일 테넌트로 정규화되면 True(셀프서비스 세션).

    Args:
        caller_number: 발신측 식별자(전화번호, SIP URI, 순수 내선 등).
        owner: 착신측 테넌트 식별자(kb_owner/_persona_owner).

    Returns:
        둘 다 비어있지 않고 정규화 후 동일하면 True. 그 외(빈 값 포함,
        킬스위치 비활성 포함)는 False.
    """
    if not self_service_enabled():
        return False

    normalized_caller = normalize_owner_username(caller_number)
    normalized_owner = normalize_owner_username(owner)

    if not normalized_caller or not normalized_owner:
        return False

    return normalized_caller == normalized_owner
