"""
셀프서비스 설정 카탈로그 (Story 1.4).

테넌트 관리자가 셀프서비스 세션에서 물어볼 수 있는 **모든 설정 도메인**을
한 곳에 등록해, AI가 어떤 설정이 존재하는지 스스로 알 수 있게 한다.

⚠️ 유지보수 규칙(FR11): 신규 설정 페이지·필드가 프론트엔드에 추가될 때
   이 모듈의 `_CATALOG`에 함께 등록하지 않으면, AI는 해당 설정을 전혀
   인식하지 못한다(조회 대상에서 누락됨). 새 도메인을 추가할 때는:
     1. 실제 백엔드 조회 함수를 확인한다(라우터가 아닌 서비스/DB 계층 우선).
     2. `get_fn(owner) -> dict`를 작성한다(부작용 없는 읽기 전용, owner 필수).
     3. `_register()`로 등록한다. `destructive`는 안전측 기본값 True —
        명시적으로 안전하다고 판단한 도메인만 False로 지정한다.

본 Story(1.4)는 **읽기 전용 조회**만 다룬다. 설정 변경(자동설정 실행)은
Story 1.8에서 별도로 구현하며, `destructive` 플래그는 여기서는 등록만 하고
실제 집행(위험 도메인 자동설정 제외)은 Story 1.8에서 처리한다.

7개 도메인과 실제 백엔드 함수(Story 1.4 Task 0 조사 결과):
  - persona        : `persona_service.PersonaService.get_persona(owner)` (조직 페르소나)
  - ai-escalation   : 위와 동일 persona 객체의 `escalation_mode`/`transfer_extension` 필드
                      (설정 화면 `/settings/ai-escalation`도 `/api/persona/{owner}`를 그대로 사용)
  - call-control    : `src/call_control/db.py`의 `list_rules`/`list_schedules`/`list_announcements`
                      (라우터 함수가 아닌 데이터 접근 계층을 직접 호출 — FastAPI Query 의존성 우회)
  - chat-relay      : `src/services/chat_relay_service.py::get_chat_relay_settings(owner)`
  - contacts        : `src/common/caller_contact_db.py::list_caller_contacts` +
                      `src/common/contact_folder_db.py::list_contact_folders`
                      (프론트 `/settings/contacts`는 `/contacts`로 리다이렉트되지만 데이터 자체는 유효)
  - general         : `src/api/routers/tenants.py::TENANTS_DATA` 테넌트 프로필(이름·업종 등)
  - integrations    : `src/services/gcal_service.py::get_oauth_status(owner)` (Google Calendar 연동)
                      (프론트 `/settings/integrations`는 `/settings/general`로 리다이렉트되지만
                      카탈로그 관점에서는 "테넌트 프로필"과 "외부 연동"을 별개 도메인으로 유지한다 —
                      두 개념은 성격이 달라 자동설정 시 서로 다른 destructive 판단이 필요할 수 있음)
"""

from __future__ import annotations

import inspect
from dataclasses import dataclass
from typing import Any, Awaitable, Callable, Dict, List, Optional, Union

import structlog

from src.ai_voicebot.self_service import catalog_config_loader

logger = structlog.get_logger(__name__)


@dataclass
class DomainEntry:
    """카탈로그에 등록되는 단일 설정 도메인.

    update_fn(owner, field, value) -> {"ok": bool, "old_value": Any, ...}: 쓰기 지원 도메인만 등록(Story 1.8).
    writable_fields: update_fn이 있는 도메인에서 실제로 값 변경을 허용하는 필드 화이트리스트
    (공격자가 임의 문자열을 field로 넣어 예기치 않은 속성을 설정하는 것을 막는 안전장치).
    """

    name: str
    get_fn: Callable[[str], Union[Dict[str, Any], Awaitable[Dict[str, Any]]]]
    schema: Dict[str, Any]
    destructive: bool = True
    update_fn: Optional[Callable[[str, str, Any], Awaitable[Dict[str, Any]]]] = None
    writable_fields: Optional[frozenset] = None
    # 필드별 허용값(enum형 필드만 등록). 미등록 필드는 값 검증을 하지 않는다(자유 문자열 필드용).
    # [2026-07-16 QA(Story 1.10 실행성 케이스)에서 발견된 버그] LLM이 escalation_mode에 유효한
    # "hitl"|"transfer"|"none" 대신 "disabled"라는 임의 값을 써서 실제로는 hitl_alert.py의
    # `escalation_mode == "none"` 분기를 타지 못해(무엇과도 매치 안 됨) AI가 사용자에게
    # "비활성화했다"고 답했지만 실제로는 HITL이 계속 트리거되는 불일치가 발생했다. 도구 설명에
    # 필드명만 나열하고 허용값은 나열하지 않은 것이 근본 원인(Story 1.8의 field_not_writable
    # 방어와 동일한 패턴을 값 레벨에도 적용해야 함).
    field_allowed_values: Optional[Dict[str, frozenset]] = None


_CATALOG: Dict[str, DomainEntry] = {}


def _register(
    name: str,
    get_fn: Callable[[str], Any],
    schema: Dict[str, Any],
    destructive: bool = True,
    update_fn: Optional[Callable[[str, str, Any], Any]] = None,
    writable_fields: Optional[Any] = None,
    field_allowed_values: Optional[Dict[str, Any]] = None,
) -> None:
    _CATALOG[name] = DomainEntry(
        name=name, get_fn=get_fn, schema=schema, destructive=destructive,
        update_fn=update_fn,
        writable_fields=frozenset(writable_fields) if writable_fields else None,
        field_allowed_values=(
            {k: frozenset(v) for k, v in field_allowed_values.items()}
            if field_allowed_values else None
        ),
    )


# ── persona 도메인 ──────────────────────────────────────────────────────────
async def _get_persona(owner: str) -> Dict[str, Any]:
    from src.ai_voicebot.knowledge.persona_service import get_persona_service

    service = get_persona_service()
    if service is None:
        return {"error": "persona_service_unavailable"}
    persona = await service.get_persona(owner)
    if persona is None:
        return {"owner": owner, "exists": False}
    return {
        "owner": persona.owner,
        "exists": True,
        "name": persona.name,
        "description": persona.description,
        "scope_keywords": persona.scope_keywords,
        "enabled": persona.enabled,
    }


# ── ai-escalation 도메인 (persona의 에스컬레이션 관련 필드만 발췌) ──────────
async def _get_ai_escalation(owner: str) -> Dict[str, Any]:
    from src.ai_voicebot.knowledge.persona_service import get_persona_service

    service = get_persona_service()
    if service is None:
        return {"error": "persona_service_unavailable"}
    persona = await service.get_persona(owner)
    if persona is None:
        # persona_exists=False: escalation_mode="hitl"은 코드 기본값일 뿐 관리자가 의식적으로
        # 선택한 값이 아니다 — Story 1.5 온보딩 체크리스트가 이 플래그로 "미결정" 여부를 판별한다.
        return {"owner": owner, "escalation_mode": "hitl", "transfer_extension": None, "persona_exists": False}
    return {
        "owner": persona.owner,
        "escalation_mode": persona.escalation_mode,
        "transfer_extension": persona.transfer_extension,
        "persona_exists": True,
    }


# ── call-control 도메인 ─────────────────────────────────────────────────────
async def _get_call_control(owner: str) -> Dict[str, Any]:
    from src.call_control import db as _db

    return {
        "owner": owner,
        "rules": _db.list_rules(owner),
        "schedules": _db.list_schedules(owner),
        "announcements": _db.list_announcements(owner),
    }


# ── chat-relay 도메인 ───────────────────────────────────────────────────────
async def _get_chat_relay(owner: str) -> Dict[str, Any]:
    from src.services.chat_relay_service import get_chat_relay_settings

    return get_chat_relay_settings(owner)


# ── contacts 도메인 ─────────────────────────────────────────────────────────
async def _get_contacts(owner: str) -> Dict[str, Any]:
    from src.common.caller_contact_db import list_caller_contacts
    from src.common.contact_folder_db import list_contact_folders

    items, total = list_caller_contacts(owner=owner, q="", limit=100, offset=0)
    folders = list_contact_folders(owner=owner)
    return {"owner": owner, "contacts_total": total, "contacts": items, "folders": folders}


# ── general 도메인 (테넌트 프로필) ──────────────────────────────────────────
async def _get_general(owner: str) -> Dict[str, Any]:
    from src.api.routers.tenants import TENANTS_DATA

    for tenant in TENANTS_DATA:
        if tenant.get("owner") == owner:
            return dict(tenant)
    return {"owner": owner, "error": "tenant_not_found"}


# ── integrations 도메인 (Google Calendar 연동) ──────────────────────────────
async def _get_integrations(owner: str) -> Dict[str, Any]:
    from src.services import gcal_service

    return gcal_service.get_oauth_status(owner)


# ── 변경 함수 (Story 1.8) ───────────────────────────────────────────────────
# persona/ai-escalation은 동일 OrganizationPersona 객체를 저장하는 하나의 매커니즘을 공유한다.
async def _update_persona(owner: str, field: str, value: Any) -> Dict[str, Any]:
    from src.ai_voicebot.knowledge.persona_service import get_persona_service
    from src.config.models import OrganizationPersona

    service = get_persona_service()
    if service is None:
        return {"ok": False, "error": "persona_service_unavailable"}
    persona = await service.get_persona(owner)
    if persona is None:
        return {"ok": False, "error": "persona_not_found"}
    old_value = getattr(persona, field, None)
    data = persona.model_dump()
    data[field] = value
    updated = OrganizationPersona(**data)
    ok = await service.save_persona(updated)
    return {"ok": bool(ok), "old_value": old_value, "new_value": value}


async def _update_ai_escalation(owner: str, field: str, value: Any) -> Dict[str, Any]:
    # ai-escalation은 persona 문서의 필드이므로 동일 저장 매커니즘을 재사용한다(CR4).
    return await _update_persona(owner, field, value)


async def _update_chat_relay(owner: str, field: str, value: Any) -> Dict[str, Any]:
    from src.services.chat_relay_service import get_chat_relay_settings, upsert_chat_relay_settings

    current = get_chat_relay_settings(owner)
    old_value = current.get(field)
    result = upsert_chat_relay_settings(owner, current.get("sip_username", ""), **{field: value})
    return {"ok": True, "old_value": old_value, "new_value": value, "result": result}


# ── 함수 화이트리스트 레지스트리 (Epic 2 Story 2.1) ─────────────────────────
# DB(동적 구성, self_service_catalog_config_db.py)에 저장되는 설정 레코드는 실제 Python
# 콜러블이 아니라 아래 화이트리스트에 등록된 **이름 문자열**만 참조할 수 있다. DB 설정에
# 임의 코드를 담아 실행하는 구조는 절대 허용하지 않는다(RCE 방지 — Epic 2 핵심 보안 설계,
# docs/architecture/self-service-ai-assistant-architecture.md §Epic 2 참고). 신규 함수를
# 추가해도 이 레지스트리에 등록하지 않으면 동적 구성이 참조할 수 없다(안전측 기본).
_GET_FN_REGISTRY: Dict[str, Callable[[str], Any]] = {
    "get_persona": _get_persona,
    "get_ai_escalation": _get_ai_escalation,
    "get_call_control": _get_call_control,
    "get_chat_relay": _get_chat_relay,
    "get_contacts": _get_contacts,
    "get_general": _get_general,
    "get_integrations": _get_integrations,
}
_UPDATE_FN_REGISTRY: Dict[str, Callable[[str, str, Any], Any]] = {
    "update_persona": _update_persona,
    "update_ai_escalation": _update_ai_escalation,
    "update_chat_relay": _update_chat_relay,
}


def get_fn_whitelist_names() -> List[str]:
    """등록된 get_fn 화이트리스트 이름 목록(검증·프론트엔드 안내용, Story 2.5에서 사용 예정)."""
    return list(_GET_FN_REGISTRY.keys())


def update_fn_whitelist_names() -> List[str]:
    """등록된 update_fn 화이트리스트 이름 목록(검증·프론트엔드 안내용, Story 2.5에서 사용 예정)."""
    return list(_UPDATE_FN_REGISTRY.keys())


def _reverse_lookup_whitelist(registry: Dict[str, Callable], fn: Optional[Callable]) -> Optional[str]:
    """콜러블 → 화이트리스트 이름 역조회. 등록되어 있지 않으면 None."""
    if fn is None:
        return None
    for name, registered_fn in registry.items():
        if registered_fn is fn:
            return name
    return None


def export_static_snapshot() -> Dict[str, Any]:
    """현재 하드코딩된 `_CATALOG`를 Story 2.1 DB 스키마와 동일한 JSON 구조로 내보낸다.

    용도:
    - `scripts/self_service_catalog_migrate_seed.py`의 최초 시드 데이터 소스.
    - DB에 활성 버전이 없을 때 export API(Story 2.4)의 폴백 응답.

    get_fn/update_fn은 실제 콜러블이 아니라 화이트리스트 이름 문자열로만 직렬화된다
    (RCE 방지 — Epic 2 핵심 보안 설계).
    """
    domains: Dict[str, Any] = {}
    for domain_name, entry in _CATALOG.items():
        domains[domain_name] = {
            "get_fn_ref": _reverse_lookup_whitelist(_GET_FN_REGISTRY, entry.get_fn),
            "update_fn_ref": _reverse_lookup_whitelist(_UPDATE_FN_REGISTRY, entry.update_fn),
            "schema": dict(entry.schema),
            "destructive": entry.destructive,
            "writable_fields": sorted(entry.writable_fields) if entry.writable_fields else [],
            "field_allowed_values": (
                {k: sorted(v) for k, v in entry.field_allowed_values.items()}
                if entry.field_allowed_values else {}
            ),
        }
    return {"domains": domains}


# ── 동적 카탈로그 로딩 (Epic 2 Story 2.2) ───────────────────────────────────
# `_CATALOG`(아래 `_register()` 호출로 채워짐)는 DB 미가용 시 사용하는 **하드코딩 폴백**으로만
# 유지된다. 정상 상태에서는 `_get_effective_catalog()`가 DB(Story 2.1)에 저장된 활성 버전을
# 우선 사용한다 — 이 함수만이 실제 조회 대상 카탈로그를 결정하며, `list_domains()` 등 5개
# 공개 함수는 전부 이 함수를 거쳐간다(CR5: 외부 시그니처는 변경하지 않음).
_effective_catalog_cache: Optional[Dict[str, "DomainEntry"]] = None
_effective_catalog_cache_source_id: Optional[int] = None


def _build_dynamic_catalog(raw_config: Dict[str, Any]) -> Dict[str, "DomainEntry"]:
    """DB에서 읽은 `config_json`(도메인별 메타데이터 dict)을 `DomainEntry` 딕셔너리로 변환한다.

    화이트리스트에 없는 `get_fn_ref`를 참조하는 도메인은 통째로 건너뛴다(조회조차 위험하므로
    안전측). `update_fn_ref`만 화이트리스트에 없으면 해당 도메인은 조회는 유지하되 쓰기만
    비활성화한다(update_fn=None → `call_update_fn()`이 `domain_not_writable` 반환).
    """
    domains_cfg = raw_config.get("domains")
    if not isinstance(domains_cfg, dict):
        logger.warning("settings_catalog_dynamic_config_missing_domains")
        return {}

    built: Dict[str, DomainEntry] = {}
    for domain_name, cfg in domains_cfg.items():
        if not isinstance(cfg, dict):
            logger.warning("settings_catalog_dynamic_invalid_domain_entry", domain=domain_name)
            continue

        get_ref = cfg.get("get_fn_ref")
        get_fn = _GET_FN_REGISTRY.get(get_ref) if get_ref else None
        if get_fn is None:
            logger.warning(
                "settings_catalog_dynamic_get_fn_not_whitelisted", domain=domain_name, get_fn_ref=get_ref,
            )
            continue

        update_ref = cfg.get("update_fn_ref")
        update_fn = _UPDATE_FN_REGISTRY.get(update_ref) if update_ref else None
        if update_ref and update_fn is None:
            logger.warning(
                "settings_catalog_dynamic_update_fn_not_whitelisted",
                domain=domain_name, update_fn_ref=update_ref,
            )

        writable_fields = cfg.get("writable_fields") or []
        field_allowed_values = cfg.get("field_allowed_values") or {}
        built[domain_name] = DomainEntry(
            name=domain_name,
            get_fn=get_fn,
            schema=dict(cfg.get("schema") or {}),
            destructive=bool(cfg.get("destructive", True)),
            update_fn=update_fn,
            writable_fields=frozenset(writable_fields) if writable_fields else None,
            field_allowed_values=(
                {k: frozenset(v) for k, v in field_allowed_values.items()} if field_allowed_values else None
            ),
        )
    return built


def _get_effective_catalog() -> Dict[str, "DomainEntry"]:
    """실제로 사용할 카탈로그를 반환한다 — DB 활성 버전 우선, 없거나 불가 시 하드코딩 폴백.

    `catalog_config_loader`가 반환하는 raw config dict는 활성 버전이 바뀌지 않는 한 동일 객체를
    재사용하므로(로더 자체 캐시), `id()` 비교만으로 재빌드 필요 여부를 판단할 수 있다 — DB 조회
    빈도뿐 아니라 `DomainEntry` 재구성 빈도도 함께 캐싱한다(NFR6).
    """
    global _effective_catalog_cache, _effective_catalog_cache_source_id

    raw_config = catalog_config_loader.get_cached_config(catalog_config_loader.CATALOG_KIND)
    if raw_config is None:
        return _CATALOG  # DB에 활성 버전 없음(마이그레이션 전 등) → 하드코딩 폴백

    if _effective_catalog_cache is not None and _effective_catalog_cache_source_id == id(raw_config):
        return _effective_catalog_cache

    built = _build_dynamic_catalog(raw_config)
    if not built:
        logger.warning("settings_catalog_dynamic_build_empty_fallback_to_static")
        return _CATALOG

    _effective_catalog_cache = built
    _effective_catalog_cache_source_id = id(raw_config)
    return built


_register(
    "persona", _get_persona,
    schema={"required": ["owner", "name", "description"], "optional": ["scope_keywords", "enabled"]},
    destructive=False,  # 조직 소개 정보 열람은 위험 없음
    update_fn=_update_persona,
    writable_fields={"name", "description", "scope_keywords", "enabled"},
)
_register(
    "ai-escalation", _get_ai_escalation,
    schema={"required": ["escalation_mode"], "optional": ["transfer_extension", "persona_exists"]},
    destructive=True,  # 고객 응대 개입 방식(HITL/호전환/미사용)을 바꾸는 민감 설정 — 안전측 True
    update_fn=_update_ai_escalation,
    writable_fields={"escalation_mode", "transfer_extension"},
    # escalation_mode는 hitl_alert.py가 정확한 문자열 일치로 분기하는 enum이다(config/models.py
    # OrganizationPersona.escalation_mode 설명 참고). 다른 값(예: "disabled")은 어떤 분기와도
    # 매치되지 않아 hitl 기본 동작으로 조용히 폴백되는 위험한 실패 모드라 반드시 검증해야 한다.
    field_allowed_values={"escalation_mode": {"hitl", "transfer", "none"}},
)
_register(
    "call-control", _get_call_control,
    schema={"required": [], "optional": ["rules", "schedules", "announcements"]},
    destructive=True,  # 착신 규칙 변경은 전화 라우팅에 직접 영향 — 안전측 True
    # update_fn 없음: rules/schedules/announcements는 목록형 데이터(개별 ID 필요)라
    # "단일 필드=값" 갱신 모델에 맞지 않음(Story 1.8 Task 0 발견 사실, exclusions.yaml 참고)
)
_register(
    "chat-relay", _get_chat_relay,
    schema={
        "required": [],
        "optional": ["sip_username", "message_ai_policy", "message_ai_reply_enabled", "message_ai_reply_prefix"],
    },
    destructive=True,  # 채팅 자동응답 on/off는 고객 응대에 직접 영향 — 안전측 True
    update_fn=_update_chat_relay,
    writable_fields={"message_ai_policy", "message_ai_reply_enabled", "message_ai_reply_prefix"},
)
_register(
    "contacts", _get_contacts,
    schema={"required": [], "optional": ["contacts", "folders"]},
    destructive=False,  # 연락처 열람 자체는 위험 없음(생성·수정·삭제는 본 Story 범위 아님)
    # update_fn 없음: 연락처는 목록형 데이터(개별 연락처 ID 필요) — 단일 필드 갱신 모델 부적합
)
_register(
    "general", _get_general,
    schema={"required": ["owner"], "optional": ["name", "name_en", "type", "description", "is_active"]},
    destructive=True,  # 테넌트 프로필 변경 파급 범위 불확실 — 안전측 True
    # update_fn 없음: TENANTS_DATA는 정적 하드코딩 리스트로 실제 변경 함수가 존재하지 않음
)
_register(
    "integrations", _get_integrations,
    schema={"required": ["connected"], "optional": ["calendar_id", "connected_at", "updated_at", "token_expiry"]},
    destructive=True,  # 외부 서비스 연동 해제/변경은 예약 파이프라인에 영향 — 안전측 True
    # update_fn 없음: 연동은 OAuth 리디렉션이 필요한 액션이지 값 설정이 아님
)


def list_domains() -> List[str]:
    """등록된 설정 도메인명 목록(등록 순서 유지)."""
    return list(_get_effective_catalog().keys())


def get_domain_schema(domain: str) -> Dict[str, Any]:
    """도메인의 필수/옵션 필드 스키마 + destructive 여부. 미등록 도메인이면 빈 dict."""
    entry = _get_effective_catalog().get(domain)
    if entry is None:
        logger.warning("settings_catalog_schema_unregistered_domain", domain=domain)
        return {}
    return {
        "domain": entry.name,
        "destructive": entry.destructive,
        "required": list(entry.schema.get("required", [])),
        "optional": list(entry.schema.get("optional", [])),
    }


async def get_domain_value(domain: str, owner: str) -> Dict[str, Any]:
    """등록된 `get_fn(owner)`를 호출해 현재 설정값을 반환한다.

    - 미등록 도메인: `{"error": "unregistered_domain: <domain>"}`
    - `get_fn` 예외: `{"error": str(e)}`로 흡수(부작용 없음, 예외를 그대로 전파하지 않음)
    """
    entry = _get_effective_catalog().get(domain)
    if entry is None:
        logger.warning("settings_catalog_value_unregistered_domain", domain=domain, owner=owner)
        return {"error": f"unregistered_domain: {domain}"}
    try:
        result = entry.get_fn(owner)
        if inspect.isawaitable(result):
            result = await result
        return result
    except Exception as e:
        logger.warning(
            "settings_catalog_get_fn_error", domain=domain, owner=owner, error=str(e),
        )
        return {"error": str(e)}


def domain_writable_fields(domain: str) -> Optional[frozenset]:
    """도메인의 쓰기 허용 필드 집합. 도메인이 없거나 update_fn 미등록이면 None."""
    entry = _get_effective_catalog().get(domain)
    if entry is None or entry.update_fn is None:
        return None
    return entry.writable_fields


def get_field_allowed_values(domain: str, field: str) -> Optional[frozenset]:
    """필드의 허용값 집합(enum형 필드만 등록됨). 미등록 필드는 None(검증 대상 아님)."""
    entry = _get_effective_catalog().get(domain)
    if entry is None or entry.field_allowed_values is None:
        return None
    return entry.field_allowed_values.get(field)


async def call_update_fn(domain: str, owner: str, field: str, value: Any) -> Dict[str, Any]:
    """등록된 `update_fn(owner, field, value)`를 호출한다(Story 1.8).

    순수 디스패처 — 제외 목록·확인 발화·감사 로깅은 `self_service/auto_config.py`가 담당한다
    (Story 1.5부터 이어온 원칙: 카탈로그는 순수 조회/디스패치, 판단·부작용은 별도 모듈).

    - 미등록 도메인: `{"ok": False, "error": "unregistered_domain: <domain>"}`
    - update_fn 미등록 도메인(쓰기 미지원): `{"ok": False, "error": "domain_not_writable: <domain>"}`
    - `field`가 `writable_fields`에 없음: `{"ok": False, "error": "field_not_writable: <field>"}`
    - `value`가 `field_allowed_values`에 등록된 허용값 집합에 없음(enum형 필드만 해당):
      `{"ok": False, "error": "invalid_value: <field>는 <허용값 목록> 중 하나여야 합니다"}`
    - `update_fn` 예외: `{"ok": False, "error": str(e)}`
    """
    entry = _get_effective_catalog().get(domain)
    if entry is None:
        logger.warning("settings_catalog_update_unregistered_domain", domain=domain, owner=owner)
        return {"ok": False, "error": f"unregistered_domain: {domain}"}
    if entry.update_fn is None:
        return {"ok": False, "error": f"domain_not_writable: {domain}"}
    if entry.writable_fields is not None and field not in entry.writable_fields:
        return {"ok": False, "error": f"field_not_writable: {field}"}
    allowed_values = get_field_allowed_values(domain, field)
    if allowed_values is not None and value not in allowed_values:
        logger.warning(
            "settings_catalog_invalid_value_rejected",
            domain=domain, owner=owner, field=field, value=value,
            allowed_values=sorted(allowed_values),
        )
        return {
            "ok": False,
            "error": f"invalid_value: {field}는 {sorted(allowed_values)} 중 하나여야 합니다(받은 값: {value!r})",
        }
    try:
        return await entry.update_fn(owner, field, value)
    except Exception as e:
        logger.warning(
            "settings_catalog_update_fn_error", domain=domain, owner=owner, field=field, error=str(e),
        )
        return {"ok": False, "error": str(e)}
