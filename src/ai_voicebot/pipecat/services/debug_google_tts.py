"""
Google / Gemini TTS 서비스 래퍼 (오디오 버퍼링 + API 호출 로깅)

스트리밍 API는 여러 청크를 비동기적으로 반환하므로 청크 간 지연이
RTP 타이밍에 영향을 줄 수 있다.
→ 모든 오디오 청크를 먼저 수집한 뒤 한꺼번에 yield하여
   RTP 스케줄러가 연속적으로 20ms 프레임을 소비할 수 있게 한다.

클래스:
  DebugGoogleTTSService  — Chirp 3 HD 스트리밍 (16kHz 출력)
  DebugGeminiTTSService  — Gemini 2.5 Flash/Pro TTS 스트리밍 (24kHz 출력)
                           RTPPacketBuilder가 어떤 샘플레이트든 8kHz로 리샘플링하므로 호환됨.
"""

import time
from typing import AsyncGenerator, List

from pipecat.services.google.tts import GoogleTTSService, GeminiTTSService
from pipecat.frames.frames import Frame, TTSAudioRawFrame, TTSStartedFrame, TTSStoppedFrame
import structlog

logger = structlog.get_logger(__name__)


def _collect_and_yield_tts(service_name: str):
    """
    TTS 스트리밍 래퍼 공통 로직을 반환하는 데코레이터 팩토리.

    run_tts 내부에서 super().run_tts() 를 실행해 모든 오디오 프레임을
    수집한 뒤 일괄 yield한다.
    """
    pass  # 각 클래스에서 직접 구현 (super() 바인딩 문제 회피)


class DebugGoogleTTSService(GoogleTTSService):
    """Chirp 3 HD TTS — 오디오 전체를 수집 후 일괄 yield (스트리밍 갭 방지)."""

    def __init__(self, call_id: str = "", **kwargs):
        super().__init__(**kwargs)
        self._call_id = call_id
        self._api_call_count = 0

    async def run_tts(self, text: str, context_id: str = "") -> AsyncGenerator[Frame, None]:
        self._api_call_count += 1
        call_num = self._api_call_count

        logger.info("google_tts_api_call",
                     call_id=self._call_id,
                     progress="tts",
                     category="tts",
                     api_call_num=call_num,
                     text_len=len(text),
                     text_preview=text[:100] if text else "",
                     note="Chirp3 HD TTS API 호출 (스트리밍 → 일괄 수집 후 yield)")

        t0 = time.perf_counter()
        collected_frames: List[Frame] = []
        total_audio_bytes = 0
        audio_frame_count = 0

        async for frame in super().run_tts(text, context_id):
            audio = getattr(frame, "audio", None)
            if isinstance(audio, bytes) and audio:
                audio_frame_count += 1
                total_audio_bytes += len(audio)
            collected_frames.append(frame)

        elapsed_ms = (time.perf_counter() - t0) * 1000
        # Chirp3 HD: 16kHz, 16-bit (2 bytes/sample) → bytes_per_sec = 16000 * 2 = 32000
        duration_sec = round(total_audio_bytes / 32000, 3) if total_audio_bytes > 0 else 0

        logger.info("google_tts_api_complete",
                     call_id=self._call_id,
                     progress="tts",
                     category="tts",
                     api_call_num=call_num,
                     frames_generated=audio_frame_count,
                     total_audio_bytes=total_audio_bytes,
                     duration_sec=duration_sec,
                     api_elapsed_ms=round(elapsed_ms, 1),
                     note="Chirp3 HD TTS 수집 완료 — 일괄 yield 시작 (스트리밍 갭 제거)")

        for frame in collected_frames:
            yield frame


class DebugGeminiTTSService(GeminiTTSService):
    """Gemini 2.5 Flash/Pro TTS — 오디오 전체를 수집 후 일괄 yield (스트리밍 갭 방지).

    Gemini TTS는 24kHz PCM을 출력한다.
    RTPPacketBuilder.build_packets()가 입력 sample_rate를 받아 8kHz로 리샘플링하므로
    파이프라인 변경 없이 그대로 연결 가능하다.
    """

    # Gemini TTS 고정 출력 샘플레이트 (Google 공식 spec)
    GEMINI_SAMPLE_RATE = 24000

    def __init__(self, call_id: str = "", **kwargs):
        super().__init__(**kwargs)
        self._call_id = call_id
        self._api_call_count = 0

    async def run_tts(self, text: str, context_id: str = "") -> AsyncGenerator[Frame, None]:
        self._api_call_count += 1
        call_num = self._api_call_count

        logger.info("gemini_tts_api_call",
                     call_id=self._call_id,
                     progress="tts",
                     category="tts",
                     api_call_num=call_num,
                     text_len=len(text),
                     text_preview=text[:100] if text else "",
                     note="Gemini TTS API 호출 (24kHz 스트리밍 → 일괄 수집 후 yield)")

        t0 = time.perf_counter()
        collected_frames: List[Frame] = []
        total_audio_bytes = 0
        audio_frame_count = 0

        async for frame in super().run_tts(text, context_id):
            audio = getattr(frame, "audio", None)
            if isinstance(audio, bytes) and audio:
                audio_frame_count += 1
                total_audio_bytes += len(audio)
            collected_frames.append(frame)

        elapsed_ms = (time.perf_counter() - t0) * 1000
        # Gemini TTS: 24kHz, 16-bit (2 bytes/sample) → bytes_per_sec = 24000 * 2 = 48000
        duration_sec = round(total_audio_bytes / 48000, 3) if total_audio_bytes > 0 else 0

        logger.info("gemini_tts_api_complete",
                     call_id=self._call_id,
                     progress="tts",
                     category="tts",
                     api_call_num=call_num,
                     frames_generated=audio_frame_count,
                     total_audio_bytes=total_audio_bytes,
                     duration_sec=duration_sec,
                     api_elapsed_ms=round(elapsed_ms, 1),
                     sample_rate=self.GEMINI_SAMPLE_RATE,
                     note="Gemini TTS 수집 완료 — 일괄 yield 시작 (24kHz → RTP에서 8kHz 리샘플링)")

        for frame in collected_frames:
            yield frame
