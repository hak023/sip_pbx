"""
IntelliDecision 판단 근거 로그 SQLite 헬퍼 (Story 1.21, FR30).

booking.db와 동일 파일을 공유한다(src.booking.database).
`self_service/decision_rationale.py`의 백그라운드 캡처 태스크가 성공했을 때만 호출한다.
순수 관측 전용 데이터이며, 원본 발화 전문은 저장하지 않는다(개인정보 최소 노출 원칙).
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

_DB_AVAILABLE = True

# 근거 요약 저장 시 최대 길이(FR30 명시 — 원본 발화 전문 대신 짧은 요약만 저장)
_REASONING_SUMMARY_MAX_LEN = 200


def record_decision_rationale(
    *,
    owner: str,
    call_id: str = "",
    caller_number: str = "",
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
                    (owner, call_id, caller_number, matched_type, reasoning_summary, related_domain)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (owner, call_id or "", caller_number or "", matched_type or "unknown", summary, related_domain or ""),
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


# ---------------------------------------------------------------------------
# 세션 단위 그룹핑 (Story 1.38, FR34-F)
#
# 채널별로 세션 경계 정의가 다르다 — 음성 통화는 call_id 하나가 이미 세션 하나(자연 성립)지만,
# SIP MESSAGE(채팅)는 트랜잭션마다 call_id가 새로 발급되므로 call_id로 그룹핑할 수 없다.
# 채널 판별은 별도 컬럼 없이, decision_log의 call_id가 `chat_messages.call_id`에 존재하는지
# 교차 조회해서 동적으로 판정한다(이미 SIP MESSAGE 발신/수신 시 chat_messages에 call_id가
# 함께 저장되고 있음 — chat_service.py::save_chat_message).
# ---------------------------------------------------------------------------

_DEFAULT_CHAT_SESSION_WINDOW_MINUTES = 30


def _parse_created_at(value: str):
    from datetime import datetime

    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace(" ", "T"))
    except ValueError:
        return None


def _fetch_chat_call_ids(conn, call_ids: set) -> set:
    """전달된 call_id 중 실제로 SIP MESSAGE(채팅) 트랜잭션에 해당하는 것만 골라 반환한다."""
    call_ids = {c for c in call_ids if c}
    if not call_ids:
        return set()
    placeholders = ",".join("?" for _ in call_ids)
    try:
        rows = conn.execute(
            f"SELECT DISTINCT call_id FROM chat_messages WHERE call_id IN ({placeholders})",
            list(call_ids),
        ).fetchall()
        return {r[0] for r in rows}
    except Exception as exc:
        logger.warning("self_service_decision_log_chat_call_id_lookup_failed err=%s", exc)
        return set()


def _group_rows_into_sessions(
    rows: List[Dict[str, Any]], chat_call_ids: set, window_minutes: int
) -> List[Dict[str, Any]]:
    """created_at 오름차순 rows를 채널별 규칙으로 세션 목록으로 묶는다.

    - 음성(call_id가 chat_call_ids에 없음): call_id 하나 = 세션 하나.
    - 채팅(call_id가 chat_call_ids에 있음): 동일 caller_number이고 직전 턴과의 시간 간격이
      window_minutes 이내면 같은 세션, 초과하면 새 세션.
    """
    from datetime import timedelta

    voice_sessions: Dict[str, Dict[str, Any]] = {}
    chat_open: Dict[str, Dict[str, Any]] = {}
    sessions: List[Dict[str, Any]] = []
    window = timedelta(minutes=window_minutes)

    for row in rows:
        call_id = row.get("call_id") or ""
        caller_number = row.get("caller_number") or ""
        ts = _parse_created_at(row.get("created_at") or "")
        is_chat = bool(call_id) and call_id in chat_call_ids

        if not is_chat:
            key = call_id or f"__voice_no_call_id_{row.get('id')}"
            sess = voice_sessions.get(key)
            if sess is None:
                sess = {
                    "session_key": f"voice:{key}",
                    "channel": "voice",
                    "caller_number": caller_number,
                    "turns": [],
                    "_last_ts": None,
                }
                voice_sessions[key] = sess
                sessions.append(sess)
            sess["turns"].append(row)
            sess["_last_ts"] = ts or sess["_last_ts"]
            continue

        key = caller_number or f"__chat_no_caller_{row.get('id')}"
        sess = chat_open.get(key)
        if (
            sess is not None
            and ts is not None
            and sess["_last_ts"] is not None
            and (ts - sess["_last_ts"]) <= window
        ):
            sess["turns"].append(row)
            sess["_last_ts"] = ts
        else:
            sess = {
                "session_key": f"chat:{key}:{row.get('created_at')}",
                "channel": "chat",
                "caller_number": caller_number,
                "turns": [row],
                "_last_ts": ts,
            }
            chat_open[key] = sess
            sessions.append(sess)

    return sessions


def _summarize_session(sess: Dict[str, Any]) -> Dict[str, Any]:
    turns = sess["turns"]
    type_sequence = [t.get("matched_type") or "unknown" for t in turns]
    return {
        "session_key": sess["session_key"],
        "channel": sess["channel"],
        "caller_number": sess["caller_number"],
        "turn_count": len(turns),
        "type_sequence": type_sequence,
        "final_type": type_sequence[-1] if type_sequence else "unknown",
        "first_turn_at": turns[0].get("created_at") if turns else None,
        "last_turn_at": turns[-1].get("created_at") if turns else None,
    }


def list_decision_log_sessions(
    owner: str,
    limit: int = 20,
    chat_session_window_minutes: int = _DEFAULT_CHAT_SESSION_WINDOW_MINUTES,
) -> List[Dict[str, Any]]:
    """owner의 판단 이력을 세션(채널별 그룹핑 규칙) 단위 요약으로 반환한다(AC10 1단계 로딩).

    턴 상세는 포함하지 않고 세션당 턴 수·유형 전환 시퀀스·최종 유형만 반환해 목록 조회를
    가볍게 유지한다 — 특정 세션의 전체 턴은 `get_decision_log_session_detail()`로 별도 조회.
    """
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
                # created_at은 초 단위라 같은 초에 여러 턴이 기록되면 순서가 모호해진다 — id를 보조
                # 정렬키로 추가해 삽입 순서(=실제 턴 순서)를 보장한다(Story 1.38 IV 중 발견).
                "SELECT * FROM self_service_decision_log WHERE owner = ? ORDER BY created_at ASC, id ASC",
                (owner,),
            ).fetchall()
            items = [dict(r) for r in rows]
            chat_call_ids = _fetch_chat_call_ids(conn, {i.get("call_id") or "" for i in items})
    except Exception as exc:
        logger.warning("self_service_decision_log_sessions_query_failed owner=%s err=%s", owner, exc)
        return []

    sessions = _group_rows_into_sessions(items, chat_call_ids, chat_session_window_minutes)
    summaries = [_summarize_session(s) for s in sessions]
    summaries.sort(key=lambda s: s["last_turn_at"] or "", reverse=True)
    return summaries[:limit]


def get_decision_log_session_detail(
    owner: str,
    session_key: str,
    chat_session_window_minutes: int = _DEFAULT_CHAT_SESSION_WINDOW_MINUTES,
) -> Optional[Dict[str, Any]]:
    """session_key(list_decision_log_sessions가 반환한 값)에 해당하는 세션의 턴 전체를 반환한다(AC10 2단계).

    session_key는 DB에 저장된 값이 아니라 그룹핑 결과에서 파생되므로, 동일한 그룹핑을 다시
    수행해 일치하는 세션을 찾는다.
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
            rows = conn.execute(
                "SELECT * FROM self_service_decision_log WHERE owner = ? ORDER BY created_at ASC, id ASC",
                (owner,),
            ).fetchall()
            items = [dict(r) for r in rows]
            chat_call_ids = _fetch_chat_call_ids(conn, {i.get("call_id") or "" for i in items})
    except Exception as exc:
        logger.warning("self_service_decision_log_session_detail_query_failed owner=%s err=%s", owner, exc)
        return None

    sessions = _group_rows_into_sessions(items, chat_call_ids, chat_session_window_minutes)
    for sess in sessions:
        if sess["session_key"] == session_key:
            summary = _summarize_session(sess)
            summary["turns"] = sess["turns"]
            return summary
    return None

