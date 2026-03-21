"""
SQLite 저장소 — 통화 이력(call_history), 발신자별 요약(call_summaries).

환경 변수 SQLITE_DB_PATH (기본: data/calls.db). 디렉터리 없으면 생성.
"""

import json
import os
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

# DB 경로 (디렉터리 생성 포함)
def get_db_path() -> str:
    path = os.environ.get("SQLITE_DB_PATH", "data/calls.db")
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    return path


def _conn():
    return sqlite3.connect(get_db_path(), check_same_thread=False)


def _row_to_entry(row: tuple, col_names: List[str]) -> Dict[str, Any]:
    d = dict(zip(col_names, row))
    # INTEGER -> bool where needed
    for k in ("is_ai_handled", "resolved", "follow_up_required"):
        if k in d and d[k] is not None:
            d[k] = bool(d[k])
    if d.get("transcripts"):
        try:
            d["transcripts"] = json.loads(d["transcripts"]) if isinstance(d["transcripts"], str) else d["transcripts"]
        except Exception:
            d["transcripts"] = []
    else:
        d["transcripts"] = []
    return d


_CALL_HISTORY_COLS = [
    "call_id", "caller_id", "callee_id", "start_time", "end_time",
    "hitl_status", "user_question", "ai_confidence", "is_ai_handled",
    "resolved", "operator_note", "follow_up_required", "follow_up_phone",
    "transcripts", "created_at",
]


def init_db() -> None:
    """테이블 생성 (없을 때만)."""
    conn = _conn()
    try:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS call_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                call_id TEXT NOT NULL UNIQUE,
                caller_id TEXT,
                callee_id TEXT,
                start_time TEXT,
                end_time TEXT,
                hitl_status TEXT,
                user_question TEXT,
                ai_confidence REAL,
                is_ai_handled INTEGER NOT NULL DEFAULT 0,
                resolved INTEGER NOT NULL DEFAULT 0,
                operator_note TEXT DEFAULT '',
                follow_up_required INTEGER NOT NULL DEFAULT 0,
                follow_up_phone TEXT,
                transcripts TEXT DEFAULT '[]',
                created_at TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_call_history_callee ON call_history(callee_id);
            CREATE INDEX IF NOT EXISTS idx_call_history_start ON call_history(start_time DESC);

            CREATE TABLE IF NOT EXISTS call_summaries (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                tenant_id TEXT NOT NULL,
                caller_id TEXT NOT NULL,
                call_id TEXT NOT NULL,
                summary_text TEXT NOT NULL,
                created_at TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_call_summaries_tenant_caller ON call_summaries(tenant_id, caller_id);
            CREATE INDEX IF NOT EXISTS idx_call_summaries_created ON call_summaries(created_at DESC);
        """)
        conn.commit()
    finally:
        conn.close()


def append_call_history_row(entry: Dict[str, Any]) -> None:
    """통화 이력 한 건 추가. call_id 중복 시 무시(INSERT OR IGNORE)."""
    now = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    call_id = entry.get("call_id") or ""
    if not call_id:
        return
    conn = _conn()
    try:
        transcripts = entry.get("transcripts")
        if isinstance(transcripts, list):
            transcripts = json.dumps(transcripts, ensure_ascii=False)
        else:
            transcripts = transcripts or "[]"
        conn.execute(
            """
            INSERT OR IGNORE INTO call_history (
                call_id, caller_id, callee_id, start_time, end_time,
                hitl_status, user_question, ai_confidence, is_ai_handled,
                resolved, operator_note, follow_up_required, follow_up_phone,
                transcripts, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                call_id,
                entry.get("caller_id") or "",
                entry.get("callee_id") or "",
                entry.get("start_time") or now,
                entry.get("end_time"),
                entry.get("hitl_status") or "",
                entry.get("user_question"),
                entry.get("ai_confidence"),
                1 if entry.get("is_ai_handled") else 0,
                1 if entry.get("resolved") else 0,
                entry.get("operator_note") or "",
                1 if entry.get("follow_up_required") else 0,
                entry.get("follow_up_phone"),
                transcripts,
                now,
            ),
        )
        conn.commit()
    finally:
        conn.close()


def record_hitl_request_row(
    call_id: str,
    callee_id: str,
    user_question: str,
    ai_confidence: float,
    caller_id: Optional[str] = None,
    start_time: Optional[str] = None,
) -> None:
    """HITL 발생 시 행 있으면 UPDATE, 없으면 INSERT."""
    now = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    conn = _conn()
    try:
        cur = conn.execute(
            "SELECT id FROM call_history WHERE call_id = ?", (call_id,)
        )
        row = cur.fetchone()
        if row:
            if caller_id is not None or start_time is not None:
                updates = [
                    "hitl_status = ?", "user_question = ?", "ai_confidence = ?"
                ]
                params: List[Any] = ["pending", user_question, ai_confidence]
                if start_time is not None:
                    updates.append("start_time = ?")
                    params.append(start_time)
                if caller_id is not None:
                    updates.append("caller_id = ?")
                    params.append(caller_id)
                params.append(call_id)
                conn.execute(
                    "UPDATE call_history SET " + ", ".join(updates) + " WHERE call_id = ?",
                    params,
                )
            else:
                conn.execute(
                    """UPDATE call_history SET hitl_status = ?, user_question = ?, ai_confidence = ?
                       WHERE call_id = ?""",
                    ("pending", user_question, ai_confidence, call_id),
                )
        else:
            conn.execute(
                """
                INSERT INTO call_history (
                    call_id, caller_id, callee_id, start_time, end_time,
                    hitl_status, user_question, ai_confidence, is_ai_handled,
                    resolved, operator_note, follow_up_required, follow_up_phone,
                    transcripts, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 1, 0, '', 0, ?, '[]', ?)
                """,
                (
                    call_id,
                    caller_id or "",
                    callee_id,
                    start_time or now,
                    None,
                    "pending",
                    user_question,
                    ai_confidence,
                    None,
                    now,
                ),
            )
        conn.commit()
    finally:
        conn.close()


def mark_hitl_resolved_row(call_id: str) -> None:
    conn = _conn()
    try:
        conn.execute(
            "UPDATE call_history SET hitl_status = ?, resolved = 1 WHERE call_id = ?",
            ("resolved", call_id),
        )
        conn.commit()
    finally:
        conn.close()


def mark_pending_hitl_unresolved_row(call_id: str) -> None:
    conn = _conn()
    try:
        conn.execute(
            """UPDATE call_history SET hitl_status = 'unresolved'
               WHERE call_id = ? AND hitl_status = 'pending' AND resolved = 0""",
            (call_id,),
        )
        conn.commit()
    finally:
        conn.close()


def list_call_history_rows(
    page: int = 1,
    limit: int = 50,
    callee: Optional[str] = None,
    unresolved_hitl: Optional[str] = None,
) -> tuple[List[Dict[str, Any]], int]:
    """목록 + 전체 개수. 정렬 최신순."""
    conn = _conn()
    try:
        where_parts: List[str] = []
        params: List[Any] = []
        if callee:
            where_parts.append("callee_id = ?")
            params.append(callee)
        if unresolved_hitl and unresolved_hitl != "all":
            if unresolved_hitl == "unresolved":
                where_parts.append("(hitl_status IS NOT NULL AND hitl_status != '' AND hitl_status != 'resolved' AND resolved = 0)")
            elif unresolved_hitl == "noted":
                where_parts.append("(operator_note IS NOT NULL AND trim(operator_note) != '')")
            elif unresolved_hitl == "resolved":
                where_parts.append("resolved = 1")
        where_sql = (" WHERE " + " AND ".join(where_parts)) if where_parts else ""
        count_sql = "SELECT COUNT(*) FROM call_history" + where_sql
        total = conn.execute(count_sql, params).fetchone()[0]
        offset = (page - 1) * limit
        sel = "SELECT " + ", ".join(_CALL_HISTORY_COLS) + " FROM call_history" + where_sql
        sel += " ORDER BY start_time DESC LIMIT ? OFFSET ?"
        params.extend([limit, offset])
        rows = conn.execute(sel, params).fetchall()
        items = [_row_to_entry(r, _CALL_HISTORY_COLS) for r in rows]
        return items, total
    finally:
        conn.close()


def get_call_history_row(call_id: str) -> Optional[Dict[str, Any]]:
    conn = _conn()
    try:
        row = conn.execute(
            "SELECT " + ", ".join(_CALL_HISTORY_COLS) + " FROM call_history WHERE call_id = ?",
            (call_id,),
        ).fetchone()
        if not row:
            return None
        return _row_to_entry(row, _CALL_HISTORY_COLS)
    finally:
        conn.close()


def update_call_note_row(
    call_id: str,
    operator_note: str,
    follow_up_required: bool = False,
    follow_up_phone: Optional[str] = None,
) -> bool:
    """메모 저장. 행 없으면 False."""
    conn = _conn()
    try:
        cur = conn.execute(
            """UPDATE call_history SET operator_note = ?, follow_up_required = ?, follow_up_phone = ?
               WHERE call_id = ?""",
            (operator_note, 1 if follow_up_required else 0, follow_up_phone, call_id),
        )
        conn.commit()
        return cur.rowcount > 0
    finally:
        conn.close()


def resolve_call_row(call_id: str) -> bool:
    conn = _conn()
    try:
        cur = conn.execute(
            "UPDATE call_history SET resolved = 1, hitl_status = 'resolved' WHERE call_id = ?",
            (call_id,),
        )
        conn.commit()
        return cur.rowcount > 0
    finally:
        conn.close()


def save_call_summary(
    tenant_id: str,
    caller_id: str,
    call_id: str,
    summary_text: str,
) -> None:
    now = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    conn = _conn()
    try:
        conn.execute(
            "INSERT INTO call_summaries (tenant_id, caller_id, call_id, summary_text, created_at) VALUES (?, ?, ?, ?, ?)",
            (tenant_id, caller_id, call_id, summary_text, now),
        )
        conn.commit()
    finally:
        conn.close()


def get_recent_summaries_by_caller(
    tenant_id: str,
    caller_id: str,
    limit: int = 5,
) -> List[Dict[str, Any]]:
    """발신자별 최근 요약 (created_at DESC)."""
    if not tenant_id or not caller_id:
        return []
    conn = _conn()
    try:
        rows = conn.execute(
            """SELECT call_id, summary_text, created_at
               FROM call_summaries
               WHERE tenant_id = ? AND caller_id = ?
               ORDER BY created_at DESC
               LIMIT ?""",
            (tenant_id, caller_id, limit),
        ).fetchall()
        return [
            {"call_id": r[0], "summary_text": r[1], "created_at": r[2]}
            for r in rows
        ]
    finally:
        conn.close()


def get_all_call_history_rows(limit: int = 10000) -> List[Dict[str, Any]]:
    """테스트/디버그용. 전체 이력 (최대 limit건)."""
    items, _ = list_call_history_rows(page=1, limit=limit)
    return items


def end_call_and_save_summary(call_id: str) -> None:
    """통화 종료: end_time 갱신 + 요약 저장(placeholder 또는 user_question 기반). 동일 call_id 요약은 1회만 저장."""
    now = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    conn = _conn()
    try:
        conn.execute(
            "UPDATE call_history SET end_time = ? WHERE call_id = ?",
            (now, call_id),
        )
        row = conn.execute(
            "SELECT caller_id, callee_id, user_question FROM call_history WHERE call_id = ?",
            (call_id,),
        ).fetchone()
        conn.commit()
        if row:
            caller_id, callee_id, user_question = row
            caller_id = caller_id or ""
            callee_id = callee_id or ""
            if caller_id and callee_id:
                # 동일 통화에 대해 요약 중복 저장 방지 (emit_call_ended 이중 호출 시)
                existing = conn.execute(
                    "SELECT 1 FROM call_summaries WHERE call_id = ? LIMIT 1",
                    (call_id,),
                ).fetchone()
                if not existing:
                    summary = (user_question or "통화 완료").strip()
                    if not summary:
                        summary = "통화 완료"
                    save_call_summary(callee_id, caller_id, call_id, summary)
    finally:
        conn.close()
