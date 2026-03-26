"""
Google Cloud Speech-to-Text gRPC Streaming Client

실시간 음성 → 텍스트 변환

[중요] 블로킹 gRPC 스트리밍을 ThreadPoolExecutor로 분리해 asyncio 이벤트 루프를
블로킹하지 않도록 구현되어 있습니다.
"""

import queue
import asyncio
import threading
from typing import Optional, Callable, Any
import structlog

from google.cloud import speech

logger = structlog.get_logger(__name__)


class STTClient:
    """
    Google Cloud Speech-to-Text gRPC Streaming Client

    블로킹 gRPC 스트리밍을 별도 스레드에서 실행하고,
    결과 콜백만 asyncio 이벤트 루프로 전달합니다.
    """

    def __init__(self, config: dict):
        """
        Args:
            config: STT 설정
                - model: "telephony" | "latest_long"
                - language_code: "ko-KR"
                - sample_rate: 16000
                - enable_enhanced: True
                - enable_automatic_punctuation: True
        """
        self.config = config
        self.client = speech.SpeechClient()

        self.recognition_config = speech.RecognitionConfig(
            encoding=speech.RecognitionConfig.AudioEncoding.LINEAR16,
            sample_rate_hertz=config.get("sample_rate", 16000),
            language_code=config.get("language_code", "ko-KR"),
            model=config.get("model", "telephony"),
            use_enhanced=config.get("enable_enhanced", True),
            enable_automatic_punctuation=config.get("enable_automatic_punctuation", True),
            enable_word_time_offsets=config.get("enable_word_time_offsets", False),
        )

        self.streaming_config = speech.StreamingRecognitionConfig(
            config=self.recognition_config,
            interim_results=True,
            single_utterance=False,
        )

        # 스레드에서 이벤트 루프로 오디오를 전달하는 스레드 안전 큐
        self._audio_queue: Optional[queue.Queue] = None
        self.result_callback: Optional[Callable] = None

        # 스레드 참조 및 이벤트 루프 참조 (스레드→async 콜백용)
        self._thread: Optional[threading.Thread] = None
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._running = False

        # 통계
        self.total_requests = 0
        self.total_results = 0

        logger.info("STTClient initialized",
                   model=config.get("model"),
                   language=config.get("language_code"),
                   sample_rate=config.get("sample_rate"))

    async def start_stream(self, result_callback: Callable[[str, bool], Any]):
        """
        스트리밍 인식 시작 (블로킹 gRPC를 별도 스레드에서 실행).

        Args:
            result_callback: async def callback(text: str, is_final: bool)
        """
        if self._running:
            logger.warning("STT stream already running")
            return

        self._running = True
        self.result_callback = result_callback
        self._loop = asyncio.get_event_loop()
        # maxsize=200 : 200ms 이상의 오디오 버퍼
        self._audio_queue = queue.Queue(maxsize=200)

        # 블로킹 gRPC 스트리밍을 daemon 스레드에서 실행해 이벤트 루프를 보호
        self._thread = threading.Thread(
            target=self._blocking_recognize,
            name="stt-stream",
            daemon=True,
        )
        self._thread.start()
        logger.info("STT streaming started")

    async def stop_stream(self):
        """스트리밍 인식 중지"""
        self._running = False

        # 종료 신호 전송
        if self._audio_queue is not None:
            try:
                self._audio_queue.put_nowait(None)
            except queue.Full:
                pass

        # 스레드 종료 대기 (최대 5초)
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=5.0)
            if self._thread.is_alive():
                logger.warning("STT thread did not stop within timeout")

        logger.info("STT streaming stopped",
                   total_requests=self.total_requests,
                   total_results=self.total_results)

    async def send_audio(self, audio_data: bytes):
        """
        오디오 데이터를 STT 스레드로 전달 (논블로킹 queue.put_nowait 사용).

        Args:
            audio_data: 16-bit PCM audio bytes
        """
        if not self._running or self._audio_queue is None:
            logger.debug("STT not running, audio dropped")
            return

        try:
            self._audio_queue.put_nowait(audio_data)
            self.total_requests += 1
        except queue.Full:
            logger.warning("STT audio queue full, frame dropped")

    # -------------------------------------------------------------------------
    # 스레드 내부 구현 (이벤트 루프를 블로킹하지 않음)
    # -------------------------------------------------------------------------

    def _request_generator(self):
        """
        STT 요청 제너레이터 (스레드에서 실행).
        queue.Queue.get(timeout) 으로 블로킹 대기 → 이벤트 루프와 분리됨.
        """
        while self._running:
            try:
                audio_data = self._audio_queue.get(timeout=0.05)
            except queue.Empty:
                continue

            if audio_data is None:
                # 종료 신호
                break

            yield speech.StreamingRecognizeRequest(audio_content=audio_data)

    def _blocking_recognize(self):
        """
        블로킹 gRPC 스트리밍 인식 루프 (별도 스레드에서 실행).
        결과는 asyncio.run_coroutine_threadsafe로 이벤트 루프에 전달.
        """
        try:
            requests = self._request_generator()
            responses = self.client.streaming_recognize(
                self.streaming_config, requests
            )

            for response in responses:
                if not self._running:
                    break

                if not response.results:
                    continue

                result = response.results[0]
                if not result.alternatives:
                    continue

                transcript = result.alternatives[0].transcript
                is_final = result.is_final
                self.total_results += 1

                logger.debug("STT result",
                           text=transcript,
                           is_final=is_final)

                # 이벤트 루프로 콜백 전달 (스레드 안전)
                if self.result_callback and self._loop and self._loop.is_running():
                    try:
                        if asyncio.iscoroutinefunction(self.result_callback):
                            future = asyncio.run_coroutine_threadsafe(
                                self.result_callback(transcript, is_final),
                                self._loop,
                            )
                            # 콜백 완료를 최대 2초 대기 (이벤트 루프 지연 방지)
                            future.result(timeout=2.0)
                        else:
                            self._loop.call_soon_threadsafe(
                                self.result_callback, transcript, is_final
                            )
                    except Exception as cb_err:
                        logger.error("STT callback error", error=str(cb_err))

        except Exception as e:
            logger.error("STT streaming error", error=str(e), exc_info=True)
        finally:
            self._running = False
            logger.info("STT streaming ended")

    def get_stats(self) -> dict:
        """STT 통계 반환"""
        return {
            "total_requests": self.total_requests,
            "total_results": self.total_results,
            "is_running": self._running,
            "queue_size": self._audio_queue.qsize() if self._audio_queue else 0,
        }
