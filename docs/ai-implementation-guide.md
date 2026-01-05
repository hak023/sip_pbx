# AI 컴포넌트 구현 가이드

## 📋 문서 정보

이 문서는 AI 아키텍처 문서에서 인터페이스만 정의된 8개 컴포넌트의 상세한 구현 가이드를 제공합니다.

**대상 컴포넌트:**
1. Audio Buffer & Jitter ✅
2. VAD Detector ✅
3. STT Client (Google gRPC)
4. TTS Client (Google gRPC)
5. LLM Client (Gemini)
6. RAG Engine
7. Call Recorder
8. Knowledge Extractor

---

## 1. Audio Buffer & Jitter ✅

### 1.1 책임 (Responsibility)
- RTP 패킷 (UDP) → gRPC 스트림 (TCP) 변환
- Jitter 버퍼링 (20-60ms)
- 패킷 순서 재정렬
- 샘플레이트 변환 (8kHz → 16kHz)

### 1.2 완전한 구현

파일 위치: `src/ai_voicebot/audio_buffer.py`

```python
import asyncio
import audioop
from collections import deque
from dataclasses import dataclass
from typing import Optional
import structlog

logger = structlog.get_logger(__name__)


@dataclass
class AudioFrame:
    """오디오 프레임 데이터"""
    sequence: int
    timestamp: int
    payload: bytes
    sample_rate: int = 8000


class AudioBuffer:
    """
    RTP 패킷을 버퍼링하고 gRPC 스트리밍을 위해 변환합니다.
    
    Features:
    - Jitter buffering (패킷 지연 보정)
    - Packet reordering (순서 재정렬)
    - Sample rate conversion (8kHz → 16kHz)
    - Packet loss detection
    """
    
    def __init__(
        self, 
        jitter_buffer_ms: int = 60,
        max_buffer_size: int = 100,
        target_sample_rate: int = 16000
    ):
        self.jitter_buffer_ms = jitter_buffer_ms
        self.max_buffer_size = max_buffer_size
        self.target_sample_rate = target_sample_rate
        
        self.buffer: deque[AudioFrame] = deque(maxlen=max_buffer_size)
        self.packets_received = 0
        self.packets_dropped = 0
        self.packets_reordered = 0
        self.last_sequence = -1
        
        self.output_queue: asyncio.Queue[bytes] = asyncio.Queue(maxsize=50)
        self._buffering_task: Optional[asyncio.Task] = None
        self._running = False
        
    async def start(self):
        """버퍼링 태스크 시작"""
        if self._running:
            return
            
        self._running = True
        self._buffering_task = asyncio.create_task(self._buffer_worker())
        logger.info("AudioBuffer started")
    
    async def stop(self):
        """버퍼링 태스크 중지"""
        self._running = False
        if self._buffering_task:
            self._buffering_task.cancel()
            try:
                await self._buffering_task
            except asyncio.CancelledError:
                pass
    
    async def add_packet(self, rtp_packet) -> None:
        """RTP 패킷을 버퍼에 추가"""
        self.packets_received += 1
        
        frame = AudioFrame(
            sequence=rtp_packet.sequence,
            timestamp=rtp_packet.timestamp,
            payload=rtp_packet.payload,
            sample_rate=rtp_packet.sample_rate or 8000
        )
        
        # 패킷 손실 감지
        if self.last_sequence >= 0:
            expected_seq = (self.last_sequence + 1) % 65536
            if frame.sequence != expected_seq:
                gap = (frame.sequence - expected_seq) % 65536
                self.packets_dropped += gap
                logger.warning("Packet loss", gap=gap)
        
        self._insert_sorted(frame)
        self.last_sequence = frame.sequence
    
    def _insert_sorted(self, frame: AudioFrame) -> None:
        """버퍼에 sequence number 순서로 삽입"""
        if not self.buffer or frame.sequence > self.buffer[-1].sequence:
            self.buffer.append(frame)
            return
        
        for i, buffered_frame in enumerate(self.buffer):
            if frame.sequence < buffered_frame.sequence:
                self.buffer.insert(i, frame)
                self.packets_reordered += 1
                return
    
    async def _buffer_worker(self):
        """버퍼 워커 태스크"""
        while self._running:
            try:
                await asyncio.sleep(self.jitter_buffer_ms / 1000.0)
                
                if not self.buffer:
                    continue
                
                frame = self.buffer.popleft()
                converted = self._convert_sample_rate(
                    frame.payload,
                    frame.sample_rate,
                    self.target_sample_rate
                )
                
                try:
                    self.output_queue.put_nowait(converted)
                except asyncio.QueueFull:
                    logger.warning("Output queue full")
                    
            except Exception as e:
                logger.error("Buffer worker error", error=str(e))
    
    def _convert_sample_rate(
        self, 
        audio_data: bytes, 
        from_rate: int, 
        to_rate: int
    ) -> bytes:
        """샘플레이트 변환"""
        if from_rate == to_rate:
            return audio_data
        
        try:
            converted, _ = audioop.ratecv(
                audio_data, 2, 1, from_rate, to_rate, None
            )
            return converted
        except Exception as e:
            logger.error("Sample rate conversion failed", error=str(e))
            return audio_data
    
    async def get_frame(self, timeout: float = 0.1) -> Optional[bytes]:
        """변환된 오디오 프레임 가져오기"""
        try:
            return await asyncio.wait_for(
                self.output_queue.get(), 
                timeout=timeout
            )
        except asyncio.TimeoutError:
            return None
```

### 1.3 사용 예시

```python
# 초기화
buffer = AudioBuffer(
    jitter_buffer_ms=60,
    target_sample_rate=16000
)
await buffer.start()

# RTP 패킷 추가
await buffer.add_packet(rtp_packet)

# 프레임 가져오기
frame = await buffer.get_frame()
if frame:
    # STT로 전송
    await stt_client.send_audio(frame)

await buffer.stop()
```

---

## 2. VAD Detector ✅

### 2.1 완전한 구현

파일 위치: `src/ai_voicebot/vad_detector.py`

```python
import webrtcvad
from collections import deque
import structlog

logger = structlog.get_logger(__name__)


class VADDetector:
    """
    Voice Activity Detector (음성 활동 감지기)
    WebRTC VAD 기반 Barge-in 지원
    """
    
    def __init__(
        self,
        mode: int = 3,  # 0-3, 3이 가장 민감
        sample_rate: int = 16000,
        frame_duration_ms: int = 30,
        trigger_threshold: float = 0.5,
        speech_frame_count: int = 3
    ):
        if mode not in [0, 1, 2, 3]:
            raise ValueError("VAD mode must be 0-3")
        
        if sample_rate not in [8000, 16000, 32000, 48000]:
            raise ValueError("Invalid sample rate")
        
        self.vad = webrtcvad.Vad(mode)
        self.sample_rate = sample_rate
        self.frame_duration_ms = frame_duration_ms
        self.trigger_threshold = trigger_threshold
        self.speech_frame_count = speech_frame_count
        
        # 프레임 크기 (bytes): sample_rate * duration / 1000 * 2
        self.frame_size = int(sample_rate * frame_duration_ms / 1000 * 2)
        
        self.recent_frames = deque(maxlen=10)
        self.consecutive_speech = 0
        
        logger.info("VADDetector initialized", mode=mode)
    
    def detect(self, audio_frame: bytes) -> bool:
        """음성 감지"""
        # 프레임 크기 맞추기
        if len(audio_frame) != self.frame_size:
            if len(audio_frame) < self.frame_size:
                audio_frame = audio_frame + b'\x00' * (self.frame_size - len(audio_frame))
            else:
                audio_frame = audio_frame[:self.frame_size]
        
        try:
            is_speech = self.vad.is_speech(audio_frame, self.sample_rate)
            
            if is_speech:
                self.consecutive_speech += 1
            else:
                self.consecutive_speech = 0
            
            self.recent_frames.append(is_speech)
            return is_speech
            
        except Exception as e:
            logger.error("VAD detection failed", error=str(e))
            return False
    
    def is_speaking(self) -> bool:
        """현재 발화 중인지 (Barge-in 트리거용)"""
        return self.consecutive_speech >= self.speech_frame_count
    
    def get_speech_ratio(self) -> float:
        """최근 윈도우 음성 비율"""
        if not self.recent_frames:
            return 0.0
        speech_count = sum(1 for is_speech in self.recent_frames if is_speech)
        return speech_count / len(self.recent_frames)
    
    def is_barge_in(self) -> bool:
        """Barge-in 조건 만족 여부"""
        if not self.is_speaking():
            return False
        
        speech_ratio = self.get_speech_ratio()
        return speech_ratio >= self.trigger_threshold
    
    def reset(self):
        """VAD 상태 초기화"""
        self.recent_frames.clear()
        self.consecutive_speech = 0
```

### 2.2 사용 예시

```python
# 초기화
vad = VADDetector(
    mode=3,
    sample_rate=16000,
    trigger_threshold=0.6,
    speech_frame_count=3
)

# 오디오 프레임 감지
is_speech = vad.detect(audio_frame)

# Barge-in 확인
if vad.is_barge_in():
    # TTS 재생 중단
    await orchestrator.stop_speaking()
```

---

## 3. STT Client (Google gRPC) 🆕

### 3.1 완전한 구현

파일 위치: `src/ai_voicebot/ai_pipeline/stt_client.py`

```python
from google.cloud import speech
import asyncio
from typing import Optional, Callable
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
        """
        self.config = config
        self.client = speech.SpeechClient()
        
        # 설정
        self.recognition_config = speech.RecognitionConfig(
            encoding=speech.RecognitionConfig.AudioEncoding.LINEAR16,
            sample_rate_hertz=config.get("sample_rate", 16000),
            language_code=config.get("language_code", "ko-KR"),
            model=config.get("model", "telephony"),
            use_enhanced=config.get("enable_enhanced", True),
            enable_automatic_punctuation=True,
            enable_word_time_offsets=False,
        )
        
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
        
        logger.info("STTClient initialized", 
                   model=config.get("model"),
                   language=config.get("language_code"))
    
    async def start_stream(self, result_callback: Callable):
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
                self._streaming_task.cancel()
        
        logger.info("STT streaming stopped")
    
    async def send_audio(self, audio_data: bytes):
        """
        오디오 데이터를 STT로 전송
        
        Args:
            audio_data: 16-bit PCM audio bytes
        """
        if not self._running or not self.audio_queue:
            logger.warning("STT not running, audio dropped")
            return
        
        try:
            self.audio_queue.put_nowait(audio_data)
        except asyncio.QueueFull:
            logger.warning("STT audio queue full, frame dropped")
    
    async def _streaming_recognize(self):
        """스트리밍 인식 메인 루프"""
        try:
            # 요청 생성기
            requests = self._request_generator()
            
            # gRPC 스트리밍 호출
            responses = self.client.streaming_recognize(
                self.streaming_config,
                requests
            )
            
            # 응답 처리
            for response in responses:
                if not response.results:
                    continue
                
                result = response.results[0]
                if not result.alternatives:
                    continue
                
                transcript = result.alternatives[0].transcript
                is_final = result.is_final
                
                # 콜백 호출
                if self.result_callback:
                    await self.result_callback(transcript, is_final)
                
                logger.debug("STT result", 
                           text=transcript,
                           is_final=is_final)
                
        except Exception as e:
            logger.error("STT streaming error", error=str(e))
        finally:
            self._running = False
    
    def _request_generator(self):
        """STT 요청 생성기 (동기 generator)"""
        # 첫 번째 요청: 설정
        yield speech.StreamingRecognizeRequest(
            streaming_config=self.streaming_config
        )
        
        # 이후 요청: 오디오 데이터
        while self._running:
            try:
                # asyncio.Queue를 동기적으로 사용 (blocking)
                audio_data = self.audio_queue.get_nowait() if self.audio_queue else None
                
                if audio_data is None:
                    break
                
                yield speech.StreamingRecognizeRequest(
                    audio_content=audio_data
                )
                
            except asyncio.QueueEmpty:
                # 큐가 비었으면 짧은 대기
                import time
                time.sleep(0.01)
                continue
            except Exception as e:
                logger.error("Request generator error", error=str(e))
                break


# 사용 예시
async def example_usage():
    """STTClient 사용 예시"""
    
    async def on_stt_result(text: str, is_final: bool):
        """STT 결과 콜백"""
        print(f"{'[FINAL]' if is_final else '[INTERIM]'} {text}")
        
        if is_final:
            # 최종 결과 → AI Orchestrator로 전달
            await orchestrator.on_stt_result(text, is_final)
    
    config = {
        "model": "telephony",
        "language_code": "ko-KR",
        "sample_rate": 16000,
        "enable_enhanced": True
    }
    
    stt = STTClient(config)
    await stt.start_stream(on_stt_result)
    
    # 오디오 전송
    while True:
        audio_frame = await audio_buffer.get_frame()
        if audio_frame:
            await stt.send_audio(audio_frame)
    
    await stt.stop_stream()
```

---

## 4. TTS Client (Google gRPC) 🆕

### 4.1 완전한 구현

파일 위치: `src/ai_voicebot/ai_pipeline/tts_client.py`

```python
from google.cloud import texttospeech
import asyncio
from typing import AsyncGenerator, Optional
import structlog

logger = structlog.get_logger(__name__)


class TTSClient:
    """
    Google Cloud Text-to-Speech gRPC Client
    
    텍스트 → 음성 스트리밍 생성을 제공합니다.
    """
    
    def __init__(self, config: dict):
        """
        Args:
            config: TTS 설정
                - voice_name: "ko-KR-Neural2-A"
                - speaking_rate: 1.0
                - pitch: 0.0
        """
        self.config = config
        self.client = texttospeech.TextToSpeechClient()
        
        # 음성 설정
        self.voice = texttospeech.VoiceSelectionParams(
            language_code=config.get("language_code", "ko-KR"),
            name=config.get("voice_name", "ko-KR-Neural2-A"),
            ssml_gender=texttospeech.SsmlVoiceGender.FEMALE
        )
        
        # 오디오 설정
        self.audio_config = texttospeech.AudioConfig(
            audio_encoding=texttospeech.AudioEncoding.LINEAR16,
            sample_rate_hertz=16000,
            speaking_rate=config.get("speaking_rate", 1.0),
            pitch=config.get("pitch", 0.0),
        )
        
        self._is_generating = False
        self._stop_flag = False
        
        logger.info("TTSClient initialized", 
                   voice=config.get("voice_name"))
    
    async def synthesize_stream(
        self, 
        text: str
    ) -> AsyncGenerator[bytes, None]:
        """
        텍스트를 음성으로 변환 (스트리밍)
        
        Args:
            text: 변환할 텍스트
            
        Yields:
            오디오 청크 (bytes)
        """
        if self._is_generating:
            logger.warning("TTS already generating")
            return
        
        self._is_generating = True
        self._stop_flag = False
        
        try:
            # TTS 요청
            synthesis_input = texttospeech.SynthesisInput(text=text)
            
            # 동기 API를 비동기로 실행
            loop = asyncio.get_event_loop()
            response = await loop.run_in_executor(
                None,
                lambda: self.client.synthesize_speech(
                    input=synthesis_input,
                    voice=self.voice,
                    audio_config=self.audio_config
                )
            )
            
            # 오디오 데이터를 청크로 분할
            audio_data = response.audio_content
            chunk_size = 4096  # 4KB chunks
            
            for i in range(0, len(audio_data), chunk_size):
                # 중지 플래그 확인 (Barge-in)
                if self._stop_flag:
                    logger.info("TTS stopped (barge-in)")
                    break
                
                chunk = audio_data[i:i + chunk_size]
                yield chunk
                
                # 스트리밍 효과를 위한 짧은 대기
                await asyncio.sleep(0.01)
            
            logger.debug("TTS synthesis completed", text_length=len(text))
            
        except Exception as e:
            logger.error("TTS synthesis error", error=str(e))
        finally:
            self._is_generating = False
            self._stop_flag = False
    
    async def synthesize(self, text: str) -> bytes:
        """
        텍스트를 음성으로 변환 (전체)
        
        Args:
            text: 변환할 텍스트
            
        Returns:
            전체 오디오 데이터 (bytes)
        """
        try:
            synthesis_input = texttospeech.SynthesisInput(text=text)
            
            loop = asyncio.get_event_loop()
            response = await loop.run_in_executor(
                None,
                lambda: self.client.synthesize_speech(
                    input=synthesis_input,
                    voice=self.voice,
                    audio_config=self.audio_config
                )
            )
            
            return response.audio_content
            
        except Exception as e:
            logger.error("TTS synthesis error", error=str(e))
            return b''
    
    def stop(self):
        """TTS 생성 중지 (Barge-in용)"""
        if self._is_generating:
            self._stop_flag = True
            logger.info("TTS stop requested")
    
    def is_generating(self) -> bool:
        """현재 생성 중인지 확인"""
        return self._is_generating


# 사용 예시
async def example_usage():
    """TTSClient 사용 예시"""
    config = {
        "voice_name": "ko-KR-Neural2-A",
        "speaking_rate": 1.0,
        "pitch": 0.0
    }
    
    tts = TTSClient(config)
    
    # 스트리밍 생성
    text = "안녕하세요, AI 비서입니다."
    
    async for audio_chunk in tts.synthesize_stream(text):
        # RTP로 전송
        await rtp_relay.send_audio(audio_chunk)
        
        # Barge-in 체크
        if vad.is_barge_in():
            tts.stop()
            break
    
    # 또는 전체 생성
    audio_data = await tts.synthesize(text)
    await rtp_relay.send_audio(audio_data)
```

---

이 문서는 계속 이어집니다. 나머지 4개 컴포넌트(LLM Client, RAG Engine, Call Recorder, Knowledge Extractor)는 다음 파일로 분리하겠습니다.

**다음 작업:**
- `docs/ai-implementation-guide-part2.md` 생성
- 나머지 4개 컴포넌트 상세 구현
- 통합 예시 및 E2E 테스트

계속 진행할까요?

