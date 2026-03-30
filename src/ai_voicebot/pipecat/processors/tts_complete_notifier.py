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

from pipecat.frames.frames import Frame, LLMFullResponseEndFrame, LLMFullResponseStartFrame
from pipecat.processors.frame_processor import FrameDirection, FrameProcessor

logger = structlog.get_logger(__name__)

# 공유 컨텍스트 키 (RAGLLMProcessor와 동일 문자열 사용)
KEY_ON_TTS_COMPLETE = "on_tts_complete"
KEY_LAST_TTS_DURATION_SEC = "last_tts_duration_sec"
KEY_LAST_TTS_FRAME_COUNT = "last_tts_audio_frame_count"  # tts_rtp_duration_mismatch 로그 강화용

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
        self._audio_frame_count: int = 0  # 이번 응답에서 누적한 오디오 프레임 수 (디버깅)

    def _add_audio_duration(self, frame: Frame) -> None:
        """오디오 프레임이면 재생 길이 누적 (OutputAudioRawFrame, TTSAudioRawFrame 등)."""
        audio = getattr(frame, "audio", None)
        if not audio or not isinstance(audio, bytes):
            return
        self._audio_frame_count += 1
        sample_rate = getattr(frame, "sample_rate", None) or 16000
        num_channels = getattr(frame, "num_channels", None) or 1
        duration_ms = _audio_duration_sec(audio, sample_rate, num_channels) * 1000
        self._current_duration_sec += _audio_duration_sec(audio, sample_rate, num_channels)
        
        # 📌 프레임 타입·길이 추적 (Notifier vs Output 불일치 원인 파악)
        if self._audio_frame_count <= 5 or self._audio_frame_count % 50 == 0:
            call_id = self._sync_context.get("_call_id", "")
            logger.debug("notifier_audio_frame_detail",
                        call_id=call_id,
                        frame_index=self._audio_frame_count,
                        frame_type=type(frame).__name__,
                        audio_len=len(audio),
                        duration_ms=round(duration_ms, 2),
                        sample_rate=sample_rate,
                        note="Notifier 프레임 타입·길이 추적 (Output 불일치 원인 파악)")

    async def process_frame(self, frame: Frame, direction: FrameDirection):
        await super().process_frame(frame, direction)

        # Output과 동일하게 "응답 1건" 구간을 StartFrame ~ EndFrame으로 정의 (리셋 시점 통일)
        if isinstance(frame, LLMFullResponseStartFrame):
            self._current_duration_sec = 0.0
            self._audio_frame_count = 0
            self._expecting_first_audio = True
            await self.push_frame(frame, direction)
            return

        if isinstance(frame, LLMFullResponseEndFrame):
            self._sync_context[KEY_LAST_TTS_DURATION_SEC] = self._current_duration_sec
            self._sync_context[KEY_LAST_TTS_FRAME_COUNT] = self._audio_frame_count
            duration_sec = round(self._current_duration_sec, 3)
            ts_iso = datetime.now().isoformat(timespec="milliseconds")
            call_id = self._sync_context.get("_call_id", "")
            # EndFrame 처리 시점: 이 응답에서 받은 오디오 프레임 수·누적 초 (원인 파악용)
            logger.info("notifier_endframe_processed",
                        call=True,
                        call_id=call_id,
                        category="tts",
                        progress="tts",
                        duration_sec=duration_sec,
                        audio_frame_count=self._audio_frame_count,
                        ts_iso=ts_iso,
                        note="Notifier가 EndFrame 수신 시점 — 이 응답에서 받은 오디오 프레임 수·누적 재생 길이")
            # Phase1 인사말 등 짧은 재생(예: 1.75s) 시 끊김 가능성 — InterruptionFrame으로 TTS 조기 종료됐을 수 있음
            if duration_sec > 0 and duration_sec < 2.5 and self._audio_frame_count < 30:
                logger.warning("tts_duration_short_possible_interrupt",
                              call_id=call_id,
                              duration_sec=duration_sec,
                              audio_frame_count=self._audio_frame_count,
                              note="TTS 재생이 예상보다 짧음 — InterruptionFrame(barge-in)으로 조기 종료됐을 가능성, barge_in_suppress_blocked 로그 확인")
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
            self._audio_frame_count = 0
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
