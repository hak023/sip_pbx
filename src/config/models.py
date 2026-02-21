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
    DIRECT = "direct"
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


class SIPTimersConfig(BaseModel):
    """SIP 타이머 설정 (RFC 3261, RFC 4028)"""
    # 트랜잭션 타이머
    t1: float = Field(default=0.5, ge=0.1, le=2.0, description="RTT Estimate (초)")
    t2: float = Field(default=4.0, ge=1.0, le=10.0, description="최대 재전송 간격 (초)")
    t4: float = Field(default=5.0, ge=1.0, le=10.0, description="최대 메시지 수명 (초)")
    
    # 세션 타이머
    invite_timeout: int = Field(default=30, ge=10, le=120, description="INVITE 응답 대기 시간 (초)")
    bye_timeout: int = Field(default=32, ge=10, le=120, description="BYE 응답 대기 시간 (초)")
    register_expires: int = Field(default=3600, ge=60, le=86400, description="REGISTER 만료 시간 (초)")
    
    # Session-Expires (RFC 4028)
    session_expires: int = Field(default=1800, ge=90, le=7200, description="세션 만료 시간 (초)")
    min_se: int = Field(default=90, ge=60, le=600, description="최소 세션 갱신 간격 (초)")
    session_refresher: str = Field(default="uas", description="세션 갱신 주체 (uac/uas)")
    
    # 부재중 타임아웃
    no_answer_timeout: int = Field(default=10, ge=5, le=60, description="AI 활성화 타임아웃 (초)")
    
    @field_validator('session_expires')
    @classmethod
    def validate_session_expires(cls, v: int, info) -> int:
        """session_expires가 min_se보다 크거나 같은지 검증"""
        if 'min_se' in info.data and v < info.data['min_se']:
            raise ValueError(f"session_expires ({v}) must be >= min_se ({info.data['min_se']})")
        return v


class SIPConfig(BaseModel):
    """SIP 서버 설정"""
    listen_ip: str = Field(default="0.0.0.0", description="SIP 서버 리스닝 IP")
    listen_port: int = Field(default=5060, ge=1, le=65535, description="SIP 서버 포트")
    advertised_ip: Optional[str] = Field(default=None, description="외부 노출 IP (SDP c= 라인용)")
    transport: TransportType = Field(default=TransportType.UDP, description="전송 프로토콜")
    max_concurrent_calls: int = Field(default=100, ge=1, le=1000, description="최대 동시 통화 수")
    timers: SIPTimersConfig = Field(default_factory=SIPTimersConfig, description="SIP 타이머 설정")


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
    rtp_bind_ip: str = Field(default="0.0.0.0", description="RTP 소켓 bind IP (0.0.0.0=모든 인터페이스)")
    port_pool: PortPoolConfig = Field(default_factory=PortPoolConfig)
    rtp_timeout: int = Field(default=60, ge=10, le=300, description="RTP 타임아웃 (초)")
    cleanup_interval: int = Field(default=10, ge=1, le=60, description="세션 정리 주기 (초)")
    codec_priority: List[str] = Field(
        default=["opus", "pcmu", "pcma"],
        description="코덱 우선순위"
    )


class STTConfig(BaseModel):
    """STT (Speech-to-Text) 설정"""
    model_config = {"protected_namespaces": ()}
    
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
    model_config = {"protected_namespaces": ()}
    
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


class PostProcessingSTTConfig(BaseModel):
    """후처리 STT 설정"""
    enabled: bool = Field(default=False, description="후처리 STT 활성화 여부")
    language: str = Field(default="ko-KR", description="언어 코드")
    enable_diarization: bool = Field(default=True, description="화자 분리 활성화")
    model: str = Field(default="telephony", description="STT 모델")
    enable_automatic_punctuation: bool = Field(default=True, description="자동 구두점")
    enable_word_time_offsets: bool = Field(default=True, description="단어별 타임스탬프")


class KnowledgeExtractionConfig(BaseModel):
    """지식 추출 설정 (v1/v2 호환)"""
    enabled: bool = Field(default=False, description="지식 추출 활성화")
    version: str = Field(default="v1", description="파이프라인 버전 (v1 | v2)")
    min_confidence: float = Field(default=0.7, description="LLM 판단 최소 신뢰도")
    chunk_size: int = Field(default=500, description="텍스트 청크 크기 (문자)")
    chunk_overlap: int = Field(default=50, description="청크 오버랩 크기 (문자)")
    min_text_length: int = Field(default=10, description="최소 텍스트 길이")
    # v2 전용
    steps: Optional[dict] = Field(default=None, description="추출 스텝 설정 (v2)")
    quality: Optional[dict] = Field(default=None, description="품질 검증 설정 (v2)")
    auto_approve: Optional[dict] = Field(default=None, description="자동 승인 설정 (v2)")
    max_llm_calls_per_extraction: int = Field(default=6, description="추출당 최대 LLM 호출 수")
    skip_short_calls_seconds: int = Field(default=30, description="스킵할 짧은 통화 기준 (초)")


class RecordingConfig(BaseModel):
    """녹음 설정"""
    enabled: bool = Field(default=True, description="녹음 활성화")
    output_dir: str = Field(default="./recordings", description="출력 디렉토리")
    format: str = Field(default="wav", description="파일 포맷")
    sample_rate: int = Field(default=16000, description="샘플링 레이트")
    post_processing_stt: PostProcessingSTTConfig = Field(default_factory=PostProcessingSTTConfig)
    knowledge_extraction: KnowledgeExtractionConfig = Field(default_factory=KnowledgeExtractionConfig, description="지식 추출 설정")


class GoogleCloudConfig(BaseModel):
    """Google Cloud 설정"""
    project_id: Optional[str] = Field(default=None, description="프로젝트 ID")
    credentials_path: Optional[str] = Field(default=None, description="인증 파일 경로")
    quota_management: Optional[dict] = Field(default=None, description="Quota 관리")
    stt: Optional[dict] = Field(default=None, description="STT 설정")
    tts: Optional[dict] = Field(default=None, description="TTS 설정")
    gemini: Optional[dict] = Field(default=None, description="Gemini 설정")


class TransferConfig(BaseModel):
    """호 전환(Transfer) 설정"""
    enabled: bool = Field(default=True, description="전환 기능 활성화")
    ring_timeout: int = Field(default=30, ge=5, le=120, description="착신 대기 시간 (초)")
    announcement_mode: str = Field(default="template", description="안내 멘트 방식 (template | llm)")
    announcement_template: Optional[str] = Field(
        default=None,
        description="전환 안내 멘트 템플릿 ({department}, {phone} 치환)"
    )
    waiting_message: str = Field(default="연결 중입니다. 잠시만 기다려주세요.", description="대기 중 안내")
    retry_enabled: bool = Field(default=True, description="실패 시 재시도 허용")
    max_retries: int = Field(default=2, ge=0, le=5, description="최대 재시도 횟수")
    min_similarity_threshold: float = Field(default=0.75, ge=0.0, le=1.0, description="전환 의도 감지 최소 유사도")
    hold_music_file: Optional[str] = Field(default=None, description="Hold music 파일 경로")


class OutboundRetryConfig(BaseModel):
    """아웃바운드 재시도 설정"""
    enabled: bool = Field(default=True, description="재시도 활성화")
    max_retries: int = Field(default=2, ge=0, le=5, description="최대 재시도 횟수")
    retry_interval: int = Field(default=300, ge=30, le=3600, description="재시도 간격 (초)")
    retry_on: List[str] = Field(default=["no_answer", "busy"], description="재시도 대상 상태")


class OutboundAIConfig(BaseModel):
    """아웃바운드 AI 대화 설정"""
    greeting_template: str = Field(
        default="안녕하세요, {display_name} AI 비서입니다. {purpose} 관련하여 연락드렸습니다.",
        description="첫 인사말 템플릿"
    )
    closing_template: str = Field(
        default="확인 감사합니다. 좋은 하루 되세요.",
        description="끝인사 템플릿"
    )
    max_turns: int = Field(default=20, ge=5, le=50, description="최대 대화 턴 수")
    task_completion_check: bool = Field(default=True, description="태스크 완료 자동 감지")


class OutboundResultConfig(BaseModel):
    """아웃바운드 결과 저장 설정"""
    save_transcript: bool = Field(default=True, description="대화록 저장")
    save_recording: bool = Field(default=True, description="녹음 파일 저장")
    generate_summary: bool = Field(default=True, description="AI 요약 생성")


class OutboundConfig(BaseModel):
    """AI 아웃바운드 콜 설정"""
    enabled: bool = Field(default=True, description="아웃바운드 기능 활성화")
    default_gateway: Optional[str] = Field(default=None, description="SIP Gateway 주소 (예: sip:gw.example.com:5060)")
    max_concurrent_calls: int = Field(default=5, ge=1, le=50, description="동시 아웃바운드 콜 최대 수")
    ring_timeout: int = Field(default=30, ge=5, le=120, description="링 타임아웃 (초)")
    max_call_duration: int = Field(default=300, ge=30, le=1800, description="최대 통화 시간 (초)")
    retry: OutboundRetryConfig = Field(default_factory=OutboundRetryConfig, description="재시도 정책")
    ai: OutboundAIConfig = Field(default_factory=OutboundAIConfig, description="AI 대화 설정")
    result: OutboundResultConfig = Field(default_factory=OutboundResultConfig, description="결과 저장 설정")


class AIVoicebotConfig(BaseModel):
    """AI 보이스봇 설정"""
    model_config = {"extra": "allow"}  # ✅ 추가 필드 허용
    
    enabled: bool = Field(default=True, description="보이스봇 활성화")
    no_answer_timeout: int = Field(default=10, description="부재중 타임아웃")
    greeting_message: str = Field(default="안녕하세요", description="인사말")
    google_cloud: Optional[GoogleCloudConfig] = Field(default=None, description="Google Cloud 설정")
    resilience: Optional[dict] = Field(default=None, description="Resilience 설정")
    vector_db: Optional[dict] = Field(default=None, description="Vector DB 설정")
    embedding: Optional[dict] = Field(default=None, description="Embedding 설정")
    rag: Optional[dict] = Field(default=None, description="RAG 설정")
    knowledge_extractor: Optional[dict] = Field(default=None, description="Knowledge Extractor 설정")
    recording: Optional[RecordingConfig] = Field(default=None, description="녹음 설정")
    transfer: Optional[TransferConfig] = Field(default=None, description="호 전환 설정")
    outbound: Optional[OutboundConfig] = Field(default=None, description="AI 아웃바운드 콜 설정")
    vad: Optional[dict] = Field(default=None, description="VAD 설정")
    barge_in: Optional[dict] = Field(default=None, description="Barge-in 설정")
    audio_buffer: Optional[dict] = Field(default=None, description="Audio Buffer 설정")
    logging: Optional[dict] = Field(default=None, description="로깅 설정")


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
    ai_voicebot: Optional[AIVoicebotConfig] = Field(default=None, description="AI 보이스봇 설정")

    class Config:
        """Pydantic Config"""
        use_enum_values = True
        validate_assignment = True

