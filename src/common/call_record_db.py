"""
통화 이력 SQLite 헬퍼 (P3: call_records 테이블 upsert/조회).

booking.db와 동일 파일을 공유한다 (src.booking.database).
파이프라인/녹음 등 어디서든 import 후 upsert_call_record()를 호출하면 됨.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

_DB_AVAILABLE = True


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def upsert_call_record(
    *,
    call_id: str,
    owner: str = "",
    caller_id: str = "",
    callee_id: str = "",
    direction: str = "inbound",
    start_time: Optional[str] = None,
    end_time: Optional[str] = None,
    duration: Optional[float] = None,
    call_summary: Optional[str] = None,
    is_ai_handled: bool = False,
    ai_unhandled_count: int = 0,
    is_unresolved: Optional[bool] = None,
    has_recording: bool = False,
    has_transcript: bool = False,
    recordings_dir: str = "",
    extra_data: Optional[Dict[str, Any]] = None,
) -> bool:
    """call_records 테이블에 INSERT OR REPLACE (upsert).

    이미 row가 있으면 non-None 필드만 덮어쓴다 (partial update).
    Returns True on success, False on failure.
    """
    if not call_id:
        return False
    global _DB_AVAILABLE
    if not _DB_AVAILABLE:
        return False

    try:
        from src.booking.database import get_db
    except ImportError:
        _DB_AVAILABLE = False
        logger.debug("call_record_db_import_failed booking.database not available")
        return False

    now = _now_iso()
    extra_json = json.dumps(extra_data or {}, ensure_ascii=False)

    try:
        with get_db() as conn:
            # 기존 row 조회
            existing = conn.execute(
                "SELECT * FROM call_records WHERE call_id = ?", (call_id,)
            ).fetchone()

            if existing is None:
                conn.execute(
                    """
                    INSERT INTO call_records (
                        call_id, owner, caller_id, callee_id, direction,
                        start_time, end_time, duration,
                        call_summary, is_ai_handled, ai_unhandled_count,
                        is_unresolved,
                        has_recording, has_transcript, recordings_dir,
                        extra_data, created_at, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        call_id,
                        owner or "",
                        caller_id or "",
                        callee_id or "",
                        direction or "inbound",
                        start_time,
                        end_time,
                        duration,
                        call_summary or "",
                        1 if is_ai_handled else 0,
                        ai_unhandled_count,
                        1 if is_unresolved else 0,
                        1 if has_recording else 0,
                        1 if has_transcript else 0,
                        recordings_dir or "",
                        extra_json,
                        now,
                        now,
                    ),
                )
                logger.debug("call_record_inserted call_id=%s", call_id)
            else:
                # 부분 업데이트: None이 아닌 필드만 갱신
                updates: List[str] = ["updated_at = ?"]
                params: List[Any] = [now]

                def _set(col: str, val: Any) -> None:
                    if val is not None:
                        updates.append(f"{col} = ?")
                        params.append(val)

                if owner:
                    _set("owner", owner)
                if caller_id:
                    _set("caller_id", caller_id)
                if callee_id:
                    _set("callee_id", callee_id)
                if direction:
                    _set("direction", direction)
                _set("start_time", start_time)
                _set("end_time", end_time)
                _set("duration", duration)
                _set("call_summary", call_summary)
                if is_ai_handled:
                    _set("is_ai_handled", 1)
                if ai_unhandled_count > 0:
                    _set("ai_unhandled_count", ai_unhandled_count)
                if is_unresolved is not None:
                    _set("is_unresolved", 1 if is_unresolved else 0)
                if has_recording:
                    _set("has_recording", 1)
                if has_transcript:
                    _set("has_transcript", 1)
                if recordings_dir:
                    _set("recordings_dir", recordings_dir)
                if extra_data:
                    _set("extra_data", extra_json)

                sql = f"UPDATE call_records SET {', '.join(updates)} WHERE call_id = ?"
                params.append(call_id)
                conn.execute(sql, params)
                logger.debug("call_record_updated call_id=%s", call_id)
        return True
    except Exception as exc:
        logger.warning("call_record_upsert_failed call_id=%s err=%s", call_id, exc)
        return False


def get_call_records_page(
    *,
    owner: str = "",
    since: Optional[str] = None,
    direction: Optional[str] = None,
    limit: int = 100,
    offset: int = 0,
) -> Optional[Dict[str, Any]]:
    """DB에서 통화 이력 페이지 조회.

    Returns dict {"items": [...], "total": int} 또는 None (DB 미사용 시).
    """
    global _DB_AVAILABLE
    if not _DB_AVAILABLE:
        return None

    try:
        from src.booking.database import get_db
    except ImportError:
        _DB_AVAILABLE = False
        return None

    try:
        with get_db() as conn:
            conditions: List[str] = []
            params: List[Any] = []

            if owner:
                conditions.append(
                    "(owner = ? OR caller_id LIKE ? OR callee_id LIKE ?)"
                )
                params.extend([owner, f"%{owner}%", f"%{owner}%"])
            if since:
                conditions.append("(start_time >= ? OR start_time IS NULL)")
                params.append(since)
            if direction and direction in ("inbound", "outbound"):
                conditions.append("direction = ?")
                params.append(direction)

            where = ("WHERE " + " AND ".join(conditions)) if conditions else ""

            total = conn.execute(
                f"SELECT COUNT(*) FROM call_records {where}", params
            ).fetchone()[0]

            rows = conn.execute(
                f"""
                SELECT * FROM call_records {where}
                ORDER BY start_time DESC NULLS LAST
                LIMIT ? OFFSET ?
                """,
                params + [limit, offset],
            ).fetchall()

            items = [dict(r) for r in rows]
            # extra_data JSON 파싱
            for item in items:
                raw = item.get("extra_data") or "{}"
                try:
                    item["extra_data"] = json.loads(raw)
                except (json.JSONDecodeError, TypeError):
                    item["extra_data"] = {}
            return {"items": items, "total": total}
    except Exception as exc:
        logger.warning("call_records_query_failed err=%s", exc)
        return None


def get_prior_inbound_call_for_caller(
    *,
    owner: str,
    caller_like: str,
    exclude_call_id: str = "",
) -> Optional[Dict[str, Any]]:
    """동일 발신(부분 일치)·착신 테넌트 기준으로 **직전 종료 통화 1건**(현재 통화 제외).

    ``caller_like`` 는 ``%`` 를 포함하지 않은 숫자/문자열 조각(예: 전화 끝 8자리)으로,
    ``caller_id`` 컬럼에 ``LIKE '%' || caller_like || '%'`` 로 매칭한다.
    """
    global _DB_AVAILABLE
    if not _DB_AVAILABLE or not owner or not caller_like:
        return None

    try:
        from src.booking.database import get_db
    except ImportError:
        _DB_AVAILABLE = False
        return None

    ex = (exclude_call_id or "").strip()
    own = owner.strip()
    needle = caller_like.strip()
    if not needle:
        return None

    try:
        with get_db() as conn:
            # owner 필터: 테넌트 owner 또는 callee에 owner가 포함된 착신
            sql = """
                SELECT call_id, start_time, end_time, call_summary, caller_id, callee_id, direction
                FROM call_records
                WHERE (? = '' OR call_id != ?)
                  AND direction = 'inbound'
                  AND (owner = ? OR callee_id LIKE ? OR callee_id = ? OR callee_id LIKE ?)
                  AND caller_id LIKE ?
                ORDER BY
                  (CASE WHEN end_time IS NULL OR end_time = '' THEN 1 ELSE 0 END),
                  end_time DESC,
                  start_time DESC
                LIMIT 1
            """
            like_owner = f"%{own}%"
            like_caller = f"%{needle}%"
            row = conn.execute(
                sql,
                (ex, ex, own, like_owner, own, like_owner, like_caller),
            ).fetchone()
            if row is None:
                return None
            return dict(row)
    except Exception as exc:
        logger.warning("get_prior_inbound_call_for_caller_failed err=%s", exc)
        return None


def _params_inbound_caller_owner(
    owner: str, caller_like: str, exclude_call_id: str
) -> tuple[str, str, str, str, str, str, str]:
    """get_prior_inbound_call_for_caller / COUNT 에 공통으로 쓰는 (ex, ex, own, like_owner...) 튜플."""
    ex = (exclude_call_id or "").strip()
    own = owner.strip()
    needle = caller_like.strip()
    like_owner = f"%{own}%"
    like_caller = f"%{needle}%"
    return (ex, ex, own, like_owner, own, like_owner, like_caller)


def count_inbound_calls_for_caller(
    *,
    owner: str,
    caller_like: str,
    since_iso: Optional[str] = None,
    exclude_call_id: str = "",
) -> int:
    """동일 발신 needle·착신 테넌트 기준 인입 통화 건수 (선택: since_iso 이후, 현재 통화 제외)."""
    global _DB_AVAILABLE
    if not _DB_AVAILABLE or not owner or not caller_like:
        return 0
    try:
        from src.booking.database import get_db
    except ImportError:
        _DB_AVAILABLE = False
        return 0
    needle = caller_like.strip()
    if not needle:
        return 0
    try:
        with get_db() as conn:
            p = _params_inbound_caller_owner(owner, needle, exclude_call_id)
            time_clause = ""
            time_params: List[Any] = []
            if since_iso and str(since_iso).strip():
                time_clause = (
                    " AND (COALESCE(NULLIF(TRIM(end_time), ''), start_time) >= ?) "
                )
                time_params = [since_iso.strip()]
            sql = f"""
                SELECT COUNT(*)
                FROM call_records
                WHERE (? = '' OR call_id != ?)
                  AND direction = 'inbound'
                  AND (owner = ? OR callee_id LIKE ? OR callee_id = ? OR callee_id LIKE ?)
                  AND caller_id LIKE ?
                  {time_clause}
            """
            row = conn.execute(sql, list(p) + time_params).fetchone()
            return int(row[0]) if row else 0
    except Exception as exc:
        logger.warning("count_inbound_calls_for_caller_failed err=%s", exc)
        return 0
