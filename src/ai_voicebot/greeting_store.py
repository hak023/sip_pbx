"""
통화별 AI 인사말 저장소 (Phase1/Phase2).

- RAG processor가 인사말 전송 시 저장.
- CDR 작성 시 메타데이터로 포함·조회 후 삭제.
- 실시간은 WebSocket emit으로 전달.
"""

from typing import Dict, Optional
import threading

_store: Dict[str, dict] = {}
_lock = threading.Lock()


def set_greeting(call_id: str, greeting_phase1: Optional[str] = None, greeting_phase2: Optional[str] = None) -> None:
    """통화별 인사말 저장 (phase1/phase2)."""
    if not call_id:
        return
    with _lock:
        if call_id not in _store:
            _store[call_id] = {}
        if greeting_phase1 is not None:
            _store[call_id]["greeting_phase1"] = greeting_phase1
        if greeting_phase2 is not None:
            _store[call_id]["greeting_phase2"] = greeting_phase2


def get_greeting(call_id: str) -> dict:
    """통화별 인사말 조회 (복사본)."""
    with _lock:
        return (_store.get(call_id) or {}).copy()


def pop_greeting(call_id: str) -> dict:
    """통화별 인사말 조회 후 삭제 (CDR 작성 시 사용)."""
    with _lock:
        return _store.pop(call_id, {})
