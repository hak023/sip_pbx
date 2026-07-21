"""
셀프서비스 설정 카탈로그/Screen Graph 동적 구성 SQLite 헬퍼 (Epic 2 Story 2.1).

booking.db와 동일 파일을 공유한다(src.booking.database). `self_service_catalog_config`
테이블에 config_kind("catalog" | "screen_graph")별로 버전을 누적 저장하고, 그 중 정확히
1건만 `is_active=1`로 표시한다 — 이 활성 레코드가 런타임에 로드되는 설정이다(Story 2.2/2.3의
`catalog_config_loader.py`가 소비).

버전 관리 원칙:
- `save_new_version()`은 항상 새 버전을 비활성 상태로 추가만 한다(기존 활성 버전을 건드리지 않음).
- `activate_version()`을 별도로 호출해야 실제로 반영된다(업로드 검증 통과 후 명시적 승인 단계를
  분리하기 위함 — Story 2.5의 "미리보기 → 확정" 흐름과 대응).
- 롤백은 과거 version_no를 다시 `activate_version()`하는 것으로 구현한다(별도 롤백 전용 API 불필요).
"""

from __future__ import annotations

import json
import logging
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

_DB_AVAILABLE = True

CATALOG_KIND = "catalog"
SCREEN_GRAPH_KIND = "screen_graph"
_VALID_KINDS = frozenset({CATALOG_KIND, SCREEN_GRAPH_KIND})


def _row_to_dict(row) -> Dict[str, Any]:
    d = dict(row)
    try:
        d["config_json"] = json.loads(d.get("config_json") or "{}")
    except (json.JSONDecodeError, TypeError):
        d["config_json"] = {}
    d["is_active"] = bool(d.get("is_active"))
    return d


def get_active_config(config_kind: str) -> Optional[Dict[str, Any]]:
    """config_kind의 현재 활성 버전 레코드를 반환한다. 없으면 None(호출측이 하드코딩 폴백 등을 판단)."""
    global _DB_AVAILABLE
    if config_kind not in _VALID_KINDS or not _DB_AVAILABLE:
        return None
    try:
        from src.booking.database import get_db
    except ImportError:
        _DB_AVAILABLE = False
        logger.debug("self_service_catalog_config_db_import_failed")
        return None

    try:
        with get_db() as conn:
            row = conn.execute(
                "SELECT * FROM self_service_catalog_config WHERE config_kind = ? AND is_active = 1"
                " ORDER BY version_no DESC LIMIT 1",
                (config_kind,),
            ).fetchone()
        return _row_to_dict(row) if row is not None else None
    except Exception as exc:
        logger.warning("self_service_catalog_config_get_active_failed kind=%s err=%s", config_kind, exc)
        return None


def save_new_version(
    config_kind: str, config: Dict[str, Any], *, uploaded_by: str = "", note: str = "",
) -> Optional[int]:
    """신규 버전을 비활성 상태로 저장한다. 반환값은 새 version_no(실패 시 None)."""
    global _DB_AVAILABLE
    if config_kind not in _VALID_KINDS:
        logger.warning("self_service_catalog_config_invalid_kind kind=%s", config_kind)
        return None
    if not _DB_AVAILABLE:
        return None
    try:
        from src.booking.database import get_db
    except ImportError:
        _DB_AVAILABLE = False
        return None

    config_json = json.dumps(config, ensure_ascii=False)
    try:
        with get_db() as conn:
            row = conn.execute(
                "SELECT COALESCE(MAX(version_no), 0) AS max_v FROM self_service_catalog_config"
                " WHERE config_kind = ?",
                (config_kind,),
            ).fetchone()
            next_version = int(row["max_v"]) + 1
            conn.execute(
                """
                INSERT INTO self_service_catalog_config
                    (config_kind, version_no, config_json, is_active, uploaded_by, note)
                VALUES (?, ?, ?, 0, ?, ?)
                """,
                (config_kind, next_version, config_json, uploaded_by or "", note or ""),
            )
        return next_version
    except Exception as exc:
        logger.warning("self_service_catalog_config_save_failed kind=%s err=%s", config_kind, exc)
        return None


def activate_version(config_kind: str, version_no: int, *, activated_by: str = "") -> bool:
    """지정 버전을 활성화하고 같은 kind의 다른 버전은 모두 비활성화한다(롤백도 동일 함수 재사용).

    `activated_at`/`activated_by`를 함께 기록한다 — 별도 감사 로그 테이블 없이 이 두 컬럼이
    "현재 활성 버전을 누가/언제 적용(또는 롤백)했는지"에 대한 감사 추적 역할을 한다
    (Epic 2 Story 2.5 AC4).
    """
    global _DB_AVAILABLE
    if config_kind not in _VALID_KINDS or not _DB_AVAILABLE:
        return False
    try:
        from src.booking.database import get_db
    except ImportError:
        _DB_AVAILABLE = False
        return False

    try:
        with get_db() as conn:
            existing = conn.execute(
                "SELECT id FROM self_service_catalog_config WHERE config_kind = ? AND version_no = ?",
                (config_kind, version_no),
            ).fetchone()
            if existing is None:
                return False
            conn.execute(
                "UPDATE self_service_catalog_config SET is_active = 0 WHERE config_kind = ?",
                (config_kind,),
            )
            conn.execute(
                "UPDATE self_service_catalog_config"
                " SET is_active = 1, activated_at = datetime('now','localtime'), activated_by = ?"
                " WHERE config_kind = ? AND version_no = ?",
                (activated_by or "", config_kind, version_no),
            )
        return True
    except Exception as exc:
        logger.warning(
            "self_service_catalog_config_activate_failed kind=%s version=%s err=%s",
            config_kind, version_no, exc,
        )
        return False


def list_versions(config_kind: str, limit: int = 20) -> List[Dict[str, Any]]:
    """config_kind의 버전 이력을 최신순으로 반환한다(config_json은 요약을 위해 제외하지 않고 포함)."""
    global _DB_AVAILABLE
    if config_kind not in _VALID_KINDS or not _DB_AVAILABLE:
        return []
    try:
        from src.booking.database import get_db
    except ImportError:
        _DB_AVAILABLE = False
        return []

    try:
        with get_db() as conn:
            rows = conn.execute(
                "SELECT * FROM self_service_catalog_config WHERE config_kind = ?"
                " ORDER BY version_no DESC LIMIT ?",
                (config_kind, limit),
            ).fetchall()
        return [_row_to_dict(r) for r in rows]
    except Exception as exc:
        logger.warning("self_service_catalog_config_list_versions_failed kind=%s err=%s", config_kind, exc)
        return []
