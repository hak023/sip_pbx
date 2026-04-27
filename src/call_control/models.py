"""
Call Control 도메인 모델

착신 라우팅 규칙(RoutingRule), 시간 스케줄(Schedule), 안내멘트(AnnouncementProfile).
"""

from __future__ import annotations

from enum import Enum
from typing import List, Literal, Optional

from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------


class RoutingAction(str, Enum):
    """착신 동작 유형."""

    DIRECT = "direct"               # A→B 직접 연결
    NO_ANSWER_AI = "no_answer_ai"   # N초 무응답 시 AI 응대
    IMMEDIATE_AI = "immediate_ai"   # 무조건 즉시 AI 응대
    BUSY_AI = "busy_ai"             # 착신자 통화 중일 때만 즉시 AI 응대
    FORWARD = "forward"             # (하위 호환) 무조건 착신전환 — forward_always 와 동일
    FORWARD_ALWAYS = "forward_always"           # 항상 착신번호를 forward_to 로 변경
    FORWARD_WHEN_BUSY = "forward_when_busy"     # 착신자 통화 중일 때만 forward_to 로 전환
    RING_GROUP = "ring_group"       # 착신 그룹 (여러 내선 동시/순차 링)
    BLOCK = "block"                 # 수신 거부 (SIP 603 Decline)


class RingGroupMode(str, Enum):
    """착신 그룹 링 방식."""

    SIMULTANEOUS = "simultaneous"   # 동시 링
    SEQUENTIAL = "sequential"       # 순차 링


class ForwardTargetKind(str, Enum):
    """착신 전환 대상 유형 (규칙의 forward_to 에 `fwd:<id>` 로 참조)."""

    SINGLE = "single"
    GROUP = "group"


class ForwardRingMode(str, Enum):
    """그룹일 때 실제 INVITE 1건으로 보낼 내선 선택 방식.

    동시(simultaneous): 대표번호·헌트그룹의 동시링 개념을 참고하되,
    B2BUA는 한 시점에 한 내선만 선택해 «등록·비통화중» 우선으로 고른다.
    순차(sequential): 목록 순서대로 유휴·등록된 내선을 선택.
    순환(circular): 현재는 순차와 동일(향후 마지막 응답 내선 기준 순환 확장 가능).
    """

    SIMULTANEOUS = "simultaneous"
    SEQUENTIAL = "sequential"
    CIRCULAR = "circular"


class DayOfWeek(str, Enum):
    """요일."""

    MON = "mon"
    TUE = "tue"
    WED = "wed"
    THU = "thu"
    FRI = "fri"
    SAT = "sat"
    SUN = "sun"


# ---------------------------------------------------------------------------
# Sub-models
# ---------------------------------------------------------------------------


class TimeRange(BaseModel):
    """시간 범위 (HH:MM 형식)."""

    start: str = Field(..., pattern=r"^\d{2}:\d{2}$", description="시작 시각 (HH:MM)")
    end: str = Field(..., pattern=r"^\d{2}:\d{2}$", description="종료 시각 (HH:MM)")


# ---------------------------------------------------------------------------
# Core models
# ---------------------------------------------------------------------------


class RoutingRule(BaseModel):
    """착신 라우팅 규칙.

    priority 가 낮을수록(=숫자가 작을수록) 먼저 평가된다.
    schedule_id 가 None 이면 항상(always) 적용.
    """

    id: str = Field(..., description="규칙 고유 ID (UUID)")
    owner: str = Field(..., description="적용 내선 번호 (callee)")
    name: str = Field(..., description="규칙 이름 (표시용)")
    priority: int = Field(default=100, ge=0, description="우선순위 (낮을수록 먼저 평가)")
    action: RoutingAction = Field(..., description="착신 동작")
    no_answer_timeout: int = Field(
        default=20,
        ge=5,
        le=60,
        description="무응답 AI 전환 대기 시간(초). action=NO_ANSWER_AI 일 때 유효.",
    )
    forward_to: Optional[str] = Field(
        default=None,
        description=(
            "착신전환 대상: 내선/SIP URI, 또는 등록 대상 참조 `fwd:<uuid>`. "
            "action=FORWARD|FORWARD_ALWAYS|FORWARD_WHEN_BUSY 일 때 필수."
        ),
    )
    announcement_id: Optional[str] = Field(
        default=None,
        description="착신 시 재생할 안내멘트 ID (선택).",
    )
    schedule_id: Optional[str] = Field(
        default=None,
        description="적용 시간 스케줄 ID. None = 항상 적용.",
    )
    enabled: bool = Field(default=True, description="규칙 활성화 여부")
    created_at: Optional[str] = Field(default=None, description="생성 시각 (ISO 8601)")
    updated_at: Optional[str] = Field(default=None, description="수정 시각 (ISO 8601)")


class Schedule(BaseModel):
    """착신 시간 스케줄.

    days + time_ranges 조합이 일치할 때 해당 스케줄이 '활성' 상태가 된다.
    include_holidays=True 이면 공휴일도 스케줄에 포함.
    """

    id: str = Field(..., description="스케줄 고유 ID (UUID)")
    owner: str = Field(..., description="적용 내선 번호")
    name: str = Field(..., description="스케줄 이름 (표시용)")
    days: List[DayOfWeek] = Field(
        default_factory=list,
        description="적용 요일 목록. 비어있으면 매일.",
    )
    time_ranges: List[TimeRange] = Field(
        default_factory=list,
        description="적용 시간 범위 목록. 비어있으면 하루 종일.",
    )
    include_holidays: bool = Field(
        default=False,
        description="공휴일을 요일 조건에 포함할지 여부",
    )
    holiday_country: str = Field(
        default="KR",
        description="공휴일 기준 국가 코드 (예: KR)",
    )
    timezone: str = Field(
        default="Asia/Seoul",
        description="스케줄 판단 기준 타임존",
    )
    created_at: Optional[str] = Field(default=None)
    updated_at: Optional[str] = Field(default=None)


class AnnouncementProfile(BaseModel):
    """착신 안내멘트 프로필.

    text 로 TTS 생성 또는 audio_file 경로에서 직접 재생.
    use_as_ringback_greeting=True 인 프로필은 SIP 링 단계(early media)에서
    발신자에게 1회 재생되는 인사말로 사용된다.
    generation_mode='suno' 인 경우 Suno AI 로 생성한 음원을 사용한다.
    """

    id: str = Field(..., description="안내멘트 고유 ID (UUID)")
    owner: str = Field(..., description="적용 내선 번호")
    name: str = Field(..., description="안내멘트 이름 (표시용)")
    text: str = Field(default="", description="TTS 생성용 텍스트 (generation_mode=tts 일 때 사용)")
    audio_file: Optional[str] = Field(
        default=None,
        description="업로드된 오디오 파일 경로 (None이면 TTS 사용)",
    )
    use_tts: bool = Field(default=True, description="True면 TTS, False면 audio_file 사용")
    use_as_ringback_greeting: bool = Field(
        default=False,
        description="True면 SIP 링 단계(early media)에서 발신자에게 재생되는 인사말로 사용",
    )
    # 음원 생성 모드: 'tts' | 'suno'
    generation_mode: str = Field(
        default="tts",
        description="음원 생성 방식. 'tts'=TTS 텍스트, 'suno'=Suno AI 음악 생성",
    )
    # TTS 배경음 옵션
    tts_background_music: bool = Field(
        default=False,
        description="TTS 음성에 배경음악을 합성할지 여부",
    )
    tts_background_style: Optional[str] = Field(
        default=None,
        description="배경음악 스타일 태그 문자열 (tts_background_music=True 일 때 사용)",
    )
    # Suno AI 생성 결과
    suno_lyrics: Optional[str] = Field(default=None, description="Suno AI 가사")
    suno_style: Optional[str] = Field(default=None, description="Suno AI 스타일 태그")
    suno_audio_url: Optional[str] = Field(default=None, description="Suno AI 생성 음원 URL")
    suno_task_id: Optional[str] = Field(default=None, description="Suno AI 작업 ID")
    created_at: Optional[str] = Field(default=None)
    updated_at: Optional[str] = Field(default=None)


# ---------------------------------------------------------------------------
# Request/Response helpers
# ---------------------------------------------------------------------------


class RoutingRuleCreate(BaseModel):
    """RoutingRule 생성 요청 (id/timestamps 제외)."""

    owner: str
    name: str
    priority: int = 100
    action: RoutingAction
    no_answer_timeout: int = 20
    forward_to: Optional[str] = None
    announcement_id: Optional[str] = None
    schedule_id: Optional[str] = None
    enabled: bool = True


class RoutingRuleUpdate(BaseModel):
    """RoutingRule 수정 요청 (모든 필드 선택)."""

    name: Optional[str] = None
    priority: Optional[int] = None
    action: Optional[RoutingAction] = None
    no_answer_timeout: Optional[int] = None
    forward_to: Optional[str] = None
    announcement_id: Optional[str] = None
    schedule_id: Optional[str] = None
    enabled: Optional[bool] = None


class ScheduleCreate(BaseModel):
    """Schedule 생성 요청."""

    owner: str
    name: str
    days: List[DayOfWeek] = []
    time_ranges: List[TimeRange] = []
    include_holidays: bool = False
    holiday_country: str = "KR"
    timezone: str = "Asia/Seoul"


class ScheduleUpdate(BaseModel):
    """Schedule 수정 요청."""

    name: Optional[str] = None
    days: Optional[List[DayOfWeek]] = None
    time_ranges: Optional[List[TimeRange]] = None
    include_holidays: Optional[bool] = None
    holiday_country: Optional[str] = None
    timezone: Optional[str] = None


class AnnouncementCreate(BaseModel):
    """AnnouncementProfile 생성 요청."""

    owner: str
    name: str
    text: str = ""
    audio_file: Optional[str] = None
    use_tts: bool = True
    use_as_ringback_greeting: bool = False
    generation_mode: str = "tts"
    tts_background_music: bool = False
    tts_background_style: Optional[str] = None
    suno_lyrics: Optional[str] = None
    suno_style: Optional[str] = None
    suno_audio_url: Optional[str] = None
    suno_task_id: Optional[str] = None


class AnnouncementUpdate(BaseModel):
    """AnnouncementProfile 수정 요청."""

    name: Optional[str] = None
    text: Optional[str] = None
    audio_file: Optional[str] = None
    use_tts: Optional[bool] = None
    use_as_ringback_greeting: Optional[bool] = None
    generation_mode: Optional[str] = None
    tts_background_music: Optional[bool] = None
    tts_background_style: Optional[str] = None
    suno_lyrics: Optional[str] = None
    suno_style: Optional[str] = None
    suno_audio_url: Optional[str] = None
    suno_task_id: Optional[str] = None


class PriorityUpdate(BaseModel):
    """우선순위 변경 요청."""

    priority: int = Field(..., ge=0, description="새 우선순위")


class RingGroup(BaseModel):
    """착신 그룹 — 여러 내선을 묶어 동시/순차 링."""

    id: str = Field(..., description="그룹 고유 ID (UUID)")
    owner: str = Field(..., description="관리 내선 번호")
    name: str = Field(..., description="그룹 이름")
    members: List[str] = Field(
        default_factory=list,
        description="멤버 내선 번호 목록",
    )
    mode: RingGroupMode = Field(
        default=RingGroupMode.SIMULTANEOUS,
        description="링 방식 (simultaneous=동시, sequential=순차)",
    )
    no_answer_timeout: int = Field(
        default=20,
        ge=5,
        le=60,
        description="전원 무응답 시 AI 전환 대기 시간(초)",
    )
    created_at: Optional[str] = None
    updated_at: Optional[str] = None


class RingGroupCreate(BaseModel):
    owner: str
    name: str
    members: List[str] = []
    mode: RingGroupMode = RingGroupMode.SIMULTANEOUS
    no_answer_timeout: int = 20


class RingGroupUpdate(BaseModel):
    name: Optional[str] = None
    members: Optional[List[str]] = None
    mode: Optional[RingGroupMode] = None
    no_answer_timeout: Optional[int] = None


class CallerFilter(BaseModel):
    """발신자 필터 — VIP/차단 등 특정 발신자 패턴에 별도 라우팅 적용."""

    id: str = Field(..., description="필터 고유 ID")
    owner: str = Field(..., description="관리 내선 번호")
    name: str = Field(..., description="필터 이름")
    pattern: str = Field(
        ...,
        description="발신번호 패턴 (정확 일치 또는 prefix*). 예: 010*, +8210*",
    )
    action: RoutingAction = Field(..., description="이 발신자에게 적용할 동작")
    no_answer_timeout: int = Field(default=20)
    forward_to: Optional[str] = None
    announcement_id: Optional[str] = None
    priority: int = Field(default=0, description="우선순위 (낮을수록 먼저)")
    enabled: bool = True
    created_at: Optional[str] = None
    updated_at: Optional[str] = None


class CallerFilterCreate(BaseModel):
    owner: str
    name: str
    pattern: str
    action: RoutingAction
    no_answer_timeout: int = 20
    forward_to: Optional[str] = None
    announcement_id: Optional[str] = None
    priority: int = 0
    enabled: bool = True


class OverflowPolicy(BaseModel):
    """통화량 오버플로우 정책 — 동시 통화 임계치 초과 시 AI 자동 전환."""

    owner: str = Field(..., description="내선 번호")
    enabled: bool = Field(default=False)
    max_concurrent_calls: int = Field(
        default=3,
        ge=1,
        le=100,
        description="임계치 (이 수 초과 시 overflow_action 적용)",
    )
    overflow_action: RoutingAction = Field(
        default=RoutingAction.IMMEDIATE_AI,
        description="임계치 초과 시 동작",
    )
    announcement_id: Optional[str] = None
    updated_at: Optional[str] = None


class ResolvedRoutingRule(BaseModel):
    """현재 시각에 적용 중인 규칙 조회 결과."""

    owner: str
    rule: Optional[RoutingRule] = None
    schedule: Optional[Schedule] = None
    is_schedule_active: bool = False
    current_time: str = ""
    description: str = ""


RingbackGenerationMode = Literal["tts", "suno"]
RingbackSunoGenerationStatus = Literal["idle", "pending", "complete", "failed"]


class RingbackScheduleAssignment(BaseModel):
    """시간 스케줄(또는 항상)에 따른 통화 연결음(TTS 또는 Suno 생성 MP3)."""

    id: str
    owner: str
    name: str = Field(default="", description="표시용 이름")
    schedule_id: Optional[str] = Field(
        default=None,
        description="call_schedules.id. None·빈 값이면 항상 적용.",
    )
    position: int = Field(default=0, ge=0, description="목록·평가 순서(위에서 아래)")
    enabled: bool = True
    generation_mode: RingbackGenerationMode = Field(
        default="suno",
        description="tts: 저장 시 생성한 tts_audio_path(WAV) 루프 | suno: suno_audio_path MP3 루프",
    )
    tts_text: str = ""
    tts_audio_path: Optional[str] = Field(
        default=None,
        description="TTS 모드일 때 설정 저장 시 Google TTS로 생성한 16kHz mono WAV 로컬 경로",
    )
    suno_lyrics: Optional[str] = None
    suno_style: Optional[str] = None
    suno_title: Optional[str] = None
    suno_vocal_gender: str = Field(default="m", description="m 또는 f")
    suno_duration_target: int = Field(default=60, ge=15, le=240)
    suno_audio_path: Optional[str] = None
    suno_audio_url: Optional[str] = None
    suno_task_id: Optional[str] = None
    suno_generation_status: RingbackSunoGenerationStatus = Field(
        default="idle",
        description="Suno: idle | pending(생성 중) | complete | failed",
    )
    created_at: Optional[str] = None
    updated_at: Optional[str] = None


class RingbackScheduleAssignmentOut(RingbackScheduleAssignment):
    """목록 API용 — 스케줄 이름 조인."""

    schedule_name: Optional[str] = None


class RingbackScheduleAssignmentCreate(BaseModel):
    owner: str
    name: str = ""
    schedule_id: Optional[str] = None
    enabled: bool = True
    generation_mode: RingbackGenerationMode = "suno"
    tts_text: str = ""
    tts_audio_path: Optional[str] = None
    suno_lyrics: Optional[str] = None
    suno_style: Optional[str] = None
    suno_title: Optional[str] = None
    suno_vocal_gender: str = "m"
    suno_duration_target: int = Field(default=60, ge=15, le=240)
    suno_audio_path: Optional[str] = None
    suno_audio_url: Optional[str] = None
    suno_task_id: Optional[str] = None
    suno_generation_status: RingbackSunoGenerationStatus = "idle"


class RingbackScheduleAssignmentUpdate(BaseModel):
    name: Optional[str] = None
    schedule_id: Optional[str] = None
    position: Optional[int] = Field(default=None, ge=0)
    enabled: Optional[bool] = None
    generation_mode: Optional[RingbackGenerationMode] = None
    tts_text: Optional[str] = None
    tts_audio_path: Optional[str] = None
    suno_lyrics: Optional[str] = None
    suno_style: Optional[str] = None
    suno_title: Optional[str] = None
    suno_vocal_gender: Optional[str] = None
    suno_duration_target: Optional[int] = Field(default=None, ge=15, le=240)
    suno_audio_path: Optional[str] = None
    suno_audio_url: Optional[str] = None
    suno_task_id: Optional[str] = None
    suno_generation_status: Optional[RingbackSunoGenerationStatus] = None


class RingbackAssignmentsReorderBody(BaseModel):
    """통화 연결음 할당 목록의 id 순서(위→아래)."""

    ordered_ids: List[str] = Field(..., min_length=1)


# ---------------------------------------------------------------------------
# 착신 전환 대상 (Call Control UI «착신 전환» 탭)
# ---------------------------------------------------------------------------


class ForwardTarget(BaseModel):
    """착신 규칙에서 `fwd:<id>` 로 참조하는 전환 대상."""

    id: str = Field(..., description="고유 ID (UUID)")
    owner: str = Field(..., description="관리 내선 (규칙 owner 와 동일해야 참조 유효)")
    name: str = Field(..., description="표시 이름")
    kind: ForwardTargetKind = Field(default=ForwardTargetKind.SINGLE)
    single_extension: Optional[str] = Field(
        default=None,
        description="kind=single 일 때 전환 내선 번호",
    )
    members: List[str] = Field(
        default_factory=list,
        description="kind=group 일 때 내선 번호 목록(순서 유지)",
    )
    ring_mode: ForwardRingMode = Field(default=ForwardRingMode.SIMULTANEOUS)
    created_at: Optional[str] = None
    updated_at: Optional[str] = None


class ForwardTargetCreate(BaseModel):
    owner: str
    name: str
    kind: ForwardTargetKind = ForwardTargetKind.SINGLE
    single_extension: Optional[str] = None
    members: List[str] = Field(default_factory=list)
    ring_mode: ForwardRingMode = ForwardRingMode.SIMULTANEOUS


class ForwardTargetUpdate(BaseModel):
    name: Optional[str] = None
    kind: Optional[ForwardTargetKind] = None
    single_extension: Optional[str] = None
    members: Optional[List[str]] = None
    ring_mode: Optional[ForwardRingMode] = None
