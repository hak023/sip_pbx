"""
AI Voicebot Unit Tests - 셀프서비스 이용 통계 조회 (Story 1.7)

Story 1.7: 이용 통계 조회 Tool
docs/stories/1.7.usage-stats-tool.story.md §Testing 참고
"""

import json
from datetime import datetime, timedelta, timezone

import pytest

from src.ai_voicebot.self_service import stats
from src.ai_voicebot.self_service.tools import SELF_SERVICE_TOOLS, _get_self_service_stats


class TestPeriodSinceUtc:
    def test_week_returns_monday_midnight(self):
        result = stats._period_since_utc("week")
        assert result is not None
        assert result.weekday() == 0
        assert result.hour == 0 and result.minute == 0

    def test_month_returns_first_day_midnight(self):
        result = stats._period_since_utc("month")
        assert result is not None
        assert result.day == 1
        assert result.hour == 0 and result.minute == 0

    def test_unsupported_period_returns_none(self):
        assert stats._period_since_utc("year") is None


class TestGetSelfServiceStats:
    """get_self_service_stats()가 call_record_db만 사용하는지(IV1), 기간 필터링/폴백 검증"""

    @pytest.mark.asyncio
    async def test_unsupported_period_returns_fallback_message(self):
        result = await stats.get_self_service_stats("1003", "year")
        assert "error" in result
        assert "이번 주" in result["error"] or "이번 달" in result["error"]

    @pytest.mark.asyncio
    async def test_supported_period_returns_call_count_from_call_record_db(self, monkeypatch):
        captured_since = {}

        def fake_get_call_records_page(*, owner, since=None, direction=None, limit=100, offset=0):
            captured_since["owner"] = owner
            captured_since["since"] = since
            return {
                "items": [
                    {"call_id": "c1", "is_ai_handled": True, "recordings_dir": ""},
                    {"call_id": "c2", "is_ai_handled": False, "recordings_dir": ""},
                ],
                "total": 2,
            }

        monkeypatch.setattr(
            "src.common.call_record_db.get_call_records_page",
            fake_get_call_records_page,
        )
        result = await stats.get_self_service_stats("1003", "week")

        assert result["call_count"] == 2
        assert result["ai_handled_count"] == 1
        assert captured_since["owner"] == "1003"
        assert captured_since["since"] is not None

    @pytest.mark.asyncio
    async def test_call_record_db_unavailable_returns_error(self, monkeypatch):
        def fake_get_call_records_page(*, owner, since=None, direction=None, limit=100, offset=0):
            return None

        monkeypatch.setattr(
            "src.common.call_record_db.get_call_records_page",
            fake_get_call_records_page,
        )
        result = await stats.get_self_service_stats("1003", "month")
        assert "error" in result

    @pytest.mark.asyncio
    async def test_empty_items_returns_zero_counts(self, monkeypatch):
        def fake_get_call_records_page(*, owner, since=None, direction=None, limit=100, offset=0):
            return {"items": [], "total": 0}

        monkeypatch.setattr(
            "src.common.call_record_db.get_call_records_page",
            fake_get_call_records_page,
        )
        result = await stats.get_self_service_stats("1003", "week")
        assert result["call_count"] == 0
        assert result["ai_handled_count"] == 0
        assert result["avg_confidence"] == 0.0
        assert result["hitl_count"] == 0

    @pytest.mark.asyncio
    async def test_different_owners_are_isolated(self, monkeypatch):
        """owner 파라미터가 call_record_db.get_call_records_page에 그대로 전달되는지(테넌트 격리)"""
        received_owners = []

        def fake_get_call_records_page(*, owner, since=None, direction=None, limit=100, offset=0):
            received_owners.append(owner)
            return {"items": [], "total": 0}

        monkeypatch.setattr(
            "src.common.call_record_db.get_call_records_page",
            fake_get_call_records_page,
        )
        await stats.get_self_service_stats("owner-a", "week")
        await stats.get_self_service_stats("owner-b", "week")

        assert received_owners == ["owner-a", "owner-b"]


class TestAvgConfidenceForCallIds:
    def test_filters_by_call_id_and_event_name(self, tmp_path, monkeypatch):
        monkeypatch.setattr(stats, "_PROJECT_ROOT", tmp_path)
        log_dir = tmp_path / "logs"
        log_dir.mkdir()
        today = datetime.now(timezone.utc)
        log_path = log_dir / f"call_data_record_{today.strftime('%Y%m%d')}.log"
        lines = [
            {"call_id": "c1", "event": "llm_response_generated", "confidence": 0.8},
            {"call_id": "c2", "event": "llm_response_generated", "confidence": 0.9},  # 다른 owner 통화 - 제외되어야 함
            {"call_id": "c1", "event": "some_other_event", "confidence": 0.1},  # 이벤트명 불일치 - 제외
        ]
        log_path.write_text("\n".join(json.dumps(x) for x in lines), encoding="utf-8")

        avg = stats._avg_confidence_for_call_ids({"c1"}, today - timedelta(days=1))
        assert avg == 0.8

    def test_no_matching_lines_returns_zero(self, tmp_path, monkeypatch):
        monkeypatch.setattr(stats, "_PROJECT_ROOT", tmp_path)
        avg = stats._avg_confidence_for_call_ids({"nonexistent"}, datetime.now(timezone.utc))
        assert avg == 0.0


class TestHitlCountForItems:
    def test_sums_resolved_by_hitl_count_from_call_insights(self, tmp_path, monkeypatch):
        monkeypatch.setattr(stats, "_recordings_root", lambda: tmp_path)
        call_dir = tmp_path / "call1"
        call_dir.mkdir()
        (call_dir / "call_insights.json").write_text(
            json.dumps({"ai_unhandled_resolved_by_hitl_count": 2}), encoding="utf-8"
        )
        items = [{"call_id": "call1", "recordings_dir": str(call_dir)}]
        assert stats._hitl_count_for_items(items) == 2

    def test_missing_recordings_dir_is_skipped(self):
        items = [{"call_id": "call1", "recordings_dir": ""}]
        assert stats._hitl_count_for_items(items) == 0


class TestGetSelfServiceStatsTool:
    def test_registered_in_self_service_tools(self):
        # Story 1.5/1.6/1.7/1.8/1.13(통화 이력 NLQ 3개) — 도구가 늘어날 때마다 갱신
        assert len(SELF_SERVICE_TOOLS) == 9

    @pytest.mark.asyncio
    async def test_tool_returns_json_from_impl(self, monkeypatch):
        async def fake_impl(owner, period):
            return {"call_count": 5, "period": period}

        monkeypatch.setattr(
            "src.ai_voicebot.self_service.tools._get_self_service_stats_impl",
            fake_impl,
        )
        result = json.loads(await _get_self_service_stats("1003", "week"))
        assert result == {"call_count": 5, "period": "week"}

    @pytest.mark.asyncio
    async def test_tool_absorbs_exceptions(self, monkeypatch):
        async def fake_impl(owner, period):
            raise RuntimeError("boom")

        monkeypatch.setattr(
            "src.ai_voicebot.self_service.tools._get_self_service_stats_impl",
            fake_impl,
        )
        result = json.loads(await _get_self_service_stats("1003", "week"))
        assert "error" in result
