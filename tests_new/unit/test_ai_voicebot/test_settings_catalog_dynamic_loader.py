"""
AI Voicebot Unit Tests - settings_catalog.py 동적(DB) 카탈로그 로딩 (Epic 2 Story 2.2)

docs/stories/2.2.catalog-loader-dynamic.story.md §AC/Testing 참고

tests_new/unit/conftest.py의 오토유즈 픽스처가 기본적으로
`catalog_config_loader.get_cached_config()`를 None으로 고정해 하드코딩 폴백을 쓰도록
격리하므로, 이 파일의 테스트들은 그 위에서 `get_cached_config`를 원하는 값으로 다시
패치해 동적 로딩 자체를 검증한다.
"""

import pytest

from src.ai_voicebot.self_service import settings_catalog as catalog
from src.ai_voicebot.self_service import catalog_config_loader


@pytest.fixture(autouse=True)
def _reset_effective_catalog_cache():
    """모듈 전역 캐시(`_effective_catalog_cache*`)가 테스트 간 오염되지 않도록 초기화."""
    catalog._effective_catalog_cache = None
    catalog._effective_catalog_cache_source_id = None
    yield
    catalog._effective_catalog_cache = None
    catalog._effective_catalog_cache_source_id = None


class TestEffectiveCatalogFallback:
    def test_no_active_db_config_falls_back_to_static_catalog(self, monkeypatch):
        monkeypatch.setattr(catalog_config_loader, "get_cached_config", lambda kind: None)
        assert catalog.list_domains() == list(catalog._CATALOG.keys())

    def test_empty_domains_dict_falls_back_to_static_catalog(self, monkeypatch):
        monkeypatch.setattr(catalog_config_loader, "get_cached_config", lambda kind: {"domains": {}})
        assert catalog.list_domains() == list(catalog._CATALOG.keys())

    def test_malformed_config_missing_domains_key_falls_back(self, monkeypatch):
        monkeypatch.setattr(catalog_config_loader, "get_cached_config", lambda kind: {"oops": True})
        assert catalog.list_domains() == list(catalog._CATALOG.keys())


class TestEffectiveCatalogDynamicOverride:
    def test_dynamic_config_with_single_domain_replaces_static_list(self, monkeypatch):
        dynamic_config = {
            "domains": {
                "persona": {
                    "get_fn_ref": "get_persona",
                    "update_fn_ref": "update_persona",
                    "schema": {"required": ["owner"], "optional": []},
                    "destructive": False,
                    "writable_fields": ["name"],
                    "field_allowed_values": {},
                },
            },
        }
        monkeypatch.setattr(catalog_config_loader, "get_cached_config", lambda kind: dynamic_config)

        assert catalog.list_domains() == ["persona"]
        schema = catalog.get_domain_schema("persona")
        assert schema["destructive"] is False
        assert schema["required"] == ["owner"]

    @pytest.mark.asyncio
    async def test_dynamic_get_fn_resolves_to_actual_whitelisted_callable(self, monkeypatch):
        dynamic_config = {
            "domains": {
                "chat-relay": {
                    "get_fn_ref": "get_chat_relay",
                    "update_fn_ref": None,
                    "schema": {}, "destructive": True,
                },
            },
        }
        monkeypatch.setattr(catalog_config_loader, "get_cached_config", lambda kind: dynamic_config)
        monkeypatch.setattr(
            "src.services.chat_relay_service.get_chat_relay_settings",
            lambda owner: {"owner": owner, "message_ai_reply_enabled": 1},
        )

        result = await catalog.get_domain_value("chat-relay", "1003")
        assert result["message_ai_reply_enabled"] == 1

    def test_unwhitelisted_get_fn_ref_skips_domain_entirely(self, monkeypatch):
        dynamic_config = {
            "domains": {
                "persona": {"get_fn_ref": "get_persona", "schema": {}, "destructive": False},
                "evil": {"get_fn_ref": "os.system", "schema": {}, "destructive": False},
            },
        }
        monkeypatch.setattr(catalog_config_loader, "get_cached_config", lambda kind: dynamic_config)

        domains = catalog.list_domains()
        assert "persona" in domains
        assert "evil" not in domains  # 화이트리스트에 없는 참조는 도메인 자체가 제외됨

    def test_unwhitelisted_update_fn_ref_disables_write_but_keeps_read(self, monkeypatch):
        dynamic_config = {
            "domains": {
                "persona": {
                    "get_fn_ref": "get_persona",
                    "update_fn_ref": "does_not_exist_fn",
                    "schema": {}, "destructive": False, "writable_fields": ["name"],
                },
            },
        }
        monkeypatch.setattr(catalog_config_loader, "get_cached_config", lambda kind: dynamic_config)

        assert "persona" in catalog.list_domains()
        assert catalog.domain_writable_fields("persona") is None  # update_fn=None → 쓰기 불가 취급

    def test_effective_catalog_is_cached_by_raw_config_identity(self, monkeypatch):
        call_count = {"n": 0}
        dynamic_config = {"domains": {"persona": {"get_fn_ref": "get_persona", "schema": {}, "destructive": False}}}

        def fake_get_cached_config(kind):
            call_count["n"] += 1
            return dynamic_config  # 동일 객체를 매번 반환(로더 자체 캐시를 흉내)

        monkeypatch.setattr(catalog_config_loader, "get_cached_config", fake_get_cached_config)

        catalog.list_domains()
        catalog.list_domains()
        catalog.list_domains()

        assert call_count["n"] == 3  # 로더 호출 자체는 매번 일어나지만
        # DomainEntry 재구성(_build_dynamic_catalog)은 캐시되어 동일 dict 인스턴스를 재사용해야 함
        first = catalog._get_effective_catalog()
        second = catalog._get_effective_catalog()
        assert first is second
