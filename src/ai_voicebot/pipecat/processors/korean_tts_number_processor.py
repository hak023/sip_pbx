"""
TTS 직전 TextFrame의 아라비아 숫자를 한글 수사로 바꿔 ko-KR TTS가 영어로 읽는 현상을 완화한다.
"""

from __future__ import annotations

from typing import Optional

import structlog

from pipecat.frames.frames import Frame, TextFrame
from pipecat.processors.frame_processor import FrameDirection, FrameProcessor

from src.common.korean_tts_normalize import normalize_text_for_korean_tts

logger = structlog.get_logger(__name__)


class KoreanTTSNumberProcessor(FrameProcessor):
    """rag_llm → (본 프로세서) → tts 순서로 배치."""

    def __init__(self, *, call_id: Optional[str] = None, **kwargs):
        super().__init__(**kwargs)
        self._call_id = call_id or ""

    async def process_frame(self, frame: Frame, direction: FrameDirection):
        await super().process_frame(frame, direction)
        if isinstance(frame, TextFrame):
            orig = frame.text or ""
            norm = normalize_text_for_korean_tts(orig)
            
            # 📌 TTS 직전 TextFrame 추적 (분할 원인 파악용)
            logger.info(
                "korean_numbers_textframe_input",
                call_id=self._call_id,
                progress="tts",
                category="tts",
                text_len=len(orig),
                text_preview=orig[:80] if orig else "",
                normalized=(norm != orig),
                note="korean_tts_numbers → TTS로 전달 직전 TextFrame (분할 여부 추적)",
            )
            
            if norm != orig:
                logger.debug(
                    "korean_tts_number_normalized",
                    call_id=self._call_id,
                    orig_len=len(orig),
                    norm_len=len(norm),
                    orig_preview=orig[:120],
                    norm_preview=norm[:120],
                    note="TTS 입력 숫자 → 한글 수사 치환",
                )
            await self.push_frame(TextFrame(text=norm), direction)
            return
        await self.push_frame(frame, direction)
