"""
LangGraph Checkpointer — SQLite 비동기(AsyncSqliteSaver) 기반.

``ainvoke`` / ``astream`` 등 비동기 그래프 API는 동기 ``SqliteSaver`` 와 호환되지 않는다
(런타임: "The SqliteSaver does not support async methods...").

통화(call_id)를 thread_id로 사용한다. 저장소는 ``BOOKING_DB_PATH``(기본 ./data/booking.db).

동기 ``get_checkpointer()`` 는 테스트·레거시용 **MemorySaver** 만 반환한다.
실제 PBX 경로는 ``await get_async_sqlite_checkpointer()`` 를 사용한다.
"""

from __future__ import annotations

import asyncio
import os
from typing import Any, Optional

import structlog

logger = structlog.get_logger(__name__)

_checkpointer_memory = None

_async_sqlite_cp: Any = None
_async_sqlite_lock = asyncio.Lock()


def _db_path() -> str:
    return os.environ.get("BOOKING_DB_PATH", "./data/booking.db")


def get_checkpointer():
    """동기 호환용 인메모리 체크포인터만 반환 (SqliteSaver 미사용).

    LangGraph 비동기 실행 경로에서는 ``get_async_sqlite_checkpointer`` 를 쓴다.
    """
    global _checkpointer_memory
    if _checkpointer_memory is not None:
        return _checkpointer_memory

    try:
        from langgraph.checkpoint.memory import MemorySaver

        _checkpointer_memory = MemorySaver()
        logger.info(
            "langgraph_checkpointer_memory_sync_singleton",
            note="동기 get_checkpointer() — MemorySaver만 제공. PBX는 get_async_sqlite_checkpointer 사용.",
        )
        return _checkpointer_memory
    except ImportError:
        logger.warning("langgraph_checkpointer_memory_unavailable")
        return None


async def get_async_sqlite_checkpointer():
    """AsyncSqliteSaver 싱글턴. ``ainvoke``/``astream`` 과 함께 사용."""
    global _async_sqlite_cp
    if _async_sqlite_cp is not None:
        return _async_sqlite_cp

    async with _async_sqlite_lock:
        if _async_sqlite_cp is not None:
            return _async_sqlite_cp

        try:
            import aiosqlite
            from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver
        except ImportError as e:
            logger.warning(
                "langgraph_async_sqlite_import_failed",
                error=str(e),
                note="pip install aiosqlite langgraph-checkpoint-sqlite",
            )
            return None

        db_path = _db_path()
        os.makedirs(os.path.dirname(os.path.abspath(db_path)), exist_ok=True)

        try:
            conn = await aiosqlite.connect(db_path)
            saver = AsyncSqliteSaver(conn)
            await saver.setup()
        except Exception as e:
            logger.warning("langgraph_async_sqlite_connect_failed", error=str(e))
            return None

        _async_sqlite_cp = saver
        logger.info(
            "langgraph_checkpointer_async_sqlite",
            db_path=db_path,
            note="ainvoke/astream 호환 영속 체크포인터",
        )
        return _async_sqlite_cp


def get_thread_config(call_id: str) -> dict:
    """call_id를 LangGraph thread_id로 매핑."""
    return {"configurable": {"thread_id": call_id or "default"}}


def clear_checkpoint(call_id: str) -> None:
    """통화 종료 후 thread_id 행 삭제. AsyncSaver 연결과 무관하게 동기 sqlite3 로 수행."""
    if not call_id:
        return
    db_path = _db_path()
    try:
        import sqlite3

        if not os.path.isfile(os.path.abspath(db_path)):
            return
        conn = sqlite3.connect(db_path, check_same_thread=False)
        try:
            targets = [
                ("checkpoints", "thread_id"),
                ("checkpoint_blobs", "thread_id"),
                ("checkpoint_writes", "thread_id"),
                ("langgraph_checkpoints", "thread_id"),
                ("langgraph_checkpoint_blobs", "thread_id"),
                ("langgraph_checkpoint_writes", "thread_id"),
            ]
            for table, col in targets:
                try:
                    conn.execute(f"DELETE FROM {table} WHERE {col} = ?", (call_id,))
                except sqlite3.OperationalError:
                    pass
            conn.commit()
            logger.info("langgraph_checkpoint_cleared", call_id=call_id)
        finally:
            conn.close()
    except Exception as e:
        logger.warning("langgraph_checkpoint_clear_failed", call_id=call_id, error=str(e))
