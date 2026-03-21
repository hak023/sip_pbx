"""
RAG 검색 결과를 DB에 기록하는 로거.

- set_db_client(db): 앱 기동 시 DB 연결을 주입. 미설정 시 RAG 로깅은 스킵되고
  "DB client not configured, skipping RAG logging" 힌트 로그만 남김.
- log_rag_search(...): RAG 검색 완료 시 호출. call_id, query, owner_filter,
  results_count, latency_ms 등 저장.

사용 예 (앱 진입점에서):
  from ai_logging import set_db_client, use_sqlite_file, init_sqlite_schema, log_rag_search

  # SQLite 파일 사용 시
  use_sqlite_file("data/rag_log.db")
  init_sqlite_schema()

  # 또는 기존 DB 연결 주입
  # set_db_client(existing_connection)
  # init_sqlite_schema()

  # RAG 검색 직후
  log_rag_search(call_id="...", query="오늘의 날씨", owner_filter="1004", results_count=0, latency_ms=15)
"""
from __future__ import annotations

import json
import logging
import sqlite3
import time
from pathlib import Path
from typing import Any, Optional

logger = logging.getLogger(__name__)

# DB 클라이언트: sqlite3.Connection 또는 .execute(...).commit() 를 지원하는 객체
_db: Any = None
_skip_hint_logged = False


def set_db_client(db: Any) -> None:
    """RAG 로깅에 사용할 DB 연결을 설정. None이면 로깅 스킵."""
    global _db, _skip_hint_logged
    _db = db
    if db is not None:
        _skip_hint_logged = False


def get_db_client() -> Any:
    """현재 설정된 DB 클라이언트 반환 (미설정 시 None)."""
    return _db


def use_sqlite_file(path: str | Path) -> None:
    """SQLite 파일 경로로 연결 생성 후 set_db_client 호출."""
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(p))
    conn.row_factory = sqlite3.Row
    set_db_client(conn)


# 테이블명
TABLE_RAG_SEARCH = "rag_search_log"

INIT_SQL = f"""
CREATE TABLE IF NOT EXISTS {TABLE_RAG_SEARCH} (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at TEXT NOT NULL,
    call_id TEXT NOT NULL,
    query TEXT NOT NULL,
    owner_filter TEXT NOT NULL,
    results_count INTEGER NOT NULL,
    latency_ms REAL,
    doc_ids_json TEXT,
    top_score REAL,
    similarity_threshold REAL,
    top_k INTEGER
);
CREATE INDEX IF NOT EXISTS ix_rag_search_call_id ON {TABLE_RAG_SEARCH}(call_id);
CREATE INDEX IF NOT EXISTS ix_rag_search_owner ON {TABLE_RAG_SEARCH}(owner_filter);
CREATE INDEX IF NOT EXISTS ix_rag_search_created ON {TABLE_RAG_SEARCH}(created_at);
"""


def init_sqlite_schema() -> None:
    """현재 설정된 DB 클라이언트에 RAG 로그 테이블이 없으면 생성."""
    db = get_db_client()
    if db is None:
        return
    try:
        db.executescript(INIT_SQL)
        if hasattr(db, "commit"):
            db.commit()
        logger.info("rag_search_log table ready")
    except Exception as e:
        logger.exception("init_sqlite_schema failed: %s", e)


def log_rag_search(
    call_id: str,
    query: str,
    owner_filter: str,
    results_count: int,
    *,
    latency_ms: Optional[float] = None,
    doc_ids: Optional[list[str]] = None,
    top_score: Optional[float] = None,
    similarity_threshold: Optional[float] = None,
    top_k: Optional[int] = None,
) -> None:
    """
    RAG 검색 1건을 DB에 기록. set_db_client()가 호출되지 않았으면 기록하지 않고
    힌트 로그만 남김.
    """
    db = get_db_client()
    if db is None:
        global _skip_hint_logged
        if not _skip_hint_logged:
            _skip_hint_logged = True
            logger.info(
                "DB client not configured, skipping RAG logging (hint: ai_logger.set_db_client(db))"
            )
        return
    created_at = time.strftime("%Y-%m-%dT%H:%M:%S.000Z", time.gmtime())
    doc_ids_json = json.dumps(doc_ids, ensure_ascii=False) if doc_ids is not None else None
    try:
        db.execute(
            f"""
            INSERT INTO {TABLE_RAG_SEARCH}
            (created_at, call_id, query, owner_filter, results_count, latency_ms, doc_ids_json, top_score, similarity_threshold, top_k)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                created_at,
                call_id or "",
                query,
                owner_filter,
                results_count,
                latency_ms,
                doc_ids_json,
                top_score,
                similarity_threshold,
                top_k,
            ),
        )
        if hasattr(db, "commit"):
            db.commit()
    except Exception as e:
        logger.warning("log_rag_search failed: %s", e)
