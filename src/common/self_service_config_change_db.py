"""
셀프서비스 자동설정 변경 이력 SQLite 헬퍼 (Story 1.8 FR8).

booking.db와 동일 파일을 공유한다(src.booking.database).
`update_self_service_setting` Tool이 실제 변경에 성공했을 때만 호출한다.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

_DB_AVAILABLE = True


def record_config_change(
    *,
    owner: str,
    domain: str,
    field: str,
    old_value: Any,
    new_value: Any,
    call_id: str = "",
) -> bool:
    """self_service_config_changes 테이블에 변경 이력 1건을 추가한다."""
    global _DB_AVAILABLE
    if not _DB_AVAILABLE:
        return False
    try:
        from src.booking.database import get_db
    except ImportError:
        _DB_AVAILABLE = False
        logger.debug("self_service_config_change_db_import_failed")
        return False

    try:
        with get_db() as conn:
            conn.execute(
                """
                INSERT INTO self_service_config_changes
                    (owner, domain, field, old_value, new_value, call_id)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (owner, domain, field, str(old_value), str(new_value), call_id or ""),
            )
        return True
    except Exception as exc:
        logger.warning(
            "self_service_config_change_insert_failed owner=%s domain=%s field=%s err=%s",
            owner, domain, field, exc,
        )
        return False


def list_config_changes(owner: str, limit: int = 100) -> List[Dict[str, Any]]:
    """owner의 최근 변경 이력을 조회한다(테스트·감사 조회용)."""
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
                SELECT * FROM self_service_config_changes
                WHERE owner = ?
                ORDER BY changed_at DESC
                LIMIT ?
                """,
                (owner, limit),
            ).fetchall()
            return [dict(r) for r in rows]
    except Exception as exc:
        logger.warning("self_service_config_change_query_failed owner=%s err=%s", owner, exc)
        return []
