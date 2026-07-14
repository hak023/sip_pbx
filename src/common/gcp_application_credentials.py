"""Google Cloud 클라이언트(STT/TTS 등)용 서비스 계정 JSON.

config.yaml 에 비밀을 넣지 않을 때:
- 환경 변수 GOOGLE_APPLICATION_CREDENTIALS 가 이미 있으면 그대로 사용
- 없으면 GCP_CREDENTIALS_FILE → 기본 경로 순으로 서비스 계정 JSON 파일을 찾아 설정

※ Cloud Speech 등은 \"API 키 문자열\"이 아니라 GCP에서 받은 JSON 키(서비스 계정)가 필요합니다.
"""

from __future__ import annotations

import json
import os
import warnings
from pathlib import Path

# 로컬 개발 기본 경로 (저장소 밖 — 푸시 대상 아님)
_DEFAULT_CREDENTIALS_JSON = Path(r"C:\work\gcp-api-key.json")


def _looks_like_service_account(data: object) -> bool:
    if not isinstance(data, dict):
        return False
    if data.get("type") == "service_account":
        return True
    return "private_key" in data and "client_email" in data


def _load_valid_service_account(path: Path) -> bool:
    """파일이 있고, 파싱 가능하며 서비스 계정 JSON 형태이면 True."""
    try:
        resolved = path.expanduser().resolve()
    except OSError:
        return False
    if not resolved.is_file():
        return False
    try:
        raw = resolved.read_text(encoding="utf-8-sig")
        if not raw.strip():
            return False
        data = json.loads(raw)
    except (OSError, json.JSONDecodeError):
        return False
    return _looks_like_service_account(data)


def ensure_google_application_credentials() -> None:
    """STT/TTS 등 google-cloud-* 가 처음 쓰이기 전에 호출."""
    preset = os.environ.get("GOOGLE_APPLICATION_CREDENTIALS")
    if preset:
        preset = preset.strip()
        if preset and _load_valid_service_account(Path(preset)):
            return
        if preset:
            try:
                del os.environ["GOOGLE_APPLICATION_CREDENTIALS"]
            except KeyError:
                pass
            warnings.warn(
                "GOOGLE_APPLICATION_CREDENTIALS 가 가리키는 파일이 비어 있거나 "
                "유효한 서비스 계정 JSON이 아닙니다. GCP 콘솔에서 받은 JSON 키 전체를 저장하세요. "
                f"(경로: {preset})",
                stacklevel=2,
            )

    paths: list[Path] = []
    env_path = os.environ.get("GCP_CREDENTIALS_FILE")
    if env_path:
        paths.append(Path(env_path.strip()))
    paths.append(_DEFAULT_CREDENTIALS_JSON)

    for p in paths:
        if not _load_valid_service_account(p):
            continue
        try:
            resolved = p.expanduser().resolve()
        except OSError:
            continue
        os.environ["GOOGLE_APPLICATION_CREDENTIALS"] = str(resolved)
        return
