"""
Google Cloud Speech-to-Text gRPC Streaming Client

실시간 음성 → 텍스트 변환
"""

from google.cloud import speech
import asyncio
from typing import Optional, Callable, Any
import structlog

logger = structlog.get_logger(__name__)


class STTClient:
    """
    Google Cloud Speech-to-Text gRPC Streaming Client
    
    실시간 음성 → 텍스트 변환을 제공합니다.
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
        
        # 인식 설정
        self.recognition_config = speech.RecognitionConfig(
            encoding=speech.RecognitionConfig.AudioEncoding.LINEAR16,
            sample_rate_hertz=config.get("sample_rate", 16000),
            language_code=config.get("language_code", "ko-KR"),
            model=config.get("model", "telephony"),
            use_enhanced=config.get("enable_enhanced", True),
            enable_automatic_punctuation=config.get("enable_automatic_punctuation", True),
            enable_word_time_offsets=config.get("enable_word_time_offsets", False),
        )
        
        # 스트리밍 설정
        self.streaming_config = speech.StreamingRecognitionConfig(
            config=self.recognition_config,
            interim_results=True,  # 중간 결과
            single_utterance=False,  # 연속 인식
        )
        
        # 스트리밍 상태
        self.audio_queue: Optional[asyncio.Queue] = None
        self.result_callback: Optional[Callable] = None
        self._streaming_task: Optional[asyncio.Task] = None
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
        스트리밍 인식 시작
        
        Args:
            result_callback: async def callback(text: str, is_final: bool)
        """
        if self._running:
            logger.warning("STT stream already running")
            return
        
        self._running = True
        self.result_callback = result_callback
        self.audio_queue = asyncio.Queue(maxsize=100)
        
        self._streaming_task = asyncio.create_task(self._streaming_recognize())
        logger.info("STT streaming started")
    
    async def stop_stream(self):
        """스트리밍 인식 중지"""
        self._running = False
        
        if self.audio_queue:
            await self.audio_queue.put(None)  # 종료 신호
        
        if self._streaming_task:
            try:
                await asyncio.wait_for(self._streaming_task, timeout=5.0)
            except asyncio.TimeoutError:
                logger.warning("STT stream stop timeout, cancelling")
                self._streaming_task.cancel()
                try:
                    await self._streaming_task
                except asyncio.CancelledError:
                    pass
        
        logger.info("STT streaming stopped",
                   total_requests=self.total_requests,
                   total_results=self.total_results)
    
    async def send_audio(self, audio_data: bytes):
        """
        오디오 데이터를 STT로 전송
        
        Args:
            audio_data: 16-bit PCM audio bytes
        """
        if not self._running or not self.audio_queue:
            logger.debug("STT not running, audio dropped")
            return
        
        try:
            self.audio_queue.put_nowait(audio_data)
            self.total_requests += 1
        except asyncio.QueueFull:
            logger.warning("STT audio queue full, frame dropped")
    
    async def _streaming_recognize(self):
        """스트리밍 인식 메인 루프"""
        try:
            # 요청 생성기 (오디오만 포함)
            requests = self._request_generator()
            
            # gRPC 스트리밍 호출
            # ✅ streaming_config와 requests를 별도 파라미터로 전달 (Google API 공식 사용법)
            responses = self.client.streaming_recognize(self.streaming_config, requests)
            
            # 응답 처리
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
                
                # 콜백 호출
                if self.result_callback:
                    try:
                        if asyncio.iscoroutinefunction(self.result_callback):
                            await self.result_callback(transcript, is_final)
                        else:
                            self.result_callback(transcript, is_final)
                    except Exception as e:
                        logger.error("STT callback error", error=str(e), exc_info=True)
                
                self.total_results += 1
                logger.debug("STT result", 
                           text=transcript[:50] if len(transcript) > 50 else transcript,
                           is_final=is_final)
                
        except Exception as e:
            logger.error("STT streaming error", error=str(e), exc_info=True)
        finally:
            self._running = False
            logger.info("STT streaming ended")
    
    def _request_generator(self):
        """
        STT 요청 생성기 (동기 generator)
        
        Google Cloud STT는 동기 generator를 요구합니다.
        streaming_config는 streaming_recognize() 호출 시 별도 파라미터로 전달되므로
        여기서는 오디오 데이터만 포함합니다.
        """
        # 오디오 데이터만 스트리밍 (첫 번째 요청에 config 포함하지 않음)
        while self._running:
            try:
                # asyncio.Queue를 동기적으로 사용
                # 짧은 타임아웃으로 주기적으로 체크
                try:
                    audio_data = self.audio_queue.get_nowait() if self.audio_queue else None
                except asyncio.QueueEmpty:
                    # 큐가 비었으면 짧은 대기
                    import time
                    time.sleep(0.01)
                    continue
                
                if audio_data is None:
                    # 종료 신호
                    break
                
                yield speech.StreamingRecognizeRequest(
                    audio_content=audio_data
                )
                
            except Exception as e:
                logger.error("Request generator error", error=str(e))
                break
    
    def get_stats(self) -> dict:
        """STT 통계 반환"""
        return {
            "total_requests": self.total_requests,
            "total_results": self.total_results,
            "is_running": self._running,
            "queue_size": self.audio_queue.qsize() if self.audio_queue else 0,
        }

