"""
Call Control SQLite 저장소

call_routing_rules, call_schedules, announcement_profiles 테이블.
DB 경로: 환경변수 CALL_CONTROL_DB_PATH (기본 data/call_control.db).
"""

from __future__ import annotations

import json
import os
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

import structlog

logger = structlog.get_logger(__name__)

_DEFAULT_DB = "data/call_control.db"


def _get_db_path() -> str:
    path = os.environ.get("CALL_CONTROL_DB_PATH", _DEFAULT_DB)
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    return path


def _conn() -> sqlite3.Connection:
    c = sqlite3.connect(_get_db_path(), check_same_thread=False)
    c.row_factory = sqlite3.Row
    return c


def _now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


# ---------------------------------------------------------------------------
# Schema init
# ---------------------------------------------------------------------------

_DDL = """
CREATE TABLE IF NOT EXISTS call_ring_groups (
    id TEXT PRIMARY KEY,
    owner TEXT NOT NULL,
    name TEXT NOT NULL,
    members TEXT NOT NULL DEFAULT '[]',
    mode TEXT NOT NULL DEFAULT 'simultaneous',
    no_answer_timeout INTEGER NOT NULL DEFAULT 20,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_crg_owner ON call_ring_groups(owner);

CREATE TABLE IF NOT EXISTS call_caller_filters (
    id TEXT PRIMARY KEY,
    owner TEXT NOT NULL,
    name TEXT NOT NULL,
    pattern TEXT NOT NULL,
    action TEXT NOT NULL,
    no_answer_timeout INTEGER NOT NULL DEFAULT 20,
    forward_to TEXT,
    announcement_id TEXT,
    priority INTEGER NOT NULL DEFAULT 0,
    enabled INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_ccf_owner ON call_caller_filters(owner);
CREATE INDEX IF NOT EXISTS idx_ccf_priority ON call_caller_filters(owner, priority);

CREATE TABLE IF NOT EXISTS call_overflow_policies (
    owner TEXT PRIMARY KEY,
    enabled INTEGER NOT NULL DEFAULT 0,
    max_concurrent_calls INTEGER NOT NULL DEFAULT 3,
    overflow_action TEXT NOT NULL DEFAULT 'immediate_ai',
    announcement_id TEXT,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS call_routing_rules (
    id TEXT PRIMARY KEY,
    owner TEXT NOT NULL,
    name TEXT NOT NULL,
    priority INTEGER NOT NULL DEFAULT 100,
    action TEXT NOT NULL,
    no_answer_timeout INTEGER NOT NULL DEFAULT 20,
    forward_to TEXT,
    announcement_id TEXT,
    schedule_id TEXT,
    enabled INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_crr_owner ON call_routing_rules(owner);
CREATE INDEX IF NOT EXISTS idx_crr_priority ON call_routing_rules(owner, priority);

CREATE TABLE IF NOT EXISTS call_schedules (
    id TEXT PRIMARY KEY,
    owner TEXT NOT NULL,
    name TEXT NOT NULL,
    days TEXT NOT NULL DEFAULT '[]',
    time_ranges TEXT NOT NULL DEFAULT '[]',
    include_holidays INTEGER NOT NULL DEFAULT 0,
    holiday_country TEXT NOT NULL DEFAULT 'KR',
    timezone TEXT NOT NULL DEFAULT 'Asia/Seoul',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_cs_owner ON call_schedules(owner);

CREATE TABLE IF NOT EXISTS announcement_profiles (
    id TEXT PRIMARY KEY,
    owner TEXT NOT NULL,
    name TEXT NOT NULL,
    text TEXT NOT NULL DEFAULT '',
    audio_file TEXT,
    use_tts INTEGER NOT NULL DEFAULT 1,
    use_as_ringback_greeting INTEGER NOT NULL DEFAULT 0,
    generation_mode TEXT NOT NULL DEFAULT 'tts',
    tts_background_music INTEGER NOT NULL DEFAULT 0,
    tts_background_style TEXT,
    suno_lyrics TEXT,
    suno_style TEXT,
    suno_audio_url TEXT,
    suno_task_id TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_ap_owner ON announcement_profiles(owner);

CREATE TABLE IF NOT EXISTS ringback_schedule_assignments (
    id TEXT PRIMARY KEY,
    owner TEXT NOT NULL,
    name TEXT NOT NULL DEFAULT '',
    schedule_id TEXT,
    position INTEGER NOT NULL DEFAULT 0,
    enabled INTEGER NOT NULL DEFAULT 1,
    generation_mode TEXT NOT NULL DEFAULT 'suno',
    tts_text TEXT NOT NULL DEFAULT '',
    tts_audio_path TEXT,
    suno_lyrics TEXT,
    suno_style TEXT,
    suno_title TEXT,
    suno_vocal_gender TEXT NOT NULL DEFAULT 'm',
    suno_duration_target INTEGER NOT NULL DEFAULT 60,
    suno_audio_path TEXT,
    suno_audio_url TEXT,
    suno_task_id TEXT,
    suno_generation_status TEXT NOT NULL DEFAULT 'idle',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_rsa_owner ON ringback_schedule_assignments(owner);
CREATE INDEX IF NOT EXISTS idx_rsa_owner_pos ON ringback_schedule_assignments(owner, position);

CREATE TABLE IF NOT EXISTS call_forward_targets (
    id TEXT PRIMARY KEY,
    owner TEXT NOT NULL,
    name TEXT NOT NULL,
    kind TEXT NOT NULL DEFAULT 'single',
    single_extension TEXT,
    members TEXT NOT NULL DEFAULT '[]',
    ring_mode TEXT NOT NULL DEFAULT 'simultaneous',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_cft_owner ON call_forward_targets(owner);
"""


def _migrate_announcement_profiles(conn: sqlite3.Connection) -> None:
    """announcement_profiles 테이블에 신규 컬럼과 인덱스를 추가한다 (기존 DB 호환)."""
    columns = {row[1] for row in conn.execute("PRAGMA table_info(announcement_profiles)")}

    new_columns = [
        ("use_as_ringback_greeting", "INTEGER NOT NULL DEFAULT 0"),
        ("generation_mode", "TEXT NOT NULL DEFAULT 'tts'"),
        ("tts_background_music", "INTEGER NOT NULL DEFAULT 0"),
        ("tts_background_style", "TEXT"),
        ("suno_lyrics", "TEXT"),
        ("suno_style", "TEXT"),
        ("suno_audio_url", "TEXT"),
        ("suno_task_id", "TEXT"),
    ]
    for col_name, col_def in new_columns:
        if col_name not in columns:
            conn.execute(f"ALTER TABLE announcement_profiles ADD COLUMN {col_name} {col_def}")
            logger.info("call_control_db_migrated", added_column=col_name)

    # 인덱스 추가 (ALTER 이후 실행)
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_ap_ringback ON announcement_profiles(owner, use_as_ringback_greeting)"
    )


def _booking_music_local_path(owner: str, item_id: int) -> str:
    """예약 DB ringback_music_items 의 로컬 MP3 경로 (마이그레이션용)."""
    import os
    from pathlib import Path

    raw = os.environ.get("BOOKING_DB_PATH") or "./data/booking.db"
    p = Path(raw).resolve()
    if not p.is_file():
        return ""
    c2 = sqlite3.connect(str(p), check_same_thread=False)
    c2.row_factory = sqlite3.Row
    try:
        row = c2.execute(
            "SELECT local_path FROM ringback_music_items WHERE id = ? AND owner = ?",
            (item_id, owner),
        ).fetchone()
        if not row:
            return ""
        lp = (row["local_path"] or "").strip()
        return lp if lp and os.path.isfile(lp) else ""
    finally:
        c2.close()


def _migrate_ringback_schedule_assignments_v2(conn: sqlite3.Connection) -> None:
    """music_item_id·priority 스키마 → TTS/Suno 필드 + position + 드래그 순서."""
    cur = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='ringback_schedule_assignments'"
    )
    if not cur.fetchone():
        return
    cols = {row[1] for row in conn.execute("PRAGMA table_info(ringback_schedule_assignments)")}
    if "generation_mode" in cols:
        return

    old_rows = [dict(r) for r in conn.execute("SELECT * FROM ringback_schedule_assignments").fetchall()]
    conn.execute("DROP TABLE ringback_schedule_assignments")
    conn.executescript(
        """
CREATE TABLE ringback_schedule_assignments (
    id TEXT PRIMARY KEY,
    owner TEXT NOT NULL,
    name TEXT NOT NULL DEFAULT '',
    schedule_id TEXT,
    position INTEGER NOT NULL DEFAULT 0,
    enabled INTEGER NOT NULL DEFAULT 1,
    generation_mode TEXT NOT NULL DEFAULT 'suno',
    tts_text TEXT NOT NULL DEFAULT '',
    suno_lyrics TEXT,
    suno_style TEXT,
    suno_title TEXT,
    suno_vocal_gender TEXT NOT NULL DEFAULT 'm',
    suno_duration_target INTEGER NOT NULL DEFAULT 60,
    suno_audio_path TEXT,
    suno_audio_url TEXT,
    suno_task_id TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_rsa_owner ON ringback_schedule_assignments(owner);
CREATE INDEX IF NOT EXISTS idx_rsa_owner_pos ON ringback_schedule_assignments(owner, position);
"""
    )

    def _sort_key(r: Dict[str, Any]) -> tuple:
        return (int(r.get("priority") or 100), str(r.get("created_at") or ""))

    for pos, row in enumerate(sorted(old_rows, key=_sort_key)):
        oid = row.get("owner") or ""
        mid = row.get("music_item_id")
        audio_path = ""
        if mid is not None:
            try:
                audio_path = _booking_music_local_path(oid, int(mid)) or ""
            except Exception:
                audio_path = ""
        conn.execute(
            """
            INSERT INTO ringback_schedule_assignments (
                id, owner, name, schedule_id, position, enabled, generation_mode, tts_text,
                suno_lyrics, suno_style, suno_title, suno_vocal_gender, suno_duration_target,
                suno_audio_path, suno_audio_url, suno_task_id, created_at, updated_at
            ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            """,
            (
                row["id"],
                oid,
                row.get("name") or "",
                row.get("schedule_id"),
                pos,
                1 if row.get("enabled") else 0,
                "suno",
                "",
                None,
                None,
                row.get("name") or "통화 연결음",
                "m",
                60,
                audio_path or None,
                None,
                None,
                row["created_at"],
                row["updated_at"],
            ),
        )
    logger.info("call_control_ringback_assignments_migrated_v2", rows=len(old_rows))


def _migrate_ringback_schedule_assignments_suno_status(conn: sqlite3.Connection) -> None:
    """ringback_schedule_assignments 에 Suno 생성 진행 상태 컬럼 추가."""
    cur = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='ringback_schedule_assignments'"
    )
    if not cur.fetchone():
        return
    cols = {row[1] for row in conn.execute("PRAGMA table_info(ringback_schedule_assignments)")}
    if "suno_generation_status" in cols:
        return
    conn.execute(
        "ALTER TABLE ringback_schedule_assignments "
        "ADD COLUMN suno_generation_status TEXT NOT NULL DEFAULT 'idle'"
    )
    logger.info("call_control_db_migrated", added_column="suno_generation_status")


def _migrate_ringback_schedule_assignments_suno_task_index(conn: sqlite3.Connection) -> None:
    """``suno_task_id`` 로 콜백 매칭 시 조회용 인덱스."""
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_rsa_suno_task ON ringback_schedule_assignments(suno_task_id)"
    )


def _migrate_ringback_schedule_assignments_tts_audio(conn: sqlite3.Connection) -> None:
    """통화 연결음 TTS 사전 렌더 WAV 경로."""
    cur = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='ringback_schedule_assignments'"
    )
    if not cur.fetchone():
        return
    cols = {row[1] for row in conn.execute("PRAGMA table_info(ringback_schedule_assignments)")}
    if "tts_audio_path" in cols:
        return
    conn.execute("ALTER TABLE ringback_schedule_assignments ADD COLUMN tts_audio_path TEXT")
    logger.info("call_control_db_migrated", added_column="tts_audio_path")


def init_db() -> None:
    """테이블과 인덱스 생성 (없을 때만). 기존 테이블 컬럼 migration도 수행."""
    conn = _conn()
    try:
        conn.executescript(_DDL)
        _migrate_announcement_profiles(conn)
        _migrate_ringback_schedule_assignments_v2(conn)
        _migrate_ringback_schedule_assignments_suno_status(conn)
        _migrate_ringback_schedule_assignments_tts_audio(conn)
        _migrate_ringback_schedule_assignments_suno_task_index(conn)
        conn.commit()
        logger.info("call_control_db_initialized", path=_get_db_path())
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# RoutingRule CRUD
# ---------------------------------------------------------------------------


def _rule_from_row(row: sqlite3.Row) -> Dict[str, Any]:
    d = dict(row)
    d["enabled"] = bool(d["enabled"])
    return d


def list_rules(owner: str) -> List[Dict[str, Any]]:
    conn = _conn()
    try:
        rows = conn.execute(
            "SELECT * FROM call_routing_rules WHERE owner = ? ORDER BY priority ASC, created_at ASC",
            (owner,),
        ).fetchall()
        return [_rule_from_row(r) for r in rows]
    finally:
        conn.close()


def get_rule(rule_id: str) -> Optional[Dict[str, Any]]:
    conn = _conn()
    try:
        row = conn.execute(
            "SELECT * FROM call_routing_rules WHERE id = ?", (rule_id,)
        ).fetchone()
        return _rule_from_row(row) if row else None
    finally:
        conn.close()


def create_rule(data: Dict[str, Any]) -> Dict[str, Any]:
    now = _now()
    conn = _conn()
    try:
        conn.execute(
            """INSERT INTO call_routing_rules
               (id, owner, name, priority, action, no_answer_timeout,
                forward_to, announcement_id, schedule_id, enabled, created_at, updated_at)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                data["id"],
                data["owner"],
                data["name"],
                data.get("priority", 100),
                data["action"],
                data.get("no_answer_timeout", 20),
                data.get("forward_to"),
                data.get("announcement_id"),
                data.get("schedule_id"),
                1 if data.get("enabled", True) else 0,
                now,
                now,
            ),
        )
        conn.commit()
        return get_rule(data["id"])  # type: ignore[return-value]
    finally:
        conn.close()


def update_rule(rule_id: str, updates: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    now = _now()
    allowed = {
        "name", "priority", "action", "no_answer_timeout",
        "forward_to", "announcement_id", "schedule_id", "enabled",
    }
    filtered = {k: v for k, v in updates.items() if k in allowed and v is not None}
    if "enabled" in filtered:
        filtered["enabled"] = 1 if filtered["enabled"] else 0
    if not filtered:
        return get_rule(rule_id)
    set_clause = ", ".join(f"{k} = ?" for k in filtered)
    values = list(filtered.values()) + [now, rule_id]
    conn = _conn()
    try:
        conn.execute(
            f"UPDATE call_routing_rules SET {set_clause}, updated_at = ? WHERE id = ?",
            values,
        )
        conn.commit()
        return get_rule(rule_id)
    finally:
        conn.close()


def delete_rule(rule_id: str) -> bool:
    conn = _conn()
    try:
        cur = conn.execute(
            "DELETE FROM call_routing_rules WHERE id = ?", (rule_id,)
        )
        conn.commit()
        return cur.rowcount > 0
    finally:
        conn.close()


def update_rule_priority(rule_id: str, priority: int) -> Optional[Dict[str, Any]]:
    return update_rule(rule_id, {"priority": priority})


# ---------------------------------------------------------------------------
# Schedule CRUD
# ---------------------------------------------------------------------------


def _schedule_from_row(row: sqlite3.Row) -> Dict[str, Any]:
    d = dict(row)
    d["include_holidays"] = bool(d["include_holidays"])
    for k in ("days", "time_ranges"):
        try:
            d[k] = json.loads(d[k]) if isinstance(d[k], str) else d[k]
        except Exception:
            d[k] = []
    return d


def list_schedules(owner: str) -> List[Dict[str, Any]]:
    conn = _conn()
    try:
        rows = conn.execute(
            "SELECT * FROM call_schedules WHERE owner = ? ORDER BY created_at ASC",
            (owner,),
        ).fetchall()
        return [_schedule_from_row(r) for r in rows]
    finally:
        conn.close()


def get_schedule(schedule_id: str) -> Optional[Dict[str, Any]]:
    conn = _conn()
    try:
        row = conn.execute(
            "SELECT * FROM call_schedules WHERE id = ?", (schedule_id,)
        ).fetchone()
        return _schedule_from_row(row) if row else None
    finally:
        conn.close()


def create_schedule(data: Dict[str, Any]) -> Dict[str, Any]:
    now = _now()
    conn = _conn()
    try:
        conn.execute(
            """INSERT INTO call_schedules
               (id, owner, name, days, time_ranges, include_holidays, holiday_country, timezone, created_at, updated_at)
               VALUES (?,?,?,?,?,?,?,?,?,?)""",
            (
                data["id"],
                data["owner"],
                data["name"],
                json.dumps(data.get("days", []), ensure_ascii=False),
                json.dumps(data.get("time_ranges", []), ensure_ascii=False),
                1 if data.get("include_holidays") else 0,
                data.get("holiday_country", "KR"),
                data.get("timezone", "Asia/Seoul"),
                now,
                now,
            ),
        )
        conn.commit()
        return get_schedule(data["id"])  # type: ignore[return-value]
    finally:
        conn.close()


def update_schedule(schedule_id: str, updates: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    now = _now()
    allowed = {"name", "days", "time_ranges", "include_holidays", "holiday_country", "timezone"}
    filtered: Dict[str, Any] = {}
    for k, v in updates.items():
        if k not in allowed or v is None:
            continue
        if k in ("days", "time_ranges"):
            filtered[k] = json.dumps(v, ensure_ascii=False)
        elif k == "include_holidays":
            filtered[k] = 1 if v else 0
        else:
            filtered[k] = v
    if not filtered:
        return get_schedule(schedule_id)
    set_clause = ", ".join(f"{k} = ?" for k in filtered)
    values = list(filtered.values()) + [now, schedule_id]
    conn = _conn()
    try:
        conn.execute(
            f"UPDATE call_schedules SET {set_clause}, updated_at = ? WHERE id = ?",
            values,
        )
        conn.commit()
        return get_schedule(schedule_id)
    finally:
        conn.close()


def delete_schedule(schedule_id: str) -> bool:
    conn = _conn()
    try:
        cur = conn.execute(
            "DELETE FROM call_schedules WHERE id = ?", (schedule_id,)
        )
        conn.commit()
        return cur.rowcount > 0
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# AnnouncementProfile CRUD
# ---------------------------------------------------------------------------


def _announcement_from_row(row: sqlite3.Row) -> Dict[str, Any]:
    d = dict(row)
    d["use_tts"] = bool(d["use_tts"])
    d["use_as_ringback_greeting"] = bool(d.get("use_as_ringback_greeting", 0))
    d["tts_background_music"] = bool(d.get("tts_background_music", 0))
    d.setdefault("generation_mode", "tts")
    return d


def list_announcements(owner: str) -> List[Dict[str, Any]]:
    conn = _conn()
    try:
        rows = conn.execute(
            "SELECT * FROM announcement_profiles WHERE owner = ? ORDER BY created_at ASC",
            (owner,),
        ).fetchall()
        return [_announcement_from_row(r) for r in rows]
    finally:
        conn.close()


def get_announcement(announcement_id: str) -> Optional[Dict[str, Any]]:
    conn = _conn()
    try:
        row = conn.execute(
            "SELECT * FROM announcement_profiles WHERE id = ?", (announcement_id,)
        ).fetchone()
        return _announcement_from_row(row) if row else None
    finally:
        conn.close()


def create_announcement(data: Dict[str, Any]) -> Dict[str, Any]:
    now = _now()
    conn = _conn()
    try:
        # use_as_ringback_greeting=True 시 다른 행의 플래그를 먼저 해제
        if data.get("use_as_ringback_greeting"):
            conn.execute(
                "UPDATE announcement_profiles SET use_as_ringback_greeting = 0 WHERE owner = ?",
                (data["owner"],),
            )
        conn.execute(
            """INSERT INTO announcement_profiles
               (id, owner, name, text, audio_file, use_tts, use_as_ringback_greeting,
                generation_mode, tts_background_music, tts_background_style,
                suno_lyrics, suno_style, suno_audio_url, suno_task_id,
                created_at, updated_at)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                data["id"],
                data["owner"],
                data["name"],
                data.get("text", ""),
                data.get("audio_file"),
                1 if data.get("use_tts", True) else 0,
                1 if data.get("use_as_ringback_greeting") else 0,
                data.get("generation_mode", "tts"),
                1 if data.get("tts_background_music") else 0,
                data.get("tts_background_style"),
                data.get("suno_lyrics"),
                data.get("suno_style"),
                data.get("suno_audio_url"),
                data.get("suno_task_id"),
                now,
                now,
            ),
        )
        conn.commit()
        return get_announcement(data["id"])  # type: ignore[return-value]
    finally:
        conn.close()


def update_announcement(announcement_id: str, updates: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    now = _now()
    bool_cols = {"use_tts", "use_as_ringback_greeting", "tts_background_music"}
    allowed = {
        "name", "text", "audio_file", "use_tts", "use_as_ringback_greeting",
        "generation_mode", "tts_background_music", "tts_background_style",
        "suno_lyrics", "suno_style", "suno_audio_url", "suno_task_id",
    }
    filtered: Dict[str, Any] = {}
    for k, v in updates.items():
        if k not in allowed or v is None:
            continue
        filtered[k] = (1 if v else 0) if k in bool_cols else v
    if not filtered:
        return get_announcement(announcement_id)
    conn = _conn()
    try:
        # use_as_ringback_greeting=True로 변경할 때 다른 행 플래그 해제
        if filtered.get("use_as_ringback_greeting") == 1:
            existing = get_announcement(announcement_id)
            if existing:
                conn.execute(
                    "UPDATE announcement_profiles SET use_as_ringback_greeting = 0 WHERE owner = ? AND id != ?",
                    (existing["owner"], announcement_id),
                )
        set_clause = ", ".join(f"{k} = ?" for k in filtered)
        values = list(filtered.values()) + [now, announcement_id]
        conn.execute(
            f"UPDATE announcement_profiles SET {set_clause}, updated_at = ? WHERE id = ?",
            values,
        )
        conn.commit()
        return get_announcement(announcement_id)
    finally:
        conn.close()


def get_ringback_greeting_announcement(owner: str) -> Optional[Dict[str, Any]]:
    """owner의 안내멘트 중 use_as_ringback_greeting=1 인 것을 반환한다."""
    conn = _conn()
    try:
        row = conn.execute(
            "SELECT * FROM announcement_profiles WHERE owner = ? AND use_as_ringback_greeting = 1 LIMIT 1",
            (owner,),
        ).fetchone()
        return _announcement_from_row(row) if row else None
    finally:
        conn.close()


def delete_announcement(announcement_id: str) -> bool:
    conn = _conn()
    try:
        cur = conn.execute(
            "DELETE FROM announcement_profiles WHERE id = ?", (announcement_id,)
        )
        conn.commit()
        return cur.rowcount > 0
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Ringback schedule assignments (시간 스케줄 → 통화 연결음)
# ---------------------------------------------------------------------------


def _rsa_from_row(row: sqlite3.Row) -> Dict[str, Any]:
    d = dict(row)
    d["enabled"] = bool(d["enabled"])
    sid = d.get("schedule_id")
    if sid is not None and str(sid).strip() == "":
        d["schedule_id"] = None
    if not (d.get("suno_generation_status") or "").strip():
        d["suno_generation_status"] = "idle"
    return d


def list_ringback_schedule_assignments(owner: str) -> List[Dict[str, Any]]:
    conn = _conn()
    try:
        rows = conn.execute(
            """
            SELECT * FROM ringback_schedule_assignments
            WHERE owner = ?
            ORDER BY position ASC, created_at ASC
            """,
            (owner,),
        ).fetchall()
        return [_rsa_from_row(r) for r in rows]
    finally:
        conn.close()


def get_ringback_schedule_assignment(assignment_id: str) -> Optional[Dict[str, Any]]:
    conn = _conn()
    try:
        row = conn.execute(
            "SELECT * FROM ringback_schedule_assignments WHERE id = ?",
            (assignment_id,),
        ).fetchone()
        return _rsa_from_row(row) if row else None
    finally:
        conn.close()


def get_ringback_schedule_assignment_by_suno_task_id(task_id: str) -> Optional[Dict[str, Any]]:
    """Suno ``task_id`` 가 일치하는 통화 연결음 할당 1건 (콜백·폴링 매칭용)."""
    tid = (task_id or "").strip()
    if not tid:
        return None
    conn = _conn()
    try:
        row = conn.execute(
            "SELECT * FROM ringback_schedule_assignments WHERE suno_task_id = ? LIMIT 1",
            (tid,),
        ).fetchone()
        return _rsa_from_row(row) if row else None
    finally:
        conn.close()


def create_ringback_schedule_assignment(data: Dict[str, Any]) -> Dict[str, Any]:
    now = _now()
    sid = data.get("schedule_id")
    if sid is not None and str(sid).strip() == "":
        sid = None
    gm = (data.get("generation_mode") or "suno").strip().lower()
    if gm not in ("tts", "suno"):
        gm = "suno"
    conn = _conn()
    try:
        pos_row = conn.execute(
            "SELECT COALESCE(MAX(position), -1) + 1 AS n FROM ringback_schedule_assignments WHERE owner = ?",
            (data["owner"],),
        ).fetchone()
        pos = int(data["position"]) if data.get("position") is not None else int(pos_row["n"] if pos_row else 0)
        dur = int(data.get("suno_duration_target") or 60)
        vg = (data.get("suno_vocal_gender") or "m").strip().lower()[:1]
        if vg not in ("m", "f"):
            vg = "m"
        sgs = (data.get("suno_generation_status") or "idle").strip().lower()
        if sgs not in ("idle", "pending", "complete", "failed"):
            sgs = "idle"
        conn.execute(
            """
            INSERT INTO ringback_schedule_assignments (
                id, owner, name, schedule_id, position, enabled, generation_mode, tts_text,
                tts_audio_path,
                suno_lyrics, suno_style, suno_title, suno_vocal_gender, suno_duration_target,
                suno_audio_path, suno_audio_url, suno_task_id, suno_generation_status,
                created_at, updated_at
            ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            """,
            (
                data["id"],
                data["owner"],
                data.get("name", "") or "",
                sid,
                pos,
                1 if data.get("enabled", True) else 0,
                gm,
                (data.get("tts_text") or "") or "",
                (data.get("tts_audio_path") or None) or None,
                data.get("suno_lyrics"),
                data.get("suno_style"),
                data.get("suno_title"),
                vg,
                dur,
                (data.get("suno_audio_path") or None) or None,
                (data.get("suno_audio_url") or None) or None,
                (data.get("suno_task_id") or None) or None,
                sgs,
                now,
                now,
            ),
        )
        conn.commit()
        return get_ringback_schedule_assignment(data["id"])  # type: ignore[return-value]
    finally:
        conn.close()


def update_ringback_schedule_assignment(
    assignment_id: str, updates: Dict[str, Any]
) -> Optional[Dict[str, Any]]:
    now = _now()
    allowed = {
        "name",
        "schedule_id",
        "position",
        "enabled",
        "generation_mode",
        "tts_text",
        "tts_audio_path",
        "suno_lyrics",
        "suno_style",
        "suno_title",
        "suno_vocal_gender",
        "suno_duration_target",
        "suno_audio_path",
        "suno_audio_url",
        "suno_task_id",
        "suno_generation_status",
    }
    filtered: Dict[str, Any] = {}
    for k, v in updates.items():
        if k not in allowed:
            continue
        if k == "enabled":
            filtered[k] = 1 if v else 0
        elif k == "schedule_id":
            filtered[k] = None if v is None or str(v).strip() == "" else str(v)
        elif k == "position":
            filtered[k] = int(v)
        elif k == "suno_duration_target":
            filtered[k] = int(v) if v is not None else 60
        elif k == "generation_mode":
            gm = str(v or "suno").strip().lower()
            filtered[k] = gm if gm in ("tts", "suno") else "suno"
        elif k == "suno_vocal_gender":
            c = str(v or "m").strip().lower()[:1]
            filtered[k] = c if c in ("m", "f") else "m"
        elif k in (
            "suno_lyrics",
            "suno_style",
            "suno_title",
            "suno_audio_path",
            "suno_audio_url",
            "suno_task_id",
            "suno_generation_status",
            "tts_audio_path",
        ):
            if k == "suno_generation_status":
                s = (str(v) if v is not None else "idle").strip().lower()
                filtered[k] = s if s in ("idle", "pending", "complete", "failed") else "idle"
            else:
                filtered[k] = None if v is None else str(v)
        elif k == "tts_text":
            filtered[k] = str(v or "")
        else:
            filtered[k] = v
    if not filtered:
        return get_ringback_schedule_assignment(assignment_id)
    set_clause = ", ".join(f"{k} = ?" for k in filtered)
    values = list(filtered.values()) + [now, assignment_id]
    conn = _conn()
    try:
        conn.execute(
            f"UPDATE ringback_schedule_assignments SET {set_clause}, updated_at = ? WHERE id = ?",
            values,
        )
        conn.commit()
        return get_ringback_schedule_assignment(assignment_id)
    finally:
        conn.close()


def reorder_ringback_schedule_assignments(owner: str, ordered_ids: List[str]) -> None:
    """목록 순서(위→아래)대로 position 0..n-1 재설정."""
    now = _now()
    conn = _conn()
    try:
        for pos, aid in enumerate(ordered_ids):
            conn.execute(
                """
                UPDATE ringback_schedule_assignments
                SET position = ?, updated_at = ?
                WHERE id = ? AND owner = ?
                """,
                (pos, now, aid, owner),
            )
        conn.commit()
    finally:
        conn.close()


def delete_ringback_schedule_assignment(assignment_id: str) -> bool:
    conn = _conn()
    try:
        cur = conn.execute(
            "DELETE FROM ringback_schedule_assignments WHERE id = ?",
            (assignment_id,),
        )
        conn.commit()
        return cur.rowcount > 0
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# RingGroup CRUD
# ---------------------------------------------------------------------------


def _ring_group_from_row(row: sqlite3.Row) -> Dict[str, Any]:
    d = dict(row)
    try:
        d["members"] = json.loads(d["members"]) if isinstance(d["members"], str) else d["members"]
    except Exception:
        d["members"] = []
    return d


def list_ring_groups(owner: str) -> List[Dict[str, Any]]:
    conn = _conn()
    try:
        rows = conn.execute(
            "SELECT * FROM call_ring_groups WHERE owner = ? ORDER BY created_at ASC",
            (owner,),
        ).fetchall()
        return [_ring_group_from_row(r) for r in rows]
    finally:
        conn.close()


def get_ring_group(group_id: str) -> Optional[Dict[str, Any]]:
    conn = _conn()
    try:
        row = conn.execute(
            "SELECT * FROM call_ring_groups WHERE id = ?", (group_id,)
        ).fetchone()
        return _ring_group_from_row(row) if row else None
    finally:
        conn.close()


def create_ring_group(data: Dict[str, Any]) -> Dict[str, Any]:
    now = _now()
    conn = _conn()
    try:
        conn.execute(
            """INSERT INTO call_ring_groups (id, owner, name, members, mode, no_answer_timeout, created_at, updated_at)
               VALUES (?,?,?,?,?,?,?,?)""",
            (
                data["id"],
                data["owner"],
                data["name"],
                json.dumps(data.get("members", []), ensure_ascii=False),
                data.get("mode", "simultaneous"),
                data.get("no_answer_timeout", 20),
                now,
                now,
            ),
        )
        conn.commit()
        return get_ring_group(data["id"])  # type: ignore[return-value]
    finally:
        conn.close()


def update_ring_group(group_id: str, updates: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    now = _now()
    allowed = {"name", "members", "mode", "no_answer_timeout"}
    filtered: Dict[str, Any] = {}
    for k, v in updates.items():
        if k not in allowed or v is None:
            continue
        filtered[k] = json.dumps(v, ensure_ascii=False) if k == "members" else v
    if not filtered:
        return get_ring_group(group_id)
    set_clause = ", ".join(f"{k} = ?" for k in filtered)
    values = list(filtered.values()) + [now, group_id]
    conn = _conn()
    try:
        conn.execute(
            f"UPDATE call_ring_groups SET {set_clause}, updated_at = ? WHERE id = ?", values
        )
        conn.commit()
        return get_ring_group(group_id)
    finally:
        conn.close()


def delete_ring_group(group_id: str) -> bool:
    conn = _conn()
    try:
        cur = conn.execute("DELETE FROM call_ring_groups WHERE id = ?", (group_id,))
        conn.commit()
        return cur.rowcount > 0
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# ForwardTarget (착신 전환 대상: 단일 내선 또는 그룹)
# ---------------------------------------------------------------------------


def _forward_target_from_row(row: sqlite3.Row) -> Dict[str, Any]:
    d = dict(row)
    raw = d.get("members")
    try:
        d["members"] = json.loads(raw) if isinstance(raw, str) else (raw or [])
    except Exception:
        d["members"] = []
    if not isinstance(d["members"], list):
        d["members"] = []
    return d


def list_forward_targets(owner: str) -> List[Dict[str, Any]]:
    conn = _conn()
    try:
        rows = conn.execute(
            "SELECT * FROM call_forward_targets WHERE owner = ? ORDER BY created_at ASC",
            (owner,),
        ).fetchall()
        return [_forward_target_from_row(r) for r in rows]
    finally:
        conn.close()


def get_forward_target(target_id: str) -> Optional[Dict[str, Any]]:
    conn = _conn()
    try:
        row = conn.execute(
            "SELECT * FROM call_forward_targets WHERE id = ?", (target_id,)
        ).fetchone()
        return _forward_target_from_row(row) if row else None
    finally:
        conn.close()


def create_forward_target(data: Dict[str, Any]) -> Dict[str, Any]:
    now = _now()
    conn = _conn()
    try:
        conn.execute(
            """INSERT INTO call_forward_targets
               (id, owner, name, kind, single_extension, members, ring_mode, created_at, updated_at)
               VALUES (?,?,?,?,?,?,?,?,?)""",
            (
                data["id"],
                data["owner"],
                data["name"],
                data.get("kind", "single"),
                data.get("single_extension"),
                json.dumps(data.get("members", []), ensure_ascii=False),
                data.get("ring_mode", "simultaneous"),
                now,
                now,
            ),
        )
        conn.commit()
        return get_forward_target(data["id"])  # type: ignore[return-value]
    finally:
        conn.close()


def update_forward_target(target_id: str, updates: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    now = _now()
    allowed = {"name", "kind", "single_extension", "members", "ring_mode"}
    filtered: Dict[str, Any] = {}
    for k, v in updates.items():
        if k not in allowed:
            continue
        if k == "members":
            if v is None:
                continue
            filtered[k] = json.dumps(v if isinstance(v, list) else [], ensure_ascii=False)
        elif k == "single_extension":
            filtered[k] = v  # None 허용 (그룹 전환 시 비움)
        elif v is not None:
            filtered[k] = v
    if not filtered:
        return get_forward_target(target_id)
    set_clause = ", ".join(f"{k} = ?" for k in filtered)
    values = list(filtered.values()) + [now, target_id]
    conn = _conn()
    try:
        conn.execute(
            f"UPDATE call_forward_targets SET {set_clause}, updated_at = ? WHERE id = ?", values
        )
        conn.commit()
        return get_forward_target(target_id)
    finally:
        conn.close()


def delete_forward_target(target_id: str) -> bool:
    conn = _conn()
    try:
        cur = conn.execute("DELETE FROM call_forward_targets WHERE id = ?", (target_id,))
        conn.commit()
        return cur.rowcount > 0
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# CallerFilter CRUD
# ---------------------------------------------------------------------------


def _caller_filter_from_row(row: sqlite3.Row) -> Dict[str, Any]:
    d = dict(row)
    d["enabled"] = bool(d["enabled"])
    return d


def list_caller_filters(owner: str) -> List[Dict[str, Any]]:
    conn = _conn()
    try:
        rows = conn.execute(
            "SELECT * FROM call_caller_filters WHERE owner = ? ORDER BY priority ASC, created_at ASC",
            (owner,),
        ).fetchall()
        return [_caller_filter_from_row(r) for r in rows]
    finally:
        conn.close()


def get_caller_filter(filter_id: str) -> Optional[Dict[str, Any]]:
    conn = _conn()
    try:
        row = conn.execute(
            "SELECT * FROM call_caller_filters WHERE id = ?", (filter_id,)
        ).fetchone()
        return _caller_filter_from_row(row) if row else None
    finally:
        conn.close()


def create_caller_filter(data: Dict[str, Any]) -> Dict[str, Any]:
    now = _now()
    conn = _conn()
    try:
        conn.execute(
            """INSERT INTO call_caller_filters
               (id, owner, name, pattern, action, no_answer_timeout, forward_to, announcement_id, priority, enabled, created_at, updated_at)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                data["id"],
                data["owner"],
                data["name"],
                data["pattern"],
                data["action"],
                data.get("no_answer_timeout", 20),
                data.get("forward_to"),
                data.get("announcement_id"),
                data.get("priority", 0),
                1 if data.get("enabled", True) else 0,
                now,
                now,
            ),
        )
        conn.commit()
        return get_caller_filter(data["id"])  # type: ignore[return-value]
    finally:
        conn.close()


def update_caller_filter(filter_id: str, updates: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    now = _now()
    allowed = {"name", "pattern", "action", "no_answer_timeout", "forward_to", "announcement_id", "priority", "enabled"}
    filtered = {k: (1 if v else 0) if k == "enabled" else v for k, v in updates.items() if k in allowed and v is not None}
    if not filtered:
        return get_caller_filter(filter_id)
    set_clause = ", ".join(f"{k} = ?" for k in filtered)
    values = list(filtered.values()) + [now, filter_id]
    conn = _conn()
    try:
        conn.execute(f"UPDATE call_caller_filters SET {set_clause}, updated_at = ? WHERE id = ?", values)
        conn.commit()
        return get_caller_filter(filter_id)
    finally:
        conn.close()


def delete_caller_filter(filter_id: str) -> bool:
    conn = _conn()
    try:
        cur = conn.execute("DELETE FROM call_caller_filters WHERE id = ?", (filter_id,))
        conn.commit()
        return cur.rowcount > 0
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# OverflowPolicy CRUD
# ---------------------------------------------------------------------------


def _overflow_from_row(row: sqlite3.Row) -> Dict[str, Any]:
    d = dict(row)
    d["enabled"] = bool(d["enabled"])
    return d


def get_overflow_policy(owner: str) -> Optional[Dict[str, Any]]:
    conn = _conn()
    try:
        row = conn.execute(
            "SELECT * FROM call_overflow_policies WHERE owner = ?", (owner,)
        ).fetchone()
        return _overflow_from_row(row) if row else None
    finally:
        conn.close()


def upsert_overflow_policy(owner: str, data: Dict[str, Any]) -> Dict[str, Any]:
    now = _now()
    conn = _conn()
    try:
        conn.execute(
            """INSERT INTO call_overflow_policies (owner, enabled, max_concurrent_calls, overflow_action, announcement_id, updated_at)
               VALUES (?,?,?,?,?,?)
               ON CONFLICT(owner) DO UPDATE SET
                 enabled=excluded.enabled,
                 max_concurrent_calls=excluded.max_concurrent_calls,
                 overflow_action=excluded.overflow_action,
                 announcement_id=excluded.announcement_id,
                 updated_at=excluded.updated_at""",
            (
                owner,
                1 if data.get("enabled") else 0,
                data.get("max_concurrent_calls", 3),
                data.get("overflow_action", "immediate_ai"),
                data.get("announcement_id"),
                now,
            ),
        )
        conn.commit()
        return get_overflow_policy(owner)  # type: ignore[return-value]
    finally:
        conn.close()
