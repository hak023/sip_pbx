"""Pydantic models for API"""
from pydantic import BaseModel, EmailStr
from typing import Optional, List, Literal, Dict, Any
from datetime import datetime


# User & Auth
class User(BaseModel):
    """대시보드 사용자. 착신번호 기반 로그인 시 email은 식별자(예: 1004@voicebot.local)로 사용."""
    id: str
    email: str  # 착신번호 기반일 때는 "{extension}@voicebot.local" 형식 (EmailStr 아님)
    name: str
    role: Literal["admin", "operator", "viewer"]
    is_active: bool = True
    created_at: datetime
    last_login: Optional[datetime] = None


class LoginRequest(BaseModel):
    """착신번호 기반 로그인 요청"""
    extension: str  # 착신번호 (예: "1004")
    # 기존 호환성을 위해 email/password도 Optional로 유지
    email: Optional[EmailStr] = None
    password: Optional[str] = None


class TenantInfo(BaseModel):
    """테넌트 정보 (로그인 응답에 포함)"""
    owner: str
    name: str
    type: str


class LoginResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user: User
    tenant: Optional[TenantInfo] = None


# Call Models
class CallerInfo(BaseModel):
    uri: str
    name: Optional[str] = None
    number: Optional[str] = None


class ActiveCall(BaseModel):
    call_id: str
    caller: CallerInfo
    callee: CallerInfo
    status: Literal["ringing", "active", "on-hold", "ending"]
    is_ai_handled: bool
    duration: int  # seconds
    current_question: Optional[str] = None
    ai_confidence: Optional[float] = None
    needs_hitl: bool = False


class ConversationMessage(BaseModel):
    role: Literal["user", "assistant", "system", "operator"]
    content: str
    timestamp: datetime
    is_final: bool = True
    confidence: Optional[float] = None
    audio_file: Optional[str] = None


# Knowledge Base
class KnowledgeEntryCreate(BaseModel):
    text: str
    category: str
    keywords: List[str]
    metadata: Optional[Dict[str, Any]] = {}


class KnowledgeEntryUpdate(BaseModel):
    text: Optional[str] = None
    category: Optional[str] = None
    keywords: Optional[List[str]] = None
    metadata: Optional[Dict[str, Any]] = None


class KnowledgeEntry(BaseModel):
    id: str
    text: str
    category: str
    keywords: List[str]
    metadata: Dict[str, Any]
    created_at: datetime
    updated_at: Optional[datetime] = None


class KnowledgeListResponse(BaseModel):
    items: List[KnowledgeEntry]
    total: int
    page: int
    limit: int


# Capability (AI 서비스)
class CapabilityCreate(BaseModel):
    """서비스(Capability) 생성"""
    display_name: str
    text: str
    category: str
    response_type: Literal["info", "api_call", "transfer", "collect"] = "info"
    keywords: List[str] = []
    priority: int = 50
    is_active: bool = True
    owner: Optional[str] = None
    # response_type별 선택 필드
    api_endpoint: Optional[str] = None
    api_method: Optional[Literal["GET", "POST"]] = None
    api_params: Optional[Dict[str, Any]] = None
    transfer_to: Optional[str] = None
    phone_display: Optional[str] = None
    collect_fields: Optional[List[Dict[str, Any]]] = None


class CapabilityUpdate(BaseModel):
    """서비스(Capability) 수정"""
    display_name: Optional[str] = None
    text: Optional[str] = None
    category: Optional[str] = None
    response_type: Optional[Literal["info", "api_call", "transfer", "collect"]] = None
    keywords: Optional[List[str]] = None
    priority: Optional[int] = None
    is_active: Optional[bool] = None
    owner: Optional[str] = None
    api_endpoint: Optional[str] = None
    api_method: Optional[Literal["GET", "POST"]] = None
    api_params: Optional[Dict[str, Any]] = None
    transfer_to: Optional[str] = None
    collect_fields: Optional[List[Dict[str, Any]]] = None


class CapabilityEntry(BaseModel):
    """서비스(Capability) 응답"""
    id: str
    display_name: str
    text: str
    category: str
    response_type: str = "info"
    keywords: List[str] = []
    priority: int = 50
    is_active: bool = True
    owner: Optional[str] = None
    api_endpoint: Optional[str] = None
    api_method: Optional[str] = None
    api_params: Optional[Dict[str, Any]] = None
    transfer_to: Optional[str] = None
    phone_display: Optional[str] = None
    collect_fields: Optional[List[Dict[str, Any]]] = None
    created_at: str = ""
    updated_at: Optional[str] = None


class CapabilityListResponse(BaseModel):
    """서비스 목록 응답"""
    items: List[CapabilityEntry]
    total: int


class CapabilityReorderRequest(BaseModel):
    """서비스 순서 변경"""
    ordered_ids: List[str]


class GuideTextResponse(BaseModel):
    """가이드 멘트 응답"""
    text: str
    capability_count: int
    cached: bool
    generated_at: str


# Extraction (지식 추출 리뷰)
class ExtractionEntry(BaseModel):
    """추출된 지식 항목"""
    id: str
    doc_type: Literal["knowledge", "qa_pair", "entity"]
    text: str
    category: str
    confidence_score: float
    review_status: Literal["pending", "approved", "rejected", "edited"] = "pending"
    hallucination_check: str = ""
    dedup_status: str = "unique"
    extraction_source: str = "call"
    extraction_call_id: str = ""
    extraction_timestamp: str = ""
    pipeline_version: str = ""
    owner: str = ""
    # QA 전용
    question: Optional[str] = None
    source_speaker: Optional[str] = None
    # Entity 전용
    entity_type: Optional[str] = None
    normalized_value: Optional[str] = None
    # 활용
    usage_count: int = 0
    keywords: str = ""
    reviewed_by: Optional[str] = None
    reviewed_at: Optional[str] = None


class ExtractionListResponse(BaseModel):
    """추출 목록 응답"""
    items: List[ExtractionEntry]
    total: int


class ExtractionReviewRequest(BaseModel):
    """리뷰 요청"""
    action: Literal["approve", "reject", "edit"]
    edited_text: Optional[str] = None
    edited_category: Optional[str] = None
    reviewer: str = "operator"


class ExtractionStatsResponse(BaseModel):
    """추출 통계 응답"""
    total: int
    pending: int
    approved: int
    rejected: int
    auto_approved: int
    by_doc_type: Dict[str, int]
    by_category: Dict[str, int]
    avg_confidence: float


class BatchDedupRequest(BaseModel):
    """§7 누적 기반 추출: 클러스터·중복 제거 요청"""
    owner: Optional[str] = None
    similarity_threshold: float = 0.92
    limit: int = 500
    apply: bool = False  # True 시 비대표 항목에 dedup_status=merged 반영


class BatchDedupResponse(BaseModel):
    """배치 중복 제거 결과"""
    total: int
    clusters: int
    representative_ids: List[str]
    merged_count: int
    by_category: Dict[str, int]


# HITL
class HITLRequest(BaseModel):
    call_id: str
    question: str
    context: Dict[str, Any]
    urgency: Literal["high", "medium", "low"]
    timestamp: datetime


class HITLResponse(BaseModel):
    call_id: str
    response_text: str
    save_to_kb: bool = False
    category: Optional[str] = None


# Metrics
class DashboardMetrics(BaseModel):
    active_calls: int
    hitl_queue_size: int
    avg_ai_confidence: float
    today_calls_count: int
    avg_response_time: float
    knowledge_base_size: int

