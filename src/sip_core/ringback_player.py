"""RingbackPlayer — Early Media 구간 동안 인사말(TTS) + 통화 연결음을 RTP로 스트리밍.

흐름:
    1. enabled_greeting: 인사말 텍스트 → Google TTS 스트림 → send_ai_audio() 1회
    2. enabled_ringback: 스케줄 할당이면 **사전 생성된** Suno MP3 또는 TTS WAV 파일을
       FFmpeg 등으로 PCM 16kHz로 디코드 후 send_ai_audio() 루프 (링 중 실시간 TTS 합성 없음)
    3. stop() 호출 시 루프 즉시 종료 (200 OK 또는 AI takeover)
"""

from __future__ import annotations

import asyncio
import audioop
import io
import os
import struct
import wave
from typing import TYPE_CHECKING

import structlog

if TYPE_CHECKING:
    from src.media.rtp_relay import RTPRelayWorker

logger = structlog.get_logger(__name__)

# PCM 청크 크기 (20ms @ 16kHz, 16-bit mono = 640 bytes)
_CHUNK_BYTES = 640
_CHUNK_DURATION_S = 0.02  # 20 ms


class RingbackPlayer:
    """18x 구간 동안 발신자에게 인사말+연결음을 RTP로 전송하는 플레이어."""

    def __init__(self) -> None:
        self._task: asyncio.Task | None = None
        self._stop_event = asyncio.Event()

    # ── 공개 API ─────────────────────────────────────────────────────────────

    async def start(self, rtp_worker: "RTPRelayWorker", owner: str, call_id: str) -> None:
        """Early media 스트리밍을 비동기 태스크로 시작한다."""
        self._stop_event.clear()
        self._task = asyncio.create_task(
            self._run(rtp_worker, owner, call_id),
            name=f"ringback_{call_id}",
        )
        logger.info("ringback_player_started", owner=owner, call_id=call_id)

    async def stop(self) -> None:
        """루프를 종료하고 태스크를 취소한다."""
        self._stop_event.set()
        if self._task and not self._task.done():
            self._task.cancel()
            try:
                await self._task
            except (asyncio.CancelledError, Exception):
                pass
        self._task = None
        logger.info("ringback_player_stopped")

    # ── 내부 실행 루프 ────────────────────────────────────────────────────────

    async def _run(self, rtp_worker: "RTPRelayWorker", owner: str, call_id: str) -> None:
        try:
            from src.services.ringback_service import (
                get_effective_ringback_settings_for_player,
                resolve_ringback_segment,
            )
            settings = get_effective_ringback_settings_for_player(owner)
            if not settings:
                logger.info("ringback_no_settings", owner=owner)
                return

            enabled_greeting = bool(settings.get("enabled_greeting"))
            enabled_ringback = bool(settings.get("enabled_ringback"))
            greeting_text = settings.get("greeting_text", "")
            seg = resolve_ringback_segment(owner)

            if not enabled_greeting and not enabled_ringback:
                logger.info("ringback_disabled", owner=owner)
                return

            # ① 인사말 TTS (1회)
            if enabled_greeting and greeting_text and not self._stop_event.is_set():
                await self._play_tts(rtp_worker, greeting_text, call_id)

            # ② 통화 연결음: 스케줄 할당(Suno MP3 또는 TTS 사전 렌더 WAV) → ringback_settings MP3 폴백
            if enabled_ringback and not self._stop_event.is_set():
                if seg.get("kind") == "mp3" and seg.get("path"):
                    logger.info(
                        "ringback_audio_file_selected",
                        owner=owner,
                        call_id=call_id,
                        source=seg.get("reason"),
                    )
                    await self._play_mp3_loop(rtp_worker, str(seg["path"]), call_id)
                else:
                    logger.info(
                        "ringback_segment_skipped",
                        owner=owner,
                        call_id=call_id,
                        kind=seg.get("kind"),
                        reason=seg.get("reason"),
                    )

        except asyncio.CancelledError:
            logger.info("ringback_task_cancelled", call_id=call_id)
        except Exception as e:
            logger.error("ringback_run_error", call_id=call_id, error=str(e), exc_info=True)

    # ── 인사말 TTS ────────────────────────────────────────────────────────────

    async def _play_tts(self, rtp_worker: "RTPRelayWorker", text: str, call_id: str) -> None:
        """텍스트를 Google TTS로 합성하여 RTP로 전송한다."""
        try:
            from src.ai_voicebot.ai_pipeline.tts_client import TTSClient
            from src.config.config_loader import load_config

            cfg = load_config()
            tts_cfg = getattr(cfg, "tts", None)
            tts_dict = tts_cfg.model_dump() if hasattr(tts_cfg, "model_dump") else (
                dict(tts_cfg) if tts_cfg else {}
            )

            tts = TTSClient(tts_dict)
            loop = asyncio.get_event_loop()

            logger.info("ringback_tts_start", call_id=call_id, chars=len(text))
            async for pcm_chunk in tts.synthesize_stream(text):
                if self._stop_event.is_set():
                    break
                if pcm_chunk:
                    await loop.run_in_executor(
                        None,
                        lambda c=pcm_chunk: rtp_worker.send_ai_audio(c, ringback_early_media=True),
                    )
                    await asyncio.sleep(0)  # yield

            logger.info("ringback_tts_done", call_id=call_id)
        except Exception as e:
            logger.error("ringback_tts_error", call_id=call_id, error=str(e), exc_info=True)

    # ── 연결음 MP3 루프 ───────────────────────────────────────────────────────

    async def _play_mp3_loop(self, rtp_worker: "RTPRelayWorker", mp3_path: str, call_id: str) -> None:
        """MP3/WAV 등 로컬 음원을 PCM 16kHz로 디코딩하여 반복 재생한다."""
        try:
            pcm_data = await asyncio.get_event_loop().run_in_executor(
                None, self._decode_media_to_pcm16k, mp3_path
            )
        except Exception as e:
            logger.error("ringback_mp3_decode_error", path=mp3_path, error=str(e), exc_info=True)
            return

        if not pcm_data:
            logger.warning("ringback_mp3_empty", path=mp3_path)
            return

        logger.info("ringback_mp3_loop_start", call_id=call_id, pcm_bytes=len(pcm_data))
        loop = asyncio.get_event_loop()

        while not self._stop_event.is_set():
            offset = 0
            while offset < len(pcm_data) and not self._stop_event.is_set():
                chunk = pcm_data[offset: offset + _CHUNK_BYTES]
                if not chunk:
                    break
                if len(chunk) < _CHUNK_BYTES:
                    chunk = chunk + b"\x00" * (_CHUNK_BYTES - len(chunk))
                await loop.run_in_executor(
                    None,
                    lambda c=chunk: rtp_worker.send_ai_audio(c, ringback_early_media=True),
                )
                offset += _CHUNK_BYTES
                await asyncio.sleep(_CHUNK_DURATION_S)

        logger.info("ringback_mp3_loop_stopped", call_id=call_id)

    # ── MP3 → PCM 16kHz 변환 ─────────────────────────────────────────────────

    @staticmethod
    def _decode_media_to_pcm16k(media_path: str) -> bytes:
        """MP3/WAV 등 → 16kHz, mono, 16-bit PCM (LINEAR16).

        FFmpeg가 있으면 우선 사용(WAV·MP3 공통). MP3만 pydub 폴백.
        """
        try:
            return _decode_with_ffmpeg(media_path)
        except Exception as e:
            logger.warning("ringback_ffmpeg_failed", path=media_path, error=str(e))

        if str(media_path).lower().endswith(".mp3"):
            try:
                return _decode_with_pydub(media_path)
            except Exception as e2:
                logger.warning("ringback_pydub_failed", error=str(e2))

        return b""


# ── 변환 헬퍼 ──────────────────────────────────────────────────────────────────

def _decode_with_ffmpeg(mp3_path: str) -> bytes:
    """ffmpeg subprocess로 MP3 → raw PCM 16kHz/mono/s16le 변환."""
    import subprocess

    result = subprocess.run(
        [
            "ffmpeg", "-y",
            "-i", mp3_path,
            "-ar", "16000",
            "-ac", "1",
            "-f", "s16le",
            "pipe:1",
        ],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=30,
    )
    if result.returncode != 0:
        raise RuntimeError(f"ffmpeg 변환 실패: {result.stderr[-200:]}")
    return result.stdout


def _decode_with_pydub(mp3_path: str) -> bytes:
    """pydub으로 MP3 → PCM 16kHz/mono/16-bit 변환 (ffmpeg 백엔드 필요)."""
    from pydub import AudioSegment

    audio = AudioSegment.from_mp3(mp3_path)
    audio = audio.set_frame_rate(16000).set_channels(1).set_sample_width(2)
    return audio.raw_data
