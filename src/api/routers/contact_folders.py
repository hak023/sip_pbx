"""연락처 사용자 폴더 REST."""

from __future__ import annotations

from typing import Any, Dict, Optional

import structlog
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from src.common.contact_folder_db import (
    default_unfiled_folder_id,
    delete_contact_folder,
    insert_contact_folder,
    list_contact_folders,
    update_contact_folder,
)

logger = structlog.get_logger(__name__)

router = APIRouter(prefix="/contact-folders", tags=["contact-folders"])


class ContactFolderCreate(BaseModel):
    owner: str = Field(..., description="테넌트 owner")
    name: str = Field(..., min_length=1)
    parent_id: Optional[str] = Field(None, description="없으면 루트")


class ContactFolderPatch(BaseModel):
    owner: str = Field(..., description="테넌트 owner")
    name: Optional[str] = None
    parent_id: Optional[str] = Field(
        None,
        description="부모 변경 시 값(빈 문자열이면 루트). 본 필드를 요청에 넣지 않으면 부모 유지.",
    )


@router.get("")
def api_list_contact_folders(owner: str) -> Dict[str, Any]:
    own = (owner or "").strip()
    items = list_contact_folders(owner=own)
    return {
        "items": items,
        "default_unfiled_folder_id": default_unfiled_folder_id(own) if own else None,
    }


@router.post("", status_code=201)
def api_create_contact_folder(body: ContactFolderCreate) -> Dict[str, Any]:
    row = insert_contact_folder(
        owner=body.owner.strip(),
        name=body.name.strip(),
        parent_id=body.parent_id,
    )
    if not row:
        raise HTTPException(status_code=400, detail="폴더를 만들 수 없습니다. 이름·owner·부모 폴더를 확인하세요.")
    return row


@router.patch("/{folder_id}")
def api_patch_contact_folder(folder_id: str, body: ContactFolderPatch) -> Dict[str, Any]:
    own = body.owner.strip()
    patch = body.model_dump(exclude_unset=True)
    has_parent = "parent_id" in patch
    try:
        row = update_contact_folder(
            folder_id=folder_id,
            owner=own,
            name=body.name.strip() if body.name is not None else None,
            parent_id=body.parent_id if has_parent else None,
            parent_id_explicit=has_parent,
            sort_order=None,
        )
    except ValueError as e:
        code = str(e)
        if code == "folder_cycle":
            raise HTTPException(status_code=400, detail="폴더를 자기 자신 또는 하위 폴더 안으로 옮길 수 없습니다.") from e
        if code == "invalid_parent":
            raise HTTPException(status_code=400, detail="유효하지 않은 부모 폴더입니다.") from e
        if code == "unfiled_must_stay_root":
            raise HTTPException(
                status_code=400,
                detail="기본 미분류 폴더는 최상위에만 둘 수 있습니다.",
            ) from e
        raise HTTPException(status_code=400, detail=str(e)) from e
    if not row:
        raise HTTPException(status_code=404, detail="폴더를 찾을 수 없습니다")
    return row


@router.delete("/{folder_id}")
def api_delete_contact_folder(folder_id: str, owner: str) -> Dict[str, Any]:
    own = (owner or "").strip()
    if own and folder_id.strip() == default_unfiled_folder_id(own):
        raise HTTPException(
            status_code=400,
            detail="기본 미분류 폴더는 삭제할 수 없습니다.",
        )
    ok = delete_contact_folder(folder_id=folder_id, owner=own)
    if not ok:
        raise HTTPException(status_code=404, detail="폴더를 찾을 수 없습니다")
    return {"ok": True}
