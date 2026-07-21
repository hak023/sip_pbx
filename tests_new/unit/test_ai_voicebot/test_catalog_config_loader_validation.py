"""
AI Voicebot Unit Tests - catalog_config_loader.py validate_config()/diff_configs() (Epic 2 Story 2.5)

docs/stories/2.5.frontend-catalog-import.story.md §AC1/AC2/IV1 참고
"""

from src.ai_voicebot.self_service import catalog_config_loader as loader


class TestValidateCatalogConfig:
    def _valid_config(self):
        return {
            "domains": {
                "persona": {
                    "get_fn_ref": "get_persona",
                    "update_fn_ref": "update_persona",
                    "schema": {"required": [], "optional": []},
                    "destructive": False,
                    "writable_fields": ["name"],
                    "field_allowed_values": {},
                },
            },
        }

    def _whitelist(self):
        return {"get_fn_names": ["get_persona"], "update_fn_names": ["update_persona"]}

    def test_valid_config_returns_no_errors(self):
        errors = loader.validate_config(loader.CATALOG_KIND, self._valid_config(), **self._whitelist())
        assert errors == []

    def test_missing_domains_key_is_rejected(self):
        errors = loader.validate_config(loader.CATALOG_KIND, {}, **self._whitelist())
        assert len(errors) == 1
        assert "domains" in errors[0]

    def test_domains_not_a_dict_is_rejected(self):
        errors = loader.validate_config(loader.CATALOG_KIND, {"domains": ["not", "a", "dict"]}, **self._whitelist())
        assert len(errors) == 1

    def test_non_dict_domain_entry_is_rejected(self):
        errors = loader.validate_config(
            loader.CATALOG_KIND, {"domains": {"persona": "not-a-dict"}}, **self._whitelist(),
        )
        assert any("persona" in e for e in errors)

    def test_missing_get_fn_ref_is_rejected(self):
        config = self._valid_config()
        del config["domains"]["persona"]["get_fn_ref"]
        errors = loader.validate_config(loader.CATALOG_KIND, config, **self._whitelist())
        assert any("get_fn_ref" in e for e in errors)

    def test_unwhitelisted_get_fn_ref_is_rejected(self):
        config = self._valid_config()
        config["domains"]["persona"]["get_fn_ref"] = "os.system"
        errors = loader.validate_config(loader.CATALOG_KIND, config, **self._whitelist())
        assert any("os.system" in e for e in errors)

    def test_unwhitelisted_update_fn_ref_is_rejected(self):
        config = self._valid_config()
        config["domains"]["persona"]["update_fn_ref"] = "eval"
        errors = loader.validate_config(loader.CATALOG_KIND, config, **self._whitelist())
        assert any("eval" in e for e in errors)

    def test_update_fn_ref_none_is_allowed(self):
        config = self._valid_config()
        config["domains"]["persona"]["update_fn_ref"] = None
        errors = loader.validate_config(loader.CATALOG_KIND, config, **self._whitelist())
        assert errors == []


class TestValidateScreenGraphConfig:
    def _valid_config(self):
        return {
            "screens": {
                "chat-relay": {
                    "route": "/settings/chat-relay",
                    "title": "채팅 자동응답",
                    "description": "설명",
                    "nav_hint": "설정 > 조직·채팅",
                    "fields": [],
                },
            },
        }

    def test_valid_config_returns_no_errors(self):
        assert loader.validate_config(loader.SCREEN_GRAPH_KIND, self._valid_config()) == []

    def test_missing_screens_key_is_rejected(self):
        errors = loader.validate_config(loader.SCREEN_GRAPH_KIND, {})
        assert len(errors) == 1
        assert "screens" in errors[0]

    def test_missing_required_field_is_rejected(self):
        config = self._valid_config()
        del config["screens"]["chat-relay"]["nav_hint"]
        errors = loader.validate_config(loader.SCREEN_GRAPH_KIND, config)
        assert any("nav_hint" in e for e in errors)

    def test_fields_not_a_list_is_rejected(self):
        config = self._valid_config()
        config["screens"]["chat-relay"]["fields"] = "not-a-list"
        errors = loader.validate_config(loader.SCREEN_GRAPH_KIND, config)
        assert any("fields" in e for e in errors)

    def test_no_whitelist_check_needed_for_screen_graph(self):
        """Screen Graph는 실행 가능한 참조가 없으므로 함수명 화이트리스트 검사 자체가 없다."""
        config = self._valid_config()
        assert loader.validate_config(loader.SCREEN_GRAPH_KIND, config) == []


class TestValidateUnknownKind:
    def test_unknown_config_kind_is_rejected(self):
        errors = loader.validate_config("bogus_kind", {})
        assert len(errors) == 1


class TestDiffConfigs:
    def test_added_domain_detected(self):
        old = {"domains": {"persona": {"a": 1}}}
        new = {"domains": {"persona": {"a": 1}, "chat-relay": {"b": 2}}}
        diff = loader.diff_configs(loader.CATALOG_KIND, old, new)
        assert diff == {"added": ["chat-relay"], "removed": [], "changed": []}

    def test_removed_domain_detected(self):
        old = {"domains": {"persona": {"a": 1}, "chat-relay": {"b": 2}}}
        new = {"domains": {"persona": {"a": 1}}}
        diff = loader.diff_configs(loader.CATALOG_KIND, old, new)
        assert diff == {"added": [], "removed": ["chat-relay"], "changed": []}

    def test_changed_domain_value_detected(self):
        old = {"domains": {"persona": {"destructive": False}}}
        new = {"domains": {"persona": {"destructive": True}}}
        diff = loader.diff_configs(loader.CATALOG_KIND, old, new)
        assert diff == {"added": [], "removed": [], "changed": ["persona"]}

    def test_identical_configs_produce_empty_diff(self):
        cfg = {"domains": {"persona": {"a": 1}}}
        diff = loader.diff_configs(loader.CATALOG_KIND, cfg, cfg)
        assert diff == {"added": [], "removed": [], "changed": []}

    def test_no_old_config_treats_all_as_added(self):
        new = {"domains": {"persona": {"a": 1}}}
        diff = loader.diff_configs(loader.CATALOG_KIND, None, new)
        assert diff == {"added": ["persona"], "removed": [], "changed": []}

    def test_screen_graph_uses_screens_top_key(self):
        old = {"screens": {"chat-relay": {"nav_hint": "old"}}}
        new = {"screens": {"chat-relay": {"nav_hint": "new"}}}
        diff = loader.diff_configs(loader.SCREEN_GRAPH_KIND, old, new)
        assert diff == {"added": [], "removed": [], "changed": ["chat-relay"]}
