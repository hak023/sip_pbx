"""
AI Voicebot Unit Tests - 셀프서비스 설정 카탈로그 (Story 1.4)

Story 1.4: 설정 카탈로그 구축(읽기 전용 등록)
docs/stories/1.4.settings-catalog-readonly.story.md §Testing 참고
"""

import pytest

from src.ai_voicebot.self_service import settings_catalog as catalog


class _FakePersona:
    def __init__(
        self,
        owner="1003",
        name="이탈리안 비스트로",
        description="정통 이탈리아 요리 레스토랑",
        escalation_mode="hitl",
        transfer_extension=None,
    ):
        self.owner = owner
        self.name = name
        self.description = description
        self.scope_keywords = ["파스타", "예약"]
        self.enabled = True
        self.escalation_mode = escalation_mode
        self.transfer_extension = transfer_extension


class _FakePersonaService:
    def __init__(self, persona=None):
        self._persona = persona

    async def get_persona(self, owner):
        return self._persona


class TestListDomains:
    def test_returns_exactly_seven_domains(self):
        domains = catalog.list_domains()
        assert len(domains) == 7
        assert set(domains) == {
            "persona", "ai-escalation", "call-control", "chat-relay",
            "contacts", "general", "integrations",
        }


class TestGetDomainSchema:
    def test_known_domain_returns_schema_with_destructive_flag(self):
        schema = catalog.get_domain_schema("persona")
        assert schema["domain"] == "persona"
        assert schema["destructive"] is False
        assert "name" in schema["required"] or "name" in schema["optional"]

    def test_destructive_defaults_true_for_sensitive_domains(self):
        assert catalog.get_domain_schema("ai-escalation")["destructive"] is True
        assert catalog.get_domain_schema("call-control")["destructive"] is True

    def test_unregistered_domain_returns_empty_dict(self):
        assert catalog.get_domain_schema("does-not-exist") == {}


class TestGetDomainValueUnregistered:
    @pytest.mark.asyncio
    async def test_unregistered_domain_returns_error(self):
        result = await catalog.get_domain_value("does-not-exist", "1003")
        assert "error" in result


class TestGetDomainValueErrorHandling:
    @pytest.mark.asyncio
    async def test_get_fn_exception_is_absorbed(self, monkeypatch):
        async def _boom(owner):
            raise RuntimeError("db down")

        monkeypatch.setitem(
            catalog._CATALOG, "persona",
            catalog.DomainEntry(name="persona", get_fn=_boom, schema={}, destructive=False),
        )
        result = await catalog.get_domain_value("persona", "1003")
        assert result == {"error": "db down"}


class TestDomainCoverageRoundTrip:
    """7개 도메인 각각 실제 조회 왕복 테스트 (IV2) — 하위 I/O는 모킹하고 카탈로그 배선을 검증"""

    @pytest.mark.asyncio
    async def test_persona_domain(self, monkeypatch):
        fake_service = _FakePersonaService(_FakePersona())
        monkeypatch.setattr(
            "src.ai_voicebot.knowledge.persona_service.get_persona_service",
            lambda: fake_service,
        )
        result = await catalog.get_domain_value("persona", "1003")
        assert result["name"] == "이탈리안 비스트로"

    @pytest.mark.asyncio
    async def test_ai_escalation_domain(self, monkeypatch):
        fake_service = _FakePersonaService(_FakePersona(escalation_mode="transfer"))
        monkeypatch.setattr(
            "src.ai_voicebot.knowledge.persona_service.get_persona_service",
            lambda: fake_service,
        )
        result = await catalog.get_domain_value("ai-escalation", "1003")
        assert result["escalation_mode"] == "transfer"

    @pytest.mark.asyncio
    async def test_call_control_domain(self, monkeypatch):
        monkeypatch.setattr("src.call_control.db.list_rules", lambda owner: [{"id": "r1"}])
        monkeypatch.setattr("src.call_control.db.list_schedules", lambda owner: [{"id": "s1"}])
        monkeypatch.setattr("src.call_control.db.list_announcements", lambda owner: [{"id": "a1"}])
        result = await catalog.get_domain_value("call-control", "1003")
        assert result["rules"] == [{"id": "r1"}]

    @pytest.mark.asyncio
    async def test_chat_relay_domain(self, monkeypatch):
        monkeypatch.setattr(
            "src.services.chat_relay_service.get_chat_relay_settings",
            lambda owner: {"owner": owner, "message_ai_reply_enabled": 1},
        )
        result = await catalog.get_domain_value("chat-relay", "1003")
        assert result["message_ai_reply_enabled"] == 1

    @pytest.mark.asyncio
    async def test_contacts_domain(self, monkeypatch):
        monkeypatch.setattr(
            "src.common.caller_contact_db.list_caller_contacts",
            lambda owner, q, limit, offset: ([{"display_name": "홍길동"}], 1),
        )
        monkeypatch.setattr(
            "src.common.contact_folder_db.list_contact_folders",
            lambda owner: [{"id": "f1", "name": "단골"}],
        )
        result = await catalog.get_domain_value("contacts", "1003")
        assert result["contacts_total"] == 1

    @pytest.mark.asyncio
    async def test_general_domain_uses_real_tenant_seed_data(self):
        # TENANTS_DATA는 정적 하드코딩 데이터라 I/O 없이 실제 값으로 왕복 검증 가능
        result = await catalog.get_domain_value("general", "1003")
        assert result["owner"] == "1003"
        assert "name" in result

    @pytest.mark.asyncio
    async def test_general_domain_unknown_owner_returns_error(self):
        result = await catalog.get_domain_value("general", "no-such-owner")
        assert result.get("error") == "tenant_not_found"

    @pytest.mark.asyncio
    async def test_integrations_domain(self, monkeypatch):
        monkeypatch.setattr(
            "src.services.gcal_service.get_oauth_status",
            lambda owner: {"connected": True, "owner": owner, "calendar_id": "primary"},
        )
        result = await catalog.get_domain_value("integrations", "1003")
        assert result["connected"] is True


class TestFunctionWhitelistRegistry:
    """Epic 2 Story 2.1 — DB 동적 구성이 참조할 수 있는 함수 이름 화이트리스트 검증.

    핵심 불변조건: `_CATALOG`에 등록된 모든 get_fn/update_fn은 반드시 화이트리스트
    (`_GET_FN_REGISTRY`/`_UPDATE_FN_REGISTRY`)에도 등록되어 있어야 한다 — 그렇지 않으면
    향후 이 도메인을 DB 동적 구성으로 마이그레이션할 때(Story 2.2) 함수를 찾지 못해 실패한다.
    """

    def test_every_catalog_get_fn_is_whitelisted(self):
        whitelisted_fns = set(catalog._GET_FN_REGISTRY.values())  # noqa: SLF001
        for domain in catalog.list_domains():
            entry = catalog._CATALOG[domain]  # noqa: SLF001
            assert entry.get_fn in whitelisted_fns, f"{domain}.get_fn이 화이트리스트에 없음"

    def test_every_catalog_update_fn_is_whitelisted(self):
        whitelisted_fns = set(catalog._UPDATE_FN_REGISTRY.values())  # noqa: SLF001
        for domain in catalog.list_domains():
            entry = catalog._CATALOG[domain]  # noqa: SLF001
            if entry.update_fn is not None:
                assert entry.update_fn in whitelisted_fns, f"{domain}.update_fn이 화이트리스트에 없음"

    def test_get_fn_whitelist_names_returns_expected_names(self):
        names = catalog.get_fn_whitelist_names()
        assert "get_persona" in names
        assert "get_chat_relay" in names
        assert len(names) == 7  # 7개 도메인 전체 조회 함수

    def test_update_fn_whitelist_names_returns_only_writable_domains(self):
        names = catalog.update_fn_whitelist_names()
        assert set(names) == {"update_persona", "update_ai_escalation", "update_chat_relay"}

    def test_whitelist_does_not_expose_arbitrary_names(self):
        """화이트리스트에 없는 임의 이름은 당연히 포함되지 않는다(회귀 방지용 명시적 확인)."""
        assert "eval" not in catalog.get_fn_whitelist_names()
        assert "exec" not in catalog.update_fn_whitelist_names()
