"""
실시간 AI 파이프라인(STT 최종 + TTS/LLM 응답) 기반 통화 대본.

통화 종료 시 녹음 디렉터리에 transcript.txt(TranscriptParser 호환)와
conversation.json(구조화)을 쓴 뒤, WAV 후처리 STT는 비워진 버퍼일 때만 수행한다.
"""

from __future__ import annotations

import json
import threading
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List

KST = timezone(timedelta(hours=9))

_lock = threading.Lock()
_buffers: Dict[str, List[Dict[str, Any]]] = {}


def _now_iso() -> str:
    return datetime.now(KST).isoformat(timespec="milliseconds")


def record_pipeline_caller(call_id: str, text: str) -> None:
    """발신자(사용자) — STT 최종이 LLM으로 넘어가는 문장."""
    if not call_id or not (text or "").strip():
        return
    t = (text or "").strip()
    with _lock:
        _buffers.setdefault(call_id, []).append(
            {
                "role": "user",
                "speaker_label": "발신자",
                "content": t,
                "ts": _now_iso(),
            }
        )


def record_pipeline_callee(call_id: str, text: str) -> None:
    """착신자(AI/TTS) — 실제 발화로 나간 텍스트."""
    if not call_id or not (text or "").strip():
        return
    t = (text or "").strip()
    with _lock:
        _buffers.setdefault(call_id, []).append(
            {
                "role": "assistant",
                "speaker_label": "착신자",
                "content": t,
                "ts": _now_iso(),
            }
        )


def flush_pipeline_transcript_to_dir(call_id: str, call_dir: Path) -> int:
    """
    버퍼를 conversation.json + transcript.txt 로 저장하고 call_id 버퍼를 비운다.

    Returns:
        저장한 메시지 개수 (0이면 파일을 만들지 않음).
    """
    if not call_id:
        return 0
    with _lock:
        rows = _buffers.pop(call_id, None)
    if not rows:
        return 0

    call_dir.mkdir(parents=True, exist_ok=True)
    try:
        payload = {
            "call_id": call_id,
            "source": "pipeline",
            "messages": rows,
        }
        conv_path = call_dir / "conversation.json"
        with open(conv_path, "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False, indent=2)

        lines: List[str] = []
        for m in rows:
            label = str(m.get("speaker_label") or "")
            if not label:
                label = "착신자" if m.get("role") == "assistant" else "발신자"
            lines.append(f"{label}: {m['content']}")

        transcript_path = call_dir / "transcript.txt"
        with open(transcript_path, "w", encoding="utf-8") as f:
            f.write("\n".join(lines))
    except Exception:
        with _lock:
            prev = _buffers.get(call_id, [])
            _buffers[call_id] = rows + prev
        raise

    return len(rows)
