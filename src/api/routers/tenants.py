"""테넌트(착신번호) 관리 API

등록된 테넌트(착신번호) 목록 조회 및 설정 관리.
로그인 페이지에서 테넌트 선택 목록을 제공하기 위해 사용됩니다.
"""

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import Optional, Dict, List
import structlog
import json

from src.services.seed_data import get_tenant_list, _get_tenant_config
from src.services.knowledge_service import get_knowledge_service

logger = structlog.get_logger(__name__)
router = APIRouter()

knowledge_service = get_knowledge_service()


@router.get("/")
async def list_tenants():
    """등록된 테넌트(착신번호) 목록 조회

    Returns:
        테넌트 목록 (owner, name, type 등)
    """
    try:
        # 정적 목록 + VectorDB 존재 확인
        tenants = get_tenant_list()

        # VectorDB에서 실제 존재 여부 확인
        for tenant in tenants:
            config = await _get_tenant_config(knowledge_service, tenant["owner"])
            tenant["is_active"] = config is not None

        return {"tenants": tenants}

    except Exception as e:
        logger.error("list_tenants_failed", error=str(e))
        # 폴백: 정적 목록만 반환
        return {"tenants": get_tenant_list()}


@router.get("/{owner}")
async def get_tenant(owner: str):
    """특정 테넌트 상세 정보 조회

    Args:
        owner: 착신번호 (예: "1004")

    Returns:
        테넌트 설정 (name, greeting_templates, system_prompt 등)
    """
    try:
        config = await _get_tenant_config(knowledge_service, owner)
        if not config:
            raise HTTPException(status_code=404, detail=f"Tenant {owner} not found")

        metadata = config.get("metadata", {})
        return {
            "owner": owner,
            "name": metadata.get("tenant_name", ""),
            "name_en": metadata.get("tenant_name_en", ""),
            "type": metadata.get("tenant_type", ""),
            "description": metadata.get("description", ""),
            "service_description": metadata.get("service_description", ""),
            "main_phone": metadata.get("main_phone", ""),
            "website": metadata.get("website", ""),
            "business_hours": metadata.get("business_hours", ""),
            "greeting_templates": metadata.get("greeting_templates", "[]"),
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error("get_tenant_failed", owner=owner, error=str(e))
        raise HTTPException(status_code=500, detail="Failed to get tenant info")


class TenantConfigUpdate(BaseModel):
    """테넌트 설정 수정 요청"""
    tenant_name: Optional[str] = None
    description: Optional[str] = None
    service_description: Optional[str] = None
    main_phone: Optional[str] = None
    website: Optional[str] = None
    business_hours: Optional[str] = None
    greeting_templates: Optional[List[str]] = None
    system_prompt_template: Optional[str] = None


@router.put("/{owner}")
async def update_tenant(owner: str, config: TenantConfigUpdate):
    """테넌트 설정 수정

    Args:
        owner: 착신번호 (예: "1004")
        config: 수정할 설정 필드 (null이 아닌 필드만 업데이트)

    Returns:
        수정된 테넌트 설정
    """
    try:
        import asyncio
        
        existing = await _get_tenant_config(knowledge_service, owner)
        if not existing:
            raise HTTPException(status_code=404, detail=f"Tenant {owner} not found")

        metadata = existing.get("metadata", {})
        
        # null이 아닌 필드만 업데이트
        update_fields = config.model_dump(exclude_none=True)
        for key, value in update_fields.items():
            if key == "greeting_templates":
                metadata[key] = json.dumps(value, ensure_ascii=False)
            else:
                metadata[key] = value

        # VectorDB에 업데이트
        doc_id = f"tenant_config_{owner}"
        text = existing.get("text", f"{metadata.get('tenant_name', '')} tenant config")
        
        embedding = await knowledge_service.embedder.embed(text)
        loop = asyncio.get_event_loop()
        await loop.run_in_executor(
            None,
            lambda: knowledge_service.vector_db.collection.upsert(
                ids=[doc_id],
                embeddings=[embedding],
                documents=[text],
                metadatas=[metadata],
            ),
        )

        logger.info("tenant_config_updated", owner=owner, updated_fields=list(update_fields.keys()))
        return {
            "owner": owner,
            "updated": list(update_fields.keys()),
            "message": f"Tenant {owner} config updated successfully",
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error("update_tenant_failed", owner=owner, error=str(e), exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to update tenant config")
