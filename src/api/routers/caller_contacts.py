"""발신자 연락처(caller_contacts) REST — CID·설정 화면."""

from __future__ import annotations

from typing import Any, Dict, Optional

import structlog
from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from src.common.caller_contact_db import (
    delete_caller_contact,
    insert_caller_contact_manual,
    list_caller_contacts,
    resolve_caller_contact,
    update_caller_contact,
)

logger = structlog.get_logger(__name__)

router = APIRouter(prefix="/caller-contacts", tags=["caller-contacts"])


class CallerContactCreate(BaseModel):
    owner: str = Field(..., description="테넌트 owner")
    canonical_phone: str = Field(..., description="매칭용 숫자 키(needle 권장)")
    display_name: str = Field(..., min_length=1)
    memo: str = ""
    folder_id: Optional[str] = Field(None, description="contact_folders.id, 없으면 미분류")


class CallerContactUpdate(BaseModel):
    owner: str = Field(..., description="테넌트 owner")
    display_name: Optional[str] = None
    memo: Optional[str] = None
    canonical_phone: Optional[str] = None
    folder_id: Optional[str] = Field(
        None,
        description="폴더 이동. 요청 본문에 키를 넣고 null이면 미분류.",
    )


@router.get("")
def api_list_caller_contacts(
    owner: str = Query(..., description="테넌트 owner"),
    q: str = Query("", description="이름·번호·메모 검색"),
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
) -> Dict[str, Any]:
    items, total = list_caller_contacts(owner=owner, q=q, limit=limit, offset=offset)
    return {"total": total, "items": items}


@router.get("/resolve")
def api_resolve_caller_contact(
    owner: str = Query(..., description="테넌트 owner(착신·채팅 owner)"),
    phone: str = Query(..., description="상대 식별 — SIP user, sip:user@host, 숫자 등"),
) -> Dict[str, Any]:
    """문자 도크 등에서 peer 키로 연락처 표시명 조회."""
    row = resolve_caller_contact(owner.strip(), phone.strip())
    if not row:
        return {"found": False, "display_name": None, "canonical_phone": None}
    return {
        "found": True,
        "display_name": row.get("display_name"),
        "canonical_phone": row.get("canonical_phone"),
    }


@router.post("", status_code=201)
def api_create_caller_contact(body: CallerContactCreate) -> Dict[str, Any]:
    row = insert_caller_contact_manual(
        owner=body.owner.strip(),
        canonical_phone=body.canonical_phone.strip(),
        display_name=body.display_name.strip(),
        memo=(body.memo or "").strip(),
        folder_id=body.folder_id,
    )
    if not row:
        raise HTTPException(status_code=400, detail="owner, canonical_phone, display_name 필수")
    return row


@router.patch("/{contact_id}")
def api_patch_caller_contact(contact_id: str, body: CallerContactUpdate) -> Dict[str, Any]:
    if body.display_name is not None and not (body.display_name or "").strip():
        raise HTTPException(status_code=422, detail="표시 이름은 비울 수 없습니다.")
    if body.canonical_phone is not None and not (body.canonical_phone or "").strip():
        raise HTTPException(status_code=422, detail="매칭 번호는 비울 수 없습니다.")
    patch = body.model_dump(exclude_unset=True)
    has_folder = "folder_id" in patch
    if (
        body.display_name is None
        and body.memo is None
        and body.canonical_phone is None
        and not has_folder
    ):
        raise HTTPException(status_code=422, detail="변경할 필드를 하나 이상 보내세요.")
    try:
        row = update_caller_contact(
            contact_id=contact_id,
            owner=body.owner.strip(),
            display_name=body.display_name,
            memo=body.memo,
            canonical_phone=body.canonical_phone,
            folder_id=body.folder_id if has_folder else None,
            folder_id_explicit=has_folder,
        )
    except ValueError as e:
        if str(e) == "duplicate_canonical_phone":
            raise HTTPException(
                status_code=409,
                detail="이미 같은 매칭 번호로 등록된 연락처가 있습니다.",
            ) from e
        if str(e) == "invalid_folder_id":
            raise HTTPException(status_code=400, detail="유효하지 않은 폴더입니다.") from e
        raise HTTPException(status_code=400, detail=str(e)) from e
    if not row:
        raise HTTPException(status_code=404, detail="연락처를 찾을 수 없습니다")
    return row


@router.delete("/{contact_id}")
def api_delete_caller_contact(
    contact_id: str,
    owner: str = Query(..., description="테넌트 owner"),
) -> Dict[str, Any]:
    ok = delete_caller_contact(contact_id=contact_id, owner=owner.strip())
    if not ok:
        raise HTTPException(status_code=404, detail="연락처를 찾을 수 없습니다")
    return {"ok": True}
