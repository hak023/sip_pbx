"""설정 모델 정의

Pydantic을 사용한 타입 안전 설정 검증 모델
"""

from typing import List, Optional
from enum import Enum
from pydantic import BaseModel, Field, field_validator, IPvAnyAddress


class TransportType(str, Enum):
    """SIP 트랜스포트 타입"""
    UDP = "udp"
    TCP = "tcp"
    TLS = "tls"


class MediaMode(str, Enum):
    """미디어 처리 모드"""
    BYPASS = "bypass"
    REFLECTING = "reflecting"


class DeviceType(str, Enum):
    """AI 모델 실행 디바이스"""
    CUDA = "cuda"
    CPU = "cpu"


class LogLevel(str, Enum):
    """로그 레벨"""
    DEBUG = "DEBUG"
    INFO = "INFO"
    WARNING = "WARNING"
    ERROR = "ERROR"
    CRITICAL = "CRITICAL"


class LogFormat(str, Enum):
    """로그 포맷"""
    JSON = "json"
    TEXT = "text"


class SIPConfig(BaseModel):
    """SIP 서버 설정"""
    listen_ip: str = Field(default="0.0.0.0", description="SIP 서버 리스닝 IP")
    listen_port: int = Field(default=5060, ge=1, le=65535, description="SIP 서버 포트")
    transport: TransportType = Field(default=TransportType.UDP, description="전송 프로토콜")
    max_concurrent_calls: int = Field(default=100, ge=1, le=1000, description="최대 동시 통화 수")


class PortPoolConfig(BaseModel):
    """포트 풀 설정"""
    start: int = Field(default=10000, ge=1024, le=65535, description="시작 포트")
    end: int = Field(default=20000, ge=1024, le=65535, description="종료 포트")

    @field_validator('end')
    @classmethod
    def validate_port_range(cls, v: int, info) -> int:
        """포트 범위 검증"""
        if 'start' in info.data and v <= info.data['start']:
            raise ValueError(f"end port ({v}) must be greater than start port ({info.data['start']})")
        return v


class MediaConfig(BaseModel):
    """미디어 처리 설정"""
    mode: MediaMode = Field(default=MediaMode.REFLECTING, description="미디어 처리 모드")
    port_pool: PortPoolConfig = Field(default_factory=PortPoolConfig)
    rtp_timeout: int = Field(default=60, ge=10, le=300, description="RTP 타임아웃 (초)")
    cleanup_interval: int = Field(default=10, ge=1, le=60, description="세션 정리 주기 (초)")
    codec_priority: List[str] = Field(
        default=["opus", "pcmu", "pcma"],
        description="코덱 우선순위"
    )


class STTConfig(BaseModel):
    """STT (Speech-to-Text) 설정"""
    model_size: str = Field(default="large-v3", description="모델 크기 (tiny, base, small, medium, large-v3)")
    device: DeviceType = Field(default=DeviceType.CUDA, description="실행 디바이스")
    language: str = Field(default="auto", description="언어 (auto, ko, en)")
    beam_size: int = Field(default=5, ge=1, le=10, description="빔 서치 크기")
    vad_filter: bool = Field(default=True, description="VAD 필터 사용 여부")
    compute_type: str = Field(default="float16", description="연산 타입 (float16, int8, int8_float16)")
    batch_size: int = Field(default=8, ge=1, le=32, description="배치 크기")
    sample_rate: int = Field(default=16000, description="샘플링 레이트 (Hz)")


class EmotionConfig(BaseModel):
    """감정 분석 설정"""
    model: str = Field(default="speechbrain/emotion-recognition", description="감정 분석 모델")
    device: DeviceType = Field(default=DeviceType.CUDA, description="실행 디바이스")
    threshold: float = Field(default=0.7, ge=0.0, le=1.0, description="감지 임계치")
    sample_rate: int = Field(default=16000, ge=8000, le=48000, description="샘플링 레이트")


class TextClassifierConfig(BaseModel):
    """텍스트 분류 설정"""
    model_korean: str = Field(default="beomi/KcELECTRA-base", description="한국어 분류 모델")
    model_english: str = Field(default="distilbert-base-uncased", description="영어 분류 모델")
    device: DeviceType = Field(default=DeviceType.CUDA, description="실행 디바이스")
    threshold: float = Field(default=0.8, ge=0.0, le=1.0, description="분류 임계치")


class ProfanityDictConfig(BaseModel):
    """욕설 사전 설정"""
    path: str = Field(default="config/profanity_dict.yaml", description="욕설 사전 파일 경로")
    enabled: bool = Field(default=True, description="욕설 사전 사용 여부")


class AIConfig(BaseModel):
    """AI 분석 설정"""
    enabled: bool = Field(default=True, description="AI 분석 활성화 여부")
    stt: STTConfig = Field(default_factory=STTConfig)
    emotion: EmotionConfig = Field(default_factory=EmotionConfig)
    text_classifier: TextClassifierConfig = Field(default_factory=TextClassifierConfig)
    profanity_dict: ProfanityDictConfig = Field(default_factory=ProfanityDictConfig)


class EventThresholdsConfig(BaseModel):
    """이벤트 임계치 설정"""
    profanity: float = Field(default=0.8, ge=0.0, le=1.0, description="욕설 임계치")
    anger: float = Field(default=0.7, ge=0.0, le=1.0, description="화남 임계치")
    threatening: float = Field(default=0.75, ge=0.0, le=1.0, description="위협 임계치")
    combined_alert: bool = Field(default=True, description="복합 알림 활성화")


class SeverityLevelsConfig(BaseModel):
    """심각도 레벨 설정"""
    low: float = Field(default=0.5, ge=0.0, le=1.0)
    medium: float = Field(default=0.7, ge=0.0, le=1.0)
    high: float = Field(default=0.85, ge=0.0, le=1.0)
    critical: float = Field(default=0.95, ge=0.0, le=1.0)


class EventsConfig(BaseModel):
    """이벤트 및 알림 설정"""
    webhook_urls: List[str] = Field(default=[], description="Webhook URL 리스트")
    webhook_timeout: int = Field(default=10, ge=1, le=60, description="Webhook 타임아웃 (초)")
    webhook_retries: int = Field(default=3, ge=0, le=10, description="Webhook 재시도 횟수")
    thresholds: EventThresholdsConfig = Field(default_factory=EventThresholdsConfig)
    severity_levels: SeverityLevelsConfig = Field(default_factory=SeverityLevelsConfig)


class CDRConfig(BaseModel):
    """CDR (Call Detail Record) 설정"""
    enabled: bool = Field(default=True, description="CDR 기록 활성화")
    output_dir: str = Field(default="/var/log/sip-pbx/cdr", description="CDR 출력 디렉토리")
    filename_pattern: str = Field(default="cdr-%Y-%m-%d.jsonl", description="파일명 패턴")
    rotation: str = Field(default="daily", description="로테이션 주기 (daily, hourly)")
    retention_days: int = Field(default=90, ge=1, le=3650, description="보관 기간 (일)")


class LoggingConfig(BaseModel):
    """로깅 설정"""
    level: LogLevel = Field(default=LogLevel.INFO, description="로그 레벨")
    format: LogFormat = Field(default=LogFormat.JSON, description="로그 포맷")
    output: str = Field(default="stdout", description="로그 출력 (stdout, file)")
    file_path: Optional[str] = Field(default=None, description="로그 파일 경로")
    max_bytes: int = Field(default=104857600, ge=1048576, description="최대 파일 크기 (바이트)")
    backup_count: int = Field(default=10, ge=1, le=100, description="백업 파일 수")


class MonitoringConfig(BaseModel):
    """모니터링 설정"""
    prometheus_port: int = Field(default=9090, ge=1, le=65535, description="Prometheus 포트")
    prometheus_path: str = Field(default="/metrics", description="메트릭 경로")
    health_check_port: int = Field(default=8080, ge=1, le=65535, description="헬스체크 포트")
    health_check_interval: int = Field(default=10, ge=1, le=60, description="헬스체크 간격 (초)")


class GPUBatchSizeConfig(BaseModel):
    """GPU 배치 크기 설정"""
    stt: int = Field(default=4, ge=1, le=32, description="STT 배치 크기")
    emotion: int = Field(default=8, ge=1, le=64, description="감정 분석 배치 크기")
    text_classifier: int = Field(default=16, ge=1, le=128, description="텍스트 분류 배치 크기")


class GPUConfig(BaseModel):
    """GPU 리소스 관리 설정"""
    device_id: int = Field(default=0, ge=0, description="CUDA 디바이스 ID")
    memory_fraction: float = Field(default=0.9, ge=0.1, le=1.0, description="최대 GPU 메모리 사용률")
    batch_size: GPUBatchSizeConfig = Field(default_factory=GPUBatchSizeConfig)


class SecurityConfig(BaseModel):
    """보안 설정"""
    admin_api_key: str = Field(default="change-me-in-production", description="Admin API 키")
    webhook_secret: str = Field(default="change-me-in-production", description="Webhook 비밀 키")
    ip_whitelist: dict = Field(
        default={"enabled": False, "allowed_ips": []},
        description="IP 화이트리스트 설정"
    )


class Config(BaseModel):
    """전체 설정 모델"""
    sip: SIPConfig = Field(default_factory=SIPConfig)
    media: MediaConfig = Field(default_factory=MediaConfig)
    ai: AIConfig = Field(default_factory=AIConfig)
    events: EventsConfig = Field(default_factory=EventsConfig)
    cdr: CDRConfig = Field(default_factory=CDRConfig)
    logging: LoggingConfig = Field(default_factory=LoggingConfig)
    monitoring: MonitoringConfig = Field(default_factory=MonitoringConfig)
    gpu: GPUConfig = Field(default_factory=GPUConfig)
    security: SecurityConfig = Field(default_factory=SecurityConfig)

    class Config:
        """Pydantic Config"""
        use_enum_values = True
        validate_assignment = True

