"""
AI Voicebot Unit Tests - 셀프서비스 실행 취소(Undo) Tool (Story 1.16, IntelliDecision 유형 E)

docs/stories/1.16.intellidecision-types-d-i.story.md 참고.
"""

import json

import pytest

from src.ai_voicebot.self_service.tools import (
    SELF_SERVICE_TOOLS,
    _get_last_self_service_change,
    _undo_last_self_service_change,
    get_last_self_service_change_tool,
    undo_last_self_service_change_tool,
)


class TestGetLastSelfServiceChangeTool:
    @pytest.mark.asyncio
    async def test_returns_history_false_when_no_changes(self, monkeypatch):
        monkeypatch.setattr(
            "src.common.self_service_config_change_db.list_config_changes",
            lambda owner, limit=100: [],
        )
        result = json.loads(await _get_last_self_service_change("1003"))
        assert result == {"has_history": False}

    @pytest.mark.asyncio
    async def test_returns_last_change_details(self, monkeypatch):
        monkeypatch.setattr(
            "src.common.self_service_config_change_db.list_config_changes",
            lambda owner, limit=100: [{
                "domain": "chat-relay",
                "field": "message_ai_reply_enabled",
                "old_value": "False",
                "new_value": "True",
                "changed_at": "2026-07-23T10:00:00",
            }],
        )
        result = json.loads(await _get_last_self_service_change("1003"))
        assert result["has_history"] is True
        assert result["domain"] == "chat-relay"
        assert result["field"] == "message_ai_reply_enabled"
        assert result["old_value"] == "False"

    @pytest.mark.asyncio
    async def test_exception_is_absorbed(self, monkeypatch):
        def boom(owner, limit=100):
            raise RuntimeError("db down")

        monkeypatch.setattr(
            "src.common.self_service_config_change_db.list_config_changes", boom,
        )
        result = json.loads(await _get_last_self_service_change("1003"))
        assert "error" in result


class TestUndoLastSelfServiceChangeTool:
    @pytest.mark.asyncio
    async def test_no_history_returns_error(self, monkeypatch):
        monkeypatch.setattr(
            "src.common.self_service_config_change_db.list_config_changes",
            lambda owner, limit=100: [],
        )
        result = json.loads(await _undo_last_self_service_change("1003", "call1"))
        assert result["ok"] is False
        assert "내역이 없습니다" in result["error"]

    @pytest.mark.asyncio
    async def test_reverts_boolean_field_to_old_value(self, monkeypatch):
        monkeypatch.setattr(
            "src.common.self_service_config_change_db.list_config_changes",
            lambda owner, limit=100: [{
                "domain": "chat-relay",
                "field": "message_ai_reply_enabled",
                "old_value": "False",
                "new_value": "True",
            }],
        )

        captured = {}

        async def fake_apply(domain, owner, field, value, call_id=""):
            captured["args"] = (domain, owner, field, value, call_id)
            return {"ok": True, "old_value": True, "new_value": value}

        monkeypatch.setattr(
            "src.ai_voicebot.self_service.tools.apply_self_service_setting", fake_apply,
        )
        result = json.loads(await _undo_last_self_service_change("1003", "call1"))
        assert result["ok"] is True
        assert result["domain"] == "chat-relay"
        assert result["field"] == "message_ai_reply_enabled"
        # old_value "False" 문자열이 boolean 필드로 coerce되어 실제 False 값으로 복원 호출됨
        assert captured["args"] == ("chat-relay", "1003", "message_ai_reply_enabled", False, "call1")

    @pytest.mark.asyncio
    async def test_apply_failure_passes_through(self, monkeypatch):
        monkeypatch.setattr(
            "src.common.self_service_config_change_db.list_config_changes",
            lambda owner, limit=100: [{
                "domain": "persona", "field": "description",
                "old_value": "친절한 매니저", "new_value": "새 설명",
            }],
        )

        async def fake_apply(domain, owner, field, value, call_id=""):
            return {"ok": False, "excluded": True, "error": "정책상 제한"}

        monkeypatch.setattr(
            "src.ai_voicebot.self_service.tools.apply_self_service_setting", fake_apply,
        )
        result = json.loads(await _undo_last_self_service_change("1003", "call1"))
        assert result["ok"] is False
        assert result["excluded"] is True

    @pytest.mark.asyncio
    async def test_exception_is_absorbed(self, monkeypatch):
        def boom(owner, limit=100):
            raise RuntimeError("db down")

        monkeypatch.setattr(
            "src.common.self_service_config_change_db.list_config_changes", boom,
        )
        result = json.loads(await _undo_last_self_service_change("1003", "call1"))
        assert result["ok"] is False
        assert "error" in result


class TestUndoToolsRegisteredInToolList:
    def test_both_tools_in_self_service_tools(self):
        assert get_last_self_service_change_tool in SELF_SERVICE_TOOLS
        assert undo_last_self_service_change_tool in SELF_SERVICE_TOOLS
        assert len(SELF_SERVICE_TOOLS) == 9
