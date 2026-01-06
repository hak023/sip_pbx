"""
Audio Buffer & Jitter Buffer

RTP 패킷을 버퍼링하고 gRPC 스트리밍을 위해 변환합니다.
"""

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
        """
        Args:
            jitter_buffer_ms: Jitter 버퍼 시간(ms)
            max_buffer_size: 최대 버퍼 크기
            target_sample_rate: 목표 샘플레이트
        """
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
        logger.info("AudioBuffer started", 
                   jitter_ms=self.jitter_buffer_ms,
                   target_sample_rate=self.target_sample_rate)
    
    async def stop(self):
        """버퍼링 태스크 중지"""
        self._running = False
        if self._buffering_task:
            self._buffering_task.cancel()
            try:
                await self._buffering_task
            except asyncio.CancelledError:
                pass
        
        logger.info("AudioBuffer stopped",
                   total_received=self.packets_received,
                   dropped=self.packets_dropped,
                   reordered=self.packets_reordered)
    
    async def add_packet(self, rtp_packet) -> None:
        """
        RTP 패킷을 버퍼에 추가
        
        Args:
            rtp_packet: RTP 패킷 객체 (sequence, timestamp, payload, sample_rate 속성 필요)
        """
        self.packets_received += 1
        
        frame = AudioFrame(
            sequence=rtp_packet.sequence,
            timestamp=rtp_packet.timestamp,
            payload=rtp_packet.payload,
            sample_rate=getattr(rtp_packet, 'sample_rate', 8000)
        )
        
        # 패킷 손실 감지
        if self.last_sequence >= 0:
            expected_seq = (self.last_sequence + 1) % 65536
            if frame.sequence != expected_seq:
                gap = (frame.sequence - expected_seq) % 65536
                self.packets_dropped += gap
                logger.warning("Packet loss detected", 
                             expected=expected_seq,
                             actual=frame.sequence,
                             gap=gap)
        
        self._insert_sorted(frame)
        self.last_sequence = frame.sequence
    
    def _insert_sorted(self, frame: AudioFrame) -> None:
        """버퍼에 sequence number 순서로 삽입"""
        if not self.buffer or frame.sequence > self.buffer[-1].sequence:
            self.buffer.append(frame)
            return
        
        # 순서가 맞지 않는 경우 정렬된 위치에 삽입
        for i, buffered_frame in enumerate(self.buffer):
            if frame.sequence < buffered_frame.sequence:
                self.buffer.insert(i, frame)
                self.packets_reordered += 1
                logger.debug("Packet reordered", sequence=frame.sequence)
                return
    
    async def _buffer_worker(self):
        """버퍼 워커 태스크"""
        while self._running:
            try:
                # Jitter 버퍼 대기
                await asyncio.sleep(self.jitter_buffer_ms / 1000.0)
                
                if not self.buffer:
                    continue
                
                # 가장 오래된 프레임 가져오기
                frame = self.buffer.popleft()
                
                # 샘플레이트 변환
                converted = self._convert_sample_rate(
                    frame.payload,
                    frame.sample_rate,
                    self.target_sample_rate
                )
                
                # 출력 큐에 추가
                try:
                    self.output_queue.put_nowait(converted)
                except asyncio.QueueFull:
                    logger.warning("Output queue full, frame dropped")
                    
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error("Buffer worker error", error=str(e), exc_info=True)
    
    def _convert_sample_rate(
        self, 
        audio_data: bytes, 
        from_rate: int, 
        to_rate: int
    ) -> bytes:
        """
        샘플레이트 변환
        
        Args:
            audio_data: 입력 오디오 데이터
            from_rate: 원본 샘플레이트
            to_rate: 목표 샘플레이트
            
        Returns:
            변환된 오디오 데이터
        """
        if from_rate == to_rate:
            return audio_data
        
        if not audio_data:
            return audio_data
        
        try:
            # audioop.ratecv: 샘플레이트 변환
            # (data, width, nchannels, inrate, outrate, state)
            converted, _ = audioop.ratecv(
                audio_data, 
                2,  # 16-bit = 2 bytes
                1,  # mono
                from_rate, 
                to_rate, 
                None
            )
            return converted
        except Exception as e:
            logger.error("Sample rate conversion failed", 
                        from_rate=from_rate,
                        to_rate=to_rate,
                        error=str(e))
            return audio_data
    
    async def get_frame(self, timeout: float = 0.1) -> Optional[bytes]:
        """
        변환된 오디오 프레임 가져오기
        
        Args:
            timeout: 대기 시간(초)
            
        Returns:
            오디오 프레임 또는 None
        """
        try:
            return await asyncio.wait_for(
                self.output_queue.get(), 
                timeout=timeout
            )
        except asyncio.TimeoutError:
            return None
    
    def get_stats(self) -> dict:
        """버퍼 통계 반환"""
        return {
            "packets_received": self.packets_received,
            "packets_dropped": self.packets_dropped,
            "packets_reordered": self.packets_reordered,
            "buffer_size": len(self.buffer),
            "output_queue_size": self.output_queue.qsize(),
        }

