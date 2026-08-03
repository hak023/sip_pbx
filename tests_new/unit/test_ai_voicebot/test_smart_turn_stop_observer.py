"""
AI Voicebot Unit Tests - Smart Turn stop 전략 관측 래퍼 (Story 7.1 Task 4)

docs/stories/7.1.smart-turn-stop-strategy-investigation.story.md 참고.
`build_observed_smart_turn_stop_strategy()`가 pipecat 기본값과 동일한 전략을 생성하고,
순수 관측용 이벤트 핸들러만 추가하는지(판단 로직 미변경) 검증한다.
"""

import pytest

from src.ai_voicebot.pipecat.smart_turn_stop_observer import (
    build_observed_smart_turn_stop_strategy,
)


class TestBuildObservedSmartTurnStopStrategy:
    def test_builds_turn_analyzer_strategy_instance(self):
        strategy = build_observed_smart_turn_stop_strategy(call_id="test-call")
        assert strategy is not None
        # pipecat 기본값과 동일한 클래스여야 한다(§7.1 핵심 발견 사실 유지 확인).
        assert type(strategy).__name__ == "TurnAnalyzerUserTurnStopStrategy"

    @pytest.mark.asyncio
    async def test_on_user_turn_stopped_observer_does_not_raise(self):
        """관측 핸들러가 이벤트 발생 시 예외 없이 실행되는지 확인(회귀 없음)."""
        strategy = build_observed_smart_turn_stop_strategy(call_id="test-call")
        assert strategy is not None
        # 실제 turn-stop 이벤트를 흉내내어 핸들러가 정상 실행되는지 확인.
        await strategy._call_event_handler("on_user_turn_stopped")

    def test_returns_none_when_strategy_construction_fails(self, monkeypatch):
        """전략 생성 자체가 실패하면 None을 반환해 호출부가 기존 기본값으로 폴백할 수 있어야 한다."""
        import pipecat.turns.user_stop.turn_analyzer_user_turn_stop_strategy as strategy_mod

        def _raise(*args, **kwargs):
            raise RuntimeError("simulated model load failure")

        monkeypatch.setattr(strategy_mod, "TurnAnalyzerUserTurnStopStrategy", _raise)
        result = build_observed_smart_turn_stop_strategy(call_id="x")
        assert result is None
