"""SDP 데이터 모델

Session Description Protocol 파싱 결과를 담는 데이터 클래스
"""

from dataclasses import dataclass, field
from typing import List, Optional, Dict


@dataclass
class MediaDescription:
    """미디어 설명 (m= line)
    
    예: m=audio 5004 RTP/AVP 0 8 101
    """
    media_type: str          # audio, video, application
    port: int                # 미디어 포트
    protocol: str            # RTP/AVP, RTP/SAVP, etc.
    formats: List[str]       # payload types (코덱 리스트)
    
    # 미디어별 속성 (a= lines)
    attributes: Dict[str, str] = field(default_factory=dict)
    
    # Connection 정보 (c= line, 미디어별로 있을 수 있음)
    connection_ip: Optional[str] = None
    
    def __repr__(self) -> str:
        return f"MediaDescription(type={self.media_type}, port={self.port}, formats={self.formats})"


@dataclass
class SDPSession:
    """SDP 세션 정보
    
    전체 SDP를 파싱한 결과
    """
    # Session 레벨 정보
    version: str = "0"                        # v=
    origin: Optional[str] = None              # o=
    session_name: str = "-"                   # s=
    connection_ip: Optional[str] = None       # c= (세션 레벨)
    timing: str = "0 0"                       # t=
    
    # 미디어 설명 리스트
    media_descriptions: List[MediaDescription] = field(default_factory=list)
    
    # 세션 레벨 속성
    attributes: Dict[str, str] = field(default_factory=dict)
    
    # 원본 SDP (디버깅용)
    raw_sdp: Optional[str] = None
    
    def get_media_by_type(self, media_type: str) -> Optional[MediaDescription]:
        """미디어 타입으로 검색
        
        Args:
            media_type: audio, video 등
            
        Returns:
            MediaDescription 또는 None
        """
        for media in self.media_descriptions:
            if media.media_type == media_type:
                return media
        return None
    
    def has_audio(self) -> bool:
        """오디오 포함 여부"""
        return self.get_media_by_type("audio") is not None
    
    def has_video(self) -> bool:
        """비디오 포함 여부"""
        return self.get_media_by_type("video") is not None
    
    def get_audio_port(self) -> Optional[int]:
        """오디오 포트 반환"""
        audio = self.get_media_by_type("audio")
        return audio.port if audio else None
    
    def get_video_port(self) -> Optional[int]:
        """비디오 포트 반환"""
        video = self.get_media_by_type("video")
        return video.port if video else None
    
    def get_audio_connection_ip(self) -> Optional[str]:
        """오디오 connection IP 반환 (미디어 레벨 우선)
        
        RFC 4566: 미디어 레벨 connection이 세션 레벨을 override
        """
        audio = self.get_media_by_type("audio")
        if audio and audio.connection_ip:
            return audio.connection_ip
        return self.connection_ip
    
    def get_video_connection_ip(self) -> Optional[str]:
        """비디오 connection IP 반환 (미디어 레벨 우선)"""
        video = self.get_media_by_type("video")
        if video and video.connection_ip:
            return video.connection_ip
        return self.connection_ip

