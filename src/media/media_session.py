"""Media Session 모델

미디어 세션 및 Leg 정보
"""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional, List
from enum import Enum

from src.media.sdp_models import SDPSession
from src.sip_core.models.enums import Direction


class MediaMode(str, Enum):
    """미디어 처리 모드"""
    BYPASS = "bypass"        # 직접 전달 (처리 없음)
    REFLECTING = "reflecting"  # 반사 (AI 분석용)


@dataclass
class MediaLeg:
    """미디어 Leg (통화의 한쪽 미디어 정보)
    
    caller 또는 callee의 미디어 엔드포인트 정보
    """
    # 방향 (incoming = caller, outgoing = callee)
    direction: Direction = Direction.INCOMING
    
    # 원본 SDP 정보
    original_sdp: Optional[SDPSession] = None  # SDP 파싱된 객체
    original_ip: Optional[str] = None
    original_audio_port: Optional[int] = None
    original_video_port: Optional[int] = None
    
    # B2BUA 할당 포트 (양쪽 leg 각각 4개)
    # [audio_rtp, audio_rtcp, video_rtp, video_rtcp]
    allocated_ports: List[int] = field(default_factory=list)
    
    # 마지막 RTP 수신 시간 (타임아웃 감지용)
    last_rtp_received: Optional[datetime] = None
    
    def get_audio_rtp_port(self) -> Optional[int]:
        """Audio RTP 포트"""
        return self.allocated_ports[0] if len(self.allocated_ports) > 0 else None
    
    def get_audio_rtcp_port(self) -> Optional[int]:
        """Audio RTCP 포트"""
        return self.allocated_ports[1] if len(self.allocated_ports) > 1 else None
    
    def get_video_rtp_port(self) -> Optional[int]:
        """Video RTP 포트"""
        return self.allocated_ports[2] if len(self.allocated_ports) > 2 else None
    
    def get_video_rtcp_port(self) -> Optional[int]:
        """Video RTCP 포트"""
        return self.allocated_ports[3] if len(self.allocated_ports) > 3 else None


@dataclass
class MediaSession:
    """미디어 세션
    
    B2BUA 전체 미디어 세션 (caller ↔ B2BUA ↔ callee)
    """
    call_id: str
    
    # 양쪽 미디어 Leg
    caller_leg: MediaLeg = field(default_factory=MediaLeg)
    callee_leg: MediaLeg = field(default_factory=MediaLeg)
    
    # 미디어 처리 모드
    mode: MediaMode = MediaMode.REFLECTING
    
    # 생성 시간
    created_at: datetime = field(default_factory=datetime.utcnow)
    
    # 통화 시작 시간 (RTP 첫 수신)
    started_at: Optional[datetime] = None
    
    # 통화 종료 시간
    ended_at: Optional[datetime] = None
    
    def is_active(self) -> bool:
        """활성 상태 여부"""
        return self.ended_at is None
    
    def mark_started(self) -> None:
        """통화 시작 마킹 (RTP 첫 수신)"""
        if not self.started_at:
            self.started_at = datetime.utcnow()
    
    def mark_ended(self) -> None:
        """통화 종료 마킹"""
        if not self.ended_at:
            self.ended_at = datetime.utcnow()
    
    def get_duration_seconds(self) -> Optional[int]:
        """통화 시간 (초)"""
        if self.started_at and self.ended_at:
            return int((self.ended_at - self.started_at).total_seconds())
        return None
    
    def update_rtp_received(self, from_caller: bool) -> None:
        """RTP 수신 시간 업데이트
        
        Args:
            from_caller: caller로부터의 RTP 여부
        """
        now = datetime.utcnow()
        
        if from_caller:
            self.caller_leg.last_rtp_received = now
        else:
            self.callee_leg.last_rtp_received = now
        
        # 첫 RTP 수신이면 시작 마킹
        if not self.started_at:
            self.mark_started()
    
    def get_seconds_since_last_rtp(self) -> Optional[int]:
        """마지막 RTP 수신 이후 경과 시간 (초)
        
        Returns:
            경과 시간 (초) 또는 None (RTP 수신 이력 없음)
        """
        last_times = []
        
        if self.caller_leg.last_rtp_received:
            last_times.append(self.caller_leg.last_rtp_received)
        
        if self.callee_leg.last_rtp_received:
            last_times.append(self.callee_leg.last_rtp_received)
        
        if not last_times:
            return None
        
        most_recent = max(last_times)
        return int((datetime.utcnow() - most_recent).total_seconds())

