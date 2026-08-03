"""
Smart Barge-in User Turn Start Strategy (Story 5.4).

Story 5.2의 설계 권고를 반영해, 죽은 코드였던 `SmartBargeInProcessor`(FrameProcessor 기반,
`barge_in_strategy.py`)를 그대로 되살리지 않고, 그 판단 로직(Stage 1 키워드/Stage 2 단어수·
맞장구 필터/Stage 3 LLM 판단)만 추출해 pipecat의 `user_turn_strategies` API
(`BaseUserTurnStartStrategy`)로 재구현한다.

기존 `MinWordsUserTurnStartStrategy(min_words=3)`가 이미 파이프라인에 연결되어 있으므로
(Story 5.1 조사 확인), 이 클래스는 그것을 **대체**하는 용도로 설계했다 — 두 전략을 동시에
`start=[...]` 리스트에 넣으면 각각 독립적으로 `trigger_user_turn_started()`를 호출해 OR로
동작하므로(pipecat `UserTurnStrategies` 다중 전략은 병렬 판정), 단어 수 게이트만 있는 기존
전략과 나란히 두면 오히려 더 민감해질 뿐 "똑똑해지지" 않는다. 따라서 봇이 말하는 중(barge-in
상황)에는 이 클래스가 키워드/맞장구/LLM 판단까지 전부 수행하고, 봇이 조용할 때(일반 발화 시작)는
`MinWordsUserTurnStartStrategy(min_words=1)`와 동일하게 즉시 트리거해 기존 동작을 그대로
유지한다.

기본값은 비활성(옵트인) — `config.yaml`의 `ai_pipeline.barge_in.smart_judge_enabled: true`로만
활성화되며, 기본 False일 때 `pipeline_builder.py`는 기존 `MinWordsUserTurnStartStrategy`를
그대로 사용해 회귀 위험이 없다.
"""

from typing import List, Optional

import structlog
from pipecat.frames.frames import (
    BotStartedSpeakingFrame,
    BotStoppedSpeakingFrame,
    Frame,
    InterimTranscriptionFrame,
    TranscriptionFrame,
)
from pipecat.turns.user_start.base_user_turn_start_strategy import (
    BaseUserTurnStartStrategy,
)

from src.ai_voicebot.pipecat.barge_in_strategy import (
    BACKCHANNEL_PATTERNS,
    INTERRUPT_KEYWORDS,
)

logger = structlog.get_logger(__name__)


class SmartBargeInUserTurnStartStrategy(BaseUserTurnStartStrategy):
    """3단계 필터(키워드/단어수·맞장구/LLM 판단) 기반 barge-in 감지 전략.

    - 봇이 말하고 있지 않을 때: 일반 발화 시작 감지(`min_words=1`과 동일, 회귀 없음).
    - 봇이 말하고 있을 때(barge-in 상황):
        Stage 1: 즉시 중단 키워드("잠깐", "그만" 등) → 즉시 트리거.
        Stage 2: 맞장구("네", "음" 등) 또는 단어 수 미달 → 트리거 안 함.
        Stage 3: LLM 판단(`llm_client.judge_barge_in`, 있는 경우만) → interruption일 때만 트리거.
          LLM 미설정 시 Stage 2를 통과하면 트리거(기존 `SmartBargeInStrategy` 기본값과 동일).
    """

    def __init__(
        self,
        *,
        min_words: int = 3,
        keywords: Optional[List[str]] = None,
        backchannel: Optional[List[str]] = None,
        llm_client=None,
        use_interim: bool = True,
        **kwargs,
    ):
        super().__init__(**kwargs)
        self._min_words = min_words
        self._keywords = keywords or INTERRUPT_KEYWORDS
        self._backchannel = backchannel or BACKCHANNEL_PATTERNS
        self._llm_client = llm_client
        self._use_interim = use_interim
        self._bot_speaking = False
        # barge-in 판단용 누적 텍스트(구 SmartBargeInStrategy와 동일 원칙 —
        # interim은 컨텍스트로만 누적하고, 최종 판단(LLM 호출 포함)은 final TranscriptionFrame에서만 수행)
        self._accumulated_text = ""

        self.stats = {
            "keyword_interrupts": 0,
            "llm_interrupts": 0,
            "backchannel_ignored": 0,
            "word_count_ignored": 0,
            "llm_continued": 0,
            "llm_error_fallback_interrupts": 0,
            "total_checks": 0,
        }

    async def reset(self):
        await super().reset()
        self._accumulated_text = ""

    async def process_frame(self, frame: Frame):
        await super().process_frame(frame)

        if isinstance(frame, BotStartedSpeakingFrame):
            self._bot_speaking = True
            self._accumulated_text = ""
            return

        if isinstance(frame, BotStoppedSpeakingFrame):
            self._bot_speaking = False
            self._accumulated_text = ""
            return

        if isinstance(frame, InterimTranscriptionFrame):
            if self._bot_speaking and self._use_interim and frame.text:
                self._accumulated_text = (self._accumulated_text + " " + frame.text).strip()
            return

        if isinstance(frame, TranscriptionFrame):
            if not self._bot_speaking:
                # 봇이 조용할 때 — 일반 발화 시작(기존 min_words=1과 동일 동작, 회귀 없음)
                if frame.text and len(frame.text.split()) >= 1:
                    await self.trigger_user_turn_started()
                return

            # ── 봇이 말하는 중(barge-in 판단) ──
            if frame.text:
                self._accumulated_text = (self._accumulated_text + " " + frame.text).strip()
            text = self._accumulated_text.strip()
            if not text:
                return

            self.stats["total_checks"] += 1
            await self._judge_and_maybe_trigger(text)
            self._accumulated_text = ""

    async def _judge_and_maybe_trigger(self, text: str) -> None:
        # ── Stage 1: 즉시 중단 키워드 ──
        for keyword in self._keywords:
            if keyword in text:
                self.stats["keyword_interrupts"] += 1
                logger.info("smart_barge_in_keyword_interrupt", keyword=keyword, text=text)
                await self.trigger_user_turn_started()
                return

        # ── Stage 2: 맞장구/단어 수 게이트 ──
        word_count = len(text.split())
        if text in self._backchannel or word_count < 2:
            self.stats["backchannel_ignored"] += 1
            logger.debug("smart_barge_in_backchannel_ignored", text=text)
            return
        if word_count < self._min_words:
            self.stats["word_count_ignored"] += 1
            logger.debug(
                "smart_barge_in_word_count_ignored", words=word_count, min=self._min_words
            )
            return

        # ── Stage 3: LLM 판단 ──
        if self._llm_client is not None and hasattr(self._llm_client, "judge_barge_in"):
            try:
                result = await self._llm_client.judge_barge_in(
                    user_text=text, ai_current_text=""
                )
                if result == "interruption":
                    self.stats["llm_interrupts"] += 1
                    logger.info("smart_barge_in_llm_interrupt", text=text)
                    await self.trigger_user_turn_started()
                else:
                    self.stats["llm_continued"] += 1
                    logger.debug("smart_barge_in_llm_continued", text=text)
            except Exception as e:
                # LLM 실패 시 안전하게 interrupt 처리(구 SmartBargeInStrategy와 동일 원칙 —
                # 판단 불가 시 사용자 발화를 무시하지 않는 쪽으로 fail-safe)
                self.stats["llm_error_fallback_interrupts"] += 1
                logger.warning("smart_barge_in_llm_error", error=str(e))
                await self.trigger_user_turn_started()
            return

        # LLM 미설정 — 단어 수 게이트만 통과하면 트리거
        await self.trigger_user_turn_started()

    def get_stats(self) -> dict:
        return dict(self.stats)
