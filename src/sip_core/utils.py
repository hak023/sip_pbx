"""SIP 유틸리티 함수

SIP URI 파싱 및 extension 추출 등
"""
import re
from typing import Optional
import structlog

logger = structlog.get_logger(__name__)


def extract_extension_from_uri(sip_uri: Optional[str]) -> str:
    """SIP URI에서 extension(username) 추출
    
    Args:
        sip_uri: SIP URI 문자열 (예: "sip:1004@10.0.0.1", "<sip:1004@domain.com>")
        
    Returns:
        str: extension (추출 실패 시 빈 문자열)
        
    Examples:
        >>> extract_extension_from_uri("sip:1004@10.0.0.1")
        "1004"
        >>> extract_extension_from_uri("<sip:1004@domain.com>")
        "1004"
        >>> extract_extension_from_uri("sip:1004@domain.com;tag=abc")
        "1004"
        >>> extract_extension_from_uri("invalid")
        ""
    """
    if not sip_uri:
        return ""
    
    # <sip:username@domain> 또는 sip:username@domain 형식
    match = re.search(r'sip:([^@;>]+)@', sip_uri)
    if match:
        return match.group(1)
    
    logger.debug("extract_extension_failed", uri=sip_uri)
    return ""


def extract_tag_from_header(header: Optional[str]) -> Optional[str]:
    """SIP 헤더에서 tag 파라미터 추출
    
    Args:
        header: SIP 헤더 (From, To 등)
        
    Returns:
        Optional[str]: tag 값 (없으면 None)
    """
    if not header:
        return None
    
    match = re.search(r';tag=([^;>\s]+)', header)
    if match:
        return match.group(1)
    return None
