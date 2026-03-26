"""
Pipecat 등에서 사용하는 호 전환 이벤트 — `websocket.server`로 위임.

`rag_processor`가 `from src.websocket_events import emit_transfer_initiated` 를 사용한다.
"""

from src.websocket.server import emit_transfer_initiated

__all__ = ["emit_transfer_initiated"]
