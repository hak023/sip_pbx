"""
WebRTC AEC (Acoustic Echo Cancellation) 래퍼.

선택 의존성: aec-audio-processing (pip install aec-audio-processing)
- 미설치 시 AEC 비활성화, 설치 시 far-end(reverse) + near-end 처리로 에코 제거.
- 16kHz 모노, 10ms(320 bytes) 프레임.
"""

from typing import Any, Optional

_AudioProcessor: Any = None
try:
    from aec_audio_processing import AudioProcessor as _AudioProcessor
except ImportError:
    _AudioProcessor = None


# 10ms @ 16kHz mono = 160 samples = 320 bytes
AEC_FRAME_BYTES = 320


def create_aec_processor(
    sample_rate: int = 16000,
    channels: int = 1,
    stream_delay_ms: int = 50,
) -> Optional["AECProcessor"]:
    """AEC 프로세서 생성. 라이브러리 미설치 시 None 반환."""
    if _AudioProcessor is None:
        return None
    try:
        ap = _AudioProcessor(enable_aec=True, enable_ns=False, enable_agc=False)
        ap.set_stream_format(sample_rate, channels)
        ap.set_reverse_stream_format(sample_rate, channels)
        ap.set_stream_delay(stream_delay_ms)
        return AECProcessor(ap)
    except Exception:
        return None


class AECProcessor:
    """WebRTC AEC 래퍼: far-end(reverse) 투입 후 near-end 처리."""

    def __init__(self, ap: Any):
        self._ap = ap

    def feed_reverse_stream(self, far_end_10ms: bytes) -> None:
        """TTS(스피커) 10ms 청크를 AEC 참조로 넣음. len(far_end_10ms) == 320 권장."""
        if len(far_end_10ms) < AEC_FRAME_BYTES:
            return
        chunk = far_end_10ms[:AEC_FRAME_BYTES]
        if hasattr(self._ap, "process_reverse_stream"):
            self._ap.process_reverse_stream(chunk)
        else:
            # 일부 API는 process_stream(near, far) 형태일 수 있음
            pass

    def process_stream(self, near_end_10ms: bytes) -> bytes:
        """마이크 10ms 청크를 에코 제거 처리. 320 bytes 입력 → 320 bytes 출력."""
        if len(near_end_10ms) < AEC_FRAME_BYTES:
            return near_end_10ms
        chunk = near_end_10ms[:AEC_FRAME_BYTES]
        out = self._ap.process_stream(chunk)
        if out and len(out) >= AEC_FRAME_BYTES:
            return out[:AEC_FRAME_BYTES]
        return chunk
