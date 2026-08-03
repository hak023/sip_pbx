"""
AI Voicebot Unit Tests - Smart Barge-in User Turn Start Strategy (Story 5.4)

docs/stories/5.4.smart-barge-in-implementation.story.md 참고.
실제 pipecat 파이프라인/오디오 없이, `SmartBargeInUserTurnStartStrategy`의 3단계 필터
(키워드/맞장구·단어수/LLM 판단) 로직이 올바르게 트리거/미트리거를 결정하는지 검증한다.
"""

import pytest

from pipecat.frames.frames import (
    BotStartedSpeakingFrame,
    BotStoppedSpeakingFrame,
    InterimTranscriptionFrame,
    TranscriptionFrame,
)

from src.ai_voicebot.pipecat.smart_barge_in_turn_strategy import (
    SmartBargeInUserTurnStartStrategy,
)


def _final_frame(text: str) -> TranscriptionFrame:
    return TranscriptionFrame(text=text, user_id="", timestamp="")


def _interim_frame(text: str) -> InterimTranscriptionFrame:
    return InterimTranscriptionFrame(text=text, user_id="", timestamp="")


class _TriggerRecorder:
    """trigger_user_turn_started() 호출 여부를 기록하는 헬퍼."""

    def __init__(self, strategy: SmartBargeInUserTurnStartStrategy):
        self.calls = 0

        async def _fake_trigger():
            self.calls += 1

        strategy.trigger_user_turn_started = _fake_trigger  # type: ignore[method-assign]


class TestBotNotSpeaking:
    @pytest.mark.asyncio
    async def test_any_word_triggers_when_bot_silent(self):
        strategy = SmartBargeInUserTurnStartStrategy(min_words=3)
        recorder = _TriggerRecorder(strategy)

        await strategy.process_frame(_final_frame("안녕하세요"))

        assert recorder.calls == 1


class TestBotSpeakingStage1Keyword:
    @pytest.mark.asyncio
    async def test_keyword_triggers_immediately_even_if_short(self):
        strategy = SmartBargeInUserTurnStartStrategy(min_words=3)
        recorder = _TriggerRecorder(strategy)

        await strategy.process_frame(BotStartedSpeakingFrame())
        await strategy.process_frame(_final_frame("잠깐만"))

        assert recorder.calls == 1
        assert strategy.get_stats()["keyword_interrupts"] == 1


class TestBotSpeakingStage2WordCountAndBackchannel:
    @pytest.mark.asyncio
    async def test_backchannel_does_not_trigger(self):
        strategy = SmartBargeInUserTurnStartStrategy(min_words=3)
        recorder = _TriggerRecorder(strategy)

        await strategy.process_frame(BotStartedSpeakingFrame())
        await strategy.process_frame(_final_frame("네"))

        assert recorder.calls == 0
        assert strategy.get_stats()["backchannel_ignored"] == 1

    @pytest.mark.asyncio
    async def test_below_min_words_does_not_trigger(self):
        strategy = SmartBargeInUserTurnStartStrategy(min_words=3)
        recorder = _TriggerRecorder(strategy)

        await strategy.process_frame(BotStartedSpeakingFrame())
        await strategy.process_frame(_final_frame("저기 그거"))  # 2 words < min_words=3

        assert recorder.calls == 0
        assert strategy.get_stats()["word_count_ignored"] == 1

    @pytest.mark.asyncio
    async def test_at_or_above_min_words_without_llm_triggers(self):
        strategy = SmartBargeInUserTurnStartStrategy(min_words=3, llm_client=None)
        recorder = _TriggerRecorder(strategy)

        await strategy.process_frame(BotStartedSpeakingFrame())
        await strategy.process_frame(_final_frame("잠시 다른 질문 있어요"))

        assert recorder.calls == 1


class _FakeLLMClient:
    def __init__(self, verdict: str = "interruption"):
        self.verdict = verdict
        self.calls = 0

    async def judge_barge_in(self, *, user_text: str, ai_current_text: str) -> str:
        self.calls += 1
        return self.verdict


class TestBotSpeakingStage3LLMJudgment:
    @pytest.mark.asyncio
    async def test_llm_says_interruption_triggers(self):
        llm = _FakeLLMClient(verdict="interruption")
        strategy = SmartBargeInUserTurnStartStrategy(min_words=3, llm_client=llm)
        recorder = _TriggerRecorder(strategy)

        await strategy.process_frame(BotStartedSpeakingFrame())
        await strategy.process_frame(_final_frame("잠시 다른 질문 있어요"))

        assert recorder.calls == 1
        assert llm.calls == 1
        assert strategy.get_stats()["llm_interrupts"] == 1

    @pytest.mark.asyncio
    async def test_llm_says_backchannel_does_not_trigger(self):
        llm = _FakeLLMClient(verdict="맞장구")
        strategy = SmartBargeInUserTurnStartStrategy(min_words=3, llm_client=llm)
        recorder = _TriggerRecorder(strategy)

        await strategy.process_frame(BotStartedSpeakingFrame())
        await strategy.process_frame(_final_frame("잠시 다른 질문 있어요"))

        assert recorder.calls == 0
        assert llm.calls == 1
        assert strategy.get_stats()["llm_continued"] == 1

    @pytest.mark.asyncio
    async def test_llm_error_fails_safe_to_interrupt(self):
        class _BrokenLLM:
            async def judge_barge_in(self, **kwargs):
                raise RuntimeError("boom")

        strategy = SmartBargeInUserTurnStartStrategy(min_words=3, llm_client=_BrokenLLM())
        recorder = _TriggerRecorder(strategy)

        await strategy.process_frame(BotStartedSpeakingFrame())
        await strategy.process_frame(_final_frame("잠시 다른 질문 있어요"))

        assert recorder.calls == 1
        assert strategy.get_stats()["llm_error_fallback_interrupts"] == 1


class TestInterimAccumulationAndReset:
    @pytest.mark.asyncio
    async def test_interim_accumulates_into_final_judgment(self):
        """interim은 판단(LLM 호출)을 트리거하지 않고 컨텍스트로만 누적된다."""
        llm = _FakeLLMClient(verdict="interruption")
        strategy = SmartBargeInUserTurnStartStrategy(min_words=3, llm_client=llm)
        recorder = _TriggerRecorder(strategy)

        await strategy.process_frame(BotStartedSpeakingFrame())
        await strategy.process_frame(_interim_frame("잠시"))
        assert recorder.calls == 0
        assert llm.calls == 0  # interim만으로는 LLM 호출 안 함

        await strategy.process_frame(_final_frame("다른 질문 있어요"))
        assert llm.calls == 1
        assert recorder.calls == 1

    @pytest.mark.asyncio
    async def test_bot_stopped_speaking_resets_accumulated_text(self):
        strategy = SmartBargeInUserTurnStartStrategy(min_words=3)
        recorder = _TriggerRecorder(strategy)

        await strategy.process_frame(BotStartedSpeakingFrame())
        await strategy.process_frame(_interim_frame("잠시"))
        await strategy.process_frame(BotStoppedSpeakingFrame())

        # 봇이 멈췄으니 다음 최종 발화는 "일반 발화 시작" 경로(1단어 이상이면 즉시 트리거)
        await strategy.process_frame(_final_frame("네"))
        assert recorder.calls == 1
