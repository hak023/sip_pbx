"""contact_folders 테이블 CRUD (booking.db)."""

from __future__ import annotations

import logging
import re
import uuid
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


def default_unfiled_folder_id(owner: str) -> str:
    """테넌트별 기본 '미분류' 폴더 id (프론트 `defaultUnfiledFolderId` 와 동일 규칙)."""
    own = (owner or "").strip() or "unknown"
    slug = re.sub(r"[^0-9a-zA-Z]+", "_", own).strip("_")[:48] or "x"
    return f"cf_unfiled_{slug}"


def ensure_default_unfiled_folder(conn: Any, owner: str) -> str:
    """행이 없으면 '미분류' 폴더 생성 + 구버전 데이터 마이그레이션(한 번)."""
    own = (owner or "").strip()
    fid = default_unfiled_folder_id(own)
    row = conn.execute(
        "SELECT 1 FROM contact_folders WHERE id = ? AND owner = ?",
        (fid, own),
    ).fetchone()
    if row:
        return fid
    conn.execute(
        """
        INSERT INTO contact_folders (id, owner, parent_id, name, sort_order, created_at, updated_at)
        VALUES (?, ?, NULL, '미분류', -9999, datetime('now','localtime'), datetime('now','localtime'))
        """,
        (fid, own),
    )
    conn.execute(
        """
        UPDATE caller_contacts SET folder_id = ?, updated_at = datetime('now','localtime')
        WHERE owner = ? AND folder_id IS NULL
        """,
        (fid, own),
    )
    conn.execute(
        """
        UPDATE contact_folders SET parent_id = ?, updated_at = datetime('now','localtime')
        WHERE owner = ? AND parent_id IS NULL AND id != ?
        """,
        (fid, own, fid),
    )
    logger.info(
        "contact_default_unfiled_folder_created",
        owner=own[:32],
        folder_id=fid,
        note="루트에 있던 폴더·folder_id NULL 연락처를 미분류 아래로 정리",
    )
    return fid


def _norm_parent(parent_id: Optional[str]) -> Optional[str]:
    p = (parent_id or "").strip()
    return p if p else None


def list_contact_folders(*, owner: str) -> List[Dict[str, Any]]:
    own = (owner or "").strip()
    if not own:
        return []
    try:
        from src.booking.database import get_db

        with get_db() as conn:
            ensure_default_unfiled_folder(conn, own)
            unif = default_unfiled_folder_id(own)
            rows = conn.execute(
                """
                SELECT id, owner, parent_id, name, sort_order, created_at, updated_at
                FROM contact_folders
                WHERE owner = ?
                ORDER BY (CASE WHEN id = ? THEN 0 ELSE 1 END),
                         parent_id IS NULL DESC, parent_id, sort_order, name
                """,
                (own, unif),
            ).fetchall()
            return [dict(r) for r in rows]
    except Exception as exc:
        logger.warning("list_contact_folders_failed err=%s", exc)
        return []


def get_contact_folder(*, folder_id: str, owner: str) -> Optional[Dict[str, Any]]:
    fid = (folder_id or "").strip()
    own = (owner or "").strip()
    if not fid or not own:
        return None
    try:
        from src.booking.database import get_db

        with get_db() as conn:
            row = conn.execute(
                """
                SELECT id, owner, parent_id, name, sort_order, created_at, updated_at
                FROM contact_folders WHERE id = ? AND owner = ?
                """,
                (fid, own),
            ).fetchone()
            return dict(row) if row else None
    except Exception as exc:
        logger.warning("get_contact_folder_failed err=%s", exc)
        return None


def _next_sort_order(conn: Any, owner: str, parent_id: Optional[str]) -> int:
    if parent_id is None:
        row = conn.execute(
            """
            SELECT COALESCE(MAX(sort_order), -1) + 1 AS n
            FROM contact_folders
            WHERE owner = ? AND parent_id IS NULL
            """,
            (owner,),
        ).fetchone()
    else:
        row = conn.execute(
            """
            SELECT COALESCE(MAX(sort_order), -1) + 1 AS n
            FROM contact_folders
            WHERE owner = ? AND parent_id = ?
            """,
            (owner, parent_id),
        ).fetchone()
    return int(row["n"]) if row else 0


def _parent_belongs_to_owner(conn: Any, owner: str, parent_id: Optional[str]) -> bool:
    if parent_id is None:
        return True
    row = conn.execute(
        "SELECT 1 FROM contact_folders WHERE id = ? AND owner = ?",
        (parent_id, owner),
    ).fetchone()
    return row is not None


def _moving_would_cycle(conn: Any, owner: str, folder_id: str, new_parent_id: Optional[str]) -> bool:
    """new_parent_id가 folder_id 자신이거나 folder_id의 자손이면 순환."""
    if new_parent_id is None:
        return False
    if new_parent_id == folder_id:
        return True
    cur: Optional[str] = new_parent_id
    seen: set[str] = set()
    while cur:
        if cur == folder_id:
            return True
        if cur in seen:
            break
        seen.add(cur)
        row = conn.execute(
            "SELECT parent_id FROM contact_folders WHERE id = ? AND owner = ?",
            (cur, owner),
        ).fetchone()
        if not row:
            break
        cur = row["parent_id"]
        if cur:
            cur = str(cur).strip() or None
    return False


def insert_contact_folder(
    *,
    owner: str,
    name: str,
    parent_id: Optional[str] = None,
) -> Optional[Dict[str, Any]]:
    own = (owner or "").strip()
    nm = (name or "").strip()
    pid = _norm_parent(parent_id)
    if not own or not nm:
        return None
    fid = f"cf_{uuid.uuid4().hex[:16]}"
    try:
        from src.booking.database import get_db

        with get_db() as conn:
            unif = ensure_default_unfiled_folder(conn, own)
            if pid is None:
                pid = unif
            if pid and not _parent_belongs_to_owner(conn, own, pid):
                return None
            sort_order = _next_sort_order(conn, own, pid)
            conn.execute(
                """
                INSERT INTO contact_folders (id, owner, parent_id, name, sort_order, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, datetime('now','localtime'), datetime('now','localtime'))
                """,
                (fid, own, pid, nm, sort_order),
            )
            row = conn.execute(
                "SELECT * FROM contact_folders WHERE id = ? AND owner = ?",
                (fid, own),
            ).fetchone()
            return dict(row) if row else None
    except Exception as exc:
        logger.warning("insert_contact_folder_failed err=%s", exc)
        return None


def update_contact_folder(
    *,
    folder_id: str,
    owner: str,
    name: Optional[str] = None,
    parent_id: Optional[str] = None,
    parent_id_explicit: bool = False,
    sort_order: Optional[int] = None,
) -> Optional[Dict[str, Any]]:
    """parent_id_explicit=True이면 parent_id 인자 값(빈 문자열→NULL)으로 부모를 설정."""
    fid = (folder_id or "").strip()
    own = (owner or "").strip()
    if not fid or not own:
        return None
    try:
        from src.booking.database import get_db

        with get_db() as conn:
            row = conn.execute(
                "SELECT * FROM contact_folders WHERE id = ? AND owner = ?",
                (fid, own),
            ).fetchone()
            if not row:
                return None

            unif = default_unfiled_folder_id(own)
            if fid == unif and parent_id_explicit:
                new_p = _norm_parent(parent_id)
                if new_p is not None:
                    raise ValueError("unfiled_must_stay_root")

            sets: List[str] = ["updated_at = datetime('now','localtime')"]
            params: List[Any] = []

            if name is not None:
                nm = (name or "").strip() or str(row["name"] or "")
                sets.append("name = ?")
                params.append(nm)

            if parent_id_explicit:
                new_pid = _norm_parent(parent_id)
                if fid != unif and new_pid is None:
                    new_pid = unif
                if new_pid and not _parent_belongs_to_owner(conn, own, new_pid):
                    raise ValueError("invalid_parent")
                if _moving_would_cycle(conn, own, fid, new_pid):
                    raise ValueError("folder_cycle")
                sets.append("parent_id = ?")
                params.append(new_pid)
            elif parent_id is not None:
                new_pid = _norm_parent(parent_id)
                if fid != unif and new_pid is None:
                    new_pid = unif
                if new_pid and not _parent_belongs_to_owner(conn, own, new_pid):
                    raise ValueError("invalid_parent")
                if _moving_would_cycle(conn, own, fid, new_pid):
                    raise ValueError("folder_cycle")
                sets.append("parent_id = ?")
                params.append(new_pid)

            if sort_order is not None:
                sets.append("sort_order = ?")
                params.append(int(sort_order))

            if len(params) == 0:
                return dict(row)

            params.extend([fid, own])
            conn.execute(
                f"UPDATE contact_folders SET {', '.join(sets)} WHERE id = ? AND owner = ?",
                params,
            )
            row2 = conn.execute(
                "SELECT * FROM contact_folders WHERE id = ? AND owner = ?",
                (fid, own),
            ).fetchone()
            return dict(row2) if row2 else None
    except ValueError:
        raise
    except Exception as exc:
        logger.warning("update_contact_folder_failed err=%s", exc)
        return None


def delete_contact_folder(*, folder_id: str, owner: str) -> bool:
    """하위 폴더는 삭제 폴더의 parent_id로 승격, 연락처는 동일 타깃으로 이동 후 삭제."""
    fid = (folder_id or "").strip()
    own = (owner or "").strip()
    if not fid or not own:
        return False
    if fid == default_unfiled_folder_id(own):
        logger.info("delete_default_unfiled_skipped", owner=own[:32])
        return False
    try:
        from src.booking.database import get_db

        with get_db() as conn:
            ensure_default_unfiled_folder(conn, own)
            row = conn.execute(
                "SELECT id, parent_id FROM contact_folders WHERE id = ? AND owner = ?",
                (fid, own),
            ).fetchone()
            if not row:
                return False
            replacement_parent = row["parent_id"]

            conn.execute(
                """
                UPDATE contact_folders SET parent_id = ?, updated_at = datetime('now','localtime')
                WHERE owner = ? AND parent_id = ?
                """,
                (replacement_parent, own, fid),
            )
            conn.execute(
                """
                UPDATE caller_contacts SET folder_id = ?, updated_at = datetime('now','localtime')
                WHERE owner = ? AND folder_id = ?
                """,
                (replacement_parent, own, fid),
            )
            cur = conn.execute(
                "DELETE FROM contact_folders WHERE id = ? AND owner = ?",
                (fid, own),
            )
            return cur.rowcount > 0
    except Exception as exc:
        logger.warning("delete_contact_folder_failed err=%s", exc)
        return False


def validate_folder_id_for_contact(*, folder_id: Optional[str], owner: str) -> bool:
    if folder_id is None or not (folder_id or "").strip():
        return True
    return get_contact_folder(folder_id=folder_id.strip(), owner=owner) is not None
