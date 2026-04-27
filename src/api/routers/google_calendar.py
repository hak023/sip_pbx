"""
Google Calendar OAuth 및 연동 상태 API.

예약 파이프라인(`gcal_service.create_event` 등)은 `owner`(착신 테넌트 ID)로
`google_tokens` 테이블에서 토큰을 읽는다. 본 라우터는 OAuth 완료 시 **동일 owner 키**로
`save_token`을 호출해 DB 행을 채운다.

엔드포인트:
  GET  /api/google/oauth/start     — owner 쿼리 → Google 인가 페이지로 리다이렉트
  GET  /api/google/oauth/callback  — code+state 검증 후 토큰 저장
  GET  /api/google/connection       — owner별 연동·만료·refresh 유무 (비밀 미전체 노출)
  DELETE /api/google/connection    — owner 연동 해제 (토큰·gcal_event_map 삭제)
"""

from __future__ import annotations

import logging
import os
from typing import Optional

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import JSONResponse, RedirectResponse

from src.common.sip_owner import normalize_owner_username
from src.services import gcal_service

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/google", tags=["google-calendar"])


def _normalize_owner(owner: str) -> str:
    s = (owner or "").strip()
    if not s:
        return ""
    return normalize_owner_username(s) or s


def _oauth_success_redirect(owner: str) -> Optional[str]:
    base = (os.environ.get("GCAL_OAUTH_SUCCESS_URL") or "").strip()
    if not base:
        return None
    sep = "&" if ("?" in base) else "?"
    from urllib.parse import quote

    return f"{base}{sep}gcal_connected=1&owner={quote(owner, safe='')}"


@router.get("/oauth/start")
def oauth_start(owner: str = Query(..., description="테넌트 owner (예: 착신 내선 1003)")):
    """Google OAuth 인가 URL로 리다이렉트. state에 서명된 owner가 포함된다."""
    own = _normalize_owner(owner)
    if not own:
        raise HTTPException(status_code=400, detail="owner is required")
    if not gcal_service.oauth_app_credentials_ok():
        raise HTTPException(
            status_code=503,
            detail="Google OAuth client_id/client_secret 미설정 (GCAL_* 또는 config.google_calendar)",
        )
    try:
        state = gcal_service.sign_oauth_owner_state(own)
        url = gcal_service.build_oauth_authorization_url(state)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    logger.info("gcal_oauth_start", owner=own)
    return RedirectResponse(url=url, status_code=302)


@router.get("/oauth/callback")
def oauth_callback(
    code: Optional[str] = Query(None),
    state: Optional[str] = Query(None),
    error: Optional[str] = Query(None),
    error_description: Optional[str] = Query(None),
):
    """Google이 돌려준 code를 토큰으로 교환 후 `google_tokens`에 owner 행으로 저장."""
    if error:
        logger.warning(
            "gcal_oauth_callback_error",
            error=error,
            error_description=(error_description or "")[:500],
        )
        raise HTTPException(
            status_code=400,
            detail=f"Google OAuth error: {error} {error_description or ''}".strip(),
        )
    if not code or not state:
        raise HTTPException(status_code=400, detail="missing code or state")

    own = gcal_service.verify_oauth_owner_state(state)
    if not own:
        raise HTTPException(status_code=400, detail="invalid or expired OAuth state")

    own = _normalize_owner(own)
    try:
        raw = gcal_service.exchange_oauth_authorization_code(code)
    except ValueError as e:
        logger.warning("gcal_oauth_callback_exchange_failed", owner=own, error=str(e))
        raise HTTPException(status_code=502, detail=str(e)) from e

    row = gcal_service.oauth_code_response_to_token_row(raw)
    # 재연동 시 기존 connected_at 유지: 이미 행이 있으면 connected_at만 덮어쓰지 않도록
    existing = gcal_service.get_token(own)
    if existing and existing.get("connected_at"):
        row["connected_at"] = existing["connected_at"]
    gcal_service.save_token(own, row)
    logger.info("gcal_oauth_callback_saved", owner=own, has_refresh=bool((row.get("refresh_token") or "").strip()))

    redir = _oauth_success_redirect(own)
    if redir:
        return RedirectResponse(url=redir, status_code=302)
    return JSONResponse(
        {
            "ok": True,
            "owner": own,
            "message": "Google Calendar 연동이 저장되었습니다.",
            "status": gcal_service.get_oauth_status(own),
        }
    )


@router.get("/connection")
def connection_status(owner: str = Query(..., description="테넌트 owner")):
    """`google_tokens`에서 해당 owner 행을 읽어 연동 여부·refresh·만료 시각(문자열)만 반환."""
    own = _normalize_owner(owner)
    if not own:
        raise HTTPException(status_code=400, detail="owner is required")
    return gcal_service.get_oauth_status(own)


@router.delete("/connection")
def connection_disconnect(owner: str = Query(..., description="테넌트 owner")):
    """연동 해제: google_tokens + gcal_event_map 해당 owner."""
    own = _normalize_owner(owner)
    if not own:
        raise HTTPException(status_code=400, detail="owner is required")
    gcal_service.delete_token(own)
    logger.info("gcal_oauth_disconnected", owner=own)
    return JSONResponse({"ok": True, "owner": own, "disconnected": True})
