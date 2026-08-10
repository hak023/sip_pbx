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


def get_active_config(config_kind: str, owner: str = "") -> Optional[Dict[str, Any]]:
    """config_kind의 현재 활성 버전 레코드를 반환한다.

    owner가 주어지면 해당 테넌트 전용 커스텀 버전을 우선 조회하고, 없으면 owner=''(전역
    기본값)로 폴백한다(2026-08-07, NFR11 — 테넌트가 커스터마이즈하지 않았으면 기존과 동일하게
    공통 기본 설정을 그대로 쓰는 하위 호환 유지). owner를 생략하면 기존과 동일하게 전역
    기본값만 조회한다. 둘 다 없으면 None(호출측이 하드코딩 폴백 등을 판단).
    """
    global _DB_AVAILABLE
    if config_kind not in _VALID_KINDS or not _DB_AVAILABLE:
        return None
    try:
        from src.booking.database import get_db
    except ImportError:
        _DB_AVAILABLE = False
        logger.debug("self_service_catalog_config_db_import_failed")
        return None

    normalized_owner = (owner or "").strip()
    try:
        with get_db() as conn:
            if normalized_owner:
                row = conn.execute(
                    "SELECT * FROM self_service_catalog_config"
                    " WHERE config_kind = ? AND owner = ? AND is_active = 1"
                    " ORDER BY version_no DESC LIMIT 1",
                    (config_kind, normalized_owner),
                ).fetchone()
                if row is not None:
                    return _row_to_dict(row)
            row = conn.execute(
                "SELECT * FROM self_service_catalog_config"
                " WHERE config_kind = ? AND owner = '' AND is_active = 1"
                " ORDER BY version_no DESC LIMIT 1",
                (config_kind,),
            ).fetchone()
        return _row_to_dict(row) if row is not None else None
    except Exception as exc:
        logger.warning("self_service_catalog_config_get_active_failed kind=%s err=%s", config_kind, exc)
        return None


def save_new_version(
    config_kind: str, config: Dict[str, Any], *, owner: str = "", uploaded_by: str = "", note: str = "",
) -> Optional[int]:
    """신규 버전을 비활성 상태로 저장한다(owner별로 독립적인 version_no 시퀀스).

    owner를 생략하면 기존과 동일하게 전역 기본값(owner='') 버전으로 저장된다.
    반환값은 새 version_no(실패 시 None).
    """
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
    normalized_owner = (owner or "").strip()
    try:
        with get_db() as conn:
            row = conn.execute(
                "SELECT COALESCE(MAX(version_no), 0) AS max_v FROM self_service_catalog_config"
                " WHERE config_kind = ? AND owner = ?",
                (config_kind, normalized_owner),
            ).fetchone()
            next_version = int(row["max_v"]) + 1
            conn.execute(
                """
                INSERT INTO self_service_catalog_config
                    (config_kind, owner, version_no, config_json, is_active, uploaded_by, note)
                VALUES (?, ?, ?, ?, 0, ?, ?)
                """,
                (config_kind, normalized_owner, next_version, config_json, uploaded_by or "", note or ""),
            )
        return next_version
    except Exception as exc:
        logger.warning("self_service_catalog_config_save_failed kind=%s err=%s", config_kind, exc)
        return None


def activate_version(config_kind: str, version_no: int, *, owner: str = "", activated_by: str = "") -> bool:
    """지정 버전을 활성화하고 같은 (kind, owner) 조합의 다른 버전은 모두 비활성화한다
    (롤백도 동일 함수 재사용). owner를 생략하면 전역 기본값(owner='') 버전을 활성화한다.

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
            normalized_owner = (owner or "").strip()
            existing = conn.execute(
                "SELECT id FROM self_service_catalog_config WHERE config_kind = ? AND owner = ? AND version_no = ?",
                (config_kind, normalized_owner, version_no),
            ).fetchone()
            if existing is None:
                return False
            conn.execute(
                "UPDATE self_service_catalog_config SET is_active = 0 WHERE config_kind = ? AND owner = ?",
                (config_kind, normalized_owner),
            )
            conn.execute(
                "UPDATE self_service_catalog_config"
                " SET is_active = 1, activated_at = datetime('now','localtime'), activated_by = ?"
                " WHERE config_kind = ? AND owner = ? AND version_no = ?",
                (activated_by or "", config_kind, normalized_owner, version_no),
            )
        return True
    except Exception as exc:
        logger.warning(
            "self_service_catalog_config_activate_failed kind=%s version=%s err=%s",
            config_kind, version_no, exc,
        )
        return False


def list_versions(config_kind: str, owner: str = "", limit: int = 20) -> List[Dict[str, Any]]:
    """(config_kind, owner)의 버전 이력을 최신순으로 반환한다(owner 생략 시 전역 기본값 버전만)."""
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
                "SELECT * FROM self_service_catalog_config WHERE config_kind = ? AND owner = ?"
                " ORDER BY version_no DESC LIMIT ?",
                (config_kind, (owner or "").strip(), limit),
            ).fetchall()
        return [_row_to_dict(r) for r in rows]
    except Exception as exc:
        logger.warning("self_service_catalog_config_list_versions_failed kind=%s err=%s", config_kind, exc)
        return []


def purge_owner_versions(owner: str) -> int:
    """지정 owner가 소유한 카탈로그/screen_graph 커스텀 버전을 전부 삭제한다("전체 삭제" 연동).

    owner=''(전역 기본값)은 다른 모든 테넌트에 영향을 주므로 이 함수로는 절대 지울 수 없다
    (호출측이 owner=''을 넘겨도 무조건 0건 처리하고 조용히 무시).
    """
    global _DB_AVAILABLE
    normalized_owner = (owner or "").strip()
    if not normalized_owner or not _DB_AVAILABLE:
        return 0
    try:
        from src.booking.database import get_db
    except ImportError:
        _DB_AVAILABLE = False
        return 0

    try:
        with get_db() as conn:
            cur = conn.execute(
                "DELETE FROM self_service_catalog_config WHERE owner = ?",
                (normalized_owner,),
            )
            return cur.rowcount or 0
    except Exception as exc:
        logger.warning("self_service_catalog_config_purge_owner_failed owner=%s err=%s", normalized_owner, exc)
        return 0


def clear_owner_catalog(owner: str) -> int:
    """owner의 카탈로그/screen_graph를 "완전히 빈 상태"로 명시적으로 초기화한다.

    (2026-08-07 버그 수정) `purge_owner_versions()`만으로는 owner 전용 행이 사라질 뿐,
    `get_active_config(kind, owner)`가 그 즉시 owner=''(전역 기본값)로 폴백해버려 프론트에
    "전체 삭제"를 눌러도 카탈로그/화면 안내가 그대로 남아있는 것처럼 보이는 문제가 있었다.
    이 함수는 삭제 직후 owner 전용의 **빈 활성 버전**({"domains": {}} / {"screens": {}})을
    새로 만들어 활성화한다 — 이후 이 테넌트는 전역 기본값으로 폴백하지 않고 "카탈로그/화면
    안내 0건"을 실제로 보게 된다. owner=''(전역 기본값)는 손대지 않는다.
    """
    normalized_owner = (owner or "").strip()
    if not normalized_owner:
        return 0
    purge_owner_versions(normalized_owner)
    cleared = 0
    for kind, empty_config in ((CATALOG_KIND, {"domains": {}}), (SCREEN_GRAPH_KIND, {"screens": {}})):
        version_no = save_new_version(kind, empty_config, owner=normalized_owner, uploaded_by="system_reset")
        if version_no is not None and activate_version(kind, version_no, owner=normalized_owner, activated_by="system_reset"):
            cleared += 1
    return cleared
