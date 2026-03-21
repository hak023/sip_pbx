"""
Ensures exactly one LLMFullResponseEndFrame per response, emitted only after TTS has
finished all audio (TTSStoppedFrame). Prevents TTS truncation caused by upstream
sending EndFrame before TTS outputs all audio.

Pipeline: … → Google TTS → [TTSEndFrameForwarder] → TTSCompleteNotifier → …

- Upstream (StreamingTTSGateway/Google TTS) may send LLMFullResponseEndFrame right after
  text flush, before TTS has generated all audio. We do NOT forward that; we wait for
  TTSStoppedFrame and then emit a synthetic EndFrame so downstream always sees
  [all audio] → TTSStoppedFrame → EndFrame.
"""

import structlog
from typing import Any, Dict, Optional

from pipecat.frames.frames import (
    Frame,
    LLMFullResponseEndFrame,
    LLMFullResponseStartFrame,
    TTSStoppedFrame,
)
from pipecat.processors.frame_processor import FrameDirection, FrameProcessor

logger = structlog.get_logger(__name__)


def _is_audio_frame(frame: Frame) -> bool:
    audio = getattr(frame, "audio", None)
    return isinstance(audio, bytes) and len(audio) > 0


class TTSEndFrameForwarder(FrameProcessor):
    """
    Forwards all frames except upstream LLMFullResponseEndFrame. Ensures exactly one
    EndFrame per response, emitted only after TTSStoppedFrame (all TTS audio for this
    response has been output).
    """

    def __init__(self, sync_context: Optional[Dict[str, Any]] = None, **kwargs):
        super().__init__(**kwargs)
        self._sync_context = sync_context or {}
        self._pending_end = False  # True after StartFrame until we push an EndFrame
        self._audio_frames_since_start = 0  # 디버깅: 이번 응답에서 지나간 오디오 프레임 수

    async def process_frame(self, frame: Frame, direction: FrameDirection):
        await super().process_frame(frame, direction)

        if isinstance(frame, LLMFullResponseStartFrame):
            self._pending_end = True
            self._audio_frames_since_start = 0
            await self.push_frame(frame, direction)
            return

        if isinstance(frame, LLMFullResponseEndFrame):
            # Upstream이 보낸 EndFrame은 절대 그대로 전달하지 않음. TTS가 모든 오디오를
            # 내보낸 뒤(TTSStoppedFrame)에만 synthetic EndFrame을 보내서 문장 끝 잘림 방지.
            call_id = self._sync_context.get("_call_id", "")
            logger.info(
                "endframe_upstream_received_not_forwarded",
                call=True,
                call_id=call_id,
                category="tts",
                progress="tts",
                audio_frames_since_start=self._audio_frames_since_start,
                note="Upstream EndFrame 수신 → 전달 안 함. TTSStoppedFrame 후에만 EndFrame 전송 예정.",
            )
            return

        if isinstance(frame, TTSStoppedFrame):
            call_id = self._sync_context.get("_call_id", "")
            logger.info(
                "tts_stopped_frame_received",
                call=True,
                call_id=call_id,
                category="tts",
                progress="tts",
                pending_end=self._pending_end,
                audio_frames_since_start=self._audio_frames_since_start,
                note="TTS 이번 응답 오디오 출력 완료. 이 시점 이후에만 EndFrame 전송.",
            )
            await self.push_frame(frame, direction)
            if self._pending_end:
                logger.info(
                    "endframe_emitted_after_tts_stopped",
                    call=True,
                    call_id=call_id,
                    category="tts",
                    progress="tts",
                    audio_frames_since_start=self._audio_frames_since_start,
                    note="Synthetic LLMFullResponseEndFrame 전송 (오디오 전부 지나간 뒤)",
                )
                await self.push_frame(LLMFullResponseEndFrame(), direction)
                self._pending_end = False
            self._audio_frames_since_start = 0
            return

        if _is_audio_frame(frame):
            self._audio_frames_since_start += 1

        await self.push_frame(frame, direction)
