"""
AI Voicebot Unit Tests - 통화 이력 자연어 질의 (Story 1.13)

Story 1.13: 셀프서비스 통화 이력 자연어 질의(키워드 검색/Top 발신자 집계/오늘자 미응답 조회)
docs/stories/1.13.call-history-nlq.story.md §Testing 참고
"""

import json

import pytest

from src.ai_voicebot.self_service import call_history_query as chq
from src.ai_voicebot.self_service.tools import (
    SELF_SERVICE_TOOLS,
    _get_missed_calls_today,
    _get_top_caller,
    _search_call_history,
)


class TestPeriodSinceUtc:
    def test_today_returns_midnight(self):
        result = chq._period_since_utc("today")
        assert result is not None
        assert result.hour == 0 and result.minute == 0

    def test_week_returns_monday_midnight(self):
        result = chq._period_since_utc("week")
        assert result is not None
        assert result.weekday() == 0

    def test_month_returns_first_day_midnight(self):
        result = chq._period_since_utc("month")
        assert result is not None
        assert result.day == 1

    def test_unsupported_period_returns_none(self):
        assert chq._period_since_utc("year") is None


class TestIsMissed:
    def test_no_recording_no_ai_is_missed(self):
        assert chq._is_missed({"has_recording": False, "is_ai_handled": False}) is True

    def test_has_recording_is_not_missed(self):
        assert chq._is_missed({"has_recording": True, "is_ai_handled": False}) is False

    def test_ai_handled_is_not_missed(self):
        assert chq._is_missed({"has_recording": False, "is_ai_handled": True}) is False

    def test_missing_fields_defaults_to_missed(self):
        assert chq._is_missed({}) is True


class TestSearchCallHistoryByKeyword:
    @pytest.mark.asyncio
    async def test_empty_keyword_returns_error(self):
        result = await chq.search_call_history_by_keyword("1003", "")
        assert "error" in result
        assert result["matches"] == []

    @pytest.mark.asyncio
    async def test_matches_call_summary_case_insensitive(self, monkeypatch):
        def fake_get_call_records_page(*, owner, since=None, direction=None, limit=100, offset=0):
            return {
                "items": [
                    {"call_id": "c1", "caller_id": "010-1111-2222", "start_time": "t1",
                     "call_summary": "예약 문의 관련 통화였습니다"},
                    {"call_id": "c2", "caller_id": "010-3333-4444", "start_time": "t2",
                     "call_summary": "영업시간 안내"},
                ],
                "total": 2,
            }

        monkeypatch.setattr(
            "src.common.call_record_db.get_call_records_page", fake_get_call_records_page,
        )
        result = await chq.search_call_history_by_keyword("1003", "예약")
        assert result["match_count"] == 1
        assert result["matches"][0]["call_id"] == "c1"

    @pytest.mark.asyncio
    async def test_no_match_returns_zero_count(self, monkeypatch):
        def fake_get_call_records_page(*, owner, since=None, direction=None, limit=100, offset=0):
            return {"items": [{"call_id": "c1", "call_summary": "영업시간 안내"}], "total": 1}

        monkeypatch.setattr(
            "src.common.call_record_db.get_call_records_page", fake_get_call_records_page,
        )
        result = await chq.search_call_history_by_keyword("1003", "존재하지않는키워드")
        assert result["match_count"] == 0

    @pytest.mark.asyncio
    async def test_db_unavailable_returns_error(self, monkeypatch):
        monkeypatch.setattr(
            "src.common.call_record_db.get_call_records_page", lambda **kw: None,
        )
        result = await chq.search_call_history_by_keyword("1003", "예약")
        assert "error" in result

    @pytest.mark.asyncio
    async def test_respects_limit(self, monkeypatch):
        def fake_get_call_records_page(*, owner, since=None, direction=None, limit=100, offset=0):
            return {
                "items": [
                    {"call_id": f"c{i}", "call_summary": "예약 문의"} for i in range(5)
                ],
                "total": 5,
            }

        monkeypatch.setattr(
            "src.common.call_record_db.get_call_records_page", fake_get_call_records_page,
        )
        result = await chq.search_call_history_by_keyword("1003", "예약", limit=2)
        assert result["match_count"] == 2


class TestGetTopCaller:
    @pytest.mark.asyncio
    async def test_unsupported_period_returns_fallback(self):
        result = await chq.get_top_caller("1003", "year")
        assert "error" in result

    @pytest.mark.asyncio
    async def test_aggregates_caller_counts(self, monkeypatch):
        def fake_get_call_records_page(*, owner, since=None, direction=None, limit=100, offset=0):
            return {
                "items": [
                    {"caller_id": "010-1111-2222"},
                    {"caller_id": "010-1111-2222"},
                    {"caller_id": "010-3333-4444"},
                ],
                "total": 3,
            }

        monkeypatch.setattr(
            "src.common.call_record_db.get_call_records_page", fake_get_call_records_page,
        )
        result = await chq.get_top_caller("1003", "month")
        assert result["top_callers"][0]["caller_id"] == "010-1111-2222"
        assert result["top_callers"][0]["call_count"] == 2

    @pytest.mark.asyncio
    async def test_no_calls_returns_empty_list(self, monkeypatch):
        monkeypatch.setattr(
            "src.common.call_record_db.get_call_records_page",
            lambda **kw: {"items": [], "total": 0},
        )
        result = await chq.get_top_caller("1003", "week")
        assert result["top_callers"] == []

    @pytest.mark.asyncio
    async def test_db_unavailable_returns_error(self, monkeypatch):
        monkeypatch.setattr(
            "src.common.call_record_db.get_call_records_page", lambda **kw: None,
        )
        result = await chq.get_top_caller("1003", "today")
        assert "error" in result


class TestGetMissedCallsToday:
    @pytest.mark.asyncio
    async def test_filters_only_missed_calls(self, monkeypatch):
        def fake_get_call_records_page(*, owner, since=None, direction=None, limit=100, offset=0):
            assert direction == "inbound"
            return {
                "items": [
                    {"call_id": "c1", "caller_id": "010-1111-2222", "start_time": "t1",
                     "has_recording": False, "is_ai_handled": False},
                    {"call_id": "c2", "caller_id": "010-3333-4444", "start_time": "t2",
                     "has_recording": True, "is_ai_handled": True},
                ],
                "total": 2,
            }

        monkeypatch.setattr(
            "src.common.call_record_db.get_call_records_page", fake_get_call_records_page,
        )
        result = await chq.get_missed_calls_today("1003")
        assert result["missed_count"] == 1
        assert result["missed_calls"][0]["call_id"] == "c1"

    @pytest.mark.asyncio
    async def test_db_unavailable_returns_error(self, monkeypatch):
        monkeypatch.setattr(
            "src.common.call_record_db.get_call_records_page", lambda **kw: None,
        )
        result = await chq.get_missed_calls_today("1003")
        assert "error" in result
        assert result["missed_calls"] == []


class TestToolsRegistration:
    def test_new_tools_present_in_self_service_tools_list(self):
        names = [getattr(t, "name", None) or getattr(t, "__name__", "") for t in SELF_SERVICE_TOOLS]
        assert "_search_call_history" in names or "search_call_history" in names
        assert "_get_top_caller" in names or "get_top_caller" in names
        assert "_get_missed_calls_today" in names or "get_missed_calls_today" in names

    @pytest.mark.asyncio
    async def test_search_call_history_tool_wrapper_returns_json(self, monkeypatch):
        monkeypatch.setattr(
            "src.common.call_record_db.get_call_records_page",
            lambda **kw: {"items": [], "total": 0},
        )
        result_str = await _search_call_history("1003", "예약")
        parsed = json.loads(result_str)
        assert parsed["match_count"] == 0

    @pytest.mark.asyncio
    async def test_get_top_caller_tool_wrapper_returns_json(self, monkeypatch):
        monkeypatch.setattr(
            "src.common.call_record_db.get_call_records_page",
            lambda **kw: {"items": [], "total": 0},
        )
        result_str = await _get_top_caller("1003", "week")
        parsed = json.loads(result_str)
        assert parsed["top_callers"] == []

    @pytest.mark.asyncio
    async def test_get_missed_calls_today_tool_wrapper_returns_json(self, monkeypatch):
        monkeypatch.setattr(
            "src.common.call_record_db.get_call_records_page",
            lambda **kw: {"items": [], "total": 0},
        )
        result_str = await _get_missed_calls_today("1003")
        parsed = json.loads(result_str)
        assert parsed["missed_count"] == 0
