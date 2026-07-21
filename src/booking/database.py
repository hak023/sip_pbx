"""
예약 시스템 SQLite DB 연결 및 테이블 초기화.

DB 파일 경로: 환경변수 BOOKING_DB_PATH (기본: ./data/booking.db)
4개 테이블:
  - booking_settings   : 테넌트별 도메인 설정
  - booking_slots      : 예약 가능 시간대 (운영자 생성)
  - bookings           : 예약 내역
  - booking_schema_fields : 도메인별 추가 수집 항목 정의
"""

from __future__ import annotations

import json
import logging
import os
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Generator

logger = logging.getLogger(__name__)

_DB_PATH: str | None = None


def _get_db_path() -> str:
    global _DB_PATH
    if _DB_PATH:
        return _DB_PATH
    raw = os.environ.get("BOOKING_DB_PATH") or "./data/booking.db"
    path = Path(raw).resolve()
    path.parent.mkdir(parents=True, exist_ok=True)
    _DB_PATH = str(path)
    return _DB_PATH


def get_connection() -> sqlite3.Connection:
    """새 SQLite 연결 반환 (WAL 모드, row_factory=Row)."""
    conn = sqlite3.connect(_get_db_path(), check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


@contextmanager
def get_db() -> Generator[sqlite3.Connection, None, None]:
    """컨텍스트 매니저: 자동 commit/rollback."""
    conn = get_connection()
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


_DDL = """
-- 테넌트별 도메인 설정
CREATE TABLE IF NOT EXISTS booking_settings (
    owner               TEXT    PRIMARY KEY,
    domain_type         TEXT    NOT NULL DEFAULT 'general',
    service_name        TEXT    NOT NULL DEFAULT '예약 서비스',
    slot_duration_min   INTEGER NOT NULL DEFAULT 60,
    max_party_size      INTEGER NOT NULL DEFAULT 1,
    require_phone       INTEGER NOT NULL DEFAULT 1,
    require_name        INTEGER NOT NULL DEFAULT 1,
    slot_label          TEXT    NOT NULL DEFAULT '예약',
    confirmation_msg    TEXT    NOT NULL DEFAULT '예약이 완료되었습니다. 예약번호는 {booking_id}입니다.',
    extra_config        TEXT    NOT NULL DEFAULT '{}',
    updated_at          TEXT    NOT NULL DEFAULT (datetime('now','localtime'))
);

-- 예약 가능 시간대 (운영자 생성)
CREATE TABLE IF NOT EXISTS booking_slots (
    slot_id         TEXT    PRIMARY KEY,
    owner           TEXT    NOT NULL,
    slot_date       TEXT    NOT NULL,
    slot_time       TEXT    NOT NULL,
    capacity        INTEGER NOT NULL DEFAULT 1,
    booked_count    INTEGER NOT NULL DEFAULT 0,
    label           TEXT    NOT NULL DEFAULT '',
    domain_id       TEXT    DEFAULT NULL,
    is_blocked      INTEGER NOT NULL DEFAULT 0,
    created_at      TEXT    NOT NULL DEFAULT (datetime('now','localtime')),
    updated_at      TEXT    NOT NULL DEFAULT (datetime('now','localtime')),
    UNIQUE(owner, slot_date, slot_time)
);
CREATE INDEX IF NOT EXISTS idx_slots_owner_date ON booking_slots(owner, slot_date);

-- 예약 내역
CREATE TABLE IF NOT EXISTS bookings (
    booking_id      TEXT    PRIMARY KEY,
    owner           TEXT    NOT NULL,
    slot_id         TEXT    REFERENCES booking_slots(slot_id),
    slot_date       TEXT    NOT NULL,
    slot_time       TEXT    NOT NULL,
    customer_name   TEXT    NOT NULL DEFAULT '',
    customer_phone  TEXT    NOT NULL DEFAULT '',
    party_size      INTEGER NOT NULL DEFAULT 1,
    service_type    TEXT    NOT NULL DEFAULT '',
    status          TEXT    NOT NULL DEFAULT 'confirmed',
    extra_data      TEXT    NOT NULL DEFAULT '{}',
    call_id         TEXT    NOT NULL DEFAULT '',
    memo            TEXT    NOT NULL DEFAULT '',
    created_at      TEXT    NOT NULL DEFAULT (datetime('now','localtime')),
    updated_at      TEXT    NOT NULL DEFAULT (datetime('now','localtime'))
);
CREATE INDEX IF NOT EXISTS idx_bookings_owner_date ON bookings(owner, slot_date);
CREATE INDEX IF NOT EXISTS idx_bookings_phone ON bookings(customer_phone);
CREATE INDEX IF NOT EXISTS idx_bookings_status ON bookings(status);

-- 통화 이력 (P3: DB 기반 관리)
CREATE TABLE IF NOT EXISTS call_records (
    call_id         TEXT    PRIMARY KEY,
    owner           TEXT    NOT NULL DEFAULT '',
    caller_id       TEXT    NOT NULL DEFAULT '',
    callee_id       TEXT    NOT NULL DEFAULT '',
    direction       TEXT    NOT NULL DEFAULT 'inbound',
    start_time      TEXT,
    end_time        TEXT,
    duration        REAL,
    call_summary    TEXT    DEFAULT '',
    is_ai_handled   INTEGER NOT NULL DEFAULT 0,
    ai_unhandled_count  INTEGER NOT NULL DEFAULT 0,
    is_unresolved   INTEGER NOT NULL DEFAULT 0,
    has_recording   INTEGER NOT NULL DEFAULT 0,
    has_transcript  INTEGER NOT NULL DEFAULT 0,
    recordings_dir  TEXT    DEFAULT '',
    extra_data      TEXT    NOT NULL DEFAULT '{}',
    created_at      TEXT    DEFAULT (datetime('now','localtime')),
    updated_at      TEXT    DEFAULT (datetime('now','localtime'))
);
CREATE INDEX IF NOT EXISTS idx_call_records_owner  ON call_records(owner);
CREATE INDEX IF NOT EXISTS idx_call_records_start  ON call_records(start_time DESC);
CREATE INDEX IF NOT EXISTS idx_call_records_caller ON call_records(caller_id);

-- 연락처 사용자 폴더 (중첩 디렉터리) — caller_contacts.folder_id 보다 먼저 생성
CREATE TABLE IF NOT EXISTS contact_folders (
    id          TEXT    PRIMARY KEY,
    owner       TEXT    NOT NULL,
    parent_id   TEXT    DEFAULT NULL REFERENCES contact_folders(id),
    name        TEXT    NOT NULL DEFAULT '',
    sort_order  INTEGER NOT NULL DEFAULT 0,
    created_at  TEXT    NOT NULL DEFAULT (datetime('now','localtime')),
    updated_at  TEXT    NOT NULL DEFAULT (datetime('now','localtime'))
);
CREATE INDEX IF NOT EXISTS idx_contact_folders_owner ON contact_folders(owner);
CREATE INDEX IF NOT EXISTS idx_contact_folders_parent ON contact_folders(owner, parent_id);

-- 발신자 CID·연락처 (테넌트별 번호 키, 수동/LLM 자동)
CREATE TABLE IF NOT EXISTS caller_contacts (
    id               TEXT    PRIMARY KEY,
    owner            TEXT    NOT NULL,
    canonical_phone  TEXT    NOT NULL,
    display_name     TEXT    NOT NULL DEFAULT '',
    memo             TEXT    NOT NULL DEFAULT '',
    source           TEXT    NOT NULL DEFAULT 'manual',
    llm_confidence   REAL,
    folder_id        TEXT    DEFAULT NULL REFERENCES contact_folders(id) ON DELETE SET NULL,
    created_at       TEXT    NOT NULL DEFAULT (datetime('now','localtime')),
    updated_at       TEXT    NOT NULL DEFAULT (datetime('now','localtime')),
    UNIQUE(owner, canonical_phone)
);
CREATE INDEX IF NOT EXISTS idx_caller_contacts_owner ON caller_contacts(owner);
CREATE INDEX IF NOT EXISTS idx_caller_contacts_phone ON caller_contacts(canonical_phone);
-- folder_id 인덱스는 _MIGRATIONS에서 ADD COLUMN 이후 생성 (구 DB에 folder_id 없으면 여기서 실패해 전체 DDL이 중단됨)

-- 도메인별 추가 수집 항목 정의
CREATE TABLE IF NOT EXISTS booking_schema_fields (
    field_id        TEXT    PRIMARY KEY,
    owner           TEXT    NOT NULL,
    field_key       TEXT    NOT NULL,
    field_label     TEXT    NOT NULL,
    field_type      TEXT    NOT NULL DEFAULT 'text',
    required        INTEGER NOT NULL DEFAULT 0,
    default_value   TEXT    NOT NULL DEFAULT '',
    options         TEXT    NOT NULL DEFAULT '[]',
    sort_order      INTEGER NOT NULL DEFAULT 0,
    created_at      TEXT    NOT NULL DEFAULT (datetime('now','localtime')),
    UNIQUE(owner, field_key)
);
CREATE INDEX IF NOT EXISTS idx_schema_fields_owner ON booking_schema_fields(owner);

-- 예약 도메인 정의 (복수 설정 가능, 슬롯과 연결됨)
CREATE TABLE IF NOT EXISTS booking_domains (
    domain_id       TEXT    PRIMARY KEY,
    owner           TEXT    NOT NULL,
    domain_name     TEXT    NOT NULL,
    description     TEXT    NOT NULL DEFAULT '',
    required_fields TEXT    NOT NULL DEFAULT '[]',
    optional_fields TEXT    NOT NULL DEFAULT '[]',
    sort_order      INTEGER NOT NULL DEFAULT 0,
    is_active       INTEGER NOT NULL DEFAULT 1,
    created_at      TEXT    NOT NULL DEFAULT (datetime('now','localtime')),
    updated_at      TEXT    NOT NULL DEFAULT (datetime('now','localtime')),
    UNIQUE(owner, domain_name)
);
CREATE INDEX IF NOT EXISTS idx_booking_domains_owner ON booking_domains(owner);

-- 도메인 수집 필드 정의 (booking_domains 에 연결)
CREATE TABLE IF NOT EXISTS booking_domain_fields (
    field_id        TEXT    PRIMARY KEY,
    owner           TEXT    NOT NULL,
    field_key       TEXT    NOT NULL,
    field_label     TEXT    NOT NULL,
    field_type      TEXT    NOT NULL DEFAULT 'text',
    options         TEXT    NOT NULL DEFAULT '[]',
    sort_order      INTEGER NOT NULL DEFAULT 0,
    created_at      TEXT    NOT NULL DEFAULT (datetime('now','localtime')),
    UNIQUE(owner, field_key)
);
CREATE INDEX IF NOT EXISTS idx_domain_fields_owner ON booking_domain_fields(owner);

-- SIP MESSAGE 채팅 이력 (수신/발신 모두 기록)
CREATE TABLE IF NOT EXISTS chat_messages (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    thread_id   TEXT    NOT NULL,
    owner       TEXT    NOT NULL,
    direction   TEXT    NOT NULL,
    from_phone  TEXT    NOT NULL,
    to_phone    TEXT    NOT NULL,
    body        TEXT    NOT NULL,
    call_id     TEXT    NOT NULL DEFAULT '',
    status      TEXT    NOT NULL DEFAULT 'delivered',
    error_code  TEXT    NOT NULL DEFAULT '',
    created_at  TEXT    NOT NULL DEFAULT (datetime('now','localtime'))
);
CREATE INDEX IF NOT EXISTS idx_chat_messages_thread  ON chat_messages(thread_id, owner);
CREATE INDEX IF NOT EXISTS idx_chat_messages_created ON chat_messages(created_at);

-- 채팅 SIP 릴레이: 테넌트(owner) ↔ REGISTER 내선(sip_username)
CREATE TABLE IF NOT EXISTS chat_relay_settings (
    owner        TEXT    PRIMARY KEY,
    sip_username TEXT    NOT NULL DEFAULT '',
    updated_at   TEXT    NOT NULL DEFAULT (datetime('now','localtime'))
);
CREATE INDEX IF NOT EXISTS idx_chat_relay_sip ON chat_relay_settings(sip_username);

-- Google OAuth 토큰 저장 (owner별 1건)
CREATE TABLE IF NOT EXISTS google_tokens (
    owner           TEXT    PRIMARY KEY,
    access_token    TEXT    NOT NULL,
    refresh_token   TEXT    NOT NULL DEFAULT '',
    token_expiry    TEXT    NOT NULL,
    calendar_id     TEXT    NOT NULL DEFAULT 'primary',
    connected_at    TEXT    NOT NULL DEFAULT (datetime('now','localtime')),
    updated_at      TEXT    NOT NULL DEFAULT (datetime('now','localtime'))
);

-- 예약 ↔ Google Calendar 이벤트 ID 매핑
CREATE TABLE IF NOT EXISTS gcal_event_map (
    booking_id      TEXT    PRIMARY KEY,
    gcal_event_id   TEXT    NOT NULL,
    owner           TEXT    NOT NULL,
    synced_at       TEXT    NOT NULL DEFAULT (datetime('now','localtime'))
);
CREATE INDEX IF NOT EXISTS idx_gcal_event_map_owner ON gcal_event_map(owner);

-- 통화 연결음 설정 (owner별 1건)
CREATE TABLE IF NOT EXISTS ringback_settings (
    owner                TEXT    PRIMARY KEY,
    greeting_text        TEXT    NOT NULL DEFAULT '',   -- TTS 인사말 텍스트
    greeting_audio_path  TEXT    NOT NULL DEFAULT '',   -- TTS 캐시 WAV 경로
    suno_task_id         TEXT    NOT NULL DEFAULT '',   -- Suno 생성 task ID
    suno_audio_url       TEXT    NOT NULL DEFAULT '',   -- Suno 음원 URL (MP3)
    suno_audio_path      TEXT    NOT NULL DEFAULT '',   -- 로컬 캐시 경로
    suno_lyrics          TEXT    NOT NULL DEFAULT '',   -- 가사
    suno_style           TEXT    NOT NULL DEFAULT '',   -- 스타일 태그
    suno_title           TEXT    NOT NULL DEFAULT '',
    suno_vocal_gender    TEXT    NOT NULL DEFAULT 'm',  -- m / f
    suno_duration_target INTEGER NOT NULL DEFAULT 60,   -- 목표 초
    enabled_greeting     INTEGER NOT NULL DEFAULT 0,    -- 1=사용
    enabled_ringback     INTEGER NOT NULL DEFAULT 0,    -- 1=사용
    updated_at           TEXT    NOT NULL DEFAULT (datetime('now','localtime'))
);

-- 통화 연결음 생성 음원 목록 (owner별 다수, 회차별 관리)
CREATE TABLE IF NOT EXISTS ringback_music_items (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    owner         TEXT    NOT NULL,
    task_id       TEXT    NOT NULL,
    index_in_task INTEGER NOT NULL DEFAULT 0,  -- task 내 곡 순서 (0, 1)
    audio_url     TEXT    NOT NULL DEFAULT '',  -- Suno 원본 MP3 URL
    local_path    TEXT    NOT NULL DEFAULT '',  -- 로컬 캐시 경로
    title         TEXT    NOT NULL DEFAULT '',
    duration      REAL    NOT NULL DEFAULT 0,
    is_active     INTEGER NOT NULL DEFAULT 0,   -- 1=현재 통화연결음으로 사용 중
    created_at    TEXT    NOT NULL DEFAULT (datetime('now','localtime'))
);
CREATE INDEX IF NOT EXISTS idx_ringback_items_owner ON ringback_music_items(owner, created_at DESC);

-- 셀프서비스 자동설정 변경 이력 (Story 1.8 FR8 — 감사 로그)
CREATE TABLE IF NOT EXISTS self_service_config_changes (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    owner       TEXT    NOT NULL,
    domain      TEXT    NOT NULL,
    field       TEXT    NOT NULL,
    old_value   TEXT    NOT NULL DEFAULT '',
    new_value   TEXT    NOT NULL DEFAULT '',
    call_id     TEXT    NOT NULL DEFAULT '',
    changed_at  TEXT    NOT NULL DEFAULT (datetime('now','localtime'))
);
CREATE INDEX IF NOT EXISTS idx_self_service_config_changes_owner ON self_service_config_changes(owner, changed_at DESC);

-- 셀프서비스 설정 카탈로그/Screen Graph 동적 구성 (Epic 2 Story 2.1)
-- config_kind: 'catalog' | 'screen_graph'. 같은 kind 내에서 version_no가 증가하며,
-- is_active=1인 레코드가 정확히 1건이어야 한다(활성 버전 = 롤백 대상).
CREATE TABLE IF NOT EXISTS self_service_catalog_config (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    config_kind  TEXT    NOT NULL,
    version_no   INTEGER NOT NULL,
    config_json  TEXT    NOT NULL DEFAULT '{}',
    is_active    INTEGER NOT NULL DEFAULT 0,
    uploaded_by  TEXT    NOT NULL DEFAULT '',
    note         TEXT    NOT NULL DEFAULT '',
    created_at   TEXT    NOT NULL DEFAULT (datetime('now','localtime')),
    UNIQUE(config_kind, version_no)
);
CREATE INDEX IF NOT EXISTS idx_self_service_catalog_config_active ON self_service_catalog_config(config_kind, is_active);
"""


_MIGRATIONS = [
    # booking_domains 테이블 추가 (이미 DDL에 포함, 여기선 컬럼 추가만)
    "ALTER TABLE booking_slots ADD COLUMN domain_id TEXT DEFAULT NULL",
    "ALTER TABLE booking_domains ADD COLUMN description TEXT NOT NULL DEFAULT ''",
    "ALTER TABLE call_records ADD COLUMN is_unresolved INTEGER NOT NULL DEFAULT 0",
    "ALTER TABLE chat_messages ADD COLUMN error_code TEXT NOT NULL DEFAULT ''",
    # SIP MESSAGE / RCS 등 텍스트 수신 시 AI 자동응답 — 테넌트「설정」(chat_relay_settings)
    "ALTER TABLE chat_relay_settings ADD COLUMN message_ai_policy TEXT NOT NULL DEFAULT 'persona'",
    "ALTER TABLE chat_relay_settings ADD COLUMN message_ai_reply_enabled INTEGER NOT NULL DEFAULT 0",
    "ALTER TABLE chat_relay_settings ADD COLUMN message_ai_reply_prefix TEXT NOT NULL DEFAULT ''",
    # 연락처 사용자 폴더 (기존 DB: 테이블은 _DDL로 생성, 컬럼만 추가)
    "ALTER TABLE caller_contacts ADD COLUMN folder_id TEXT DEFAULT NULL",
    "CREATE INDEX IF NOT EXISTS idx_caller_contacts_folder ON caller_contacts(owner, folder_id)",
    # 셀프서비스 카탈로그/Screen Graph 설정 — "누가/언제 현재 활성 버전을 활성화했는지"
    # 감사 추적용(Epic 2 Story 2.5 AC4). created_at은 버전이 "생성(업로드)"된 시각이고,
    # activated_at/activated_by는 그 버전이 마지막으로 "활성화(적용/롤백)"된 시각·주체다 —
    # 별도 감사 로그 테이블 없이 버전 이력 테이블 자체가 감사 로그를 겸한다.
    "ALTER TABLE self_service_catalog_config ADD COLUMN activated_at TEXT DEFAULT NULL",
    "ALTER TABLE self_service_catalog_config ADD COLUMN activated_by TEXT NOT NULL DEFAULT ''",
]


def init_db() -> None:
    """테이블 초기화 (서버 기동 시 1회 호출)."""
    with get_db() as conn:
        conn.executescript(_DDL)
        # 컬럼 추가 마이그레이션 (이미 존재하면 무시)
        for sql in _MIGRATIONS:
            try:
                conn.execute(sql)
            except Exception:
                pass
    logger.info("booking_db_initialized", path=_get_db_path())


def row_to_dict(row: sqlite3.Row | None) -> dict | None:
    if row is None:
        return None
    d = dict(row)
    for key in ("extra_config", "extra_data", "options", "required_fields", "optional_fields"):
        if key in d and isinstance(d[key], str):
            try:
                d[key] = json.loads(d[key])
            except (json.JSONDecodeError, TypeError):
                d[key] = {} if key == "extra_config" else []
    return d
