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
    def _split_sdp_lines(sdp: str) -> list:
        """SDP를 라인별로 분리 (CRLF 또는 LF 지원)
        
        RFC 3261: SIP 메시지는 CRLF(\r\n)를 사용해야 함
        하지만 일부 구현은 LF(\n)만 사용할 수 있으므로 둘 다 지원
        
        Args:
            sdp: SDP 문자열
            
        Returns:
            라인 리스트
        """
        return sdp.split('\r\n') if '\r\n' in sdp else sdp.split('\n')
    
    @staticmethod
    def _join_sdp_lines(lines: list) -> str:
        """SDP 라인들을 결합 (항상 CRLF 사용)
        
        RFC 3261 준수: 항상 CRLF(\r\n)로 결합
        
        Args:
            lines: 라인 리스트
            
        Returns:
            CRLF로 결합된 SDP 문자열
        """
        return '\r\n'.join(lines)
    
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
                    # RTCP 포트 추출 (a=rtcp:PORT ...)
                    if attr_name == 'rtcp' and attr_value:
                        try:
                            # "13555 IN IP4 10.106.33.75" → 13555
                            rtcp_port = int(attr_value.split()[0])
                            current_media.rtcp_port = rtcp_port
                        except (ValueError, IndexError):
                            pass  # 파싱 실패 시 무시 (RTP+1 사용)
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
    def _split_sdp_lines(sdp: str) -> list:
        """SDP를 라인별로 분리 (CRLF 또는 LF 지원)"""
        return sdp.split('\r\n') if '\r\n' in sdp else sdp.split('\n')
    
    @staticmethod
    def _join_sdp_lines(lines: list) -> str:
        """SDP 라인들을 결합 (항상 CRLF 사용)"""
        return '\r\n'.join(lines)
    
    @staticmethod
    def replace_origin_ip(sdp: str, new_ip: str) -> str:
        """Origin IP 교체
        
        o= 라인의 IP 주소를 교체
        o=<username> <sess-id> <sess-version> <nettype> <addrtype> <unicast-address>
        예: o=1001 3147 388 IN IP4 10.205.18.125 → o=1001 3147 388 IN IP4 NEW_IP
        
        Args:
            sdp: 원본 SDP
            new_ip: 새 IP 주소
            
        Returns:
            수정된 SDP
        """
        lines = SDPManipulator._split_sdp_lines(sdp)
        modified_lines = []
        
        for line in lines:
            line = line.rstrip()
            if line.startswith('o='):
                # o=1001 3147 388 IN IP4 10.205.18.125
                parts = line.split()
                if len(parts) >= 6:
                    # 마지막 부분이 IP 주소
                    parts[5] = new_ip
                    line = ' '.join(parts)
                    logger.debug("origin_ip_replaced", new_ip=new_ip)
            
            modified_lines.append(line)
        
        return SDPManipulator._join_sdp_lines(modified_lines)
    
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
        lines = SDPManipulator._split_sdp_lines(sdp)
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
        return SDPManipulator._join_sdp_lines(modified_lines)
    
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
        lines = SDPManipulator._split_sdp_lines(sdp)
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
        
        return SDPManipulator._join_sdp_lines(modified_lines)
    
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
        lines = SDPManipulator._split_sdp_lines(sdp)
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
        
        return SDPManipulator._join_sdp_lines(modified_lines)
    
    @staticmethod
    def has_rtcp_attribute(sdp: str, media_type: str) -> bool:
        """SDP에 특정 미디어 타입의 RTCP 속성이 있는지 확인
        
        Args:
            sdp: SDP 문자열
            media_type: 미디어 타입 ("audio" 또는 "video")
            
        Returns:
            bool: a=rtcp: 속성이 있으면 True, 없으면 False
        """
        lines = SDPManipulator._split_sdp_lines(sdp)
        in_target_media = False
        
        for line in lines:
            line_stripped = line.strip()
            
            # m= 라인으로 미디어 블록 감지
            if line_stripped.startswith('m='):
                in_target_media = line_stripped.startswith(f'm={media_type} ')
            
            # 타겟 미디어 블록 내의 rtcp 속성 확인
            if in_target_media and line_stripped.startswith('a=rtcp:'):
                return True
        
        return False
    
    @staticmethod
    def remove_problematic_attributes(sdp: str) -> str:
        """Linphone 호환성 문제를 일으키는 특정 SDP 속성만 제거
        
        일부 SIP 클라이언트(특히 Linphone)는 다음 속성을 거부하고 488 Not Acceptable Here를 반환합니다:
        - a=rtcp-xr:* (RTCP Extended Reports, RFC 3611)
        - a=record:* (비표준 속성, Linphone 자체 확장)
        
        다른 속성들(a=rtcp-fb:, a=ssrc: 등)은 유지하여 미디어 협상이 정상적으로 이루어지도록 합니다.
        
        Args:
            sdp: 원본 SDP
            
        Returns:
            문제 속성이 제거된 SDP
        """
        lines = SDPManipulator._split_sdp_lines(sdp)
        modified_lines = []
        
        # Linphone이 거부하는 속성 패턴
        problematic_attributes = [
            'rtcp-xr:',      # RTCP Extended Reports (Linphone 488 원인)
            'record:',       # 비표준 (Linphone 488 원인)
        ]
        
        for line in lines:
            line_stripped = line.rstrip()
            
            # a= 라인인지 확인
            if line_stripped.startswith('a='):
                # 문제 속성인지 확인
                is_problematic = any(line_stripped.startswith(f'a={attr}') for attr in problematic_attributes)
                
                if is_problematic:
                    logger.debug("problematic_attribute_removed", attribute=line_stripped[:30])
                    continue  # 이 라인 건너뛰기
            
            modified_lines.append(line_stripped)
        
        return SDPManipulator._join_sdp_lines(modified_lines)
    
    @staticmethod
    def remove_rtcp_attribute(sdp: str, media_type: str) -> str:
        """SDP에서 특정 미디어 타입의 RTCP 속성 제거 (RTP+1 암묵적 사용)
        
        Bypass/Reflecting 모드에서 RTCP 포트 형식 불일치 문제를 방지하기 위해
        a=rtcp: 속성을 제거하고 RFC 3605의 기본 동작(RTP+1)을 사용합니다.
        
        Args:
            sdp: SDP 문자열
            media_type: 미디어 타입 ("audio" 또는 "video")
            
        Returns:
            a=rtcp: 속성이 제거된 SDP
        """
        lines = SDPManipulator._split_sdp_lines(sdp)
        modified_lines = []
        in_target_media = False
        removed = False
        
        for line in lines:
            line_stripped = line.rstrip()
            
            # m= 라인으로 미디어 블록 감지
            if line_stripped.startswith('m='):
                in_target_media = line_stripped.startswith(f'm={media_type} ')
            
            # 타겟 미디어 블록 내의 rtcp 속성은 건너뜀 (제거)
            if in_target_media and line_stripped.startswith('a=rtcp:'):
                removed = True
                logger.debug("rtcp_attribute_removed",
                            media_type=media_type,
                            line=line_stripped[:50])
                continue  # 이 라인은 건너뜀
            
            modified_lines.append(line_stripped)
        
        if removed:
            logger.info("rtcp_attribute_removed_using_rtp_plus_1",
                       media_type=media_type)
        
        return SDPManipulator._join_sdp_lines(modified_lines)
    
    @staticmethod
    def replace_rtcp_attribute(sdp: str, media_type: str, new_port: int, new_ip: str) -> str:
        """RTCP 속성의 포트를 SHORT FORMAT으로 교체
        
        클라이언트 호환성을 위해 항상 short format (a=rtcp:PORT)으로 출력합니다.
        - a=rtcp:4001 IN IP4 192.168.1.100 → a=rtcp:NEW_PORT
        - a=rtcp:4001 → a=rtcp:NEW_PORT
        
        Args:
            sdp: 원본 SDP
            media_type: 미디어 타입 ("audio" 또는 "video")
            new_port: 새 RTCP 포트
            new_ip: 새 IP 주소 (short format에서는 사용하지 않음, 호환성 유지용)
            
        Returns:
            수정된 SDP (a=rtcp:는 항상 short format)
        """
        lines = SDPManipulator._split_sdp_lines(sdp)
        modified_lines = []
        in_target_media = False
        
        for line in lines:
            line_stripped = line.rstrip()
            
            # m= 라인으로 미디어 블록 감지
            if line_stripped.startswith('m='):
                in_target_media = line_stripped.startswith(f'm={media_type} ')
            
            # 타겟 미디어 블록 내의 rtcp 속성 교체
            if in_target_media and line_stripped.startswith('a=rtcp:'):
                # 원본 형식과 관계없이 항상 short format으로 출력
                line_stripped = f"a=rtcp:{new_port}"
                logger.debug("rtcp_attribute_replaced_to_short_format", 
                            media_type=media_type,
                            new_port=new_port)
            
            modified_lines.append(line_stripped)
        
        return SDPManipulator._join_sdp_lines(modified_lines)
    
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
    def sanitize_sdp_for_compatibility(sdp: str) -> str:
        """SDP를 호환성을 위해 정리 (고급 RTCP 속성 제거)
        
        Linphone, MizuDroid 등 다양한 클라이언트와의 호환성을 위해
        고급/비표준 RTCP 속성을 제거하고 필수 속성만 유지합니다.
        
        제거되는 속성:
        - a=rtcp:* (명시적 RTCP 포트, RTP+1 암묵적 사용으로 변경)
        - a=rtcp-xr:* (RTCP Extended Reports, RFC 3611)
        - a=rtcp-fb:* (RTCP Feedback, RFC 4585)
        - a=record:* (비표준 속성)
        - a=crypto:* (SRTP 암호화, 구현 미완성 시 문제 가능)
        - a=ice-*, a=candidate:* (ICE, 구현 미완성 시 문제 가능)
        
        유지되는 속성:
        - a=rtpmap:* (코덱 매핑, 필수)
        - a=fmtp:* (코덱 파라미터, 필수)
        - a=sendrecv/sendonly/recvonly/inactive (미디어 방향, 필수)
        - a=ptime:* (패킷화 시간)
        - a=maxptime:* (최대 패킷화 시간)
        
        Args:
            sdp: 원본 SDP
            
        Returns:
            정리된 SDP
        """
        lines = SDPManipulator._split_sdp_lines(sdp)
        modified_lines = []
        
        # 제거할 속성 패턴 (세션 레벨 + 미디어 레벨)
        unsafe_attributes = [
            'rtcp-xr:',      # RTCP Extended Reports
            'rtcp-fb:',      # RTCP Feedback
            'rtcp:',         # RTCP 명시적 포트 (호환성 문제 방지, RTP+1 암묵적 사용)
            'record:',       # 비표준 (Linphone 등)
            'crypto:',       # SRTP (B2BUA가 지원 안 함)
            'ice-ufrag:',    # ICE
            'ice-pwd:',      # ICE
            'ice-options:',  # ICE
            'candidate:',    # ICE candidates
            'ssrc:',         # SSRC 속성 (B2BUA에서 의미 없음)
            'ssrc-group:',   # SSRC 그룹
            'rtcp-mux',      # RTCP Multiplexing (B2BUA가 명시적 RTCP 포트 사용)
            'rtcp-rsize',    # RTCP Reduced Size
        ]
        
        removed_count = 0
        
        for line in lines:
            line_stripped = line.rstrip()
            
            # 속성 라인 체크
            if line_stripped.startswith('a='):
                # 제거할 속성인지 확인
                should_remove = any(
                    line_stripped.startswith(f'a={attr}')
                    for attr in unsafe_attributes
                )
                
                if should_remove:
                    removed_count += 1
                    logger.debug("sdp_attribute_removed_for_compatibility",
                                attribute=line_stripped[:50])  # 로그에는 앞 50자만
                    continue  # 이 라인은 건너뜀
            
            # 안전한 라인은 유지
            modified_lines.append(line_stripped)
        
        if removed_count > 0:
            logger.info("sdp_sanitized_for_compatibility",
                       removed_attributes=removed_count,
                       message=f"Removed {removed_count} advanced/non-standard attributes for compatibility")
        
        return SDPManipulator._join_sdp_lines(modified_lines)
    
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
        
        return SDPManipulator._join_sdp_lines(lines) + '\n'

