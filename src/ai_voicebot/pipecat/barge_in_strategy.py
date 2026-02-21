"""
Smart Barge-in Strategy for Pipecat Pipeline (Phase 3).

3단계 필터 구조:
  Stage 1: Fast Filter - 키워드 즉시 체크 (<1ms)
  Stage 2: Word Count Gate - 3단어 이상 체크
  Stage 3: LLM Judgment - 맞장구 vs Interrupt 판단 (200-500ms)

설계서 섹션 5. Turn-Taking / Barge-in Strategy 구현.
"""

import asyncio
import time
from typing import Optional, List

import structlog

from pipecat.frames.frames import (
    Frame,
    InterimTranscriptionFrame,
    StartInterruptionFrame,
    TranscriptionFrame,
)
from pipecat.processors.frame_processor import FrameDirection, FrameProcessor

logger = structlog.get_logger(__name__)

# Stage 1: 즉시 중단 키워드
INTERRUPT_KEYWORDS = [
    "잠깐", "잠깐만", "잠시만", "알았어", "알겠어",
    "그만", "멈춰", "됐어", "그만해", "중지",
    "아 잠깐", "아 그만", "네 알겠어",
]

# Stage 2: 맞장구 표현 (무시)
BACKCHANNEL_PATTERNS = [
    "네", "네네", "음", "음음", "아", "아~", "그렇군요",
    "그래요", "맞아요", "응", "응응", "어", "오",
    "아하", "그렇구나", "그래", "아 그래",
]

# LLM Barge-in 판단 프롬프트
BARGE_IN_PROMPT = """AI가 고객에게 설명을 하고 있는 중에 고객이 아래와 같이 말했습니다.

AI가 말하고 있는 내용: "{ai_current_text}"
고객이 말한 내용: "{user_text}"

고객의 말이 다음 중 어디에 해당하는지 판단하세요:
1. "맞장구" - 듣고 있다는 표시 (예: "네", "음", "그렇군요", "아~")
2. "interruption" - 말을 끊고 새로운 요청/질문을 하려는 의도

답변: "맞장구" 또는 "interruption" 중 하나만 출력하세요."""


class SmartBargeInStrategy:
    """
    키워드 + 단어 수 + LLM 기반 Barge-in 판단.

    Pipecat의 allow_interruptions=True와 연동하여 동작.
    TTS 발화 중 사용자 발화가 감지되면 3단계 필터로 판단.
    """

    def __init__(
        self,
        min_words: int = 3,
        keywords: Optional[List[str]] = None,
        backchannel: Optional[List[str]] = None,
        llm_client=None,
    ):
        """
        Args:
            min_words: LLM 판단 기준 최소 단어 수 (기본 3)
            keywords: 즉시 중단 키워드 리스트
            backchannel: 맞장구 표현 리스트
            llm_client: LLM 클라이언트 (judge_barge_in 메서드 필요)
        """
        self.min_words = min_words
        self.keywords = keywords or INTERRUPT_KEYWORDS
        self.backchannel = backchannel or BACKCHANNEL_PATTERNS
        self.llm_client = llm_client

        # 발화 누적
        self.accumulated_text = ""
        self.ai_current_text = ""  # TTS가 현재 발화 중인 텍스트

        # 통계
        self.stats = {
            "keyword_interrupts": 0,
            "llm_interrupts": 0,
            "backchannel_ignored": 0,
            "word_count_ignored": 0,
            "llm_continued": 0,
            "total_checks": 0,
        }

    def set_ai_text(self, text: str):
        """현재 TTS가 발화 중인 텍스트 설정"""
        self.ai_current_text = text

    async def append_text(self, text: str):
        """STT 중간 결과를 누적"""
        self.accumulated_text += " " + text

    async def should_interrupt(self) -> bool:
        """
        3단계 필터를 거쳐 interrupt 여부 판단.

        Returns:
            True: TTS 중단 + 사용자에게 주도권
            False: TTS 계속 (무시)
        """
        text = self.accumulated_text.strip()
        if not text:
            return False

        self.stats["total_checks"] += 1

        # ── Stage 1: Fast Filter - 키워드 즉시 체크 (<1ms) ──
        for keyword in self.keywords:
            if keyword in text:
                self.stats["keyword_interrupts"] += 1
                logger.info("barge_in_keyword_interrupt",
                           keyword=keyword, text=text[:60])
                return True

        # ── Stage 2: Word Count Gate ──
        word_count = len(text.split())

        # 맞장구 체크 (짧은 발화)
        text_stripped = text.strip()
        if text_stripped in self.backchannel or word_count < 2:
            self.stats["backchannel_ignored"] += 1
            logger.debug("barge_in_backchannel_ignored", text=text[:40])
            return False

        if word_count < self.min_words:
            self.stats["word_count_ignored"] += 1
            logger.debug("barge_in_word_count_ignored",
                        words=word_count, min=self.min_words)
            return False

        # ── Stage 3: LLM Judgment (200-500ms) ──
        if self.llm_client:
            try:
                result = await self.llm_client.judge_barge_in(
                    user_text=text,
                    ai_current_text=self.ai_current_text,
                )
                is_interrupt = (result == "interruption")

                if is_interrupt:
                    self.stats["llm_interrupts"] += 1
                    logger.info("barge_in_llm_interrupt",
                               text=text[:60], ai_text=self.ai_current_text[:60])
                else:
                    self.stats["llm_continued"] += 1
                    logger.debug("barge_in_llm_continued", text=text[:60])

                return is_interrupt
            except Exception as e:
                logger.warning("barge_in_llm_error", error=str(e))
                # LLM 실패 시 단어 수만으로 판단 → interrupt
                return True

        # LLM 없으면 단어 수 이상이면 interrupt
        return True

    async def reset(self):
        """발화 누적 초기화 (새 발화 주기 시작)"""
        self.accumulated_text = ""

    def get_stats(self) -> dict:
        """통계 반환"""
        return dict(self.stats)


class SmartBargeInProcessor(FrameProcessor):
    """
    Pipecat FrameProcessor로 래핑된 SmartBargeInStrategy.

    파이프라인에서 TranscriptionFrame (STT 결과)을 가로채서
    TTS 발화 중이면 3단계 필터로 interrupt 여부를 판단.

    Pipeline 위치: STT → [SmartBargeInProcessor] → RAG-LLM

    - TTS 발화 중이 아닐 때: TranscriptionFrame 그대로 통과
    - TTS 발화 중일 때:
      - interrupt 판단 → StartInterruptionFrame 전송
      - 무시 판단 → 프레임 드롭
    """

    def __init__(
        self,
        strategy: SmartBargeInStrategy,
        **kwargs,
    ):
        super().__init__(**kwargs)
        self._strategy = strategy
        self._tts_playing = False
        self._current_tts_text = ""

    async def process_frame(self, frame: Frame, direction: FrameDirection):
        await super().process_frame(frame, direction)

        # TTS 시작/종료 추적
        from pipecat.frames.frames import (
            LLMFullResponseStartFrame,
            LLMFullResponseEndFrame,
            TextFrame,
        )

        if isinstance(frame, LLMFullResponseStartFrame):
            self._tts_playing = True
            await self._strategy.reset()
            await self.push_frame(frame, direction)
            return

        if isinstance(frame, LLMFullResponseEndFrame):
            self._tts_playing = False
            self._current_tts_text = ""
            self._strategy.set_ai_text("")
            await self.push_frame(frame, direction)
            return

        # TTS 텍스트 추적 (AI가 말하고 있는 내용)
        if isinstance(frame, TextFrame) and direction == FrameDirection.DOWNSTREAM:
            self._current_tts_text += frame.text + " "
            self._strategy.set_ai_text(self._current_tts_text.strip())
            await self.push_frame(frame, direction)
            return

        # STT 중간 결과 (TTS 중일 때)
        if isinstance(frame, InterimTranscriptionFrame):
            if self._tts_playing:
                # 발화 텍스트 누적 (판단용)
                if frame.text:
                    await self._strategy.append_text(frame.text)
                # 중간 결과는 드롭 (TTS 중이므로)
                return
            else:
                await self.push_frame(frame, direction)
                return

        # STT 최종 결과
        if isinstance(frame, TranscriptionFrame):
            if self._tts_playing:
                # 최종 결과도 누적
                if frame.text:
                    await self._strategy.append_text(frame.text)

                # 3단계 필터로 판단
                should_interrupt = await self._strategy.should_interrupt()

                if should_interrupt:
                    logger.info("smart_barge_in_triggered",
                               user_text=frame.text[:80],
                               ai_text=self._current_tts_text[:60])

                    # Pipecat interrupt 프레임 전송
                    await self.push_frame(
                        StartInterruptionFrame(), FrameDirection.UPSTREAM
                    )

                    # STT 결과는 그대로 통과시켜 RAG-LLM이 처리하도록
                    await self.push_frame(frame, direction)

                    # 상태 초기화
                    self._tts_playing = False
                    self._current_tts_text = ""
                    await self._strategy.reset()
                else:
                    # 무시 (맞장구 등)
                    logger.debug("smart_barge_in_ignored",
                               user_text=frame.text[:60])
                    await self._strategy.reset()
                return
            else:
                # TTS 중이 아니면 그대로 통과
                await self.push_frame(frame, direction)
                return

        # 기타 프레임은 그대로 통과
        await self.push_frame(frame, direction)
