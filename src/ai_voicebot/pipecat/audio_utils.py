"""
Audio utility functions for SIP PBX <-> Pipecat bridge.

Handles:
- G.711 (PCMU/PCMA) encode/decode
- RTP packet parse/build
- Sample rate conversion (8kHz <-> 16kHz)
"""

import struct
import audioop
import time
import random
from typing import Optional, Tuple

import structlog

logger = structlog.get_logger(__name__)

# RTP header size (fixed, no CSRC)
RTP_HEADER_SIZE = 12

# G.711 payload types
PT_PCMU = 0
PT_PCMA = 8
PT_TELEPHONE_EVENT = 101


def decode_g711(payload: bytes, codec: str = "PCMU") -> bytes:
    """
    G.711 인코딩된 오디오를 16-bit PCM으로 디코딩.
    
    Args:
        payload: G.711 인코딩된 오디오 데이터
        codec: "PCMU" (mu-law) 또는 "PCMA" (A-law)
    
    Returns:
        16-bit signed PCM 데이터 (8kHz)
    """
    if not payload:
        return b""
    
    if codec == "PCMU":
        return audioop.ulaw2lin(payload, 2)  # 2 = 16-bit
    elif codec == "PCMA":
        return audioop.alaw2lin(payload, 2)
    else:
        logger.warning("unknown_codec_using_pcmu", codec=codec)
        return audioop.ulaw2lin(payload, 2)


def encode_g711(pcm_data: bytes, codec: str = "PCMU") -> bytes:
    """
    16-bit PCM 오디오를 G.711으로 인코딩.
    
    Args:
        pcm_data: 16-bit signed PCM 데이터
        codec: "PCMU" (mu-law) 또는 "PCMA" (A-law)
    
    Returns:
        G.711 인코딩된 오디오 데이터
    """
    if not pcm_data:
        return b""
    
    if codec == "PCMU":
        return audioop.lin2ulaw(pcm_data, 2)
    elif codec == "PCMA":
        return audioop.lin2alaw(pcm_data, 2)
    else:
        return audioop.lin2ulaw(pcm_data, 2)


def resample(pcm_data: bytes, from_rate: int, to_rate: int) -> bytes:
    """
    PCM 오디오 리샘플링.
    
    Args:
        pcm_data: 16-bit signed PCM 데이터
        from_rate: 원본 샘플레이트
        to_rate: 대상 샘플레이트
    
    Returns:
        리샘플링된 PCM 데이터
    """
    if from_rate == to_rate or not pcm_data:
        return pcm_data
    
    converted, _ = audioop.ratecv(pcm_data, 2, 1, from_rate, to_rate, None)
    return converted


def rtp_to_pcm16k(rtp_packet: bytes, codec: str = "PCMU") -> Optional[bytes]:
    """
    RTP 패킷에서 오디오 추출 -> G.711 디코딩 -> 16kHz PCM 변환.
    
    Args:
        rtp_packet: 전체 RTP 패킷 (헤더 + 페이로드)
        codec: G.711 코덱 타입
    
    Returns:
        16kHz 16-bit PCM 데이터 또는 None (비오디오 패킷)
    """
    if len(rtp_packet) <= RTP_HEADER_SIZE:
        return None
    
    # RTP 헤더 파싱
    header = rtp_packet[:RTP_HEADER_SIZE]
    first_byte = header[0]
    
    # CC (CSRC count) 확인 - 추가 헤더 건너뛰기
    cc = first_byte & 0x0F
    payload_offset = RTP_HEADER_SIZE + (cc * 4)
    
    # Extension bit 확인
    has_extension = (first_byte >> 4) & 0x01
    if has_extension and len(rtp_packet) > payload_offset + 4:
        ext_length = struct.unpack("!H", rtp_packet[payload_offset + 2:payload_offset + 4])[0]
        payload_offset += 4 + (ext_length * 4)
    
    if payload_offset >= len(rtp_packet):
        return None
    
    # Payload type 확인
    pt = header[1] & 0x7F
    if pt == PT_TELEPHONE_EVENT:
        return None  # DTMF 이벤트 무시
    
    payload = rtp_packet[payload_offset:]
    if not payload:
        return None
    
    # G.711 디코딩 (8kHz PCM)
    pcm_8k = decode_g711(payload, codec)
    
    # 8kHz -> 16kHz 리샘플링
    pcm_16k = resample(pcm_8k, 8000, 16000)
    
    return pcm_16k


class RTPPacketBuilder:
    """RTP 패킷 생성기 - TTS 출력을 RTP로 패킷화"""
    
    def __init__(self, ssrc: Optional[int] = None, codec: str = "PCMU"):
        self.ssrc = ssrc or random.randint(1000000, 9999999)
        self.sequence = random.randint(0, 65535)
        self.timestamp = random.randint(0, 2**31)
        self.codec = codec
        self.pt = PT_PCMU if codec == "PCMU" else PT_PCMA
        
        # G.711은 8kHz, 1 sample = 1 byte, 20ms = 160 samples
        self.samples_per_packet = 160  # 20ms at 8kHz
        self.timestamp_increment = 160
    
    def build_packets(self, pcm_data: bytes, sample_rate: int = 16000) -> list:
        """
        PCM 오디오를 RTP 패킷들로 변환.
        
        Args:
            pcm_data: 16-bit PCM 데이터 (임의 샘플레이트)
            sample_rate: 입력 PCM의 샘플레이트
        
        Returns:
            RTP 패킷 리스트
        """
        if not pcm_data:
            return []
        
        # 입력 PCM을 8kHz로 리샘플링
        pcm_8k = resample(pcm_data, sample_rate, 8000)
        
        # G.711 인코딩
        g711_data = encode_g711(pcm_8k, self.codec)
        
        # 20ms 단위로 분할하여 RTP 패킷 생성
        packets = []
        offset = 0
        
        while offset < len(g711_data):
            chunk = g711_data[offset:offset + self.samples_per_packet]
            if not chunk:
                break
            
            packet = self._build_rtp_packet(chunk)
            packets.append(packet)
            offset += self.samples_per_packet
        
        return packets
    
    def _build_rtp_packet(self, payload: bytes) -> bytes:
        """단일 RTP 패킷 생성"""
        # V=2, P=0, X=0, CC=0
        first_byte = 0x80
        # M=0, PT
        second_byte = self.pt & 0x7F
        
        header = struct.pack(
            "!BBHII",
            first_byte,
            second_byte,
            self.sequence & 0xFFFF,
            self.timestamp & 0xFFFFFFFF,
            self.ssrc & 0xFFFFFFFF,
        )
        
        self.sequence = (self.sequence + 1) & 0xFFFF
        self.timestamp = (self.timestamp + self.timestamp_increment) & 0xFFFFFFFF
        
        return header + payload
