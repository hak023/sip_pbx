"""Gemini / Google Generative AI API 키 — 환경 변수만 사용.

링백 LLM, 보이스봇 LLM, 지식 추출 등 동일 순서로 통일한다.
config.yaml 등 파일에 API 키를 두지 않는다.
"""

from __future__ import annotations

import os
from typing import Optional


def resolve_gemini_api_key() -> Optional[str]:
    """GEMINI_API_KEY 우선, 없으면 GOOGLE_API_KEY. 공백만 있으면 None."""
    for name in ("GEMINI_API_KEY", "GOOGLE_API_KEY"):
        raw = os.environ.get(name)
        if raw:
            key = raw.strip()
            if key:
                return key
    return None
