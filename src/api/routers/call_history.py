"""
통화 이력 REST: 녹음 디렉터리 `metadata.json` + `call_insights.json` 병합.

- `append_call_history` / `record_hitl_request`: RAG 등에서 import — 현재는 인덱스는 파일 스캔으로 충분해 디버그 로그만 남김.
"""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import FileResponse, PlainTextResponse

from src.common.call_insights_buffer import (
    load_call_insights_for_directory,
    resolve_callee_summary_for_list_item,
)
from src.common.sip_owner import normalize_owner_username

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/call-history", tags=["call-history"])

_ALLOWED_MEDIA = {"mixed": "mixed.wav", "caller": "caller.wav", "callee": "callee.wav"}


def _recordings_root() -> Path:
    raw = (
        os.environ.get("SIP_RECORDINGS_DIR")
        or os.environ.get("RECORDINGS_DIR")
        or "./recordings"
    )
    return Path(raw).resolve()


def append_call_history(entry: Dict[str, Any]) -> None:
    """통화 시작 시 1회 호출(설계상). 목록 소스는 통화 종료 후 `metadata.json` 스캔."""
    cid = entry.get("call_id") if isinstance(entry, dict) else None
    logger.debug("append_call_history call_id=%s", cid)


def record_hitl_request(
    *,
    call_id: str,
    callee_id: str = "",
    user_question: str = "",
    ai_confidence: Optional[float] = None,
    caller_id: Optional[str] = None,
) -> None:
    """HITL 요청 기록 훅 — 미처리 큐는 HITL 서비스·WS 경로 사용."""
    logger.debug(
        "record_hitl_request call_id=%s callee_id=%s q_preview=%s conf=%s caller=%s",
        call_id,
        callee_id,
        (user_question or "")[:80],
        ai_confidence,
        caller_id,
    )


def _owner_matches_row(owner_filter: str, callee_id: str, caller_id: str = "") -> bool:
    """owner_filter가 callee_id(수신) 또는 caller_id(발신) 어느 쪽에든 해당하면 True."""
    if not owner_filter:
        return True
    want = normalize_owner_username(owner_filter)

    def _matches(field: str) -> bool:
        got = normalize_owner_username(field or "")
        if want and got:
            return want == got or want in got or got in want
        return owner_filter.strip().lower() in (field or "").lower()

    return _matches(callee_id) or _matches(caller_id)


def _load_metadata_rows(root: Path) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    if not root.is_dir():
        return rows
    for sub in root.iterdir():
        if not sub.is_dir() or sub.name.startswith("."):
            continue
        meta_path = sub / "metadata.json"
        if not meta_path.is_file():
            continue
        try:
            with open(meta_path, "r", encoding="utf-8") as f:
                meta = json.load(f)
        except (OSError, json.JSONDecodeError):
            continue
        if not isinstance(meta, dict) or not meta.get("call_id"):
            continue
        meta["_call_dir"] = str(sub)
        rows.append(meta)
    return rows


def _sort_key(m: Dict[str, Any]) -> str:
    return str(m.get("end_time") or m.get("start_time") or "")


def _sip_pbx_root() -> Path:
    return Path(__file__).resolve().parent.parent.parent.parent


def _logs_dir() -> Path:
    d = _sip_pbx_root() / "logs"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _find_call_dir(call_id: str) -> Optional[Path]:
    if not (call_id or "").strip():
        return None
    root = _recordings_root()
    if not root.is_dir():
        return None
    for sub in root.iterdir():
        if not sub.is_dir() or sub.name.startswith("."):
            continue
        meta_path = sub / "metadata.json"
        if not meta_path.is_file():
            continue
        try:
            with open(meta_path, "r", encoding="utf-8") as f:
                meta = json.load(f)
        except (OSError, json.JSONDecodeError):
            continue
        if isinstance(meta, dict) and str(meta.get("call_id") or "") == str(call_id):
            return sub
    return None


def _scan_call_data_record_for_call(call_id: str, max_items: int) -> Tuple[List[Dict[str, Any]], bool]:
    """`logs/call_data_record_*.log` 에서 해당 call_id 행만 수집 (시간순 정렬)."""
    log_dir = _logs_dir()
    if not log_dir.is_dir():
        return [], False
    files = sorted(log_dir.glob("call_data_record_*.log"), reverse=True)
    out: List[Dict[str, Any]] = []
    truncated = False
    want = str(call_id)
    for path in files:
        if len(out) >= max_items:
            truncated = True
            break
        try:
            with open(path, "r", encoding="utf-8", errors="replace") as f:
                for line in f:
                    if len(out) >= max_items:
                        truncated = True
                        break
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        obj = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    if str(obj.get("call_id") or "") != want:
                        continue
                    out.append(obj)
        except OSError:
            continue
    out.sort(key=lambda x: str(x.get("ts") or ""))
    return out, truncated


def _recording_flags(call_dir: Path, meta: Dict[str, Any]) -> Dict[str, bool]:
    files = meta.get("files")
    fd: Dict[str, Any] = files if isinstance(files, dict) else {}

    def _has(key: str, wav_name: str) -> bool:
        v = fd.get(key)
        if v and str(v).strip():
            return True
        return (call_dir / wav_name).is_file()

    return {
        "has_recording_mixed": _has("mixed", "mixed.wav"),
        "has_recording_caller": _has("caller", "caller.wav"),
        "has_recording_callee": _has("callee", "callee.wav"),
    }


@router.get("/{call_id}/debug-trace")
def get_call_debug_trace(
    call_id: str,
    limit: int = Query(800, ge=1, le=5000),
) -> Dict[str, Any]:
    """통화별 call_data_record (대시보드 `call_debug_trace`와 동일 필드) 조회."""
    if _find_call_dir(call_id) is None:
        raise HTTPException(status_code=404, detail="call not found")
    items, truncated = _scan_call_data_record_for_call(call_id, limit)
    return {"call_id": call_id, "items": items, "truncated": truncated}


@router.get("/{call_id}/media/{kind}")
def get_call_media(call_id: str, kind: str) -> FileResponse:
    if kind not in _ALLOWED_MEDIA:
        raise HTTPException(status_code=404, detail="unknown media kind")
    call_dir = _find_call_dir(call_id)
    if call_dir is None:
        raise HTTPException(status_code=404, detail="call not found")
    fname = _ALLOWED_MEDIA[kind]
    base = call_dir.resolve()
    path = (call_dir / fname).resolve()
    if path.parent != base:
        raise HTTPException(status_code=404, detail="invalid path")
    if not path.is_file():
        raise HTTPException(status_code=404, detail="file not found")
    return FileResponse(path, media_type="audio/wav", filename=fname)


@router.get("/{call_id}/transcript")
def get_call_transcript(call_id: str) -> PlainTextResponse:
    call_dir = _find_call_dir(call_id)
    if call_dir is None:
        raise HTTPException(status_code=404, detail="call not found")
    tp = call_dir / "transcript.txt"
    if not tp.is_file():
        raise HTTPException(status_code=404, detail="transcript not found")
    try:
        text = tp.read_text(encoding="utf-8", errors="replace")
    except OSError:
        raise HTTPException(status_code=404, detail="transcript read failed")
    return PlainTextResponse(content=text, media_type="text/plain; charset=utf-8")


@router.get("")
def list_call_history(
    owner: Optional[str] = Query(None, description="테넌트 필터 — caller_id(발신) 또는 callee_id(착신) 어느 쪽에든 매칭"),
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
    since: Optional[str] = Query(None, description="ISO 8601 기준 시각 — 이 시각 이후 통화만 반환 (최근 30일 등)"),
    direction: Optional[str] = Query(
        None,
        description="통화 방향 필터: inbound | outbound (미지정 시 전체)",
    ),
) -> Dict[str, Any]:
    """
    완료 통화 목록. 각 항목에 `callee_summary`, `ai_unhandled_items`, `ai_unhandled_count` 포함
    (`call_insights.json`이 있을 때만 채워짐).
    owner 필터는 caller_id(발신)·callee_id(착신) 양쪽을 검사하므로 수신·발신 통화 모두 반환됨.
    """
    root = _recordings_root()
    metas = _load_metadata_rows(root)
    metas.sort(key=_sort_key, reverse=True)

    owner_f = (owner or "").strip()
    since_f = (since or "").strip()
    direction_f = (direction or "").strip().lower()
    if direction_f and direction_f not in ("inbound", "outbound"):
        direction_f = ""

    def _row_matches(m: Dict[str, Any]) -> bool:
        if owner_f and not _owner_matches_row(
            owner_f,
            str(m.get("callee_id") or ""),
            str(m.get("caller_id") or ""),
        ):
            return False
        if since_f:
            row_time = str(m.get("end_time") or m.get("start_time") or "")
            if row_time and row_time < since_f:
                return False
        if direction_f:
            row_dir = str(m.get("direction") or "").strip().lower()
            # direction 필드가 없는 경우 call_id 접두사로 방향 판별
            if not row_dir:
                cid = str(m.get("call_id") or "")
                row_dir = "outbound" if cid.startswith("outbound-") else "inbound"
            if row_dir != direction_f:
                return False
        return True

    filtered = [m for m in metas if _row_matches(m)]
    total_matching = len(filtered)
    page = filtered[offset : offset + limit]

    out: List[Dict[str, Any]] = []
    for m in page:
        call_dir = Path(m.get("_call_dir") or "")
        insights = load_call_insights_for_directory(call_dir) if call_dir.is_dir() else None

        item: Dict[str, Any] = {
            "call_id": m.get("call_id"),
            "directory": m.get("directory"),
            "caller_id": m.get("caller_id"),
            "callee_id": m.get("callee_id"),
            "direction": (
                m.get("direction")
                or ("outbound" if str(m.get("call_id") or "").startswith("outbound-") else "inbound")
            ),
            "start_time": m.get("start_time"),
            "end_time": m.get("end_time"),
            "duration": m.get("duration"),
            "type": m.get("type"),
            "has_transcript": m.get("has_transcript"),
            "transcript_source": m.get("transcript_source"),
            "files": m.get("files"),
            "callee_summary": None,
            "call_summary": None,
            "is_ai_handled_call": False,
            "ai_unhandled_items": [],
            "ai_unhandled_count": 0,
            "ai_unhandled_resolved_by_hitl_count": 0,
            "ai_unhandled_total_recorded": 0,
        }
        if call_dir.is_dir():
            item.update(_recording_flags(call_dir, m))
            summ, ai_flag = resolve_callee_summary_for_list_item(call_dir, m, insights)
            item["callee_summary"] = summ
            item["is_ai_handled_call"] = ai_flag
        else:
            item["has_recording_mixed"] = False
            item["has_recording_caller"] = False
            item["has_recording_callee"] = False

        if insights:
            _cs = insights.get("call_summary")
            item["call_summary"] = _cs if isinstance(_cs, str) and _cs.strip() else None
            item["ai_unhandled_items"] = insights.get("ai_unhandled_items") or []
            item["ai_unhandled_count"] = int(insights.get("ai_unhandled_count") or 0)
            item["ai_unhandled_resolved_by_hitl_count"] = int(
                insights.get("ai_unhandled_resolved_by_hitl_count") or 0
            )
            item["ai_unhandled_total_recorded"] = int(
                insights.get("ai_unhandled_total_recorded") or 0
            )

        out.append(item)

    return {
        "items": out,
        "total": total_matching,
        "limit": limit,
        "offset": offset,
        "recordings_dir": str(root),
    }
