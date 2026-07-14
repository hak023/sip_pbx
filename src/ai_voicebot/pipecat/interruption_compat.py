"""
Pipecat 프레임 API 호환.

구버전(pipecat-ai 0.x)의 ``StartInterruptionFrame`` / ``StopInterruptionFrame`` 은
1.x(예: 1.1.0)에서 제거되고 ``InterruptionFrame`` 등으로 정리됨.
``app.log`` 의 ``cannot import name 'StartInterruptionFrame'`` 는 이 불일치 때문.

- ``StartInterruptionFrame`` → 없으면 ``InterruptionFrame`` 으로 alias (인스턴스도 동일 타입).
- ``StopInterruptionFrame`` → 없으면 ``None`` (호출부에서 ``is not None`` 처리).
"""

from __future__ import annotations

try:
    from pipecat.frames.frames import StartInterruptionFrame, StopInterruptionFrame  # type: ignore[attr-defined]
except ImportError:
    from pipecat.frames.frames import InterruptionFrame

    StartInterruptionFrame = InterruptionFrame

    try:
        from pipecat.frames.frames import StopInterruptionFrame  # type: ignore[attr-defined]
    except ImportError:
        StopInterruptionFrame = None  # type: ignore[misc, assignment]
