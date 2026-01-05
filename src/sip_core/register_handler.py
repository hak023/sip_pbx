"""REGISTER 요청 핸들러

SIP REGISTER 메시지 처리 (항상 200 OK 응답)
"""

from typing import Optional, Dict, Any
from src.sip_core.models.enums import SIPResponseCode
from src.common.logger import get_logger

logger = get_logger(__name__)


class RegisterHandler:
    """REGISTER 요청 처리자
    
    요구사항: 모든 REGISTER 요청을 항상 200 OK로 응답
    """
    
    def __init__(self):
        """초기화"""
        logger.info("register_handler_initialized")
    
    def handle_register(
        self,
        from_uri: str,
        to_uri: str,
        contact: Optional[str] = None,
        expires: Optional[int] = None,
        call_id: Optional[str] = None,
    ) -> tuple[int, Dict[str, Any]]:
        """REGISTER 요청 처리
        
        Args:
            from_uri: SIP From URI
            to_uri: SIP To URI (일반적으로 From과 동일)
            contact: SIP Contact 헤더 (등록할 주소)
            expires: Expires 값 (초) - None이면 기본값 3600
            call_id: SIP Call-ID 헤더
            
        Returns:
            tuple[응답 코드, 응답 데이터]
        """
        # Expires 기본값 설정
        if expires is None:
            expires = 3600  # 기본 1시간
        
        # 로깅 (향후 인증 기능 확장 고려)
        logger.info("register_received",
                   from_uri=from_uri,
                   to_uri=to_uri,
                   contact=contact,
                   expires=expires,
                   call_id=call_id)
        
        # 응답 데이터 준비
        response_data = {
            "contact": contact,
            "expires": expires,
            "from_uri": from_uri,
            "to_uri": to_uri,
        }
        
        # 항상 200 OK 응답
        logger.info("register_accepted",
                   from_uri=from_uri,
                   contact=contact,
                   expires=expires)
        
        return SIPResponseCode.OK, response_data
    
    def parse_register_info(self, from_uri: str, contact: Optional[str]) -> Dict[str, Any]:
        """REGISTER 정보 파싱 (유틸리티)
        
        Args:
            from_uri: From URI
            contact: Contact 헤더
            
        Returns:
            파싱된 정보 딕셔너리
        """
        info = {
            "user": None,
            "domain": None,
            "contact_ip": None,
            "contact_port": None,
        }
        
        # From URI 파싱: sip:user@domain
        if from_uri and "@" in from_uri:
            parts = from_uri.replace("sip:", "").split("@")
            if len(parts) >= 2:
                info["user"] = parts[0]
                info["domain"] = parts[1].split(":")[0]  # domain:port에서 domain만
        
        # Contact IP/Port 파싱
        if contact and "@" in contact:
            try:
                # sip:user@192.168.1.100:5060 형태
                addr_part = contact.replace("sip:", "").split("@")[1]
                if ":" in addr_part:
                    ip, port = addr_part.split(":")
                    info["contact_ip"] = ip
                    info["contact_port"] = int(port)
                else:
                    info["contact_ip"] = addr_part
                    info["contact_port"] = 5060  # 기본 포트
            except (ValueError, IndexError):
                pass
        
        return info

