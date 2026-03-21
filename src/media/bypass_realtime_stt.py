"""
일반 통화(유저간 통화) 실시간 STT.

Bypass 모드에서 caller/callee RTP 오디오를 받아 스트리밍 STT로 전사하고,
콜백을 통해 대시보드 등으로 전달(stt_transcript 이벤트)할 수 있게 함.
WebSocket 서버가 이 모듈의 broadcast 콜백을 등록해 실시간 대화를 클라이언트에 전송하면 됨.
"""

import asyncio
import queue
import threading
import time
from typing import Callable, Optional

from src.common.logger import get_async_logger

logger = get_async_logger(__name__)

# 8kHz telephony (G.711)
SAMPLE_RATE_HZ = 8000
# 100ms 단위로 STT에 전달 (권장)
CHUNK_DURATION_MS = 100
BYTES_PER_MS = (SAMPLE_RATE_HZ * 2) // 1000  # 16-bit = 2 bytes per sample
CHUNK_BYTES = (CHUNK_DURATION_MS * BYTES_PER_MS)  # 1600


def _decode_pcmu(payload: bytes) -> bytes:
    """G.711 PCMU (μ-law) → 16-bit linear PCM (8kHz)."""
    try:
        import audioop
        return audioop.ulaw2lin(payload, 2)
    except Exception as e:
        logger.debug("bypass_stt_pcmu_decode_error", error=str(e))
        return b""


def _decode_pcma(payload: bytes) -> bytes:
    """G.711 PCMA (A-law) → 16-bit linear PCM (8kHz)."""
    try:
        import audioop
        return audioop.alaw2lin(payload, 2)
    except Exception as e:
        logger.debug("bypass_stt_pcma_decode_error", error=str(e))
        return b""


def decode_rtp_payload(payload: bytes, codec: str) -> bytes:
    """RTP 페이로드를 16-bit linear PCM으로 디코딩."""
    if not payload:
        return b""
    codec_upper = (codec or "PCMU").upper()
    if codec_upper == "PCMU":
        return _decode_pcmu(payload)
    if codec_upper == "PCMA":
        return _decode_pcma(payload)
    return b""


# 전역 브로드캐스트 콜백 (WebSocket 서버 등에서 등록)
_broadcast_callback: Optional[Callable[[str, str, bool, str], None]] = None


def set_broadcast_callback(cb: Optional[Callable[[str, str, bool, str], None]]) -> None:
    """
    실시간 STT 결과를 대시보드 등으로 보낼 콜백 등록.
    시그니처: (call_id: str, text: str, is_final: bool, channel: 'caller'|'callee') -> None
    """
    global _broadcast_callback
    _broadcast_callback = cb


def get_broadcast_callback() -> Optional[Callable[[str, str, bool, str], None]]:
    return _broadcast_callback


def _invoke_broadcast(call_id: str, text: str, is_final: bool, channel: str) -> None:
    cb = get_broadcast_callback()
    if not cb or not text.strip():
        return
    try:
        cb(call_id, text.strip(), is_final, channel)
    except Exception as e:
        logger.warning("bypass_stt_broadcast_error", call_id=call_id, error=str(e))
    # call_data_record + 대시보드 call_debug_trace (최종 구간만, 로그 과다 방지)
    if is_final and text.strip():
        try:
            from src.common.call_data_record_logger import log_call_data

            t = text.strip()
            log_call_data(
                call_id,
                "stt",
                "stt_bypass_final",
                speaker=channel,
                text=t[:4000],
                text_len=len(t),
            )
        except Exception:
            pass


class _StreamSession:
    """단일 (call_id, channel) 스트리밍 STT 세션."""

    def __init__(self, call_id: str, channel: str) -> None:
        self.call_id = call_id
        self.channel = channel
        self._queue: queue.Queue = queue.Queue()
        self._thread: Optional[threading.Thread] = None
        self._stop = threading.Event()

    def put(self, pcm_chunk: bytes) -> None:
        if pcm_chunk:
            self._queue.put(pcm_chunk)

    def stop(self) -> None:
        self._stop.set()
        self._queue.put(None)  # sentinel

    def _run_stream(self) -> None:
        try:
            from google.cloud import speech
        except ImportError:
            logger.warning("bypass_stt_google_import_failed", call_id=self.call_id, channel=self.channel)
            return
        try:
            client = speech.SpeechClient()
        except Exception as e:
            logger.warning("bypass_stt_speech_client_failed", call_id=self.call_id, error=str(e))
            return

        config = speech.StreamingRecognitionConfig(
            config=speech.RecognitionConfig(
                encoding=speech.RecognitionConfig.AudioEncoding.LINEAR16,
                sample_rate_hertz=SAMPLE_RATE_HZ,
                language_code="ko-KR",
                model="telephony",
            ),
            interim_results=True,
        )

        def request_generator():
            yield speech.StreamingRecognizeRequest(streaming_config=config)
            while not self._stop.is_set():
                try:
                    chunk = self._queue.get(timeout=0.5)
                    if chunk is None:
                        break
                    if chunk:
                        yield speech.StreamingRecognizeRequest(audio_content=chunk)
                except queue.Empty:
                    continue

        try:
            responses = client.streaming_recognize(request_generator())
            for r in responses:
                if self._stop.is_set():
                    break
                if not r.results:
                    continue
                for result in r.results:
                    if not result.alternatives:
                        continue
                    text = result.alternatives[0].transcript or ""
                    is_final = result.is_final
                    _invoke_broadcast(self.call_id, text, is_final, self.channel)
        except Exception as e:
            if not self._stop.is_set():
                logger.info("bypass_stt_stream_ended",
                            call_id=self.call_id, channel=self.channel, error=str(e))
        finally:
            self._stop.set()

    def start(self) -> None:
        if self._thread is not None and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._run_stream, daemon=True)
        self._thread.start()

    def join(self, timeout: float = 2.0) -> None:
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=timeout)


class BypassRealtimeSTT:
    """
    일반 통화(bypass) 실시간 STT 서비스.
    RTP Relay에서 오디오를 넘기면 (call_id, channel별) 버퍼링 후 Google 스트리밍 STT로 전사하고
    등록된 broadcast 콜백으로 결과를 전달.
    """

    def __init__(self) -> None:
        self._sessions: dict[tuple[str, str], _StreamSession] = {}
        self._lock = threading.Lock()
        self._buffers: dict[tuple[str, str], bytearray] = {}
        self._enabled = True

    def set_enabled(self, enabled: bool) -> None:
        self._enabled = enabled

    def feed_audio(self, call_id: str, channel: str, payload: bytes, codec: str = "PCMU") -> None:
        if not self._enabled or not payload or not call_id or channel not in ("caller", "callee"):
            return
        pcm = decode_rtp_payload(payload, codec)
        if not pcm:
            return
        key = (call_id, channel)
        with self._lock:
            buf = self._buffers.get(key)
            if buf is None:
                buf = bytearray()
                self._buffers[key] = buf
            buf.extend(pcm)
            while len(buf) >= CHUNK_BYTES:
                chunk = bytes(buf[:CHUNK_BYTES])
                del buf[:CHUNK_BYTES]
                session = self._sessions.get(key)
                if session is None:
                    session = _StreamSession(call_id, channel)
                    self._sessions[key] = session
                    session.start()
                session.put(chunk)

    def end_call(self, call_id: str) -> None:
        """통화 종료 시 해당 call_id의 모든 채널 스트림 정리."""
        with self._lock:
            to_stop = [k for k in self._sessions if k[0] == call_id]
            for key in to_stop:
                self._sessions[key].stop()
                self._sessions[key].join()
                del self._sessions[key]
                self._buffers.pop(key, None)


# 싱글톤 (RTP Relay에서 주입하거나 이 인스턴스 사용)
_bypass_stt: Optional[BypassRealtimeSTT] = None


def get_bypass_realtime_stt() -> BypassRealtimeSTT:
    global _bypass_stt
    if _bypass_stt is None:
        _bypass_stt = BypassRealtimeSTT()
    return _bypass_stt
