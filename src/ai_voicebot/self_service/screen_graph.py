"""Screen Graph — 설정 카탈로그 도메인 ↔ 프론트엔드 화면 ↔ UI 요소 경량 지식 그래프 (Story 1.11).

설계: docs/design/SELF_SERVICE_SCREEN_GUIDED_GRAPHRAG_RESEARCH.md
      docs/architecture/self-service-ai-assistant-architecture.md §Component Architecture
      docs/stories/1.11.screen-graph-guided-assistance.story.md

⚠️ Full GraphRAG(LLM 엔터티 추출 + Leiden 클러스터링 + 커뮤니티 요약)는 채택하지 않는다.
   코퍼스 규모(매뉴얼 52건, 카탈로그 도메인 7개, 프론트엔드 화면 8개)가 작고 관계가 이미
   알려져 있어(매뉴얼 저작 시점부터 도메인별로 섹션이 분류됨) LLM 자동 추출은 불필요한
   환각 리스크만 추가한다. 대신 GraphRAG의 "Local Search"(엔터티에서 이웃으로 팬아웃) 아이디어만
   차용해 `settings_catalog.py`와 동일한 정적 레지스트리 패턴으로 구현한다.

노드/엣지 모델:
  - manual_qa --relates_to--> catalog_domain   (기존, manual_indexer.py의 related_domain)
  - catalog_domain --rendered_by--> frontend_screen   (본 모듈, ScreenEntry)
  - frontend_screen --has_field--> ui_field   (본 모듈, ScreenEntry.fields)

프론트엔드 전용 화면이 없는 도메인(예: persona — name/description/scope_keywords는 지식베이스
관리 영역으로 이전되어 전용 설정 폼이 없음)은 등록하지 않는다 — 존재하지 않는 화면을 안내하는
환각을 원천 차단한다(매뉴얼 작성 원칙 "존재하지 않는 기능은 포함하지 않는다"와 동일 정신).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

import structlog

from src.ai_voicebot.self_service import catalog_config_loader

logger = structlog.get_logger(__name__)


@dataclass
class UiFieldSpec:
    """화면 내 UI 요소 1개."""

    field: str
    element_type: str  # "radio" | "toggle" | "text" | "tab" 등
    label: str
    options: Optional[List[str]] = None  # radio/select인 경우 선택지 표시용 라벨


@dataclass
class ScreenEntry:
    """도메인 하나에 대응하는 프론트엔드 화면 정보.

    route: 프론트엔드 라우트(프론트엔드 화면의 "화면 안내" 탭에서 클릭 이동용으로만 사용,
        사용자에게 음성/문자로 직접 읽어주지 않음).
    nav_hint: 전화·문자 대화에서 AI가 사용자에게 그대로 읽어주는 **메인화면 기준 클릭 경로**
        (예: "상단 메뉴의 '설정' 버튼 → '조직·채팅' 항목의 'AI 에스컬레이션'").
        사용자는 API 경로나 URL을 알 수도 없고 알 필요도 없으므로(전화로 대화 중이다),
        대화체 안내에는 반드시 이 필드를 사용하고 `route`는 노출하지 않는다
        (`frontend/components/AppHeader.tsx::SETTINGS_NAV`/`MAIN_NAV` 실제 메뉴 구조를 조사해 작성).
    """

    domain: str
    route: str
    title: str
    description: str
    nav_hint: str
    fields: List[UiFieldSpec] = field(default_factory=list)


_SCREEN_REGISTRY: Dict[str, ScreenEntry] = {}


def _register_screen(
    domain: str,
    route: str,
    title: str,
    description: str,
    nav_hint: str,
    fields: Optional[List[UiFieldSpec]] = None,
) -> None:
    _SCREEN_REGISTRY[domain] = ScreenEntry(
        domain=domain, route=route, title=title, description=description,
        nav_hint=nav_hint, fields=list(fields or []),
    )


# ── ai-escalation: 라디오 버튼 3종 (실제 frontend/app/settings/ai-escalation/page.tsx 조사 기준) ──
_register_screen(
    domain="ai-escalation",
    route="/settings/ai-escalation",
    title="AI 에스컬레이션 설정",
    description="AI가 모르는 질문을 받았을 때 처리 방식을 고르는 화면입니다.",
    nav_hint="화면 상단 메뉴의 '설정' 버튼을 누른 뒤 '조직·채팅' 항목의 'AI 에스컬레이션'을 선택하세요",
    fields=[
        UiFieldSpec(
            field="escalation_mode", element_type="radio",
            label="AI가 모를 때 처리 방식",
            options=["운영자 알림(hitl)", "상담원 직접 연결(transfer)", "에스컬레이션 안 함(none)"],
        ),
    ],
)

# ── chat-relay: 토글 + 텍스트 (실제 frontend/app/settings/chat-relay/page.tsx 조사 기준) ──
_register_screen(
    domain="chat-relay",
    route="/settings/chat-relay",
    title="채팅(SIP 문자) 자동응답 설정",
    description="문자로 온 문의에 AI가 자동으로 답장할지 켜고 끄는 화면입니다.",
    nav_hint="화면 상단 메뉴의 '설정' 버튼을 누른 뒤 '조직·채팅' 항목의 '채팅·SIP MESSAGE'를 선택하세요",
    fields=[
        UiFieldSpec(
            field="message_ai_reply_enabled", element_type="toggle",
            label="SIP MESSAGE 수신 시 AI 자동응답 사용",
        ),
        UiFieldSpec(
            field="message_ai_reply_prefix", element_type="text",
            label="자동응답 표시 접두(예: [자동응답])",
        ),
    ],
)

# ── call-control: 내부 탭 5개 (실제 frontend/app/settings/call-control/page.tsx 조사 기준 — ──
#    TabId = 'rules' | 'schedules' | 'forward-targets' | 'ringback' | 'caller-filters')
_register_screen(
    domain="call-control",
    route="/settings/call-control",
    title="착신 제어 설정",
    description="전화가 왔을 때 누가·어떻게 받을지 정하는 화면입니다. 내부에 5개 탭이 있습니다.",
    nav_hint="화면 상단 메뉴의 '설정' 버튼을 누른 뒤 '통화·착신' 항목의 '착신 제어'를 선택하세요",
    fields=[
        UiFieldSpec(field="rules", element_type="tab", label="착신 규칙 탭(?tab=rules)"),
        UiFieldSpec(field="schedules", element_type="tab", label="시간 조건 탭(?tab=schedules)"),
        UiFieldSpec(field="forward-targets", element_type="tab", label="착신전환 대상 탭(?tab=forward-targets)"),
        UiFieldSpec(field="ringback", element_type="tab", label="통화 연결음 탭(?tab=ringback)"),
        UiFieldSpec(field="caller-filters", element_type="tab", label="발신자 필터 탭(?tab=caller-filters)"),
    ],
)

# ── general/integrations: 동일 화면(/settings/general)으로 수렴 (integrations는 general로 ──
#    리다이렉트되며, Google Calendar OAuth 섹션이 general 페이지 내부에 있음 — 실제 코드 조사 기준)
_general_fields = [
    UiFieldSpec(field="connected", element_type="button", label="Google 계정 연동 / 연동 해제 버튼"),
]
_GENERAL_NAV_HINT = "화면 상단 메뉴의 '설정' 버튼을 누른 뒤 '일반 설정' 항목의 '연동·외부 서비스'를 선택하세요"
_register_screen(
    domain="general",
    route="/settings/general",
    title="일반 설정",
    description="테넌트 프로필 확인 및 Google Calendar 연동을 관리하는 화면입니다.",
    nav_hint=_GENERAL_NAV_HINT,
    fields=_general_fields,
)
_register_screen(
    domain="integrations",
    route="/settings/general",
    title="일반 설정(Google Calendar 연동)",
    description="/settings/integrations는 /settings/general로 자동 이동되며, 그 안의 Google 계정 연동 섹션에서 관리합니다.",
    nav_hint=_GENERAL_NAV_HINT,
    fields=_general_fields,
)

# ── contacts: 메인 내비 /contacts로 리다이렉트 (실제 frontend/app/settings/contacts/page.tsx 확인) ──
_register_screen(
    domain="contacts",
    route="/contacts",
    title="연락처 관리",
    description="고객 연락처를 등록·조회하는 화면입니다(설정 메뉴가 아닌 메인 내비게이션에 있습니다).",
    nav_hint="화면 상단 메인 메뉴에서 '설정'이 아닌 '연락처' 탭을 바로 클릭하세요",
    fields=[],
)

# persona: 전용 설정 폼이 없음(레거시 리다이렉트만 존재, 실제 name/description/scope_keywords는
# 지식베이스 관리 화면으로 이전됨) — 의도적으로 등록하지 않는다.


# ── 동적 Screen Graph 로딩 (Epic 2 Story 2.3) ───────────────────────────────
# `_SCREEN_REGISTRY`(위 `_register_screen()` 호출로 채워짐)는 DB 미가용 시 사용하는
# 하드코딩 폴백으로만 유지된다. Screen Graph는 실행 가능한 콜러블이 전혀 없는 순수 데이터
# (route/title/description/nav_hint/fields)이므로 settings_catalog.py와 달리 함수 화이트리스트가
# 불필요하다 — DB 값을 그대로 `ScreenEntry`/`UiFieldSpec`로 역직렬화하기만 하면 안전하다.
_effective_screens_cache: Dict[str, Dict[str, ScreenEntry]] = {}
_effective_screens_cache_source_id: Dict[str, int] = {}


def _build_dynamic_screens(raw_config: Dict[str, Any]) -> Dict[str, ScreenEntry]:
    """DB에서 읽은 `config_json`(도메인별 화면 메타데이터 dict)을 `ScreenEntry` 딕셔너리로 변환한다."""
    screens_cfg = raw_config.get("screens")
    if not isinstance(screens_cfg, dict):
        logger.warning("screen_graph_dynamic_config_missing_screens")
        return {}

    built: Dict[str, ScreenEntry] = {}
    for domain_name, cfg in screens_cfg.items():
        if not isinstance(cfg, dict):
            logger.warning("screen_graph_dynamic_invalid_domain_entry", domain=domain_name)
            continue
        fields_cfg = cfg.get("fields") or []
        fields = [
            UiFieldSpec(
                field=f.get("field", ""),
                element_type=f.get("element_type", ""),
                label=f.get("label", ""),
                options=list(f.get("options") or []) or None,
            )
            for f in fields_cfg if isinstance(f, dict)
        ]
        built[domain_name] = ScreenEntry(
            domain=domain_name,
            route=cfg.get("route", ""),
            title=cfg.get("title", ""),
            description=cfg.get("description", ""),
            nav_hint=cfg.get("nav_hint", ""),
            fields=fields,
        )
    return built


def _get_effective_screens(owner: str = "") -> Dict[str, ScreenEntry]:
    """실제로 사용할 Screen Graph 레지스트리를 반환한다 — DB 활성 버전 우선, 없거나 불가 시 폴백.

    owner를 지정하면 해당 테넌트 전용 커스텀 버전을 우선 사용하고, 없으면 전역 기본값(owner='')로
    폴백한다(NFR11, 2026-08-07). `settings_catalog.py::_get_effective_catalog()`와 동일한
    `id()` 기반 캐시 재사용 원칙(NFR6), owner별로 캐시를 분리한다.
    """
    normalized_owner = (owner or "").strip()

    raw_config = catalog_config_loader.get_cached_config(catalog_config_loader.SCREEN_GRAPH_KIND, normalized_owner)
    if raw_config is None:
        return _SCREEN_REGISTRY  # DB에 활성 버전 없음 → 하드코딩 폴백

    cached_id = _effective_screens_cache_source_id.get(normalized_owner)
    if normalized_owner in _effective_screens_cache and cached_id == id(raw_config):
        return _effective_screens_cache[normalized_owner]

    built = _build_dynamic_screens(raw_config)
    if not built:
        logger.warning("screen_graph_dynamic_build_empty_fallback_to_static")
        return _SCREEN_REGISTRY

    _effective_screens_cache[normalized_owner] = built
    _effective_screens_cache_source_id[normalized_owner] = id(raw_config)
    return built


def get_screen_for_domain(domain: str, owner: str = "") -> Optional[ScreenEntry]:
    """도메인명으로 화면 정보를 조회한다. 미등록 도메인이면 None(화면 안내 생략 신호)."""
    return _get_effective_screens(owner).get(domain)


def list_all_screens(owner: str = "") -> List[ScreenEntry]:
    """등록된 화면 정보 전체 목록(프론트엔드 열람용, Story 1.12)."""
    return list(_get_effective_screens(owner).values())


def export_static_snapshot() -> Dict[str, Any]:
    """현재 하드코딩된 `_SCREEN_REGISTRY`를 Story 2.1 DB 스키마와 동일한 JSON 구조로 내보낸다.

    용도:
    - `scripts/self_service_catalog_migrate_seed.py`의 최초 시드 데이터 소스.
    - DB에 활성 버전이 없을 때 export API(Story 2.4)의 폴백 응답.

    Screen Graph는 실행 가능한 콜러블이 없는 순수 데이터이므로 화이트리스트 역조회가 불필요하다.
    """
    screens: Dict[str, Any] = {}
    for domain_name, entry in _SCREEN_REGISTRY.items():
        screens[domain_name] = {
            "route": entry.route,
            "title": entry.title,
            "description": entry.description,
            "nav_hint": entry.nav_hint,
            "fields": [
                {
                    "field": f.field,
                    "element_type": f.element_type,
                    "label": f.label,
                    "options": list(f.options or []),
                }
                for f in entry.fields
            ],
        }
    return {"screens": screens}


def describe_screen_for_conversation(domain: str, owner: str = "") -> str:
    """대화체 화면 안내 문구를 생성한다(best-effort, 예외 없이 항상 문자열 반환).

    화면 정보가 없으면 빈 문자열을 반환한다 — 호출부가 이를 "화면 안내 생략" 신호로 사용한다.
    """
    try:
        entry = get_screen_for_domain(domain, owner)
        if entry is None:
            return ""

        lines = [f"화면 위치: {entry.nav_hint} ({entry.title})", entry.description]
        for f in entry.fields:
            if f.element_type == "radio" and f.options:
                lines.append(f"- {f.label}: 라디오 버튼 중 선택 — {', '.join(f.options)}")
            elif f.element_type == "toggle":
                lines.append(f"- {f.label}: 켜기/끄기 토글")
            elif f.element_type == "tab":
                lines.append(f"- {f.label}")
            elif f.element_type == "text":
                lines.append(f"- {f.label}: 텍스트 입력")
            elif f.element_type == "button":
                lines.append(f"- {f.label}")
            else:
                lines.append(f"- {f.label}")
        return "\n".join(lines)
    except Exception as e:
        logger.warning("screen_graph_describe_failed", domain=domain, error=str(e))
        return ""
