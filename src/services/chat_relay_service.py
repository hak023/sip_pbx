"""채팅 SIP 릴레이: 테넌트(owner)와 REGISTER 내선(sip_username) 매핑."""

from __future__ import annotations

from datetime import datetime
from typing import Any

import structlog

from src.booking.database import get_connection, get_db

logger = structlog.get_logger(__name__)


def _now_str() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _row_chat_relay(row: Any) -> dict[str, Any]:
    """sqlite3.Row → dict (message_ai_* 컬럼은 마이그레이션 전 부재 가능)."""
    d = dict(row)
    out: dict[str, Any] = {
        "owner": d.get("owner") or "",
        "sip_username": (d.get("sip_username") or "") if d.get("sip_username") is not None else "",
        "updated_at": d.get("updated_at") or "",
        "message_ai_policy": (d.get("message_ai_policy") or "settings").strip().lower()
        if d.get("message_ai_policy") is not None
        else "settings",
        "message_ai_reply_enabled": int(d.get("message_ai_reply_enabled") or 0),
        "message_ai_reply_prefix": (d.get("message_ai_reply_prefix") or "")
        if d.get("message_ai_reply_prefix") is not None
        else "",
    }
    if out["message_ai_policy"] not in ("persona", "settings"):
        out["message_ai_policy"] = "settings"
    return out


def get_chat_relay_settings(owner: str) -> dict[str, Any]:
    """owner별 릴레이·메시지 AI 설정 1건 (없으면 기본값)."""
    owner_f = (owner or "").strip()
    conn = get_connection()
    try:
        row = conn.execute("SELECT * FROM chat_relay_settings WHERE owner = ?", (owner_f,)).fetchone()
        if row:
            return _row_chat_relay(row)
    finally:
        conn.close()
    return {
        "owner": owner_f,
        "sip_username": "",
        "updated_at": "",
        "message_ai_policy": "settings",
        "message_ai_reply_enabled": 0,
        "message_ai_reply_prefix": "",
    }


def upsert_chat_relay_settings(
    owner: str,
    sip_username: str,
    *,
    message_ai_policy: str | None = None,
    message_ai_reply_enabled: bool | None = None,
    message_ai_reply_prefix: str | None = None,
) -> dict[str, Any]:
    """sip_username 및 선택적 메시지 AI 필드를 저장한다."""
    owner_f = (owner or "").strip()
    sip_f = (sip_username or "").strip()
    cur = get_chat_relay_settings(owner_f)
    # 정책 라디오 제거: API에서 생략 시 항상 settings (페르소나 레거시 미사용)
    if message_ai_policy is not None:
        policy = str(message_ai_policy or "settings").strip().lower()
    else:
        policy = "settings"
    if policy not in ("persona", "settings"):
        policy = "settings"
    if message_ai_reply_enabled is not None:
        ai_en = 1 if message_ai_reply_enabled else 0
    else:
        ai_en = int(cur.get("message_ai_reply_enabled") or 0)
    if message_ai_reply_prefix is not None:
        prefix_f = (message_ai_reply_prefix or "").strip()
    else:
        prefix_f = str(cur.get("message_ai_reply_prefix") or "")

    now = _now_str()
    with get_db() as conn:
        conn.execute(
            """
            INSERT INTO chat_relay_settings (
                owner, sip_username, updated_at,
                message_ai_policy, message_ai_reply_enabled, message_ai_reply_prefix
            )
            VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(owner) DO UPDATE SET
                sip_username = excluded.sip_username,
                updated_at = excluded.updated_at,
                message_ai_policy = excluded.message_ai_policy,
                message_ai_reply_enabled = excluded.message_ai_reply_enabled,
                message_ai_reply_prefix = excluded.message_ai_reply_prefix
            """,
            (owner_f, sip_f, now, policy, ai_en, prefix_f),
        )
    logger.info(
        "chat_relay_settings_saved",
        owner=owner_f,
        sip_username=sip_f or None,
        message_ai_policy=policy,
        message_ai_reply_enabled=ai_en,
    )
    return get_chat_relay_settings(owner_f)


def resolve_sip_from_for_outbound(owner: str) -> str:
    """발신 SIP From/REGISTER 조회에 쓸 내선.

    chat_relay_settings 에 sip_username 이 있으면 그 값, 없으면 owner 문자열 그대로.
    """
    owner_f = (owner or "").strip()
    if not owner_f:
        return ""
    row = get_chat_relay_settings(owner_f)
    sip = (row.get("sip_username") or "").strip()
    return sip if sip else owner_f


def resolve_chat_owner_for_inbound(sip_to_username: str) -> str:
    """수신 MESSAGE 의 To(또는 Request-URI) user 에 매핑되는 테넌트 owner.

    매핑이 없으면 sip_to_username 을 owner 로 쓴다 (단일 테넌트·레거시).
    """
    u = (sip_to_username or "").strip()
    if not u:
        return "pbx"
    conn = get_connection()
    try:
        row = conn.execute(
            """
            SELECT owner FROM chat_relay_settings
            WHERE sip_username = ? COLLATE NOCASE
            LIMIT 1
            """,
            (u,),
        ).fetchone()
        if row:
            return str(row["owner"])
    finally:
        conn.close()
    return u
