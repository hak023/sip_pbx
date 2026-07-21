"""
셀프서비스 통화 이력 자연어 질의 (Story 1.13).

PRD FR15/NFR5: "AI가 RAG를 통해 통화 이력에 접근"한다는 요구사항을 구현하되, 통화 이력은
이미 SQLite `call_records`(src/common/call_record_db.py)에 구조화되어 있고 요약 텍스트
(`call_summary`)까지 저장되어 있으므로, Story 1.11(Screen Graph)이 Full GraphRAG 대신
경량 정적 레지스트리를 택한 것과 동일한 원칙으로 **새 벡터 임베딩 파이프라인을 구축하지
않는다**. 대신 Story 1.7(stats.py)이 검증한 `call_record_db.get_call_records_page(owner=...)`를
그대로 재사용해 구조화 검색/집계로 구현한다.

제공 기능(FR15):
  1. search_call_history_by_keyword: call_summary 키워드 검색
  2. get_top_caller: 기간별(오늘/이번 주/이번 달) 최다 발신 번호 집계
  3. get_missed_calls_today: 오늘자 미응답 번호 조회

[미응답(missed call) 판정 기준 — Story 1.13 Task 0 조사 결과]
`call_records`에는 명시적 answered/missed 플래그가 없다. 코드 조사 결과, CANCEL(발신자가
응답 전 끊음)도 `sip_endpoint.py::_cleanup_call()`과 동일 경로로 `upsert_call_record`가
호출되며, 이때 RTP 미디어가 전혀 흐르지 않으므로 `has_recording=False`, AI 파이프라인도
시작되지 않으므로 `is_ai_handled=False`로 남는다. 따라서 `has_recording=False AND
is_ai_handled=False`를 "미응답" 판정 기준으로 사용한다. 알려진 한계: 사람이 직접 받았지만
녹음 자체가 실패한 통화는 이 기준으로는 "미응답"으로 오판될 수 있다(실제 통화 데이터로
추가 검증 권장).
"""

from __future__ import annotations

from collections import Counter
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

import structlog

logger = structlog.get_logger(__name__)

SUPPORTED_TOP_CALLER_PERIODS = ("today", "week", "month")
_UNSUPPORTED_PERIOD_MESSAGE = (
    '정형화된 기간만 가능합니다. "오늘", "이번 주" 또는 "이번 달" 중에서 질의해 주세요.'
)
_MAX_KEYWORD_MATCHES_DEFAULT = 20
_TOP_CALLER_COUNT = 5
_PAGE_SCAN_LIMIT = 10000  # stats.py(Story 1.7)와 동일 — 신규 집계 파이프라인 없이 전체 스캔


def _period_since_utc(period: str) -> Optional[datetime]:
    """period("today"|"week"|"month")의 시작 시각(UTC, 자정)을 반환. 미지원 값이면 None."""
    now = datetime.now(timezone.utc)
    if period == "today":
        return now.replace(hour=0, minute=0, second=0, microsecond=0)
    if period == "week":
        start = now - timedelta(days=now.weekday())  # 이번 주 월요일
        return start.replace(hour=0, minute=0, second=0, microsecond=0)
    if period == "month":
        return now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    return None


def _is_missed(item: Dict[str, Any]) -> bool:
    """미응답(missed) 판정 — 모듈 docstring 참고."""
    return not item.get("has_recording") and not item.get("is_ai_handled")


async def search_call_history_by_keyword(
    owner: str, keyword: str, limit: int = _MAX_KEYWORD_MATCHES_DEFAULT,
) -> Dict[str, Any]:
    """owner 소유 통화 이력 중 call_summary에 keyword가 포함된 통화를 검색한다(FR15-1).

    AC4/NFR5: 신규 벡터 인덱스 없이 기존 call_record_db만 재사용한다.
    """
    kw = (keyword or "").strip()
    if not kw:
        return {"error": "검색할 키워드를 알려주세요.", "match_count": 0, "matches": []}

    from src.common.call_record_db import get_call_records_page

    result = get_call_records_page(owner=owner, limit=_PAGE_SCAN_LIMIT, offset=0)
    if result is None:
        return {"error": "통화 이력을 조회할 수 없습니다.", "match_count": 0, "matches": []}

    kw_lower = kw.lower()
    matches: List[Dict[str, Any]] = []
    for item in result.get("items") or []:
        summary = str(item.get("call_summary") or "")
        if not summary or kw_lower not in summary.lower():
            continue
        matches.append({
            "call_id": item.get("call_id"),
            "caller_id": item.get("caller_id"),
            "start_time": item.get("start_time"),
            "call_summary": summary,
        })
        if len(matches) >= limit:
            break

    return {"owner": owner, "keyword": kw, "match_count": len(matches), "matches": matches}


async def get_top_caller(owner: str, period: str) -> Dict[str, Any]:
    """기간(오늘/이번 주/이번 달) 내 발신번호별 통화 건수를 집계해 상위 발신자를 반환한다(FR15-2).

    AC2: 미지원 기간은 명확한 폴백 메시지를 반환한다.
    """
    period_norm = (period or "").strip().lower()
    if period_norm not in SUPPORTED_TOP_CALLER_PERIODS:
        return {
            "error": _UNSUPPORTED_PERIOD_MESSAGE,
            "supported_periods": list(SUPPORTED_TOP_CALLER_PERIODS),
        }

    since_dt = _period_since_utc(period_norm)
    since_iso = since_dt.isoformat().replace("+00:00", "Z")

    from src.common.call_record_db import get_call_records_page

    result = get_call_records_page(owner=owner, since=since_iso, limit=_PAGE_SCAN_LIMIT, offset=0)
    if result is None:
        return {"error": "통화 이력을 조회할 수 없습니다."}

    counter: "Counter[str]" = Counter()
    for item in result.get("items") or []:
        caller = str(item.get("caller_id") or "").strip()
        if caller:
            counter[caller] += 1

    top = counter.most_common(_TOP_CALLER_COUNT)
    return {
        "owner": owner,
        "period": period_norm,
        "since": since_iso,
        "top_callers": [{"caller_id": c, "call_count": n} for c, n in top],
    }


async def get_missed_calls_today(owner: str) -> Dict[str, Any]:
    """오늘 걸려온 통화 중 응답(AI/사람 모두)되지 않은 것으로 판정된 통화를 조회한다(FR15-3)."""
    since_dt = _period_since_utc("today")
    since_iso = since_dt.isoformat().replace("+00:00", "Z")

    from src.common.call_record_db import get_call_records_page

    result = get_call_records_page(
        owner=owner, since=since_iso, direction="inbound", limit=_PAGE_SCAN_LIMIT, offset=0,
    )
    if result is None:
        return {"error": "통화 이력을 조회할 수 없습니다.", "missed_count": 0, "missed_calls": []}

    missed = [
        {
            "call_id": it.get("call_id"),
            "caller_id": it.get("caller_id"),
            "start_time": it.get("start_time"),
        }
        for it in (result.get("items") or [])
        if _is_missed(it)
    ]

    return {"owner": owner, "date": since_iso, "missed_count": len(missed), "missed_calls": missed}
