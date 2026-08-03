"""
IntelliDecision 판단 근거 로그 SQLite 헬퍼 (Story 1.21, FR30).

booking.db와 동일 파일을 공유한다(src.booking.database).
`self_service/decision_rationale.py`의 백그라운드 캡처 태스크가 성공했을 때만 호출한다.
순수 관측 전용 데이터이며, 원본 발화 전문은 저장하지 않는다(개인정보 최소 노출 원칙).
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List

logger = logging.getLogger(__name__)

_DB_AVAILABLE = True

# 근거 요약 저장 시 최대 길이(FR30 명시 — 원본 발화 전문 대신 짧은 요약만 저장)
_REASONING_SUMMARY_MAX_LEN = 200


def record_decision_rationale(
    *,
    owner: str,
    call_id: str = "",
    matched_type: str = "unknown",
    reasoning_summary: str = "",
    related_domain: str = "",
) -> bool:
    """self_service_decision_log 테이블에 판단 근거 1건을 추가한다."""
    global _DB_AVAILABLE
    if not _DB_AVAILABLE:
        return False
    try:
        from src.booking.database import get_db
    except ImportError:
        _DB_AVAILABLE = False
        logger.debug("self_service_decision_log_import_failed")
        return False

    summary = (reasoning_summary or "")[:_REASONING_SUMMARY_MAX_LEN]

    try:
        with get_db() as conn:
            conn.execute(
                """
                INSERT INTO self_service_decision_log
                    (owner, call_id, matched_type, reasoning_summary, related_domain)
                VALUES (?, ?, ?, ?, ?)
                """,
                (owner, call_id or "", matched_type or "unknown", summary, related_domain or ""),
            )
        return True
    except Exception as exc:
        logger.warning(
            "self_service_decision_log_insert_failed owner=%s matched_type=%s err=%s",
            owner, matched_type, exc,
        )
        return False


def list_decision_log(owner: str, limit: int = 20) -> List[Dict[str, Any]]:
    """owner의 최근 판단 근거 이력을 created_at DESC 순으로 반환한다(읽기 전용 API용)."""
    global _DB_AVAILABLE
    if not _DB_AVAILABLE:
        return []
    try:
        from src.booking.database import get_db
    except ImportError:
        _DB_AVAILABLE = False
        return []

    try:
        with get_db() as conn:
            rows = conn.execute(
                """
                SELECT * FROM self_service_decision_log
                WHERE owner = ?
                ORDER BY created_at DESC
                LIMIT ?
                """,
                (owner, limit),
            ).fetchall()
            return [dict(r) for r in rows]
    except Exception as exc:
        logger.warning("self_service_decision_log_query_failed owner=%s err=%s", owner, exc)
        return []
