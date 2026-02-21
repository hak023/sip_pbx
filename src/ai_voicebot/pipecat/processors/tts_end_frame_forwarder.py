"""
Ensures LLMFullResponseEndFrame reaches TTSCompleteNotifier when Pipecat TTS does not forward it.

Pipeline: … → Google TTS → [TTSEndFrameForwarder] → TTSCompleteNotifier → …

Pipecat TTSService with push_text_frames=True is supposed to push LLMFullResponseEndFrame
after flushing and finishing TTS. In practice, the streaming Google TTS path may not
forward it (or forwards it before TTS audio is done). This processor guarantees exactly
one EndFrame per LLM response: either the one from upstream or a synthetic one emitted
after TTSStoppedFrame.
"""

import structlog

from pipecat.frames.frames import (
    Frame,
    LLMFullResponseEndFrame,
    LLMFullResponseStartFrame,
    TTSStoppedFrame,
)
from pipecat.processors.frame_processor import FrameDirection, FrameProcessor

logger = structlog.get_logger(__name__)


class TTSEndFrameForwarder(FrameProcessor):
    """
    Forwards all frames. Ensures one LLMFullResponseEndFrame per response:
    - If upstream sends LLMFullResponseEndFrame, forward it and clear pending.
    - If we see TTSStoppedFrame while pending (no EndFrame was forwarded), push
      a synthetic LLMFullResponseEndFrame then forward TTSStoppedFrame.
    """

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self._pending_end = False  # True after StartFrame until we push an EndFrame
        self._end_sent_for_response = False  # Avoid forwarding duplicate EndFrame if both synthetic and real arrive

    async def process_frame(self, frame: Frame, direction: FrameDirection):
        await super().process_frame(frame, direction)

        if isinstance(frame, LLMFullResponseStartFrame):
            self._pending_end = True
            self._end_sent_for_response = False
            await self.push_frame(frame, direction)
            return

        if isinstance(frame, LLMFullResponseEndFrame):
            if self._end_sent_for_response:
                # Already sent synthetic EndFrame for this response; drop duplicate
                return
            self._pending_end = False
            self._end_sent_for_response = True
            await self.push_frame(frame, direction)
            return

        if isinstance(frame, TTSStoppedFrame):
            logger.info(
                "tts_stopped_frame_received",
                call=True,
                category="tts",
                pending_end=self._pending_end,
                message="TTSStoppedFrame received (TTS output finished for this chunk)",
            )
            await self.push_frame(frame, direction)
            # Emit synthetic EndFrame *after* TTSStoppedFrame so TTSCompleteNotifier has seen all audio (and accumulated duration) before the signal.
            if self._pending_end:
                logger.info(
                    "tts_end_frame_forwarder_synthetic_end",
                    call=True,
                    category="tts",
                    message="Emitting synthetic LLMFullResponseEndFrame after TTSStoppedFrame (upstream did not forward)",
                )
                await self.push_frame(LLMFullResponseEndFrame(), direction)
                self._pending_end = False
                self._end_sent_for_response = True
            return

        await self.push_frame(frame, direction)
