"""
TTS 완료 알림 프로세서 (Phase1/Phase2 인사말 순차 재생용).

GoogleTTS 직후에 배치하여:
- OutputAudioRawFrame/TTSAudioRawFrame 등 오디오 프레임의 재생 길이를 누적하고
- LLMFullResponseEndFrame이 지나가면 해당 응답의 TTS 합성 완료 + 누적 재생 시간(초)을
  공유 컨텍스트에 넣고 Event를 set한다.
RAGLLMProcessor는 이벤트를 기다린 뒤, 실제 음원 길이만큼 추가 대기 후 Phase2를 전송할 수 있다.
"""

import asyncio
import time
from datetime import datetime
from typing import Any, Dict

import structlog

from pipecat.frames.frames import Frame, LLMFullResponseEndFrame
from pipecat.processors.frame_processor import FrameDirection, FrameProcessor

logger = structlog.get_logger(__name__)

# 공유 컨텍스트 키 (RAGLLMProcessor와 동일 문자열 사용)
KEY_ON_TTS_COMPLETE = "on_tts_complete"
KEY_LAST_TTS_DURATION_SEC = "last_tts_duration_sec"

# 16-bit PCM 기준: bytes -> 초
def _audio_duration_sec(audio_bytes: bytes, sample_rate: int, num_channels: int = 1) -> float:
    if not audio_bytes or sample_rate <= 0:
        return 0.0
    return len(audio_bytes) / (sample_rate * 2 * max(1, num_channels))


class TTSCompleteNotifier(FrameProcessor):
    """
    - TTS 출력 오디오 프레임의 재생 길이를 누적하고
    - LLMFullResponseEndFrame 수신 시 Event set + last_tts_duration_sec 설정.
    """

    def __init__(self, sync_context: Dict[str, Any], **kwargs):
        super().__init__(**kwargs)
        self._sync_context = sync_context
        self._current_duration_sec: float = 0.0
        self._expecting_first_audio: bool = True  # 응답별 첫 오디오 수신 시 로그용

    def _add_audio_duration(self, frame: Frame) -> None:
        """오디오 프레임이면 재생 길이 누적 (OutputAudioRawFrame, TTSAudioRawFrame 등)."""
        audio = getattr(frame, "audio", None)
        if not audio or not isinstance(audio, bytes):
            return
        sample_rate = getattr(frame, "sample_rate", None) or 16000
        num_channels = getattr(frame, "num_channels", None) or 1
        self._current_duration_sec += _audio_duration_sec(audio, sample_rate, num_channels)

    async def process_frame(self, frame: Frame, direction: FrameDirection):
        await super().process_frame(frame, direction)

        if isinstance(frame, LLMFullResponseEndFrame):
            self._sync_context[KEY_LAST_TTS_DURATION_SEC] = self._current_duration_sec
            duration_sec = round(self._current_duration_sec, 3)
            # "이 TTS는 X초" — 합성 완료 시점에 확정되는 재생 길이 (모든 오디오 청크 누적값)
            ts_iso = datetime.now().isoformat(timespec="milliseconds")
            call_id = self._sync_context.get("_call_id", "")
            logger.info("tts_duration_known",
                        call=True,
                        call_id=call_id,
                        category="tts",
                        progress="tts",
                        duration_sec=duration_sec,
                        ts_iso=ts_iso,
                        note="이 TTS 재생 길이(초), 합성 완료 시점에 확정")
            event = self._sync_context.get(KEY_ON_TTS_COMPLETE)
            if isinstance(event, asyncio.Event):
                event.set()
                self._sync_context.pop(KEY_ON_TTS_COMPLETE, None)
                logger.info("tts_complete_notifier_signalled",
                           call=True,
                           call_id=call_id,
                           category="tts",
                           progress="tts",
                           duration_sec=duration_sec,
                           ts_iso=ts_iso,
                           note="TTS 해당 응답 출력 완료 → event.set() (Phase2 대기 해제)")
            self._current_duration_sec = 0.0
            self._expecting_first_audio = True  # 다음 응답의 첫 오디오 대기
            await self.push_frame(frame, direction)
            return

        # 응답별 첫 오디오 청크 수신 시점 (TTS 생성 첫 출력)
        audio = getattr(frame, "audio", None)
        if isinstance(audio, bytes) and audio and self._expecting_first_audio:
            logger.info("tts_first_audio_received",
                        call=True,
                        call_id=self._sync_context.get("_call_id", ""),
                        progress="tts",
                        ts_iso=datetime.now().isoformat(timespec="milliseconds"),
                        note="TTS 첫 오디오 청크 수신 시점")
            self._expecting_first_audio = False

        self._add_audio_duration(frame)
        await self.push_frame(frame, direction)
