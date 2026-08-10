"""
셀프서비스 카탈로그/Screen Graph 동적 구성 캐시 로더 (Epic 2 Story 2.1/2.2).

`self_service_catalog_config_db.py`의 활성 버전(version)을 in-memory로 캐시해, 매 조회마다
DB를 왕복하지 않도록 한다(NFR6). 활성 버전 번호가 바뀌었을 때만 캐시를 갱신한다 —
`invalidate_cache()`를 명시적으로 호출하면 다음 조회에서 강제로 DB를 다시 확인한다
(Story 2.5의 "업로드 후 즉시 반영" 요구사항이 이 무효화 호출에 의존한다).

DB 조회 자체가 실패하면(테이블 없음, 파일 잠금 등) 직전 캐시 값을 그대로 유지하고, 캐시조차
없다면 None을 반환한다 — 호출측(`settings_catalog.py`/`screen_graph.py`)이 하드코딩 폴백으로
안전하게 전환할 수 있도록 예외를 전파하지 않는다(AC3: 서버 기동 자체는 절대 실패하지 않아야 함).
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

import structlog

from src.common.self_service_catalog_config_db import CATALOG_KIND, SCREEN_GRAPH_KIND

logger = structlog.get_logger(__name__)

__all__ = [
    "CATALOG_KIND", "SCREEN_GRAPH_KIND",
    "get_cached_config", "invalidate_cache", "validate_config", "diff_configs",
]

# (config_kind, owner) -> {"version_no": int, "config": dict}
_cache: Dict[tuple, Dict[str, Any]] = {}


def get_cached_config(config_kind: str, owner: str = "") -> Optional[Dict[str, Any]]:
    """활성 버전의 `config_json`을 반환한다(owner 지정 시 해당 테넌트 커스텀 우선, 없으면
    전역 기본값으로 폴백 — `self_service_catalog_config_db.get_active_config()` 동일).

    - DB에 활성 버전이 없으면 None(호출측이 하드코딩 폴백을 사용해야 함을 의미).
    - DB 조회 자체가 실패하면(예외) 직전 캐시 값을 그대로 반환(없으면 None) — 예외를
      호출측으로 전파하지 않는다.
    """
    normalized_owner = (owner or "").strip()
    cache_key = (config_kind, normalized_owner)
    cached = _cache.get(cache_key)
    try:
        from src.common.self_service_catalog_config_db import get_active_config

        active = get_active_config(config_kind, normalized_owner)
    except Exception as e:
        logger.warning(
            "catalog_config_loader_db_query_failed", config_kind=config_kind, owner=normalized_owner, error=str(e),
        )
        return cached["config"] if cached else None

    if active is None:
        return None

    if cached is None or cached["version_no"] != active["version_no"]:
        logger.info(
            "catalog_config_loader_cache_refreshed",
            config_kind=config_kind,
            owner=normalized_owner,
            old_version=cached["version_no"] if cached else None,
            new_version=active["version_no"],
        )
        _cache[cache_key] = {"version_no": active["version_no"], "config": active["config_json"]}
    return _cache[cache_key]["config"]


def invalidate_cache(config_kind: Optional[str] = None, owner: Optional[str] = None) -> None:
    """캐시 무효화. `config_kind`/`owner` 모두 생략 시 전체 무효화,
    `config_kind`만 주면 해당 kind의 모든 owner 커스텀 무효화."""
    if config_kind is None:
        _cache.clear()
        return
    if owner is None:
        for key in [k for k in _cache if k[0] == config_kind]:
            _cache.pop(key, None)
    else:
        _cache.pop((config_kind, (owner or "").strip()), None)


def validate_config(
    config_kind: str,
    config: Dict[str, Any],
    *,
    get_fn_names: Optional[List[str]] = None,
    update_fn_names: Optional[List[str]] = None,
) -> List[str]:
    """업로드된 설정 JSON의 구조·함수 참조를 검증한다(Epic 2 Story 2.5, 업로드 게이트).

    반환값이 빈 리스트면 통과. 실패 시 호출측(`settings_ai_assistant.py::import_catalog_config()`)은
    **아무것도 저장하지 않아야 한다**(원자성 — IV1 보안 핵심 시나리오).

    - `config_kind == CATALOG_KIND`: `domains` dict의 각 항목에 대해 `get_fn_ref`(필수)가
      화이트리스트(`get_fn_names`)에 있는지, `update_fn_ref`(선택)가 있다면 역시 화이트리스트
      (`update_fn_names`)에 있는지 검증한다. 임의 코드 실행 방지가 목적이므로 이 검사가 가장 중요하다.
    - `config_kind == SCREEN_GRAPH_KIND`: 실행 가능한 참조가 전혀 없는 순수 데이터이므로 화이트리스트
      검사는 없지만, 필수 필드(route/title/description/nav_hint)가 문자열로 존재하는지 등 구조만 검증한다.
    """
    if config_kind == CATALOG_KIND:
        return _validate_catalog_config(config, get_fn_names or [], update_fn_names or [])
    if config_kind == SCREEN_GRAPH_KIND:
        return _validate_screen_graph_config(config)
    return [f"알 수 없는 config_kind입니다: {config_kind}"]


def _validate_catalog_config(
    config: Dict[str, Any], get_fn_names: List[str], update_fn_names: List[str],
) -> List[str]:
    domains = config.get("domains")
    if not isinstance(domains, dict):
        return ["'domains' 필드가 객체(dict)가 아니거나 존재하지 않습니다"]

    errors: List[str] = []
    for domain_name, entry in domains.items():
        if not isinstance(entry, dict):
            errors.append(f"{domain_name}: 항목이 객체(dict)가 아닙니다")
            continue
        get_ref = entry.get("get_fn_ref")
        if not get_ref:
            errors.append(f"{domain_name}.get_fn_ref가 비어 있습니다(필수)")
        elif get_ref not in get_fn_names:
            errors.append(f"{domain_name}.get_fn_ref='{get_ref}'는 화이트리스트에 없는 함수명입니다")
        update_ref = entry.get("update_fn_ref")
        if update_ref and update_ref not in update_fn_names:
            errors.append(f"{domain_name}.update_fn_ref='{update_ref}'는 화이트리스트에 없는 함수명입니다")
    return errors


def _validate_screen_graph_config(config: Dict[str, Any]) -> List[str]:
    screens = config.get("screens")
    if not isinstance(screens, dict):
        return ["'screens' 필드가 객체(dict)가 아니거나 존재하지 않습니다"]

    errors: List[str] = []
    for domain_name, entry in screens.items():
        if not isinstance(entry, dict):
            errors.append(f"{domain_name}: 항목이 객체(dict)가 아닙니다")
            continue
        for required_key in ("route", "title", "description", "nav_hint"):
            value = entry.get(required_key)
            if not isinstance(value, str) or not value:
                errors.append(f"{domain_name}.{required_key}가 비어 있거나 문자열이 아닙니다(필수)")
        fields = entry.get("fields", [])
        if not isinstance(fields, list):
            errors.append(f"{domain_name}.fields가 리스트가 아닙니다")
    return errors


def diff_configs(config_kind: str, old_config: Optional[Dict[str, Any]], new_config: Dict[str, Any]) -> Dict[str, List[str]]:
    """업로드 미리보기용 얕은 diff — 추가/삭제/변경된 도메인(또는 화면) 키 목록만 계산한다.

    `config_kind`에 따라 최상위 컨테이너 키가 다르다(`domains` vs `screens`). 값 비교는
    JSON 직렬화 문자열 비교로 충분하다(순서 무관 비교를 위해 `sort_keys=True` 사용).
    """
    import json as _json

    top_key = "domains" if config_kind == CATALOG_KIND else "screens"
    old_items = (old_config or {}).get(top_key, {}) if isinstance(old_config, dict) else {}
    new_items = new_config.get(top_key, {}) if isinstance(new_config, dict) else {}
    if not isinstance(old_items, dict):
        old_items = {}
    if not isinstance(new_items, dict):
        new_items = {}

    added = sorted(set(new_items) - set(old_items))
    removed = sorted(set(old_items) - set(new_items))
    changed = sorted(
        k for k in (set(new_items) & set(old_items))
        if _json.dumps(old_items[k], sort_keys=True, ensure_ascii=False)
        != _json.dumps(new_items[k], sort_keys=True, ensure_ascii=False)
    )
    return {"added": added, "removed": removed, "changed": changed}

