"""caller_contacts 테이블 CRUD (booking.db 공유)."""

from __future__ import annotations

import logging
import re
import uuid
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


def _slug_label(s: str, max_len: int = 24) -> str:
    t = (s or "").strip()
    t = re.sub(r"[^\w가-힣\-]", "", t, flags=re.UNICODE)
    return (t[:max_len] or "고객").strip("-")


def build_display_name(base_label: str, suffix4: str) -> str:
    """예: 예약손님 + 1004 → 예약손님_1004"""
    base = _slug_label(base_label, 28)
    suf = re.sub(r"\D", "", suffix4 or "")[-4:] if suffix4 else ""
    if suf:
        return f"{base}_{suf}"
    return base


def get_caller_contact(owner: str, canonical_phone: str) -> Optional[Dict[str, Any]]:
    own = (owner or "").strip()
    key = (canonical_phone or "").strip()
    if not own or not key:
        return None
    try:
        from src.booking.database import get_db

        with get_db() as conn:
            row = conn.execute(
                """
                SELECT id, owner, canonical_phone, display_name, memo, source,
                       llm_confidence, folder_id, created_at, updated_at
                FROM caller_contacts
                WHERE owner = ? AND canonical_phone = ?
                """,
                (own, key),
            ).fetchone()
            return dict(row) if row else None
    except Exception as exc:
        logger.warning("get_caller_contact_failed err=%s", exc)
        return None


def resolve_caller_contact(owner: str, peer_raw: str) -> Optional[Dict[str, Any]]:
    """SIP URI·내선 등 peer 식별자로 연락처 1건 탐색( canonical_phone 정확 일치 후보 순 )."""
    own = (owner or "").strip()
    s = (peer_raw or "").strip()
    if not own or not s:
        return None

    keys: list[str] = []

    def add_key(k: str) -> None:
        t = (k or "").strip()
        if not t:
            return
        if t not in keys:
            keys.append(t)
        tl = t.lower()
        if tl != t and tl not in keys:
            keys.append(tl)

    add_key(s)
    if "@" in s:
        left = s.split("@", 1)[0].strip()
        if left.lower().startswith("sip:"):
            left = left[4:].lstrip("<").rstrip(">")
        add_key(left)
    digits = "".join(c for c in s if c.isdigit())
    if digits:
        add_key(digits)

    for k in keys:
        row = get_caller_contact(own, k)
        if row:
            return row
    return None


def list_caller_contacts(
    *,
    owner: str,
    q: str = "",
    limit: int = 100,
    offset: int = 0,
) -> tuple[list[Dict[str, Any]], int]:
    own = (owner or "").strip()
    if not own:
        return [], 0
    try:
        from src.booking.database import get_db

        with get_db() as conn:
            if (q or "").strip():
                like = f"%{(q or '').strip()}%"
                total = conn.execute(
                    "SELECT COUNT(*) FROM caller_contacts WHERE owner = ? "
                    "AND (display_name LIKE ? OR canonical_phone LIKE ? OR memo LIKE ?)",
                    (own, like, like, like),
                ).fetchone()[0]
                rows = conn.execute(
                    """
                    SELECT id, owner, canonical_phone, display_name, memo, source,
                           llm_confidence, folder_id, created_at, updated_at
                    FROM caller_contacts
                    WHERE owner = ? AND (display_name LIKE ? OR canonical_phone LIKE ? OR memo LIKE ?)
                    ORDER BY updated_at DESC
                    LIMIT ? OFFSET ?
                    """,
                    (own, like, like, like, limit, offset),
                ).fetchall()
            else:
                total = conn.execute(
                    "SELECT COUNT(*) FROM caller_contacts WHERE owner = ?", (own,)
                ).fetchone()[0]
                rows = conn.execute(
                    """
                    SELECT id, owner, canonical_phone, display_name, memo, source,
                           llm_confidence, folder_id, created_at, updated_at
                    FROM caller_contacts
                    WHERE owner = ?
                    ORDER BY updated_at DESC
                    LIMIT ? OFFSET ?
                    """,
                    (own, limit, offset),
                ).fetchall()
            return [dict(r) for r in rows], int(total)
    except Exception as exc:
        logger.warning("list_caller_contacts_failed err=%s", exc)
        return [], 0


def _norm_folder_id(folder_id: Optional[str]) -> Optional[str]:
    f = (folder_id or "").strip()
    return f if f else None


def insert_caller_contact_manual(
    *,
    owner: str,
    canonical_phone: str,
    display_name: str,
    memo: str = "",
    folder_id: Optional[str] = None,
) -> Optional[Dict[str, Any]]:
    own = (owner or "").strip()
    key = (canonical_phone or "").strip()
    name = (display_name or "").strip()
    if not own or not key or not name:
        return None
    fid = _norm_folder_id(folder_id)
    cid = f"cc_{uuid.uuid4().hex[:16]}"
    try:
        from src.booking.database import get_db

        with get_db() as conn:
            if fid:
                from src.common.contact_folder_db import validate_folder_id_for_contact

                if not validate_folder_id_for_contact(folder_id=fid, owner=own):
                    return None
            conn.execute(
                """
                INSERT INTO caller_contacts (
                    id, owner, canonical_phone, display_name, memo, source,
                    llm_confidence, folder_id, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, 'manual', NULL, ?,
                    datetime('now','localtime'), datetime('now','localtime'))
                ON CONFLICT(owner, canonical_phone) DO UPDATE SET
                    display_name = excluded.display_name,
                    memo = excluded.memo,
                    source = 'manual',
                    llm_confidence = NULL,
                    folder_id = COALESCE(excluded.folder_id, caller_contacts.folder_id),
                    updated_at = datetime('now','localtime')
                """,
                (cid, own, key, name, memo or "", fid),
            )
            row = conn.execute(
                "SELECT * FROM caller_contacts WHERE owner = ? AND canonical_phone = ?",
                (own, key),
            ).fetchone()
            return dict(row) if row else None
    except Exception as exc:
        logger.warning("insert_caller_contact_manual_failed err=%s", exc)
        return None


def update_caller_contact(
    *,
    contact_id: str,
    owner: str,
    display_name: Optional[str] = None,
    memo: Optional[str] = None,
    canonical_phone: Optional[str] = None,
    folder_id: Optional[str] = None,
    folder_id_explicit: bool = False,
) -> Optional[Dict[str, Any]]:
    oid = (contact_id or "").strip()
    own = (owner or "").strip()
    if not oid or not own:
        return None
    try:
        from src.booking.database import get_db

        with get_db() as conn:
            row = conn.execute(
                "SELECT * FROM caller_contacts WHERE id = ? AND owner = ?", (oid, own)
            ).fetchone()
            if not row:
                return None
            sets: List[str] = ["updated_at = datetime('now','localtime')"]
            params: List[Any] = []
            if display_name is not None:
                sets.append("display_name = ?")
                params.append((display_name or "").strip())
            if memo is not None:
                sets.append("memo = ?")
                params.append(memo or "")
            if canonical_phone is not None and (canonical_phone or "").strip():
                new_key = canonical_phone.strip()
                dup = conn.execute(
                    "SELECT 1 FROM caller_contacts WHERE owner = ? AND canonical_phone = ? AND id != ?",
                    (own, new_key, oid),
                ).fetchone()
                if dup:
                    raise ValueError("duplicate_canonical_phone")
                sets.append("canonical_phone = ?")
                params.append(new_key)
            if folder_id_explicit:
                fid = _norm_folder_id(folder_id)
                if fid:
                    from src.common.contact_folder_db import validate_folder_id_for_contact

                    if not validate_folder_id_for_contact(folder_id=fid, owner=own):
                        raise ValueError("invalid_folder_id")
                sets.append("folder_id = ?")
                params.append(fid)
            if len(params) == 0:
                return dict(row)
            # 이름·메모·번호 변경 시에만 수동 확정 처리 (폴더 이동만으로는 source 유지)
            if (
                display_name is not None
                or memo is not None
                or (canonical_phone is not None and (canonical_phone or "").strip())
            ):
                sets.append("source = 'manual'")
                sets.append("llm_confidence = NULL")
            params.extend([oid, own])
            conn.execute(
                f"UPDATE caller_contacts SET {', '.join(sets)} WHERE id = ? AND owner = ?",
                params,
            )
            row2 = conn.execute(
                "SELECT * FROM caller_contacts WHERE id = ? AND owner = ?", (oid, own)
            ).fetchone()
            return dict(row2) if row2 else None
    except ValueError:
        raise
    except Exception as exc:
        logger.warning("update_caller_contact_failed err=%s", exc)
        return None


def delete_caller_contact(*, contact_id: str, owner: str) -> bool:
    oid = (contact_id or "").strip()
    own = (owner or "").strip()
    if not oid or not own:
        return False
    try:
        from src.booking.database import get_db

        with get_db() as conn:
            cur = conn.execute(
                "DELETE FROM caller_contacts WHERE id = ? AND owner = ?", (oid, own)
            )
            return cur.rowcount > 0
    except Exception as exc:
        logger.warning("delete_caller_contact_failed err=%s", exc)
        return False


def upsert_auto_llm_contact(
    *,
    owner: str,
    canonical_phone: str,
    display_name: str,
    confidence: float,
    source: str = "auto_llm",
) -> str:
    """수동 연락처가 없을 때만 삽입/갱신. 반환: inserted|updated|skipped_manual|skipped_empty|failed."""
    own = (owner or "").strip()
    key = (canonical_phone or "").strip()
    name = (display_name or "").strip()
    if not own or not key or not name:
        return "skipped_empty"
    try:
        from src.booking.database import get_db

        with get_db() as conn:
            from src.common.contact_folder_db import ensure_default_unfiled_folder

            unif = ensure_default_unfiled_folder(conn, own)
            row = conn.execute(
                "SELECT id, source FROM caller_contacts WHERE owner = ? AND canonical_phone = ?",
                (own, key),
            ).fetchone()
            if row and (row["source"] or "") == "manual":
                logger.info(
                    "caller_contact_autofill_skipped",
                    reason="manual_exists",
                    owner=own[:32],
                    canonical_phone=key[:16],
                )
                return "skipped_manual"
            conf = float(confidence) if confidence is not None else 0.0
            src = (source or "auto_llm").strip() or "auto_llm"
            if row:
                conn.execute(
                    """
                    UPDATE caller_contacts SET
                        display_name = ?,
                        source = ?,
                        llm_confidence = ?,
                        folder_id = COALESCE(folder_id, ?),
                        updated_at = datetime('now','localtime')
                    WHERE owner = ? AND canonical_phone = ?
                    """,
                    (name, src, conf, unif, own, key),
                )
                logger.info(
                    "caller_contact_autofill_inserted",
                    action="updated",
                    owner=own[:32],
                    display_preview=name[:40],
                )
                return "updated"
            cid = f"cc_{uuid.uuid4().hex[:16]}"
            conn.execute(
                """
                INSERT INTO caller_contacts (
                    id, owner, canonical_phone, display_name, memo, source,
                    llm_confidence, folder_id, created_at, updated_at
                ) VALUES (?, ?, ?, ?, '', ?, ?, ?,
                    datetime('now','localtime'), datetime('now','localtime'))
                """,
                (cid, own, key, name, src, conf, unif),
            )
            logger.info(
                "caller_contact_autofill_inserted",
                action="inserted",
                owner=own[:32],
                display_preview=name[:40],
            )
            return "inserted"
    except Exception as exc:
        logger.warning("upsert_auto_llm_contact_failed err=%s", exc)
        return "failed"
