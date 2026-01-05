"""Jitter Buffer

RTP 패킷 순서 재정렬 및 타이밍 조정
"""

from dataclasses import dataclass, field
from typing import Optional, List, Dict
from datetime import datetime, timedelta
import heapq

from src.media.rtp_reflector import AudioPacket
from src.common.logger import get_logger

logger = get_logger(__name__)


@dataclass
class JitterBufferEntry:
    """Jitter Buffer 엔트리"""
    sequence: int                # RTP Sequence Number
    audio_packet: AudioPacket    # 오디오 패킷
    received_at: datetime        # 수신 시간
    
    def __lt__(self, other):
        """정렬을 위한 비교 (sequence number 기준)"""
        return self.sequence < other.sequence


class JitterBuffer:
    """Jitter Buffer
    
    RTP 패킷의 순서를 재정렬하고 지연 시간을 조정하여
    일정한 간격으로 패킷을 출력
    """
    
    def __init__(
        self,
        buffer_size: int = 10,
        max_delay_ms: int = 100,
        packet_loss_threshold: int = 3,
    ):
        """초기화
        
        Args:
            buffer_size: 버퍼 크기 (패킷 개수)
            max_delay_ms: 최대 지연 시간 (밀리초)
            packet_loss_threshold: Packet loss로 간주할 sequence gap
        """
        self.buffer_size = buffer_size
        self.max_delay_ms = max_delay_ms
        self.packet_loss_threshold = packet_loss_threshold
        
        # Priority Queue (min-heap) - sequence number 기준 정렬
        self.buffer: List[JitterBufferEntry] = []
        
        # 마지막으로 출력한 sequence number
        self.last_output_seq: Optional[int] = None
        
        # 통계
        self.stats = {
            "packets_buffered": 0,
            "packets_output": 0,
            "packets_dropped": 0,
            "packets_reordered": 0,
            "packet_losses_detected": 0,
        }
        
        logger.debug("jitter_buffer_created",
                    buffer_size=buffer_size,
                    max_delay_ms=max_delay_ms)
    
    def add_packet(self, audio_packet: AudioPacket) -> None:
        """패킷 추가
        
        Args:
            audio_packet: 오디오 패킷
        """
        sequence = audio_packet.get_sequence()
        
        # 중복 패킷 체크
        if any(entry.sequence == sequence for entry in self.buffer):
            logger.debug("duplicate_packet_dropped", sequence=sequence)
            self.stats["packets_dropped"] += 1
            return
        
        # 버퍼에 추가
        entry = JitterBufferEntry(
            sequence=sequence,
            audio_packet=audio_packet,
            received_at=datetime.utcnow(),
        )
        
        heapq.heappush(self.buffer, entry)
        self.stats["packets_buffered"] += 1
        
        # 버퍼 크기 초과 시 오래된 패킷 제거
        if len(self.buffer) > self.buffer_size:
            oldest = heapq.heappop(self.buffer)
            logger.debug("buffer_overflow_dropped", sequence=oldest.sequence)
            self.stats["packets_dropped"] += 1
    
    def get_next_packet(self) -> Optional[AudioPacket]:
        """다음 패킷 가져오기 (순서대로)
        
        Returns:
            다음 오디오 패킷 또는 None (버퍼가 비어있거나 대기 중)
        """
        if not self.buffer:
            return None
        
        # 최소 sequence number 패킷
        entry = self.buffer[0]
        
        # 첫 패킷이거나 순서가 맞는 경우
        if self.last_output_seq is None:
            # 첫 패킷: 바로 출력
            entry = heapq.heappop(self.buffer)
            self.last_output_seq = entry.sequence
            self.stats["packets_output"] += 1
            return entry.audio_packet
        
        expected_seq = self._next_sequence(self.last_output_seq)
        
        # 순서가 맞는 패킷
        if entry.sequence == expected_seq:
            entry = heapq.heappop(self.buffer)
            self.last_output_seq = entry.sequence
            self.stats["packets_output"] += 1
            return entry.audio_packet
        
        # 순서가 앞선 패킷 (늦게 도착한 과거 패킷)
        if self._is_older_sequence(entry.sequence, expected_seq):
            # 이미 지나간 패킷 → 드롭
            entry = heapq.heappop(self.buffer)
            logger.debug("late_packet_dropped",
                        sequence=entry.sequence,
                        expected=expected_seq)
            self.stats["packets_dropped"] += 1
            return self.get_next_packet()  # 재귀적으로 다음 패킷 시도
        
        # 순서가 뒤인 패킷 (패킷 loss 가능성)
        seq_gap = self._sequence_diff(entry.sequence, expected_seq)
        
        if seq_gap >= self.packet_loss_threshold:
            # Packet loss로 판단 → 건너뛰고 출력
            logger.warning("packet_loss_detected",
                          expected=expected_seq,
                          received=entry.sequence,
                          gap=seq_gap)
            self.stats["packet_losses_detected"] += 1
            
            entry = heapq.heappop(self.buffer)
            self.last_output_seq = entry.sequence
            self.stats["packets_output"] += 1
            self.stats["packets_reordered"] += 1
            return entry.audio_packet
        
        # 작은 gap: 잠시 대기 (reordering 가능성)
        elapsed_ms = (datetime.utcnow() - entry.received_at).total_seconds() * 1000
        
        if elapsed_ms > self.max_delay_ms:
            # 최대 지연 시간 초과 → 출력
            logger.debug("max_delay_exceeded",
                        sequence=entry.sequence,
                        elapsed_ms=int(elapsed_ms))
            
            entry = heapq.heappop(self.buffer)
            self.last_output_seq = entry.sequence
            self.stats["packets_output"] += 1
            self.stats["packets_reordered"] += 1
            return entry.audio_packet
        
        # 아직 대기 (순서가 맞는 패킷이 곧 도착할 수 있음)
        return None
    
    def flush(self) -> List[AudioPacket]:
        """버퍼의 모든 패킷 강제 출력
        
        Returns:
            남은 모든 패킷 (순서대로)
        """
        packets = []
        
        while self.buffer:
            entry = heapq.heappop(self.buffer)
            packets.append(entry.audio_packet)
            self.stats["packets_output"] += 1
        
        logger.debug("jitter_buffer_flushed", count=len(packets))
        return packets
    
    def reset(self) -> None:
        """버퍼 초기화"""
        self.buffer.clear()
        self.last_output_seq = None
        
        logger.debug("jitter_buffer_reset")
    
    def get_buffer_level(self) -> int:
        """현재 버퍼 레벨
        
        Returns:
            버퍼에 있는 패킷 수
        """
        return len(self.buffer)
    
    def get_stats(self) -> dict:
        """통계 반환
        
        Returns:
            통계 딕셔너리
        """
        return self.stats.copy()
    
    # Helper methods
    
    def _next_sequence(self, seq: int) -> int:
        """다음 sequence number
        
        Args:
            seq: 현재 sequence
            
        Returns:
            다음 sequence (16-bit wrap around)
        """
        return (seq + 1) & 0xFFFF
    
    def _is_older_sequence(self, seq1: int, seq2: int) -> bool:
        """seq1이 seq2보다 오래된 sequence인지
        
        Args:
            seq1: 비교할 sequence 1
            seq2: 비교할 sequence 2
            
        Returns:
            seq1이 더 오래되었으면 True
        """
        # 16-bit sequence number의 wrap around 고려
        diff = (seq2 - seq1) & 0xFFFF
        return diff < 32768  # 절반 미만이면 seq1이 더 오래됨
    
    def _sequence_diff(self, seq1: int, seq2: int) -> int:
        """두 sequence 간 차이
        
        Args:
            seq1: sequence 1 (더 큰 값)
            seq2: sequence 2 (더 작은 값)
            
        Returns:
            차이 (seq1 - seq2, wrap around 고려)
        """
        diff = (seq1 - seq2) & 0xFFFF
        
        # Wrap around 처리
        if diff > 32768:
            diff = 65536 - diff
        
        return diff

