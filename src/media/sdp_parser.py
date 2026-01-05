"""SDP Parser

Session Description Protocol 파싱
"""

from typing import Optional
import re

from src.media.sdp_models import SDPSession, MediaDescription
from src.common.exceptions import SDPParsingError
from src.common.logger import get_logger

logger = get_logger(__name__)


class SDPParser:
    """SDP 파서
    
    RFC 4566 기반 SDP 파싱
    """
    
    @staticmethod
    def parse(sdp: str) -> SDPSession:
        """SDP 문자열 파싱
        
        Args:
            sdp: SDP 문자열
            
        Returns:
            SDPSession 객체
            
        Raises:
            SDPParsingError: 파싱 실패
        """
        if not sdp or not sdp.strip():
            raise SDPParsingError("Empty SDP string")
        
        lines = sdp.strip().split('\n')
        session = SDPSession(raw_sdp=sdp)
        
        current_media: Optional[MediaDescription] = None
        
        for line in lines:
            line = line.strip()
            if not line or '=' not in line:
                continue
            
            field_type, field_value = line.split('=', 1)
            
            # Session 레벨 파싱
            if field_type == 'v':
                session.version = field_value
            
            elif field_type == 'o':
                session.origin = field_value
            
            elif field_type == 's':
                session.session_name = field_value
            
            elif field_type == 'c':
                # Connection 정보
                ip = SDPParser._parse_connection_line(field_value)
                if current_media:
                    # 미디어 레벨 connection
                    current_media.connection_ip = ip
                else:
                    # 세션 레벨 connection
                    session.connection_ip = ip
            
            elif field_type == 't':
                session.timing = field_value
            
            elif field_type == 'm':
                # 미디어 설명 시작
                media = SDPParser._parse_media_line(field_value)
                session.media_descriptions.append(media)
                current_media = media
            
            elif field_type == 'a':
                # 속성 라인
                attr_name, attr_value = SDPParser._parse_attribute_line(field_value)
                if current_media:
                    current_media.attributes[attr_name] = attr_value
                else:
                    session.attributes[attr_name] = attr_value
        
        logger.debug("sdp_parsed",
                    has_audio=session.has_audio(),
                    has_video=session.has_video(),
                    media_count=len(session.media_descriptions))
        
        return session
    
    @staticmethod
    def _parse_connection_line(value: str) -> str:
        """Connection 라인 파싱
        
        예: IN IP4 192.168.1.100
        
        Args:
            value: c= 라인 값
            
        Returns:
            IP 주소
        """
        parts = value.split()
        if len(parts) >= 3:
            return parts[2]  # IP 주소
        return value
    
    @staticmethod
    def _parse_media_line(value: str) -> MediaDescription:
        """미디어 라인 파싱
        
        예: audio 5004 RTP/AVP 0 8 101
        
        Args:
            value: m= 라인 값
            
        Returns:
            MediaDescription
            
        Raises:
            SDPParsingError: 파싱 실패
        """
        parts = value.split()
        if len(parts) < 4:
            raise SDPParsingError(f"Invalid media line: {value}")
        
        media_type = parts[0]
        
        try:
            port = int(parts[1])
        except ValueError:
            raise SDPParsingError(f"Invalid port in media line: {parts[1]}")
        
        protocol = parts[2]
        formats = parts[3:]  # payload types
        
        return MediaDescription(
            media_type=media_type,
            port=port,
            protocol=protocol,
            formats=formats,
        )
    
    @staticmethod
    def _parse_attribute_line(value: str) -> tuple[str, str]:
        """속성 라인 파싱
        
        예: rtpmap:0 PCMU/8000
        
        Args:
            value: a= 라인 값
            
        Returns:
            (속성 이름, 속성 값) 튜플
        """
        if ':' in value:
            name, attr_value = value.split(':', 1)
            return name, attr_value
        else:
            # 값 없는 속성 (예: recvonly)
            return value, ""


class SDPManipulator:
    """SDP 조작기
    
    SDP 수정 및 재생성
    """
    
    @staticmethod
    def replace_connection_ip(sdp: str, new_ip: str) -> str:
        """Connection IP 교체
        
        모든 c= 라인의 IP 주소를 교체
        
        Args:
            sdp: 원본 SDP
            new_ip: 새 IP 주소
            
        Returns:
            수정된 SDP
        """
        lines = sdp.split('\n')
        modified_lines = []
        
        for line in lines:
            line = line.rstrip()
            if line.startswith('c='):
                # c=IN IP4 192.168.1.100 → c=IN IP4 NEW_IP
                parts = line.split()
                if len(parts) >= 3:
                    parts[2] = new_ip
                    line = ' '.join(parts)
            
            modified_lines.append(line)
        
        logger.debug("connection_ip_replaced", new_ip=new_ip)
        return '\n'.join(modified_lines)
    
    @staticmethod
    def replace_media_port(sdp: str, media_type: str, new_port: int) -> str:
        """미디어 포트 교체
        
        특정 미디어 타입의 포트를 교체
        
        Args:
            sdp: 원본 SDP
            media_type: 미디어 타입 (audio, video)
            new_port: 새 포트
            
        Returns:
            수정된 SDP
        """
        lines = sdp.split('\n')
        modified_lines = []
        
        for line in lines:
            line = line.rstrip()
            if line.startswith('m='):
                # m=audio 5004 RTP/AVP 0 8 101
                parts = line.split()
                if len(parts) >= 2 and parts[0] == f"m={media_type}":
                    parts[1] = str(new_port)
                    line = ' '.join(parts)
                    logger.debug("media_port_replaced",
                               media_type=media_type,
                               new_port=new_port)
            
            modified_lines.append(line)
        
        return '\n'.join(modified_lines)
    
    @staticmethod
    def remove_vendor_attributes(sdp: str) -> str:
        """벤더별 확장 속성 제거 (B2BUA에서 사용)
        
        PJSIP의 X-nat, Cisco의 X-* 등 벤더 특정 속성을 제거합니다.
        B2BUA는 이러한 속성을 relay하면 안됩니다.
        
        Args:
            sdp: 원본 SDP
            
        Returns:
            정리된 SDP
        """
        lines = sdp.split('\n')
        modified_lines = []
        
        vendor_prefixes = ['a=X-', 'a=x-']  # PJSIP: X-nat, Cisco: X-*
        
        for line in lines:
            line_stripped = line.rstrip()
            # 벤더 특정 속성인지 확인
            is_vendor_attr = any(line_stripped.startswith(prefix) for prefix in vendor_prefixes)
            
            if not is_vendor_attr:
                modified_lines.append(line_stripped)
            else:
                logger.debug("vendor_attribute_removed", attribute=line_stripped)
        
        return '\n'.join(modified_lines)
    
    @staticmethod
    def replace_rtcp_attribute(sdp: str, media_type: str, new_port: int, new_ip: str) -> str:
        """RTCP 속성의 포트와 IP 교체
        
        a=rtcp:4001 IN IP4 192.168.1.100 → a=rtcp:NEW_PORT IN IP4 NEW_IP
        
        Args:
            sdp: 원본 SDP
            media_type: 미디어 타입 ("audio" 또는 "video")
            new_port: 새 RTCP 포트
            new_ip: 새 IP 주소
            
        Returns:
            수정된 SDP
        """
        lines = sdp.split('\n')
        modified_lines = []
        in_target_media = False
        
        for line in lines:
            line_stripped = line.rstrip()
            
            # m= 라인으로 미디어 블록 감지
            if line_stripped.startswith('m='):
                in_target_media = line_stripped.startswith(f'm={media_type} ')
            
            # 타겟 미디어 블록 내의 rtcp 속성 교체
            if in_target_media and line_stripped.startswith('a=rtcp:'):
                # a=rtcp:4001 IN IP4 10.62.164.233
                parts = line_stripped.split()
                if len(parts) >= 4 and parts[1] == 'IN' and parts[2] == 'IP4':
                    # a=rtcp:PORT → PORT 추출
                    port_part = parts[0].split(':')[1]  # "a=rtcp:4001" → "4001"
                    line_stripped = f"a=rtcp:{new_port} IN IP4 {new_ip}"
                    logger.debug("rtcp_attribute_replaced", 
                                media_type=media_type,
                                new_port=new_port,
                                new_ip=new_ip)
            
            modified_lines.append(line_stripped)
        
        return '\n'.join(modified_lines)
    
    @staticmethod
    def replace_multiple_ports(
        sdp: str,
        audio_port: Optional[int] = None,
        video_port: Optional[int] = None,
    ) -> str:
        """여러 미디어 포트 한번에 교체
        
        Args:
            sdp: 원본 SDP
            audio_port: 새 오디오 포트 (None이면 변경 안 함)
            video_port: 새 비디오 포트 (None이면 변경 안 함)
            
        Returns:
            수정된 SDP
        """
        result = sdp
        
        if audio_port is not None:
            result = SDPManipulator.replace_media_port(result, "audio", audio_port)
        
        if video_port is not None:
            result = SDPManipulator.replace_media_port(result, "video", video_port)
        
        return result
    
    @staticmethod
    def rebuild_from_session(session: SDPSession) -> str:
        """SDPSession 객체로부터 SDP 문자열 재생성
        
        Args:
            session: SDPSession 객체
            
        Returns:
            SDP 문자열
        """
        lines = []
        
        # Version
        lines.append(f"v={session.version}")
        
        # Origin
        if session.origin:
            lines.append(f"o={session.origin}")
        
        # Session name
        lines.append(f"s={session.session_name}")
        
        # Connection (세션 레벨)
        if session.connection_ip:
            lines.append(f"c=IN IP4 {session.connection_ip}")
        
        # Timing
        lines.append(f"t={session.timing}")
        
        # Session 속성
        for attr_name, attr_value in session.attributes.items():
            if attr_value:
                lines.append(f"a={attr_name}:{attr_value}")
            else:
                lines.append(f"a={attr_name}")
        
        # Media descriptions
        for media in session.media_descriptions:
            # Media line
            formats_str = ' '.join(media.formats)
            lines.append(f"m={media.media_type} {media.port} {media.protocol} {formats_str}")
            
            # Media connection
            if media.connection_ip:
                lines.append(f"c=IN IP4 {media.connection_ip}")
            
            # Media 속성
            for attr_name, attr_value in media.attributes.items():
                if attr_value:
                    lines.append(f"a={attr_name}:{attr_value}")
                else:
                    lines.append(f"a={attr_name}")
        
        return '\n'.join(lines) + '\n'

