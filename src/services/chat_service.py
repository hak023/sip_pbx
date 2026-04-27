"""SIP MESSAGE 채팅 이력 서비스.

chat_messages 테이블 CRUD:
  - save_chat_message  : 수신/발신 메시지 저장
  - get_threads        : owner 기준 스레드 목록 (thread_id = 상대방 내선)
  - get_messages       : 특정 스레드 메시지 이력

내선 간 MESSAGE는 SIPEndpoint에서 수신 1건에 대해 (1) 착신 owner·inbound,
(2) 발신 owner·outbound 미러를 함께 저장하여, 로그인 owner 기준 API에
발신·수신이 모두 나타나게 한다.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

import structlog

from src.booking.database import get_connection, get_db

logger = structlog.get_logger(__name__)


def _now_str() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def save_chat_message(
    thread_id: str,
    owner: str,
    direction: str,
    from_phone: str,
    to_phone: str,
    body: str,
    call_id: str = "",
    status: str = "delivered",
    error_code: str = "",
) -> int:
    """메시지 1건을 chat_messages에 저장하고 생성된 id를 반환한다.

    Args:
        thread_id:  대화 스레드 식별자 (고객 전화번호).
        owner:      서비스 착신번호 / 테넌트 ID.
        direction:  'inbound' | 'outbound'
        from_phone: 발신자 번호.
        to_phone:   수신자 번호.
        body:       메시지 본문.
        call_id:    연관 통화 ID (선택).
        status:     'sent' | 'delivered' | 'failed'
        error_code: 실패 시 sip_unavailable / sender_not_registered 등
    """
    with get_db() as conn:
        cur = conn.execute(
            """
            INSERT INTO chat_messages
                (thread_id, owner, direction, from_phone, to_phone, body, call_id, status, error_code, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (thread_id, owner, direction, from_phone, to_phone, body, call_id, status, error_code or "", _now_str()),
        )
        row_id: int = cur.lastrowid or 0

    logger.info(
        "chat_message_saved",
        thread_id=thread_id,
        owner=owner,
        direction=direction,
        body_len=len(body),
    )
    return row_id


def get_threads(owner: str) -> list[dict[str, Any]]:
    """owner 기준 채팅 스레드 목록을 반환한다.

    각 스레드는 thread_id(고객 번호) 단위로 집계되며,
    마지막 메시지 내용·시각·총 메시지 수를 포함한다.
    최신 활동 순으로 정렬된다.
    """
    conn = get_connection()
    try:
        rows = conn.execute(
            """
            SELECT
                thread_id,
                owner,
                MAX(created_at)  AS last_time,
                COUNT(*)         AS message_count,
                SUM(CASE WHEN direction = 'inbound' THEN 1 ELSE 0 END) AS inbound_count
            FROM chat_messages
            WHERE owner = ?
            GROUP BY thread_id, owner
            ORDER BY last_time DESC
            """,
            (owner,),
        ).fetchall()

        threads = []
        for row in rows:
            thread_id = row["thread_id"]
            # 마지막 메시지 본문 별도 조회
            last_msg_row = conn.execute(
                """
                SELECT body, direction FROM chat_messages
                WHERE thread_id = ? AND owner = ?
                ORDER BY created_at DESC LIMIT 1
                """,
                (thread_id, owner),
            ).fetchone()

            threads.append(
                {
                    "thread_id": thread_id,
                    "owner": owner,
                    "last_time": row["last_time"],
                    "message_count": row["message_count"],
                    "inbound_count": row["inbound_count"],
                    "last_body": last_msg_row["body"] if last_msg_row else "",
                    "last_direction": last_msg_row["direction"] if last_msg_row else "",
                }
            )
        return threads
    finally:
        conn.close()


def get_messages(thread_id: str, owner: str, limit: int = 100) -> list[dict[str, Any]]:
    """특정 스레드의 메시지 이력을 시간 오름차순으로 반환한다."""
    conn = get_connection()
    try:
        rows = conn.execute(
            """
            SELECT id, thread_id, owner, direction, from_phone, to_phone,
                   body, call_id, status, error_code, created_at
            FROM chat_messages
            WHERE thread_id = ? AND owner = ?
            ORDER BY created_at ASC
            LIMIT ?
            """,
            (thread_id, owner, limit),
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def get_message_by_id(message_id: int, owner: str) -> dict[str, Any] | None:
    """owner 일치 여부로 메시지 1건 조회."""
    conn = get_connection()
    try:
        row = conn.execute(
            """
            SELECT id, thread_id, owner, direction, from_phone, to_phone,
                   body, call_id, status, error_code, created_at
            FROM chat_messages
            WHERE id = ? AND owner = ?
            """,
            (message_id, owner),
        ).fetchone()
        return dict(row) if row else None
    finally:
        conn.close()


def update_message_after_retry(
    message_id: int,
    owner: str,
    status: str,
    error_code: str = "",
) -> bool:
    """재전송 등으로 배달 상태 갱신."""
    with get_db() as conn:
        cur = conn.execute(
            """
            UPDATE chat_messages
            SET status = ?, error_code = ?
            WHERE id = ? AND owner = ? AND direction = 'outbound'
            """,
            (status, error_code or "", message_id, owner),
        )
        return cur.rowcount > 0
