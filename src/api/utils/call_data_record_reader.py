"""
logs/call_data_record_YYYYMMDD.log 에서 call_id 로 필터한 JSON 라인 반환.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List


def _project_root() -> Path:
    return Path(__file__).resolve().parent.parent.parent.parent


def read_call_data_record_for_call(call_id: str, max_lines: int = 5000) -> List[Dict[str, Any]]:
    """
    모든 call_data_record_*.log 파일을 읽어 해당 call_id 행만 수집 후 ts 기준 정렬.
    """
    if not call_id or not str(call_id).strip():
        return []

    log_dir = _project_root() / "logs"
    if not log_dir.is_dir():
        return []

    paths = sorted(log_dir.glob("call_data_record_*.log"))
    rows: List[Dict[str, Any]] = []

    for path in paths:
        try:
            with open(path, encoding="utf-8", errors="replace") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        obj = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    if obj.get("call_id") != call_id:
                        continue
                    rows.append(obj)
                    if len(rows) >= max_lines:
                        return _sort_by_ts(rows)
        except OSError:
            continue

    return _sort_by_ts(rows)


def _sort_by_ts(rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    def key(r: Dict[str, Any]) -> str:
        return str(r.get("ts") or "")

    return sorted(rows, key=key)
