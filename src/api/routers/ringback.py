"""통화 연결음(Ringback) API 라우터.

엔드포인트:
    GET    /api/ringback/settings              — 현재 설정 조회
    PUT    /api/ringback/settings              — 설정 저장
    POST   /api/ringback/generate-lyrics       — LLM 가사 자동 생성
    POST   /api/ringback/generate-style        — 스타일 랜덤 생성
    POST   /api/ringback/generate-music        — Suno 음원 생성 시작 (서버 폴링 + WS 알림)
    GET    /api/ringback/music-status          — Suno 생성 상태 폴링 (폴백용)
    POST   /api/ringback/apply-music           — 완료된 음원을 다운로드·캐시 후 설정에 적용
    POST   /api/ringback/suno-callback          — Suno callBackUrl 수신(즉시 200, 본문은 백그라운드에서 처리)
    GET    /api/ringback/preview-url           — 미리 듣기 URL 반환
    GET    /api/ringback/music-list            — 저장된 음원 목록 조회
    DELETE /api/ringback/music-item/{item_id}  — 음원 아이템 삭제
"""

from __future__ import annotations

import asyncio
import json
from typing import Any

import structlog
from fastapi import APIRouter, BackgroundTasks, HTTPException, Query, Request
from pydantic import BaseModel, Field

logger = structlog.get_logger(__name__)

router = APIRouter(prefix="/api/ringback", tags=["ringback"])


# ── 요청·응답 모델 ─────────────────────────────────────────────────────────────

class RingbackSettingsUpdate(BaseModel):
    owner: str = "pbx"
    greeting_text: str | None = None
    suno_lyrics: str | None = None
    suno_style: str | None = None
    suno_title: str | None = None
    suno_vocal_gender: str | None = None       # "m" / "f"
    suno_duration_target: int | None = None    # 초
    enabled_greeting: bool | None = None
    enabled_ringback: bool | None = None


class GenerateLyricsRequest(BaseModel):
    owner: str = "pbx"
    duration_target: int = 60
    brief: str | None = Field(
        default=None,
        description="운영자 요청(한글 가능). 비어 있으면 페르소나·KB만 반영.",
    )


class GenerateStyleRequest(BaseModel):
    vocal_gender: str = "m"   # "m" / "f"
    duration_target: int = 60
    brief: str | None = Field(default=None, description="분위기·장르 요청(brief). 가사와 함께 쓰면 태그 일관성에 유리.")
    lyrics: str | None = Field(default=None, description="이미 만든 가사(일부). 스타일이 가사 톤에 맞도록 참고.")


class GenerateMusicRequest(BaseModel):
    owner: str = "pbx"
    lyrics: str
    style: str
    title: str = "통화 연결음"
    vocal_gender: str = "m"
    duration_target: int = 60
    ringback_assignment_id: str | None = None  # 착신 제어 통화 연결음 할당 전용 (전역 설정에 task_id 미기록)


class ApplyMusicRequest(BaseModel):
    owner: str = "pbx"
    task_id: str
    audio_url: str
    item_id: int | None = None  # ringback_music_items.id (있으면 is_active 갱신)
    index: int = 0              # 다운로드 캐시 파일명 인덱스 (0, 1)
    ringback_assignment_id: str | None = None  # 있으면 ringback_schedule_assignments 행만 갱신


# ── 엔드포인트 ─────────────────────────────────────────────────────────────────

@router.get("/settings")
async def get_settings(owner: str = Query(default="pbx")) -> dict[str, Any]:
    """현재 ringback 설정 조회 (ringback_settings + 음원 목록 연동)."""
    from src.services.ringback_service import get_settings as svc_get
    settings = svc_get(owner)
    if settings is None:
        settings = {
            "owner": owner,
            "greeting_text": "",
            "suno_lyrics": "",
            "suno_style": "",
            "suno_title": "",
            "suno_vocal_gender": "m",
            "suno_duration_target": 60,
            "suno_audio_url": "",
            "suno_audio_path": "",
            "suno_task_id": "",
            "enabled_greeting": False,
            "enabled_ringback": False,
        }
    settings["enabled_greeting"] = bool(settings.get("enabled_greeting"))
    settings["enabled_ringback"] = bool(settings.get("enabled_ringback"))

    return settings


@router.put("/settings")
async def update_settings(body: RingbackSettingsUpdate) -> dict[str, str]:
    """설정 저장."""
    from src.services.ringback_service import save_settings

    data: dict[str, Any] = {}
    if body.greeting_text is not None:
        data["greeting_text"] = body.greeting_text
    if body.suno_lyrics is not None:
        data["suno_lyrics"] = body.suno_lyrics
    if body.suno_style is not None:
        data["suno_style"] = body.suno_style
    if body.suno_title is not None:
        data["suno_title"] = body.suno_title
    if body.suno_vocal_gender is not None:
        data["suno_vocal_gender"] = body.suno_vocal_gender
    if body.suno_duration_target is not None:
        data["suno_duration_target"] = body.suno_duration_target
    if body.enabled_greeting is not None:
        data["enabled_greeting"] = 1 if body.enabled_greeting else 0
    if body.enabled_ringback is not None:
        data["enabled_ringback"] = 1 if body.enabled_ringback else 0

    save_settings(body.owner, data)
    return {"status": "ok", "owner": body.owner}


@router.post("/generate-lyrics")
async def generate_lyrics(body: GenerateLyricsRequest) -> dict[str, Any]:
    """LLM으로 CM송 가사를 자동 생성한다.

    응답의 ``warning`` 은 LLM 실패로 고정 폴백 가사가 내려온 경우 등 운영자 안내용.
    """
    from src.services.ringback_service import auto_generate_lyrics
    try:
        return await auto_generate_lyrics(
            body.owner.strip(),
            body.duration_target,
            brief=body.brief,
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e)) from e


@router.post("/generate-style")
async def generate_style(body: GenerateStyleRequest) -> dict[str, Any]:
    """Suno 스타일 태그 생성. brief/lyrics 가 있으면 LLM으로 맞춤, 없으면 기존 무작위 조합."""
    from src.services.ringback_service import auto_generate_style_with_context
    try:
        style, used_llm = await auto_generate_style_with_context(
            vocal_gender=body.vocal_gender,
            duration_target=body.duration_target,
            brief=body.brief,
            lyrics=body.lyrics,
        )
        return {"style": style, "used_llm": used_llm}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e)) from e


@router.post("/generate-music")
async def generate_music(body: GenerateMusicRequest) -> dict[str, Any]:
    """Suno API로 음원 생성을 요청한다.

    - Suno API에 생성 요청 후 task_id를 즉시 반환.
    - 서버 백그라운드에서 폴링하여 완료 시 WebSocket(ringback_music_ready)으로 알림.
    - 프론트엔드는 setInterval 폴링 불필요.
    """
    from src.services.ringback_service import (
        ensure_suno_generation_prerequisites,
        generate_suno_music,
        poll_and_notify,
        save_settings,
    )
    try:
        ensure_suno_generation_prerequisites()
        result = await generate_suno_music(
            lyrics=body.lyrics,
            style=body.style,
            title=body.title,
            vocal_gender=body.vocal_gender,
            duration_target=body.duration_target,
        )
        task_id = result.get("task_id", "")

        if body.ringback_assignment_id:
            from src.call_control import db as cc_db

            row = cc_db.get_ringback_schedule_assignment(body.ringback_assignment_id)
            if not row or row.get("owner") != body.owner:
                raise HTTPException(status_code=404, detail="ringback_assignment_id를 찾을 수 없습니다.")
            cc_db.update_ringback_schedule_assignment(
                body.ringback_assignment_id,
                {"suno_task_id": task_id},
            )
        else:
            save_settings(body.owner, {"suno_task_id": task_id})

        # 서버 측 백그라운드 폴링 시작 → 완료 시 WS emit
        if task_id:
            asyncio.create_task(
                poll_and_notify(
                    owner=body.owner,
                    task_id=task_id,
                    ringback_assignment_id=body.ringback_assignment_id,
                ),
                name=f"ringback_poll_{task_id[:8]}",
            )

        return result
    except ValueError as e:
        logger.warning(
            "ringback_generate_music_bad_request",
            owner=getattr(body, "owner", None),
            error=str(e),
            lyrics_chars=len(body.lyrics or ""),
            style_chars=len(body.style or ""),
            title_preview=(body.title or "")[:120],
            ringback_assignment_id=getattr(body, "ringback_assignment_id", None),
        )
        raise HTTPException(status_code=400, detail=str(e)) from e
    except RuntimeError as e:
        logger.error(
            "ringback_generate_music_upstream_error",
            owner=getattr(body, "owner", None),
            error=str(e),
        )
        raise HTTPException(status_code=502, detail=str(e)) from e
    except Exception as e:
        logger.exception(
            "ringback_generate_music_failed",
            owner=getattr(body, "owner", None),
            error=str(e),
        )
        raise HTTPException(status_code=500, detail=str(e)) from e


@router.post("/suno-callback")
async def suno_callback(request: Request, background_tasks: BackgroundTasks) -> dict[str, str]:
    """Suno API가 생성 상태를 알릴 때 POST하는 URL.

    Suno 15초 타임아웃에 맞춰 **즉시 200**을 반환하고, 본문 처리·MP3 저장은
    ``BackgroundTasks`` 로 이어서 수행한다. 완료는 콜백 또는 ``poll_and_notify`` 중 먼저 도달한 쪽이
    DB를 갱신하며, 할당 행은 ``suno_generation_status=complete`` 로 중복을 막는다.
    """
    body = await request.body()
    preview = ""
    if body:
        preview = body[:800].decode("utf-8", errors="replace")
    logger.info(
        "ringback_suno_callback_received",
        content_type=request.headers.get("content-type", ""),
        body_len=len(body),
        body_preview=preview,
    )
    try:
        payload: Any = json.loads(body.decode("utf-8")) if body else {}
    except Exception:
        payload = {}
    if not isinstance(payload, dict):
        payload = {}

    from src.services.ringback_service import process_suno_music_callback_payload

    background_tasks.add_task(process_suno_music_callback_payload, payload)
    return {"status": "received"}


@router.get("/music-status")
async def music_status(task_id: str = Query(...)) -> dict[str, Any]:
    """Suno 생성 상태를 폴링한다 (폴백용 — WS 미사용 환경에서 사용)."""
    from src.services.ringback_service import poll_suno_task
    try:
        return await poll_suno_task(task_id)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e)) from e


@router.post("/apply-music")
async def apply_music(body: ApplyMusicRequest) -> dict[str, Any]:
    """생성이 완료된 음원을 다운로드·캐시하고 설정 및 목록에 반영한다.

    item_id가 주어진 경우 DB에 저장된 local_path를 먼저 확인한다.
    파일이 실제로 존재하면 재다운로드를 건너뛴다(서버 재시작 후에도 캐시 재사용).
    """
    import os
    from src.services.ringback_service import (
        download_and_cache_audio,
        save_settings,
        set_active_music_item,
    )
    try:
        local_path: str | None = None

        # item_id가 있으면 DB에 저장된 local_path 우선 확인
        if body.item_id is not None:
            cached = _get_item_local_path(body.item_id, body.owner)
            if cached and os.path.isfile(cached):
                local_path = cached
                import structlog
                structlog.get_logger(__name__).info(
                    "ringback_apply_use_cached",
                    owner=body.owner,
                    item_id=body.item_id,
                    path=local_path,
                )

        # 캐시 없거나 파일 소실 → 다운로드
        if local_path is None:
            local_path = await download_and_cache_audio(body.owner, body.audio_url, body.index)

        if body.ringback_assignment_id:
            from src.call_control import db as cc_db

            row = cc_db.get_ringback_schedule_assignment(body.ringback_assignment_id)
            if not row or row.get("owner") != body.owner:
                raise HTTPException(status_code=404, detail="ringback_assignment_id를 찾을 수 없습니다.")
            cc_db.update_ringback_schedule_assignment(
                body.ringback_assignment_id,
                {
                    "suno_task_id": body.task_id,
                    "suno_audio_url": body.audio_url,
                    "suno_audio_path": local_path,
                    "suno_generation_status": "complete",
                },
            )
        else:
            save_settings(body.owner, {
                "suno_task_id": body.task_id,
                "suno_audio_url": body.audio_url,
                "suno_audio_path": local_path,
            })

        if body.item_id is not None:
            _update_item_local_path(body.item_id, body.owner, local_path)
            if not body.ringback_assignment_id:
                set_active_music_item(body.owner, body.item_id)

        return {
            "status": "ok",
            "audio_url": body.audio_url,
            "local_path": local_path,
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e)) from e


def _update_item_local_path(item_id: int, owner: str, local_path: str) -> None:
    """ringback_music_items의 local_path를 갱신한다."""
    try:
        from src.booking.database import get_db
        with get_db() as conn:
            conn.execute(
                "UPDATE ringback_music_items SET local_path = ? WHERE id = ? AND owner = ?",
                (local_path, item_id, owner),
            )
    except Exception:
        pass


def _get_item_local_path(item_id: int, owner: str) -> str | None:
    """ringback_music_items에서 저장된 local_path를 읽어 반환한다. 없으면 None."""
    try:
        from src.booking.database import get_connection
        conn = get_connection()
        try:
            row = conn.execute(
                "SELECT local_path FROM ringback_music_items WHERE id = ? AND owner = ?",
                (item_id, owner),
            ).fetchone()
            return row["local_path"] if row and row["local_path"] else None
        finally:
            conn.close()
    except Exception:
        return None


@router.get("/preview-url")
async def preview_url(owner: str = Query(default="pbx")) -> dict[str, str]:
    """미리 듣기용 Suno 음원 URL을 반환한다."""
    from src.services.ringback_service import get_settings as svc_get
    settings = svc_get(owner)
    url = (settings or {}).get("suno_audio_url", "")
    return {"audio_url": url}


@router.get("/music-list")
async def list_music_items(
    owner: str = Query(default="pbx"),
    limit: int = Query(default=20, ge=1, le=100),
) -> list[dict[str, Any]]:
    """저장된 음원 목록을 최신순으로 반환한다."""
    from src.services.ringback_service import get_music_items
    items = get_music_items(owner, limit)
    # is_active를 bool로 변환
    for item in items:
        item["is_active"] = bool(item.get("is_active"))
    return items


@router.delete("/music-item/{item_id}")
async def delete_music_item(
    item_id: int,
    owner: str = Query(default="pbx"),
) -> dict[str, str]:
    """음원 아이템을 목록에서 삭제한다."""
    from src.services.ringback_service import delete_music_item as svc_delete
    try:
        svc_delete(item_id, owner)
        return {"status": "ok", "item_id": str(item_id)}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e)) from e
