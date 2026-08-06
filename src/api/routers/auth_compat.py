"""
프론트 호환: GET /api/tenants, POST /api/auth/login

운영에서는 실제 인증으로 교체 가능. 기본은 내선(extension) 선택 로그인.
"""

from __future__ import annotations

import json
import os
import secrets
from typing import Any, Dict, List

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

router = APIRouter(tags=["auth-compat"])


def _tenant_rows() -> List[Dict[str, Any]]:
    raw = os.environ.get("SIP_TENANTS_JSON", "").strip()
    if raw:
        try:
            data = json.loads(raw)
            if isinstance(data, list):
                return data
        except json.JSONDecodeError:
            pass
    # 9001: self_service/Epic 1~4 QA에서 지속적으로 쓰인 테스트 테넌트(다수 Story의 실서버 IV
    # 기본 owner) — 로그인 화면에서 선택 가능하도록 기본 목록에 포함.
    csv = os.environ.get("SIP_TENANT_EXTENSIONS", "1001,1002,1003,1004,9001")
    out: List[Dict[str, Any]] = []
    for part in csv.split(","):
        ext = part.strip()
        if not ext:
            continue
        out.append(
            {
                "owner": ext,
                "name": f"내선 {ext}",
                "name_en": f"Ext {ext}",
                "type": "default",
                "description": "",
                "is_active": True,
            }
        )
    return out


@router.get("/tenants")
def list_tenants() -> Dict[str, Any]:
    return {"tenants": _tenant_rows()}


class LoginBody(BaseModel):
    extension: str = Field(..., description="착신 내선/owner")


@router.post("/auth/login")
def auth_login(body: LoginBody) -> Dict[str, Any]:
    want = body.extension.strip()
    if not want:
        raise HTTPException(status_code=400, detail="extension이 비어 있습니다.")
    rows = _tenant_rows()
    match = next((r for r in rows if str(r.get("owner", "")).strip() == want), None)
    if not match:
        raise HTTPException(status_code=400, detail="등록되지 않은 착신번호입니다.")
    # 프론트 useWebSocket.isAcceptableWebSocketToken: JWT(.) 또는 tok_* 만 허용.
    # (token_urlsafe 단독은 거부되어 곧바로 localStorage에서 삭제됨 → 콜도크 미구독)
    token = f"tok_{secrets.token_urlsafe(32)}"
    owner = str(match["owner"])
    tenant = {
        "owner": owner,
        "name": match.get("name") or owner,
        "name_en": match.get("name_en") or owner,
        "type": match.get("type") or "default",
        "description": match.get("description") or "",
        "is_active": match.get("is_active", True),
    }
    user = {
        "id": owner,
        "username": owner,
        "role": "operator",
        "extension": owner,
    }
    return {
        "access_token": token,
        "token_type": "bearer",
        "tenant": tenant,
        "user": user,
    }
