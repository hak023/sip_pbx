"""
셀프서비스 자동설정(쓰기) 오케스트레이션 (Story 1.8).

`settings_catalog.call_update_fn()`으로 실제 변경을 위임하되, 그 전에 반드시:
  1. 제외 목록(`config/self_service_exclusions.yaml`) 확인 — 하드 코드 게이트.
     대화 흐름·프롬프트 지시와 무관하게 항상 적용된다(IV2 — 프롬프트 인젝션으로도
     우회 불가. LLM이 무엇을 호출하려 하든 이 함수가 실제 변경 이전에 항상 재검사한다).
  2. 성공 시 이중 기록: `call_data_record` JSONL + `self_service_config_changes` 테이블(AC4).

카탈로그(`settings_catalog.py`)는 순수 조회/디스패치만 하므로(Story 1.4/1.5 설계 원칙),
제외 목록 판단과 감사 로깅 같은 부작용은 이 모듈이 전담한다.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, Optional

import structlog

from src.ai_voicebot.self_service import settings_catalog

logger = structlog.get_logger(__name__)

_EXCLUSIONS_PATH = Path(__file__).resolve().parents[3] / "config" / "self_service_exclusions.yaml"
_exclusions_cache: Optional[Dict[str, Any]] = None


def _load_exclusions() -> Dict[str, Any]:
    global _exclusions_cache
    if _exclusions_cache is not None:
        return _exclusions_cache
    try:
        import yaml

        with open(_EXCLUSIONS_PATH, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}
    except Exception as e:
        logger.warning("self_service_exclusions_load_failed", path=str(_EXCLUSIONS_PATH), error=str(e))
        data = {}
    _exclusions_cache = data.get("excluded") or {}
    return _exclusions_cache


def reset_exclusions_cache() -> None:
    """테스트 전용: 캐시된 제외 목록을 초기화한다."""
    global _exclusions_cache
    _exclusions_cache = None


def is_field_excluded(domain: str, field: str) -> Optional[str]:
    """제외 대상이면 사유 문자열을, 아니면 None을 반환한다."""
    excl = _load_exclusions().get(domain)
    if not excl:
        return None
    fields = excl.get("fields") or []
    if "*" in fields or field in fields:
        return excl.get("reason") or "정책상 자동설정이 제한된 항목입니다."
    return None


async def apply_self_service_setting(
    domain: str, owner: str, field: str, value: Any, call_id: str = "",
) -> Dict[str, Any]:
    """제외 목록 확인 → `settings_catalog.call_update_fn()` 위임 → 성공 시 이중 감사 기록.

    Returns:
        {"ok": bool, "excluded": bool(선택), "old_value", "new_value", "error"(실패 시)}
    """
    excluded_reason = is_field_excluded(domain, field)
    if excluded_reason:
        logger.info(
            "self_service_auto_config_rejected",
            domain=domain, owner=owner, field=field, call_id=call_id, reason=excluded_reason,
        )
        if call_id:
            from src.common.call_data_record_logger import log_call_data
            log_call_data(
                call_id, "self_service", "self_service_auto_config_rejected",
                domain=domain, field=field, reason=excluded_reason,
            )
        return {"ok": False, "excluded": True, "error": excluded_reason}

    result = await settings_catalog.call_update_fn(domain, owner, field, value)
    ok = bool(result.get("ok"))
    if ok:
        old_value = result.get("old_value")
        from src.common.call_data_record_logger import log_call_data
        from src.common.self_service_config_change_db import record_config_change

        if call_id:
            log_call_data(
                call_id, "self_service", "self_service_auto_config_applied",
                domain=domain, field=field, old_value=str(old_value), new_value=str(value),
            )
        record_config_change(
            owner=owner, domain=domain, field=field,
            old_value=old_value, new_value=value, call_id=call_id,
        )
        logger.info(
            "self_service_auto_config_applied",
            domain=domain, owner=owner, field=field, call_id=call_id,
        )
    else:
        logger.warning(
            "self_service_auto_config_failed",
            domain=domain, owner=owner, field=field, call_id=call_id, error=result.get("error"),
        )
    return result
