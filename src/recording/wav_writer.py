"""
통화 녹음 WAV 저장.

- 저장 경로: RECORDINGS_DIR / {call_id} / mixed.wav (recordings API와 동일 규칙)
- 형식: 스테레오 16kHz 16bit PCM (채널0=발신자, 채널1=AI)
- call_id는 경로 조작 문자 제거 후 사용 (recordings 라우터와 동일)
"""

import os
import re
import struct
import wave
from pathlib import Path
from typing import List

import structlog

logger = structlog.get_logger(__name__)

RECORDINGS_DIR = Path(os.environ.get("RECORDINGS_DIR", "recordings"))
SAMPLE_RATE = 16000
NUM_CHANNELS = 2
SAMPLE_WIDTH = 2  # 16-bit


def _safe_call_id(call_id: str) -> str:
    """경로에 사용할 안전한 call_id (recordings 라우터와 동일)."""
    return re.sub(r"[^\w\-]", "", call_id)


def save_mixed_wav(
    call_id: str,
    user_chunks: List[bytes],
    ai_chunks: List[bytes],
    sample_rate: int = SAMPLE_RATE,
) -> Path:
    """
    발신자(user) / AI 오디오 청크를 스테레오 WAV로 저장.

    Args:
        call_id: 통화 ID (경로에 사용 시 sanitize됨)
        user_chunks: 발신자 PCM 청크 목록 (16bit mono)
        ai_chunks: AI(TTS) PCM 청크 목록 (16bit mono)
        sample_rate: 샘플레이트 (기본 16000)

    Returns:
        저장된 파일 경로 (Path)

    Raises:
        OSError: 디렉터리 생성/파일 쓰기 실패 시
    """
    safe_id = _safe_call_id(call_id)
    if not safe_id:
        raise ValueError("call_id is empty after sanitization")
    out_dir = RECORDINGS_DIR / safe_id
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / "mixed.wav"

    user_pcm = b"".join(user_chunks) if user_chunks else b""
    ai_pcm = b"".join(ai_chunks) if ai_chunks else b""

    # 16bit mono: 2 bytes per sample
    user_n = len(user_pcm) // 2
    ai_n = len(ai_pcm) // 2
    n_samples = max(user_n, ai_n)
    if n_samples == 0:
        logger.warning("recording_empty_pcm", call_id=call_id, note="no audio to write")
        # 빈 WAV라도 쓰면 API에서 404가 아니게 됨. 0프레임으로 최소 헤더만 씀.
        with wave.open(str(out_path), "wb") as wav:
            wav.setnchannels(NUM_CHANNELS)
            wav.setsampwidth(SAMPLE_WIDTH)
            wav.setframerate(sample_rate)
            wav.writeframes(b"")
        return out_path

    # bytes -> int16 리스트 (little-endian)
    def to_samples(b: bytes) -> List[int]:
        return list(
            int.from_bytes(b[i : i + 2], "little", signed=True)
            for i in range(0, len(b) - 1, 2)
        )

    user_samps = to_samples(user_pcm) if user_pcm else []
    ai_samps = to_samples(ai_pcm) if ai_pcm else []
    # 길이 맞추기 (짧은 쪽 0 패딩)
    user_samps.extend([0] * (n_samples - len(user_samps)))
    ai_samps.extend([0] * (n_samples - len(ai_samps)))

    # 스테레오 인터리브: L, R, L, R, ...
    frames = []
    for i in range(n_samples):
        frames.append(struct.pack("<hh", user_samps[i], ai_samps[i]))
    pcm_stereo = b"".join(frames)

    with wave.open(str(out_path), "wb") as wav:
        wav.setnchannels(NUM_CHANNELS)
        wav.setsampwidth(SAMPLE_WIDTH)
        wav.setframerate(sample_rate)
        wav.writeframes(pcm_stereo)

    logger.info(
        "recording_saved",
        call_id=call_id,
        path=str(out_path),
        samples=n_samples,
        duration_sec=round(n_samples / sample_rate, 2),
    )
    return out_path
