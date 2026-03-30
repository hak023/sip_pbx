"""
통화 종료 후 대본 기반 통화 요약(call_summary) 생성·저장.

- `call_insights.json`에 `call_summary`, `call_summary_generated_at` 병합.
- LLM 실패 시 `callee_summary` 앞부분을 짧게 폴백(선택).
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

import structlog

logger = structlog.get_logger(__name__)

_TRANSCRIPT_MAX_CHARS = 14_000


def _iso_z() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def load_transcript_text_for_summary(call_dir: Path) -> str:
    """transcript.txt 우선, 없으면 conversation.json에서 본문 조합."""
    tp = call_dir / "transcript.txt"
    if tp.is_file():
        try:
            raw = tp.read_text(encoding="utf-8", errors="replace").strip()
            if raw:
                return raw[:_TRANSCRIPT_MAX_CHARS]
        except OSError:
            pass
    conv = call_dir / "conversation.json"
    if conv.is_file():
        try:
            with open(conv, "r", encoding="utf-8") as f:
                data = json.load(f)
        except (OSError, json.JSONDecodeError):
            return ""
        msgs = data.get("messages")
        if not isinstance(msgs, list):
            return ""
        lines: List[str] = []
        for m in msgs:
            if not isinstance(m, dict):
                continue
            role = (m.get("role") or "").strip()
            content = (m.get("content") or "").strip()
            if not content:
                continue
            label = "착신자" if role in ("assistant", "착신자", "callee") else "발신자"
            lines.append(f"{label}: {content}")
        out = "\n".join(lines)
        return out[:_TRANSCRIPT_MAX_CHARS]
    return ""


def patch_call_insights_summary(call_dir: Path, summary: str, *, source: str) -> None:
    """call_insights.json 에 call_summary 필드 병합."""
    p = call_dir / "call_insights.json"
    if not p.is_file():
        logger.debug("patch_call_insights_summary_skip_no_file", path=str(p))
        return
    try:
        with open(p, "r", encoding="utf-8") as f:
            data: Dict[str, Any] = json.load(f)
    except (OSError, json.JSONDecodeError) as e:
        logger.warning("patch_call_insights_summary_read_failed", error=str(e))
        return
    data["call_summary"] = (summary or "").strip() or None
    data["call_summary_source"] = source
    data["call_summary_generated_at"] = _iso_z()
    try:
        with open(p, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
    except OSError as e:
        logger.warning("patch_call_insights_summary_write_failed", error=str(e))


def _fallback_summary_from_insights(call_dir: Path) -> str:
    p = call_dir / "call_insights.json"
    if not p.is_file():
        return ""
    try:
        with open(p, "r", encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, json.JSONDecodeError):
        return ""
    cs = data.get("callee_summary")
    if not isinstance(cs, str) or not cs.strip():
        return ""
    t = cs.strip()
    if len(t) <= 400:
        return t
    return t[:397] + "…"


async def generate_call_summary_llm(transcript: str, *, is_ai_call: bool) -> str:
    """Gemini로 짧은 한국어 요약. 실패 시 빈 문자열."""
    try:
        from src.config.config_loader import load_config
        from src.ai_voicebot.ai_pipeline.llm_client import LLMClient

        cfg = load_config()
        gemini_config: Dict[str, Any] = {}
        av = getattr(cfg, "ai_voicebot", None)
        gc = getattr(av, "google_cloud", None) if av else None
        raw_gem = getattr(gc, "gemini", None) if gc else None
        if isinstance(raw_gem, dict):
            gemini_config = dict(raw_gem)
        api_key = (
            gemini_config.get("api_key")
            or os.getenv("GEMINI_API_KEY")
            or os.getenv("GOOGLE_API_KEY")
            or ""
        )
        if not api_key:
            return ""
        if not gemini_config:
            gemini_config = {"model": "gemini-2.5-flash-lite"}
        llm = LLMClient(gemini_config, api_key)
        kind = "AI가 착신으로 응대한 통화" if is_ai_call else "발신자와 착신자 간 통화"
        prompt = f"""역할: 콜센터 통화 기록 요약.

통화 유형: {kind}

아래는 통화 대본입니다. 한국어로 **2~5문장**만 요약하세요.
- 고객(발신)이 무엇을 원했는지
- 착신(AI 또는 상대)이 어떻게 응답·처리했는지
- 결과(해결, 부분 해결, 미해결, 전환 등)가 드러나게

금지: 인사말, "요약합니다" 같은 메타 문장, 대본 인용 블록.

[대본]
{transcript}
"""
        out = await llm.generate_simple(prompt, max_tokens=1024, timeout_seconds=45.0)
        result = (out or "").strip()
        logger.info(
            "call_summary_llm_generated",
            call_id="(async_context)",
            summary_len=len(result),
            truncated=(len(result) >= 900),
            note="LLM 통화 요약 생성 완료 (truncated=True이면 토큰 제한에 근접)",
        )
        return result
    except Exception as e:
        logger.warning("generate_call_summary_llm_failed", error=str(e))
        return ""


async def run_call_summary_after_recording(
    call_id: str,
    call_dir: Path,
    *,
    is_ai_handled_call: bool,
) -> None:
    """
    녹음·call_insights flush 이후 백그라운드에서 호출.
    """
    raw = str(os.environ.get("SIP_CALL_SUMMARY_ENABLED", "1")).strip().lower()
    if raw in ("0", "false", "no", "off"):
        return
    if not call_id or not call_dir.is_dir():
        return
    transcript = load_transcript_text_for_summary(call_dir)
    if len(transcript.strip()) < 12:
        logger.info(
            "call_summary_skipped_short_transcript",
            call_id=call_id,
            len=len(transcript),
        )
        return
    summary = await generate_call_summary_llm(transcript, is_ai_call=is_ai_handled_call)
    source = "llm"
    if not summary:
        summary = _fallback_summary_from_insights(call_dir)
        source = "callee_summary_fallback" if summary else "none"
    if summary:
        patch_call_insights_summary(call_dir, summary, source=source)
        logger.info(
            "call_summary_patched",
            call_id=call_id,
            source=source,
            preview=summary[:120],
        )
    else:
        logger.info("call_summary_empty_after_llm_and_fallback", call_id=call_id)
