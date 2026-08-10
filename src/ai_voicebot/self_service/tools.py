"""
셀프서비스 AI 도우미 LangChain Tool 정의 (Story 1.5, 1.6, 1.7, 1.8).

`src/ai_voicebot/langgraph/tools/booking_tools.py::_make_tool` 패턴을 재사용한다
(langchain_core 미설치 환경에서도 import가 깨지지 않도록 원본 함수를 그대로 반환).

도구 목록:
  - get_onboarding_checklist_tool : 아직 완료하지 않은 초기 설정 항목 조회
  - get_self_service_settings_tool: 카탈로그(Story 1.4)에 등록된 임의 도메인의 현재 설정값 조회
  - get_self_service_stats_tool   : 기간(이번 주/이번 달)별 이용 통계(통화 수·평균 confidence·HITL 건수) 조회
  - update_self_service_setting_tool: 설정 값을 실제로 변경(쓰기, 제외 목록/감사 로깅은 auto_config.py가 담당)
  - search_call_history_tool      : 통화 요약(call_summary) 키워드 검색(Story 1.13, FR15-1)
  - get_top_caller_tool           : 기간별(오늘/이번 주/이번 달) 최다 발신 번호 집계(Story 1.13, FR15-2)
  - get_missed_calls_today_tool   : 오늘자 미응답 번호 조회(Story 1.13, FR15-3)
  - get_last_self_service_change_tool  : 가장 최근 대화 설정 변경 내역 조회(Story 1.16, IntelliDecision 유형 E)
  - undo_last_self_service_change_tool : 가장 최근 변경을 이전 값으로 되돌리기(Story 1.16, IntelliDecision 유형 E)

SELF_SERVICE_TOOLS: self_service_agent_node가 `bind_tools()`에 그대로 넘기는 도구 목록.
"""

from __future__ import annotations

import json
from typing import Any

import structlog

from src.ai_voicebot.self_service import settings_catalog
from src.ai_voicebot.self_service.auto_config import apply_self_service_setting
from src.ai_voicebot.self_service.call_history_query import (
    get_missed_calls_today as _get_missed_calls_today_impl,
    get_top_caller as _get_top_caller_impl,
    search_call_history_by_keyword as _search_call_history_by_keyword_impl,
)
from src.ai_voicebot.self_service.onboarding import (
    get_onboarding_checklist as _get_onboarding_checklist_impl,
)
from src.ai_voicebot.self_service.stats import get_self_service_stats as _get_self_service_stats_impl

logger = structlog.get_logger(__name__)

try:
    from langchain_core.tools import tool as langchain_tool
    _LANGCHAIN_AVAILABLE = True
except ImportError:
    _LANGCHAIN_AVAILABLE = False
    logger.warning("langchain_core not installed — self_service tools disabled")
    langchain_tool = None  # type: ignore


def _make_tool(fn):
    """langchain_core가 없으면 원본 함수를 그대로 반환 (import 안전)."""
    if _LANGCHAIN_AVAILABLE and langchain_tool is not None:
        return langchain_tool(fn)
    return fn


# ──────────────────────────────────────────────────────────────────────────
# Tool: 온보딩 체크리스트 조회
# ──────────────────────────────────────────────────────────────────────────

async def _get_onboarding_checklist(owner: str) -> str:
    """
    아직 완료하지 않은 초기 설정 항목 목록을 조회합니다.

    Args:
        owner: 테넌트 ID (착신 SIP 내선번호)

    Returns:
        JSON 문자열: {"incomplete_count": N, "items": [{"domain": ..., "message": ...}, ...]}
    """
    try:
        items = await _get_onboarding_checklist_impl(owner)
        return json.dumps({"incomplete_count": len(items), "items": items}, ensure_ascii=False)
    except Exception as e:
        logger.error("self_service_tool_onboarding_checklist_error", owner=owner, error=str(e))
        return json.dumps({"error": f"체크리스트 조회 중 오류가 발생했습니다: {e}"}, ensure_ascii=False)


get_onboarding_checklist_tool = _make_tool(_get_onboarding_checklist)
get_onboarding_checklist_tool.__doc__ = _get_onboarding_checklist.__doc__


# ──────────────────────────────────────────────────────────────────────────
# Tool: 설정 도메인 현재 값 조회 (Story 1.6)
# ──────────────────────────────────────────────────────────────────────────

async def _get_self_service_settings(owner: str, domain: str) -> str:
    """
    지정한 설정 도메인의 현재 값을 조회합니다.

    Args:
        owner: 테넌트 ID (착신 SIP 내선번호)
        domain: 설정 도메인명 (persona, ai-escalation, call-control, chat-relay,
            contacts, general, integrations 중 하나)

    Returns:
        JSON 문자열: 도메인의 현재 설정 값. 등록되지 않은 도메인이면 안내 메시지와
        확인 가능한 도메인 목록을 반환합니다.
    """
    try:
        # IV1: settings_catalog.get_domain_value() 외 별도 조회 로직을 두지 않는다.
        value = await settings_catalog.get_domain_value(domain, owner)
        if isinstance(value, dict) and str(value.get("error", "")).startswith("unregistered_domain"):
            return json.dumps({
                "error": f"'{domain}' 항목은 확인해드릴 수 없어요.",
                "available_domains": settings_catalog.list_domains(owner),
            }, ensure_ascii=False)
        return json.dumps(value, ensure_ascii=False)
    except Exception as e:
        logger.error(
            "self_service_tool_get_settings_error", owner=owner, domain=domain, error=str(e),
        )
        return json.dumps({"error": f"설정 조회 중 오류가 발생했습니다: {e}"}, ensure_ascii=False)


get_self_service_settings_tool = _make_tool(_get_self_service_settings)
get_self_service_settings_tool.__doc__ = _get_self_service_settings.__doc__


# ──────────────────────────────────────────────────────────────────────────
# Tool: 이용 통계 조회 (Story 1.7)
# ──────────────────────────────────────────────────────────────────────────

async def _get_self_service_stats(owner: str, period: str) -> str:
    """
    기간별 이용 통계(통화 수, 평균 confidence, HITL 발생 건수)를 조회합니다.

    Args:
        owner: 테넌트 ID (착신 SIP 내선번호)
        period: 조회 기간 — "week"(이번 주) 또는 "month"(이번 달)만 지원합니다.
            그 외 값은 지원되지 않음 안내를 반환합니다(AC3).

    Returns:
        JSON 문자열: {"call_count", "ai_handled_count", "avg_confidence", "hitl_count", ...}
        또는 미지원 기간일 경우 안내 메시지.
    """
    try:
        # IV1: call_record_db/call_insights.json/call_data_record 로그 읽기 전용만 수행(쓰기 없음).
        result = await _get_self_service_stats_impl(owner, period)
        return json.dumps(result, ensure_ascii=False)
    except Exception as e:
        logger.error(
            "self_service_tool_get_stats_error", owner=owner, period=period, error=str(e),
        )
        return json.dumps({"error": f"통계 조회 중 오류가 발생했습니다: {e}"}, ensure_ascii=False)


get_self_service_stats_tool = _make_tool(_get_self_service_stats)
get_self_service_stats_tool.__doc__ = _get_self_service_stats.__doc__


# ──────────────────────────────────────────────────────────────────────────
# Tool: 설정 값 변경 — 쓰기 (Story 1.8)
# ──────────────────────────────────────────────────────────────────────────

# boolean으로 해석해야 하는 필드(LLM이 문자열 "true"/"예"/"1" 등으로 보낼 수 있음)
_BOOLEAN_FIELDS = frozenset({"enabled", "message_ai_reply_enabled"})
_TRUTHY = frozenset({"true", "1", "yes", "y", "on", "예", "네", "켜짐", "켜기"})


def _coerce_value(field: str, value: Any) -> Any:
    if field not in _BOOLEAN_FIELDS or isinstance(value, bool):
        return value
    return str(value).strip().lower() in _TRUTHY


def _build_writable_fields_hint() -> str:
    """도메인별 실제 writable 필드명(+ enum 필드는 허용값까지)을 도구 설명에 정적으로 명시한다.

    [2026-07-15 QA 자동 테스트에서 발견된 문제] LLM이 필드명을 추측해서 호출하다
    존재하지 않는 필드명(예: `auto_reply_enabled` — 실제로는 `message_ai_reply_enabled`)을
    보내 `field_not_writable` 오류로 거부되는 경우가 있었다. 보안상으로는 fail-safe로
    동작하지만(잘못된 필드는 거부), UX 개선을 위해 정확한 필드명을 도구 설명에 직접
    나열해 LLM이 추측하지 않도록 한다.

    [2026-07-16 QA(Story 1.10 실행성 케이스)에서 발견된 문제] 필드명은 정확했지만 값(예:
    `escalation_mode`)에 유효하지 않은 문자열("disabled")을 추측해서 써서, 실제 시스템
    분기(`hitl_alert.py`)와 매치되지 않는 무의미한 값이 저장되는 사고가 있었다. 필드명과
    동일한 이유로 **허용값도 도구 설명에 직접 나열**해 LLM이 값을 추측하지 않도록 한다.
    """
    lines = []
    for domain in settings_catalog.list_domains():
        fields = settings_catalog.domain_writable_fields(domain)
        if not fields:
            continue
        field_descs = []
        for f in sorted(fields):
            allowed = settings_catalog.get_field_allowed_values(domain, f)
            if allowed:
                field_descs.append(f"{f}(허용값: {', '.join(sorted(allowed))} 중 하나만 사용)")
            else:
                field_descs.append(f)
        lines.append(f"      - {domain}: {', '.join(field_descs)}")
    return "\n".join(lines)


async def _update_self_service_setting(
    owner: str, domain: str, field: str, value: Any, call_id: str = "",
) -> str:
    """
    설정 값을 실제로 변경합니다. **반드시 사용자에게 확인 발화를 거친 뒤에만** 호출하세요.

    Args:
        owner: 테넌트 ID (착신 SIP 내선번호)
        domain: 설정 도메인명
        field: 변경할 필드명. **아래 나열된 정확한 필드명만 사용하세요(추측 금지)**:
{writable_fields_hint}
        value: 새 값
        call_id: 통화 ID(감사 로깅용, 자동 주입됨)

    Returns:
        JSON 문자열: {{"ok": true, "old_value", "new_value"}} 또는
        {{"ok": false, "error", "excluded"(제외 목록 항목인 경우 true)}}
    """
    try:
        coerced = _coerce_value(field, value)
        result = await apply_self_service_setting(domain, owner, field, coerced, call_id)
        return json.dumps(result, ensure_ascii=False, default=str)
    except Exception as e:
        logger.error(
            "self_service_tool_update_setting_error",
            owner=owner, domain=domain, field=field, error=str(e),
        )
        return json.dumps({"ok": False, "error": f"설정 변경 중 오류가 발생했습니다: {e}"}, ensure_ascii=False)


# 실제 writable 필드명을 도구 설명(=Gemini/LangChain에 노출되는 schema description)에
# 정적으로 주입한다. 반드시 _make_tool() 호출보다 먼저 수행해야 한다 — langchain_core의
# @tool 데코레이터가 데코레이션 시점의 __doc__을 그대로 캡처하기 때문(사후에 .__doc__을
# 바꿔도 이미 생성된 StructuredTool.description에는 반영되지 않는다).
_update_self_service_setting.__doc__ = _update_self_service_setting.__doc__.format(
    writable_fields_hint=_build_writable_fields_hint()
)

update_self_service_setting_tool = _make_tool(_update_self_service_setting)
update_self_service_setting_tool.__doc__ = _update_self_service_setting.__doc__


# ───────────────────────────────────────────────────────────────────────────
# Tool: 통화 이력 자연어 질의 (Story 1.13)
# ───────────────────────────────────────────────────────────────────────────

async def _search_call_history(owner: str, keyword: str) -> str:
    """
    내(owner) 통화 이력 중 특정 키워드가 언급된 통화를 검색합니다.

    Args:
        owner: 테넌트 ID (착신 SIP 내선번호)
        keyword: 검색할 키워드(통화 요약에서 부분 문자열 일치 검색)

    Returns:
        JSON 문자열: {"match_count": N, "matches": [{"call_id", "caller_id", "start_time", "call_summary"}, ...]}
    """
    try:
        result = await _search_call_history_by_keyword_impl(owner, keyword)
        return json.dumps(result, ensure_ascii=False)
    except Exception as e:
        logger.error("self_service_tool_search_call_history_error", owner=owner, error=str(e))
        return json.dumps({"error": f"통화 이력 검색 중 오류가 발생했습니다: {e}"}, ensure_ascii=False)


search_call_history_tool = _make_tool(_search_call_history)
search_call_history_tool.__doc__ = _search_call_history.__doc__


async def _get_top_caller(owner: str, period: str) -> str:
    """
    기간 내 내(owner)에게 가장 많이 전화한 번호(들)을 집계합니다.

    Args:
        owner: 테넌트 ID (착신 SIP 내선번호)
        period: 조회 기간 — "today"(오늘), "week"(이번 주), "month"(이번 달)만 지원합니다.

    Returns:
        JSON 문자열: {"top_callers": [{"caller_id", "call_count"}, ...]} 또는 미지원 기간 안내 메시지.
    """
    try:
        result = await _get_top_caller_impl(owner, period)
        return json.dumps(result, ensure_ascii=False)
    except Exception as e:
        logger.error("self_service_tool_get_top_caller_error", owner=owner, period=period, error=str(e))
        return json.dumps({"error": f"발신 번호 집계 중 오류가 발생했습니다: {e}"}, ensure_ascii=False)


get_top_caller_tool = _make_tool(_get_top_caller)
get_top_caller_tool.__doc__ = _get_top_caller.__doc__


async def _get_missed_calls_today(owner: str) -> str:
    """
    오늘 내(owner)에게 걸려온 통화 중 응답(AI/사람 모두)되지 않은 통화를 조회합니다.

    Args:
        owner: 테넌트 ID (착신 SIP 내선번호)

    Returns:
        JSON 문자열: {"missed_count": N, "missed_calls": [{"call_id", "caller_id", "start_time"}, ...]}
    """
    try:
        result = await _get_missed_calls_today_impl(owner)
        return json.dumps(result, ensure_ascii=False)
    except Exception as e:
        logger.error("self_service_tool_get_missed_calls_today_error", owner=owner, error=str(e))
        return json.dumps({"error": f"미응답 통화 조회 중 오류가 발생했습니다: {e}"}, ensure_ascii=False)


get_missed_calls_today_tool = _make_tool(_get_missed_calls_today)
get_missed_calls_today_tool.__doc__ = _get_missed_calls_today.__doc__


# ───────────────────────────────────────────────────────────────────────────
# Tool: 실행 취소(Undo) — IntelliDecision 유형 E (Story 1.16)
# ───────────────────────────────────────────────────────────────────────────

async def _get_last_self_service_change(owner: str) -> str:
    """
    내(owner)가 가장 최근에 대화로 변경한 설정 1건을 조회합니다(되돌리기 전 확인용).

    Args:
        owner: 테넌트 ID (착신 SIP 내선번호)

    Returns:
        JSON 문자열: {"has_history": true, "domain", "field", "old_value", "new_value",
        "changed_at"} 또는 이력이 없으면 {"has_history": false}.
    """
    try:
        from src.common.self_service_config_change_db import list_config_changes

        changes = list_config_changes(owner, limit=1)
        if not changes:
            return json.dumps({"has_history": False}, ensure_ascii=False)
        last = changes[0]
        return json.dumps({
            "has_history": True,
            "domain": last.get("domain"),
            "field": last.get("field"),
            "old_value": last.get("old_value"),
            "new_value": last.get("new_value"),
            "changed_at": last.get("changed_at"),
        }, ensure_ascii=False)
    except Exception as e:
        logger.error("self_service_tool_get_last_change_error", owner=owner, error=str(e))
        return json.dumps({"error": f"최근 변경 내역 조회 중 오류가 발생했습니다: {e}"}, ensure_ascii=False)


get_last_self_service_change_tool = _make_tool(_get_last_self_service_change)
get_last_self_service_change_tool.__doc__ = _get_last_self_service_change.__doc__


async def _undo_last_self_service_change(owner: str, call_id: str = "") -> str:
    """
    내(owner)가 가장 최근에 대화로 변경한 설정 1건을 이전 값으로 되돌립니다.
    **반드시 get_last_self_service_change로 내역을 확인하고 사용자에게 확인 발화를
    거친 뒤에만** 호출하세요(되돌리기도 설정 변경이므로 유형 B와 동일한 확인 원칙).

    Args:
        owner: 테넌트 ID (착신 SIP 내선번호)
        call_id: 통화 ID(감사 로깅용, 자동 주입됨)

    Returns:
        JSON 문자열: {"ok": true, "domain", "field", "restored_value"} 또는
        {"ok": false, "error": "되돌릴 변경 내역이 없습니다."} 등.
    """
    try:
        from src.common.self_service_config_change_db import list_config_changes

        changes = list_config_changes(owner, limit=1)
        if not changes:
            return json.dumps(
                {"ok": False, "error": "되돌릴 변경 내역이 없습니다."}, ensure_ascii=False
            )
        last = changes[0]
        domain = last.get("domain")
        field = last.get("field")
        old_value = last.get("old_value")
        coerced = _coerce_value(field, old_value)
        result = await apply_self_service_setting(domain, owner, field, coerced, call_id)
        if not result.get("ok"):
            return json.dumps(result, ensure_ascii=False, default=str)
        return json.dumps({
            "ok": True, "domain": domain, "field": field, "restored_value": coerced,
        }, ensure_ascii=False, default=str)
    except Exception as e:
        logger.error("self_service_tool_undo_last_change_error", owner=owner, error=str(e))
        return json.dumps({"ok": False, "error": f"되돌리기 중 오류가 발생했습니다: {e}"}, ensure_ascii=False)


undo_last_self_service_change_tool = _make_tool(_undo_last_self_service_change)
undo_last_self_service_change_tool.__doc__ = _undo_last_self_service_change.__doc__


# self_service_agent_node가 bind_tools()에 그대로 넘기는 도구 목록
SELF_SERVICE_TOOLS = [
    get_onboarding_checklist_tool,
    get_self_service_settings_tool,
    get_self_service_stats_tool,
    update_self_service_setting_tool,
    search_call_history_tool,
    get_top_caller_tool,
    get_missed_calls_today_tool,
    get_last_self_service_change_tool,
    undo_last_self_service_change_tool,
]
