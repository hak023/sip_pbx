"""
DB 레이어 — SQLite 기반 통화 이력·발신자별 요약.

- call_history: 통화 이력 CRUD, HITL 상태 갱신
- call_summaries: 발신자별 통화 요약 (LLM 맥락용)

설계: docs/design/CALLER_MEMORY_DESIGN.md §6
"""

from src.db.sqlite import (
    get_db_path,
    init_db,
    append_call_history_row,
    record_hitl_request_row,
    mark_hitl_resolved_row,
    mark_pending_hitl_unresolved_row,
    list_call_history_rows,
    get_call_history_row,
    update_call_note_row,
    resolve_call_row,
    save_call_summary,
    get_recent_summaries_by_caller,
    get_all_call_history_rows,
    end_call_and_save_summary,
)

__all__ = [
    "get_db_path",
    "init_db",
    "append_call_history_row",
    "record_hitl_request_row",
    "mark_hitl_resolved_row",
    "mark_pending_hitl_unresolved_row",
    "list_call_history_rows",
    "get_call_history_row",
    "update_call_note_row",
    "resolve_call_row",
    "save_call_summary",
    "get_recent_summaries_by_caller",
    "get_all_call_history_rows",
    "end_call_and_save_summary",
]
