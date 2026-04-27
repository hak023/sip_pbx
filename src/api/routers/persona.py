"""
Persona API Router

조직 페르소나 CRUD API.
Frontend에서 페르소나를 설정/수정/삭제할 수 있도록 REST API 제공.
"""

from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel
from typing import List, Optional
from datetime import datetime
import structlog

from src.config.models import OrganizationPersona
from src.ai_voicebot.knowledge.persona_service import get_persona_service

logger = structlog.get_logger(__name__)

router = APIRouter(prefix="/api/persona", tags=["persona"])


class CreatePersonaRequest(BaseModel):
    """Persona 생성 요청.

    ``sip_message_ai_reply_*`` 필드는 DB·API 호환용으로만 남아 있으며,
    SIP MESSAGE AI 자동응답 ON/OFF·접두어는 **설정 → 채팅·SIP MESSAGE** ``PUT /api/chat/relay`` 의
    ``message_ai_reply_enabled`` / ``message_ai_reply_prefix`` 만 적용된다.
    """
    owner: str
    name: str
    description: str
    scope_keywords: Optional[List[str]] = None
    chitchat_response_template: Optional[str] = None
    escalation_mode: str = "hitl"
    transfer_extension: Optional[str] = None
    sip_message_ai_reply_enabled: bool = False
    sip_message_ai_reply_prefix: Optional[str] = None


class UpdatePersonaRequest(BaseModel):
    """Persona 수정 요청"""
    name: Optional[str] = None
    description: Optional[str] = None
    scope_keywords: Optional[List[str]] = None
    chitchat_response_template: Optional[str] = None
    enabled: Optional[bool] = None
    escalation_mode: Optional[str] = None
    transfer_extension: Optional[str] = None
    sip_message_ai_reply_enabled: Optional[bool] = None
    sip_message_ai_reply_prefix: Optional[str] = None


class EscalationOnlyUpdate(BaseModel):
    """지식 베이스가 페르소나 문구를 담당할 때 — HITL/호전환 필드만 갱신."""

    escalation_mode: str = "hitl"
    transfer_extension: Optional[str] = None


class PersonaResponse(BaseModel):
    """Persona 응답"""
    owner: str
    name: str
    description: str
    scope_keywords: List[str]
    chitchat_response_template: Optional[str]
    escalation_mode: str = "hitl"
    transfer_extension: Optional[str] = None
    sip_message_ai_reply_enabled: bool = False
    sip_message_ai_reply_prefix: Optional[str] = None
    enabled: bool
    created_at: Optional[str]
    updated_at: Optional[str]


@router.post("/", response_model=PersonaResponse, summary="Persona 생성")
async def create_persona(req: CreatePersonaRequest):
    """
    조직 페르소나 생성
    
    Request Body:
    ```json
    {
        "owner": "1004",
        "name": "기상청",
        "description": "기상청은 날씨정보와 기상특보 등을 안내하는 국가 공공기관입니다.",
        "scope_keywords": ["날씨", "예보", "특보", "기상"],
        "chitchat_response_template": "죄송합니다. 저는 기상 관련 업무만 도와드릴 수 있어요."
    }
    ```
    """
    service = get_persona_service()
    if not service:
        raise HTTPException(status_code=503, detail="PersonaService not initialized")
    
    # 기존 persona 확인
    existing = await service.get_persona(req.owner)
    if existing:
        raise HTTPException(
            status_code=409,
            detail=f"Persona already exists for owner {req.owner}. Use PUT to update."
        )
    
    persona = OrganizationPersona(
        owner=req.owner,
        name=req.name,
        description=req.description,
        scope_keywords=req.scope_keywords or [],
        chitchat_response_template=req.chitchat_response_template,
        escalation_mode=req.escalation_mode or "hitl",
        transfer_extension=req.transfer_extension,
        sip_message_ai_reply_enabled=bool(req.sip_message_ai_reply_enabled),
        sip_message_ai_reply_prefix=req.sip_message_ai_reply_prefix,
        enabled=True,
        created_at=datetime.now().isoformat(),
    )
    
    success = await service.save_persona(persona)
    if not success:
        raise HTTPException(status_code=500, detail="Failed to save persona")
    
    return PersonaResponse(**persona.dict())


@router.get("/{owner}", response_model=PersonaResponse, summary="Persona 조회")
async def get_persona(owner: str):
    """Owner의 Persona 조회"""
    service = get_persona_service()
    if not service:
        raise HTTPException(status_code=503, detail="PersonaService not initialized")
    
    persona = await service.get_persona(owner)
    if not persona:
        raise HTTPException(status_code=404, detail=f"Persona not found for owner {owner}")
    
    return PersonaResponse(**persona.dict())


@router.put("/{owner}", response_model=PersonaResponse, summary="Persona 수정 또는 생성")
async def update_persona(owner: str, req: UpdatePersonaRequest):
    """
    Persona 수정 (부분 업데이트) 또는 생성
    
    기존 Persona가 있으면 업데이트, 없으면 자동 생성합니다.
    """
    service = get_persona_service()
    if not service:
        raise HTTPException(status_code=503, detail="PersonaService not initialized")
    
    # 기존 persona 조회
    persona = await service.get_persona(owner)
    
    if not persona:
        # Persona가 없으면 자동 생성 (name, description은 필수)
        if not req.name or not req.description:
            raise HTTPException(
                status_code=400, 
                detail="name and description are required when creating a new persona"
            )
        
        persona = OrganizationPersona(
            owner=owner,
            name=req.name,
            description=req.description,
            scope_keywords=req.scope_keywords or [],
            chitchat_response_template=req.chitchat_response_template,
            escalation_mode=req.escalation_mode or "hitl",
            transfer_extension=req.transfer_extension,
            sip_message_ai_reply_enabled=bool(req.sip_message_ai_reply_enabled)
            if req.sip_message_ai_reply_enabled is not None
            else False,
            sip_message_ai_reply_prefix=req.sip_message_ai_reply_prefix,
            enabled=req.enabled if req.enabled is not None else True,
            created_at=datetime.now().isoformat(),
            updated_at=datetime.now().isoformat(),
        )
        logger.info("persona_auto_created_on_put", owner=owner, name=req.name)
    else:
        # 기존 persona 업데이트 (부분 업데이트)
        if req.name is not None:
            persona.name = req.name
        if req.description is not None:
            persona.description = req.description
        if req.scope_keywords is not None:
            persona.scope_keywords = req.scope_keywords
        if req.chitchat_response_template is not None:
            persona.chitchat_response_template = req.chitchat_response_template
        if req.enabled is not None:
            persona.enabled = req.enabled
        if req.escalation_mode is not None:
            persona.escalation_mode = req.escalation_mode
        if req.transfer_extension is not None:
            persona.transfer_extension = req.transfer_extension
        _fs = getattr(req, "model_fields_set", set()) or set()
        if "sip_message_ai_reply_enabled" in _fs:
            persona.sip_message_ai_reply_enabled = bool(req.sip_message_ai_reply_enabled)
        if "sip_message_ai_reply_prefix" in _fs:
            persona.sip_message_ai_reply_prefix = req.sip_message_ai_reply_prefix

        persona.updated_at = datetime.now().isoformat()
    
    success = await service.save_persona(persona)
    if not success:
        raise HTTPException(status_code=500, detail="Failed to save persona")
    
    return PersonaResponse(**persona.dict())


@router.put("/{owner}/escalation", response_model=PersonaResponse, summary="에스컬레이션만 저장")
async def upsert_escalation_only(owner: str, req: EscalationOnlyUpdate):
    """조직 설명·키워드는 지식 베이스에서 관리하고, AI 한계 시 동작만 저장한다.

    기존 Persona가 없으면 플레이스홀더 name/description으로 한 건 생성한 뒤 에스컬레이션만 설정한다.
    """
    service = get_persona_service()
    if not service:
        raise HTTPException(status_code=503, detail="PersonaService not initialized")

    mode = (req.escalation_mode or "hitl").strip().lower()
    if mode not in ("hitl", "transfer", "none"):
        raise HTTPException(
            status_code=400,
            detail="escalation_mode must be 'hitl', 'transfer', or 'none'",
        )
    ext = (req.transfer_extension or "").strip()

    KB_PLACEHOLDER_NAME = "(지식 베이스)"
    KB_PLACEHOLDER_DESC = (
        "조직 성격·지식·키워드는 지식 베이스에서 관리합니다. "
        "이 레코드는 AI가 답변 불가일 때의 동작(HITL / SIP 호전환)만 저장합니다."
    )

    persona = await service.get_persona(owner)
    now = datetime.now().isoformat()

    if not persona:
        persona = OrganizationPersona(
            owner=owner,
            name=KB_PLACEHOLDER_NAME,
            description=KB_PLACEHOLDER_DESC,
            scope_keywords=[],
            chitchat_response_template=None,
            escalation_mode=mode,
            transfer_extension=ext if ext and mode == "transfer" else None,
            sip_message_ai_reply_enabled=False,
            sip_message_ai_reply_prefix=None,
            enabled=True,
            created_at=now,
            updated_at=now,
        )
        logger.info("persona_escalation_seed_created", owner=owner, escalation_mode=mode)
    else:
        persona.escalation_mode = mode
        persona.transfer_extension = ext if ext and mode == "transfer" else None
        persona.updated_at = now
        logger.info("persona_escalation_updated", owner=owner, escalation_mode=mode)

    success = await service.save_persona(persona)
    if not success:
        raise HTTPException(status_code=500, detail="Failed to save escalation settings")

    return PersonaResponse(**persona.dict())


@router.delete("/{owner}", summary="Persona 삭제")
async def delete_persona(owner: str):
    """Persona 삭제"""
    service = get_persona_service()
    if not service:
        raise HTTPException(status_code=503, detail="PersonaService not initialized")
    
    success = await service.delete_persona(owner)
    if not success:
        raise HTTPException(status_code=500, detail="Failed to delete persona")
    
    return {"success": True, "owner": owner}


@router.get("/", response_model=List[PersonaResponse], summary="모든 Persona 목록")
async def list_personas():
    """모든 Persona 목록 조회 (관리 UI용)"""
    service = get_persona_service()
    if not service:
        raise HTTPException(status_code=503, detail="PersonaService not initialized")
    
    personas = await service.list_personas()
    return [PersonaResponse(**p) for p in personas]


@router.post("/{owner}/check-relevance", summary="Query 관련성 체크 (테스트용)")
async def check_query_relevance(owner: str, query: str):
    """
    Query가 조직 페르소나와 관련되는지 테스트
    
    Request Body:
    ```json
    {
        "query": "너도 개나리를 좋아하니?"
    }
    ```
    
    Response:
    ```json
    {
        "is_relevant": false,
        "similarity": 0.25,
        "persona_found": true,
        "should_classify_as": "chitchat"
    }
    ```
    """
    service = get_persona_service()
    if not service:
        raise HTTPException(status_code=503, detail="PersonaService not initialized")
    
    result = await service.check_query_relevance(query, owner)
    
    return {
        **result,
        "should_classify_as": "question" if result["is_relevant"] else "chitchat"
    }
