"""
통화 이력·통화내용 집계 (call_data_record 로그 기반).

- logs/call_data_record_YYYYMMDD.log JSON Lines를 읽어 call_id별로 집계.
- 통화내용(content), 상세정보(detail) 생성. API에서 GET /api/call-history 등에 사용.

설계: docs/design/CALL_HISTORY_AND_CONTENT_DESIGN.md
"""

import json
from pathlib import Path
from typing import Any, Dict, List, Optional


def _project_root() -> Path:
    return Path(__file__).resolve().parent.parent.parent


def _default_log_dir() -> Path:
    root = _project_root()
    log_dir = root / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    return log_dir


def get_call_data_record_log_paths(
    log_dir: Optional[Path] = None,
    from_date: Optional[str] = None,
    to_date: Optional[str] = None,
) -> List[Path]:
    """
    읽을 로그 파일 경로 목록 반환.
    from_date/to_date: YYYYMMDD. 미지정 시 오늘만.
    """
    directory = log_dir or _default_log_dir()
    if not directory.exists():
        return []
    paths: List[Path] = []
    for f in directory.iterdir():
        if not f.is_file() or not f.name.startswith("call_data_record_") or not f.name.endswith(".log"):
            continue
        try:
            # call_data_record_20260314.log -> 20260314
            date_str = f.stem.replace("call_data_record_", "")
            if len(date_str) != 8 or not date_str.isdigit():
                continue
            if from_date and date_str < from_date:
                continue
            if to_date and date_str > to_date:
                continue
            paths.append(f)
        except Exception:
            continue
    paths.sort(key=lambda p: p.name)
    return paths


def _parse_line(line: str) -> Optional[Dict[str, Any]]:
    line = line.strip()
    if not line:
        return None
    try:
        return json.loads(line)
    except json.JSONDecodeError:
        return None


def _build_content_and_detail(events: List[Dict[str, Any]]) -> tuple[str, Dict[str, Any]]:
    """
    같은 call_id의 이벤트 리스트를 시간순으로 받아,
    통화내용(content) 문자열과 상세정보(detail) 딕셔너리를 만든다.
    """
    content_parts: List[str] = []
    turns: List[Dict[str, Any]] = []
    last_stt: Optional[Dict[str, Any]] = None
    last_rag: Optional[Dict[str, Any]] = None
    seq = 0

    for ev in events:
        category = ev.get("category", "")
        event = ev.get("event", "")
        ts = ev.get("ts", "")

        if category == "stt" and event == "stt_final":
            last_stt = {"text": ev.get("text", ""), "ts": ts, "seq": ev.get("seq", 0)}

        if category == "rag" and event == "rag_search_done":
            last_rag = {
                "query": ev.get("query", ""),
                "owner_filter": ev.get("owner_filter"),
                "result_count": ev.get("result_count", 0),
                "search_elapsed_sec": ev.get("search_elapsed_sec"),
                "confidence": ev.get("confidence"),
            }

        if category == "llm" and event == "llm_exchange":
            seq += 1
            user_text = ev.get("user_text", "")
            response = ev.get("response", "")
            content_parts.append(f"Q: {user_text}\nA: {response}")

            turn: Dict[str, Any] = {
                "seq": seq,
                "stt": last_stt if last_stt else {"text": user_text, "ts": ts},
                "rewrite": {"query_used": ev.get("rewritten_query") or user_text},
                "rag": last_rag,
                "llm": {
                    "intent": ev.get("intent"),
                    "confidence": ev.get("confidence"),
                    "user_text": user_text,
                    "response": response,
                    "context_docs_count": ev.get("context_docs_count"),
                    "cache_hit": ev.get("cache_hit", False),
                    "agent_elapsed_sec": _parse_elapsed(ev.get("agent_elapsed")),
                },
            }
            turns.append(turn)
            last_rag = None

    content = "\n\n".join(content_parts) if content_parts else "(대화 내용 없음)"
    detail: Dict[str, Any] = {
        "call_type": "ai" if turns else "unknown",
        "turns": turns,
    }
    return content, detail


def _parse_elapsed(v: Any) -> Optional[float]:
    if v is None:
        return None
    if isinstance(v, (int, float)):
        return float(v)
    s = str(v).replace("s", "").strip()
    try:
        return float(s)
    except ValueError:
        return None


def aggregate_by_call_id(
    events: List[Dict[str, Any]],
) -> Dict[str, Dict[str, Any]]:
    """
    이벤트 리스트를 call_id별로 묶고, 각 call_id에 대해 content/detail을 생성해 반환.
    반환: { call_id: { events, content, detail, started_at, ended_at, callee } }
    """
    by_call: Dict[str, List[Dict[str, Any]]] = {}
    for ev in events:
        cid = ev.get("call_id") or ""
        if not cid:
            continue
        if cid not in by_call:
            by_call[cid] = []
        by_call[cid].append(ev)

    result: Dict[str, Dict[str, Any]] = {}
    for call_id, evs in by_call.items():
        # 시간순 정렬 (ts 기준)
        evs_sorted = sorted(evs, key=lambda e: (e.get("ts") or ""))

        started_at: Optional[str] = None
        ended_at: Optional[str] = None
        callee: Optional[str] = None
        for e in evs_sorted:
            ts = e.get("ts")
            if ts:
                if started_at is None:
                    started_at = ts
                ended_at = ts
            if e.get("event") == "call_connected" and "callee" in e:
                callee = e.get("callee")
            if e.get("event") == "call_ended" and "callee" in e:
                callee = callee or e.get("callee")

        content, detail = _build_content_and_detail(evs_sorted)
        result[call_id] = {
            "call_id": call_id,
            "events": evs_sorted,
            "content": content,
            "detail": detail,
            "started_at": started_at,
            "ended_at": ended_at,
            "callee": callee,
            "is_ai_handled": len(detail.get("turns", [])) > 0,
        }
    return result


def read_call_history_from_logs(
    log_dir: Optional[Path] = None,
    from_date: Optional[str] = None,
    to_date: Optional[str] = None,
    limit: int = 500,
) -> List[Dict[str, Any]]:
    """
    call_data_record 로그 파일을 읽어 통화 이력 목록을 반환.
    각 항목: call_id, content (통화내용), detail (상세), started_at, ended_at, callee, is_ai_handled.

    limit: 집계할 최대 이벤트 수 (파일이 클 때 제한).
    """
    paths = get_call_data_record_log_paths(log_dir=log_dir, from_date=from_date, to_date=to_date)
    all_events: List[Dict[str, Any]] = []
    for path in paths:
        try:
            with open(path, "r", encoding="utf-8") as f:
                for line in f:
                    rec = _parse_line(line)
                    if rec:
                        all_events.append(rec)
                    if len(all_events) >= limit:
                        break
        except Exception:
            continue
        if len(all_events) >= limit:
            break

    aggregated = aggregate_by_call_id(all_events)
    # 최신 통화부터 (ended_at 기준)
    items = list(aggregated.values())
    items.sort(key=lambda x: (x.get("ended_at") or ""), reverse=True)
    return items
