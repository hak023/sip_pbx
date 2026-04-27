"""
Call Control Routing Engine

현재 시각 + 스케줄 매칭으로 착신 규칙을 결정한다.

우선순위 평가 순서:
  1. 활성화된(enabled=True) 규칙만 후보
  2. priority ASC 정렬 후 순서대로 스케줄 조건 확인
  3. schedule_id=None 이면 항상 매칭 (default fallback)
  4. 가장 먼저 매칭된 규칙 반환
"""

from __future__ import annotations

from datetime import datetime, time, timezone, timedelta
from typing import Optional

import structlog

from src.call_control import db as _db
from src.call_control.models import RoutingAction

logger = structlog.get_logger(__name__)

# ---------------------------------------------------------------------------
# tzdata / ZoneInfo — Windows 환경에서는 tzdata 패키지가 없으면 ZoneInfo 미작동.
# 선택적으로 사용하고, 없으면 UTC+9 (Asia/Seoul) 고정 오프셋으로 폴백한다.
# ---------------------------------------------------------------------------
try:
    from zoneinfo import ZoneInfo as _ZoneInfo

    def _get_tz(tz_name: str):
        """타임존 객체 반환. 실패 시 UTC+9 고정 오프셋."""
        try:
            return _ZoneInfo(tz_name)
        except Exception:
            pass
        # tzdata 없는 Windows: 알려진 타임존은 오프셋으로 대체
        _KNOWN_OFFSETS = {
            "Asia/Seoul": 9, "Asia/Tokyo": 9, "Asia/Shanghai": 8,
            "Asia/Hong_Kong": 8, "America/New_York": -5, "America/Los_Angeles": -8,
            "Europe/London": 0, "Europe/Berlin": 1,
        }
        offset_hours = _KNOWN_OFFSETS.get(tz_name, 9)  # 기본 KST(+9)
        logger.warning(
            "zoneinfo_fallback_to_fixed_offset",
            tz_name=tz_name,
            offset_hours=offset_hours,
            note="tzdata not installed; using fixed UTC offset. Run: pip install tzdata",
        )
        return timezone(timedelta(hours=offset_hours))

except ImportError:
    def _get_tz(tz_name: str):
        return timezone(timedelta(hours=9))

# 공휴일 라이브러리 (선택적 의존성)
try:
    import holidays as _holidays_lib  # type: ignore[import]
    _HOLIDAYS_AVAILABLE = True
except ImportError:
    _HOLIDAYS_AVAILABLE = False
    logger.warning("holidays_lib_not_installed", note="pip install holidays 로 설치하면 공휴일 스케줄 지원")


# ---------------------------------------------------------------------------
# 내부 헬퍼
# ---------------------------------------------------------------------------


_WEEKDAY_MAP = {
    0: "mon", 1: "tue", 2: "wed", 3: "thu",
    4: "fri", 5: "sat", 6: "sun",
}


def _parse_time(t: str) -> time:
    """'HH:MM' → time 객체."""
    h, m = t.split(":")
    return time(int(h), int(m))


def _is_holiday(dt: datetime, country: str) -> bool:
    """공휴일 여부 확인."""
    if not _HOLIDAYS_AVAILABLE:
        return False
    try:
        country_holidays = _holidays_lib.country_holidays(country, years=dt.year)
        return dt.date() in country_holidays
    except Exception:
        return False


def _schedule_matches(schedule_raw: dict, now: datetime) -> bool:
    """스케줄이 now 시각에 활성인지 판단."""
    tz_name = schedule_raw.get("timezone", "Asia/Seoul")
    tz = _get_tz(tz_name)
    local_now = now.astimezone(tz)
    weekday_str = _WEEKDAY_MAP[local_now.weekday()]

    # 요일 체크
    days: list = schedule_raw.get("days") or []
    if days and weekday_str not in days:
        # 공휴일이고 include_holidays=True 이면 요일 조건 무시
        if schedule_raw.get("include_holidays") and _is_holiday(local_now, schedule_raw.get("holiday_country", "KR")):
            pass  # 공휴일은 모든 요일에 매칭
        else:
            return False

    # 시간 범위 체크
    time_ranges: list = schedule_raw.get("time_ranges") or []
    if time_ranges:
        current_t = local_now.time().replace(second=0, microsecond=0)
        in_range = any(
            _parse_time(tr["start"]) <= current_t <= _parse_time(tr["end"])
            for tr in time_ranges
        )
        if not in_range:
            return False

    return True


# ---------------------------------------------------------------------------
# 발신자 필터 매칭
# ---------------------------------------------------------------------------


def _pattern_matches(pattern: str, caller: str) -> bool:
    """발신자 번호 패턴 매칭.

    - 정확 일치: '010-1234-5678'
    - prefix 와일드카드: '010*', '+8210*'
    """
    if pattern.endswith("*"):
        return caller.startswith(pattern[:-1])
    return caller == pattern


def resolve_caller_filter(owner: str, caller: str) -> Optional[dict]:
    """발신자 번호에 매칭되는 첫 번째 활성 필터 반환.

    VIP/차단 규칙이 일반 라우팅 규칙보다 우선 평가된다.
    """
    filters = _db.list_caller_filters(owner)
    enabled = [f for f in filters if f.get("enabled")]
    for cf in enabled:
        if _pattern_matches(cf["pattern"], caller):
            logger.debug(
                "caller_filter_matched",
                owner=owner,
                caller=caller,
                filter_id=cf["id"],
                pattern=cf["pattern"],
                action=cf["action"],
            )
            return cf
    return None


# ---------------------------------------------------------------------------
# 공개 API
# ---------------------------------------------------------------------------


def resolve_rule(owner: str, now: Optional[datetime] = None) -> Optional[dict]:
    """
    owner 내선에 대해 현재 시각에 적용할 규칙 딕셔너리를 반환.

    반환값 딕셔너리:
      - rule: RoutingRule dict
      - schedule: Schedule dict | None
      - is_schedule_active: bool

    매칭되는 규칙이 없으면 None.
    """
    if now is None:
        from datetime import timezone as _tz
        now = datetime.now(_tz.utc)

    rules = _db.list_rules(owner)
    enabled_rules = [r for r in rules if r.get("enabled")]

    for rule in enabled_rules:
        schedule_id = rule.get("schedule_id")

        if schedule_id is None:
            # 항상(always) 적용 규칙
            logger.debug(
                "routing_rule_matched_always",
                owner=owner,
                rule_id=rule["id"],
                action=rule["action"],
            )
            return {"rule": rule, "schedule": None, "is_schedule_active": True}

        schedule_raw = _db.get_schedule(schedule_id)
        if schedule_raw is None:
            # 스케줄이 삭제된 경우 건너뜀
            continue

        if _schedule_matches(schedule_raw, now):
            logger.debug(
                "routing_rule_matched_schedule",
                owner=owner,
                rule_id=rule["id"],
                schedule_id=schedule_id,
                action=rule["action"],
            )
            return {"rule": rule, "schedule": schedule_raw, "is_schedule_active": True}

    return None


def get_effective_no_answer_timeout(owner: str, default: int = 20) -> int:
    """현재 적용 규칙의 no_answer_timeout 반환. 규칙 없으면 default."""
    result = resolve_rule(owner)
    if result and result["rule"]["action"] == RoutingAction.NO_ANSWER_AI:
        return result["rule"].get("no_answer_timeout", default)
    return default


def get_effective_action(owner: str) -> Optional[str]:
    """현재 적용 규칙의 action 문자열 반환. 규칙 없으면 None."""
    result = resolve_rule(owner)
    if result:
        return result["rule"]["action"]
    return None


def schedule_active_now(schedule_id: Optional[str], now: Optional[datetime] = None) -> bool:
    """``schedule_id`` 가 비어 있으면 항상 참. 그 외에는 해당 스케줄이 ``now`` 시각에 활성인지."""
    if not schedule_id or not str(schedule_id).strip():
        return True
    if now is None:
        now = datetime.now(timezone.utc)
    raw = _db.get_schedule(str(schedule_id))
    if not raw:
        return False
    return _schedule_matches(raw, now)
