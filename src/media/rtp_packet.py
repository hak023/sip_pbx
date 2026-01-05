"""RTP Packet

RTP (Real-time Transport Protocol) 패킷 구조 및 파싱
RFC 3550
"""

from dataclasses import dataclass
import struct


@dataclass
class RTPHeader:
    """RTP 패킷 헤더 (12 bytes 고정)
    
    RFC 3550:
     0                   1                   2                   3
     0 1 2 3 4 5 6 7 8 9 0 1 2 3 4 5 6 7 8 9 0 1 2 3 4 5 6 7 8 9 0 1
    +-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+
    |V=2|P|X|  CC   |M|     PT      |       sequence number         |
    +-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+
    |                           timestamp                           |
    +-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+
    |           synchronization source (SSRC) identifier            |
    +-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+
    """
    version: int          # 2 bits (항상 2)
    padding: bool         # 1 bit
    extension: bool       # 1 bit
    csrc_count: int       # 4 bits (CSRC 개수)
    marker: bool          # 1 bit
    payload_type: int     # 7 bits (코덱 타입)
    sequence_number: int  # 16 bits
    timestamp: int        # 32 bits
    ssrc: int             # 32 bits (동기화 소스 식별자)


@dataclass
class RTPPacket:
    """RTP 패킷 전체
    
    header + payload
    """
    header: RTPHeader
    payload: bytes
    
    def __len__(self) -> int:
        """전체 패킷 크기"""
        return 12 + len(self.payload)  # 헤더(12) + payload
    
    def is_rtcp(self) -> bool:
        """RTCP 패킷 여부 확인
        
        RTCP는 payload type이 200-204 범위
        """
        return 200 <= self.header.payload_type <= 204


class RTPParser:
    """RTP 패킷 파서"""
    
    @staticmethod
    def parse(data: bytes) -> RTPPacket:
        """RTP 패킷 파싱
        
        Args:
            data: 원본 패킷 데이터
            
        Returns:
            RTPPacket 객체
            
        Raises:
            ValueError: 잘못된 패킷 형식
        """
        if len(data) < 12:
            raise ValueError(f"RTP packet too short: {len(data)} bytes")
        
        # 첫 12 bytes는 헤더
        # Big-endian (network byte order)
        header_data = data[:12]
        
        # 첫 번째 byte: V(2) P(1) X(1) CC(4)
        byte0 = header_data[0]
        version = (byte0 >> 6) & 0x03
        padding = bool((byte0 >> 5) & 0x01)
        extension = bool((byte0 >> 4) & 0x01)
        csrc_count = byte0 & 0x0F
        
        # 두 번째 byte: M(1) PT(7)
        byte1 = header_data[1]
        marker = bool((byte1 >> 7) & 0x01)
        payload_type = byte1 & 0x7F
        
        # Sequence number (2 bytes)
        sequence_number = struct.unpack('!H', header_data[2:4])[0]
        
        # Timestamp (4 bytes)
        timestamp = struct.unpack('!I', header_data[4:8])[0]
        
        # SSRC (4 bytes)
        ssrc = struct.unpack('!I', header_data[8:12])[0]
        
        # 헤더 생성
        header = RTPHeader(
            version=version,
            padding=padding,
            extension=extension,
            csrc_count=csrc_count,
            marker=marker,
            payload_type=payload_type,
            sequence_number=sequence_number,
            timestamp=timestamp,
            ssrc=ssrc,
        )
        
        # Payload (헤더 이후 모든 데이터)
        payload = data[12:]
        
        return RTPPacket(header=header, payload=payload)
    
    @staticmethod
    def is_valid_rtp(data: bytes) -> bool:
        """RTP 패킷 유효성 간단 체크
        
        Args:
            data: 패킷 데이터
            
        Returns:
            유효한 RTP 패킷 여부
        """
        if len(data) < 12:
            return False
        
        # Version이 2여야 함
        version = (data[0] >> 6) & 0x03
        return version == 2


class RTCPPacket:
    """RTCP 패킷 (단순 래퍼)
    
    RTCP는 상세 파싱하지 않고 그대로 relay
    """
    
    def __init__(self, data: bytes):
        self.data = data
    
    def __len__(self) -> int:
        return len(self.data)
    
    @staticmethod
    def is_rtcp(data: bytes) -> bool:
        """RTCP 패킷 여부 확인
        
        RTCP는 두 번째 byte가 packet type (200-204)
        RTCP 패킷에는 marker bit 개념이 없으므로 byte 전체를 확인
        """
        if len(data) < 2:
            return False
        
        # RTCP의 경우 byte 1 전체가 packet type
        packet_type = data[1]
        return 200 <= packet_type <= 204

