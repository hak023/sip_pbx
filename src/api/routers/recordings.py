"""
녹음 파일 API

- GET  /api/recordings/calls/{call_id}/info   — 오디오 파일 목록
- GET  /api/recordings/calls/{call_id}/media — 스트리밍(재생), query: file=
- GET  /api/recordings/calls/{call_id}/download — 다운로드, query: file=
"""

from pathlib import Path
from typing import Any, Dict

import structlog
from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import FileResponse, Response

from src.api.utils.recording_paths import (
    find_call_directory,
    get_recordings_dir,
    list_recording_audio_files,
    resolve_safe_audio_path,
)

logger = structlog.get_logger(__name__)

router = APIRouter(prefix="/api/recordings", tags=["recordings"])


@router.get("/calls/{call_id}/info")
async def get_recording_info(call_id: str) -> Dict[str, Any]:
    """통화 ID에 연결된 녹음 파일 메타데이터."""
    recordings_dir = get_recordings_dir()
    call_dir = find_call_directory(call_id, recordings_dir)
    if call_dir is None:
        logger.info("recordings_info_not_found", call_id=call_id, recordings_dir=recordings_dir)
        raise HTTPException(status_code=404, detail="해당 통화의 녹음 디렉터리를 찾을 수 없습니다.")

    files = list_recording_audio_files(call_dir)
    logger.info(
        "recordings_info_ok",
        call_id=call_id,
        directory=str(call_dir.name),
        file_count=len(files),
    )
    return {
        "call_id": call_id,
        "directory": call_dir.name,
        "recordings_root": recordings_dir,
        "files": files,
        "has_recording": len(files) > 0,
    }


def _media_response(
    call_id: str,
    file: str,
    as_attachment: bool,
) -> FileResponse:
    recordings_dir = get_recordings_dir()
    call_dir = find_call_directory(call_id, recordings_dir)
    if call_dir is None:
        raise HTTPException(status_code=404, detail="통화 녹음을 찾을 수 없습니다.")

    path = resolve_safe_audio_path(call_dir, file)
    if path is None:
        logger.warning(
            "recordings_media_invalid_file",
            call_id=call_id,
            requested_file=file,
        )
        raise HTTPException(status_code=404, detail="요청한 파일이 없거나 허용되지 않습니다.")

    media_type = next(
        (f["mime"] for f in list_recording_audio_files(call_dir) if f["name"] == path.name),
        "application/octet-stream",
    )

    logger.info(
        "recordings_serve",
        call_id=call_id,
        file=path.name,
        attachment=as_attachment,
        size_bytes=path.stat().st_size,
    )
    return FileResponse(
        path=str(path),
        media_type=media_type,
        filename=path.name,
        content_disposition_type="attachment" if as_attachment else "inline",
    )


@router.get("/calls/{call_id}/media")
async def stream_recording(
    call_id: str,
    file: str = Query(..., description="오디오 파일명 (예: call.wav)"),
) -> FileResponse:
    """브라우저 재생용 (inline). Authorization은 미들웨어/게이트웨이에서 처리; 현재는 Bearer 선택."""
    return _media_response(call_id, file, as_attachment=False)


@router.get("/calls/{call_id}/download")
async def download_recording(
    call_id: str,
    file: str = Query(..., description="다운로드할 오디오 파일명"),
) -> FileResponse:
    """다운로드 (Content-Disposition: attachment)."""
    return _media_response(call_id, file, as_attachment=True)
