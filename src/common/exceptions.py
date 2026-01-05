"""커스텀 예외 클래스

SIP PBX 시스템의 모든 커스텀 예외 정의
"""


class SIPPBXError(Exception):
    """Base exception for all SIP PBX errors"""
    pass


# SIP Core Exceptions
class SIPError(SIPPBXError):
    """SIP 프로토콜 관련 에러"""
    pass


class SIPServerError(SIPError):
    """SIP 서버 에러"""
    pass


class SIPEndpointError(SIPError):
    """SIP Endpoint 에러"""
    pass


class SIPTransportError(SIPError):
    """SIP 트랜스포트 에러"""
    pass


class InvalidSIPMessageError(SIPError):
    """잘못된 SIP 메시지"""
    pass


# Media Exceptions
class MediaError(SIPPBXError):
    """미디어 처리 관련 에러"""
    pass


class PortPoolExhaustedError(MediaError):
    """포트 풀 고갈"""
    pass


class SDPParsingError(MediaError):
    """SDP 파싱 실패"""
    pass


class CodecNotSupportedError(MediaError):
    """지원되지 않는 코덱"""
    pass


# AI Exceptions
class AIError(SIPPBXError):
    """AI 모델 관련 에러"""
    pass


class ModelLoadError(AIError):
    """모델 로드 실패"""
    pass


class InferenceError(AIError):
    """추론 실패"""
    pass


class GPUMemoryError(AIError):
    """GPU 메모리 부족"""
    pass


# Configuration Exceptions
class ConfigurationError(SIPPBXError):
    """설정 관련 에러"""
    pass


# Event Exceptions
class EventError(SIPPBXError):
    """이벤트 처리 관련 에러"""
    pass


class WebhookDeliveryError(EventError):
    """Webhook 전달 실패"""
    pass

