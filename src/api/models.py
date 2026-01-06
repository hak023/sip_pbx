"""Pydantic models for API"""
from pydantic import BaseModel, EmailStr
from typing import Optional, List, Literal, Dict, Any
from datetime import datetime


# User & Auth
class User(BaseModel):
    id: str
    email: EmailStr
    name: str
    role: Literal["admin", "operator", "viewer"]
    is_active: bool = True
    created_at: datetime
    last_login: Optional[datetime] = None


class LoginRequest(BaseModel):
    email: EmailStr
    password: str


class LoginResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user: User


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

