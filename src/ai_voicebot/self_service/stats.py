"""
셀프서비스 이용 통계 조회 (Story 1.7).

AC1: 기간(이번 주/이번 달)별 통화 수, 평균 confidence, HITL 발생 건수를 반환한다.
AC2/NFR3: 새 집계 파이프라인을 만들지 않고 기존 데이터 소스만 재사용한다.
  - 통화 수·AI 응대 건수: `call_record_db.get_call_records_page(owner=, since=)`
    (Story 1.7 Task 0 조사 결과 — `StatisticsCollector`는 owner 파라미터가 없는
    전역 프로세스 싱글턴이라 테넌트별 통계에 부적합함을 확인, 이 함수로 대체)
  - HITL 발생 건수: 각 통화의 `call_insights.json`(`ai_unhandled_resolved_by_hitl_count`)을
    `src/common/call_insights_buffer.py::load_call_insights_for_directory`로 읽어 합산
    (`metrics.py::_count_unresolved_calls`와 동일한 recordings_dir 조회 패턴 재사용).
    HITL 발생 건수는 DB나 프로세스 메모리(HITLService._hitl_request_fifo, 통화 종료 후
    소멸)에 별도로 남지 않고 이 파일에만 기록됨을 코드 확인으로 확정했다(Task 0).
  - 평균 confidence: `logs/call_data_record_YYYYMMDD.log`(JSONL)의 `llm_response_generated`
    이벤트 `confidence` 필드 — `metrics.py::_get_avg_confidence_today`와 동일한 로그
    형식·이벤트명을 재사용하되, (a) call_id가 해당 owner의 기간 내 통화 집합에 속하는
    것만 필터링하고 (b) 기간에 해당하는 여러 날짜의 로그 파일을 모두 스캔하도록 확장했다.
    [발견한 기존 함수의 한계] `_get_avg_confidence_today(owner)`는 시그니처에 owner를
    받지만 실제로는 owner로 필터링하지 않고 그날 전체 테넌트의 confidence를 섞어 평균낸다
    (코드 확인으로 발견). 본 모듈은 call_id 교집합 필터로 이 한계를 바로잡아 owner
    스코프를 보장한다.

AC3: "이번 주"/"이번 달" 두 정형 기간만 지원한다. 그 외 값은 폴백 메시지를 반환한다.
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Set

import structlog

logger = structlog.get_logger(__name__)

SUPPORTED_PERIODS = ("week", "month")
_UNSUPPORTED_PERIOD_MESSAGE = (
    '정형화된 질의만 가능합니다. "이번 주" 또는 "이번 달" 통계만 조회할 수 있어요.'
)

_PROJECT_ROOT = Path(__file__).resolve().parents[3]


def _period_since_utc(period: str) -> Optional[datetime]:
    """period("week"|"month")의 시작 시각(UTC, 자정)을 반환. 미지원 값이면 None."""
    now = datetime.now(timezone.utc)
    if period == "week":
        start = now - timedelta(days=now.weekday())  # 이번 주 월요일
        return start.replace(hour=0, minute=0, second=0, microsecond=0)
    if period == "month":
        return now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    return None


def _recordings_root() -> Path:
    raw = (
        os.environ.get("SIP_RECORDINGS_DIR")
        or os.environ.get("RECORDINGS_DIR")
        or "./recordings"
    )
    return Path(raw).resolve()


def _daily_log_paths(since_dt: datetime) -> List[Path]:
    """since_dt부터 오늘까지 날짜별 call_data_record_YYYYMMDD.log 경로 목록(존재 파일만)."""
    log_dir = _PROJECT_ROOT / "logs"
    paths: List[Path] = []
    day = since_dt.date()
    today = datetime.now(timezone.utc).date()
    while day <= today:
        p = log_dir / f"call_data_record_{day.strftime('%Y%m%d')}.log"
        if p.exists():
            paths.append(p)
        day += timedelta(days=1)
    return paths


def _avg_confidence_for_call_ids(call_ids: Set[str], since_dt: datetime) -> float:
    """call_ids에 속한 통화만 필터링해 llm_response_generated confidence 평균을 계산."""
    confidences: List[float] = []
    for log_path in _daily_log_paths(since_dt):
        try:
            with open(log_path, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        obj = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    if obj.get("event") != "llm_response_generated":
                        continue
                    if obj.get("call_id") not in call_ids:
                        continue
                    conf = obj.get("confidence")
                    if conf is None:
                        continue
                    try:
                        conf_f = float(conf)
                    except (TypeError, ValueError):
                        continue
                    if 0 <= conf_f <= 1:
                        confidences.append(conf_f)
        except OSError as e:
            logger.debug("self_service_stats_log_read_failed", path=str(log_path), error=str(e))
    if not confidences:
        return 0.0
    return sum(confidences) / len(confidences)


def _hitl_count_for_items(items: List[Dict[str, Any]]) -> int:
    """각 통화의 call_insights.json에서 ai_unhandled_resolved_by_hitl_count를 합산."""
    from src.common.call_insights_buffer import load_call_insights_for_directory

    root = _recordings_root()
    total = 0
    for it in items:
        rec_dir_raw = it.get("recordings_dir") or ""
        if not rec_dir_raw:
            continue
        call_dir = Path(rec_dir_raw)
        if not call_dir.is_absolute():
            call_dir = root / call_dir
        if not call_dir.is_dir():
            continue
        insights = load_call_insights_for_directory(call_dir)
        if insights:
            total += int(insights.get("ai_unhandled_resolved_by_hitl_count") or 0)
    return total


async def get_self_service_stats(owner: str, period: str) -> Dict[str, Any]:
    """기간별(이번 주/이번 달) 통화 수·평균 confidence·HITL 발생 건수를 반환한다(AC1).

    지원하지 않는 기간이면 폴백 메시지를 반환한다(AC3).
    """
    period_norm = (period or "").strip().lower()
    if period_norm not in SUPPORTED_PERIODS:
        return {"error": _UNSUPPORTED_PERIOD_MESSAGE, "supported_periods": list(SUPPORTED_PERIODS)}

    since_dt = _period_since_utc(period_norm)
    since_iso = since_dt.isoformat().replace("+00:00", "Z")

    from src.common.call_record_db import get_call_records_page

    result = get_call_records_page(owner=owner, since=since_iso, limit=10000, offset=0)
    if result is None:
        return {"error": "통계 데이터를 조회할 수 없습니다."}

    items = result.get("items") or []
    call_count = len(items)
    ai_handled_count = sum(1 for it in items if it.get("is_ai_handled"))
    call_ids = {it.get("call_id") for it in items if it.get("call_id")}

    avg_confidence = _avg_confidence_for_call_ids(call_ids, since_dt) if call_ids else 0.0
    hitl_count = _hitl_count_for_items(items)

    return {
        "owner": owner,
        "period": period_norm,
        "since": since_iso,
        "call_count": call_count,
        "ai_handled_count": ai_handled_count,
        "avg_confidence": round(avg_confidence, 3),
        "hitl_count": hitl_count,
    }
