"""
통화별 녹음 디렉터리 탐색 및 오디오 파일 목록.

recordings/<세션디렉터리>/metadata.json 의 call_id 로 매칭.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Dict, List, Optional

# 지원 오디오 확장자 (소문자)
AUDIO_EXTENSIONS = frozenset({".wav", ".mp3", ".m4a", ".ogg", ".webm", ".flac"})

MIME_BY_EXT = {
    ".wav": "audio/wav",
    ".mp3": "audio/mpeg",
    ".m4a": "audio/mp4",
    ".ogg": "audio/ogg",
    ".webm": "audio/webm",
    ".flac": "audio/flac",
}


def get_recordings_dir() -> str:
    """환경변수 RECORDINGS_DIR 또는 기본 recordings (프로세스 CWD 기준)."""
    return os.environ.get("RECORDINGS_DIR", "recordings")


def find_call_directory(call_id: str, recordings_dir: Optional[str] = None) -> Optional[Path]:
    """
    call_id에 해당하는 recordings 하위 세션 디렉터리 경로.
    """
    root = Path(recordings_dir or get_recordings_dir())
    if not root.exists() or not root.is_dir():
        return None

    for dir_path in root.iterdir():
        if not dir_path.is_dir():
            continue
        meta = dir_path / "metadata.json"
        if not meta.is_file():
            continue
        try:
            with open(meta, "r", encoding="utf-8") as f:
                data = json.load(f)
            if data.get("call_id") == call_id:
                return dir_path
        except (OSError, json.JSONDecodeError):
            continue
    return None


def list_recording_audio_files(call_dir: Path) -> List[Dict[str, Any]]:
    """세션 디렉터리 내 오디오 파일 목록 (이름·크기·mime)."""
    out: List[Dict[str, Any]] = []
    try:
        for p in sorted(call_dir.iterdir()):
            if not p.is_file():
                continue
            ext = p.suffix.lower()
            if ext not in AUDIO_EXTENSIONS:
                continue
            out.append(
                {
                    "name": p.name,
                    "size_bytes": p.stat().st_size,
                    "mime": MIME_BY_EXT.get(ext, "application/octet-stream"),
                }
            )
    except OSError:
        pass
    return out


def call_has_audio_recording(call_id: str, recordings_dir: Optional[str] = None) -> bool:
    d = find_call_directory(call_id, recordings_dir)
    if d is None:
        return False
    return len(list_recording_audio_files(d)) > 0


def resolve_safe_audio_path(call_dir: Path, filename: str) -> Optional[Path]:
    """
    filename은 순수 파일명만 허용 (경로 조작 방지).
    """
    if not filename or filename != Path(filename).name:
        return None
    if ".." in filename or "/" in filename or "\\" in filename:
        return None
    target = (call_dir / filename).resolve()
    call_resolved = call_dir.resolve()
    try:
        target.relative_to(call_resolved)
    except ValueError:
        return None
    if target.is_file() and target.suffix.lower() in AUDIO_EXTENSIONS:
        return target
    return None
