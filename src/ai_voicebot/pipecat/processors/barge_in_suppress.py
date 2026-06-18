"""
바지인은 켜두되, TTS 중단은 "사용자 발화 인식" 시에만 (Interruption 계열 차단).

- 바지인(barge-in) 기능은 켜 둠. TTS가 멈추는 경우는 사용자 발화가 인식될 때(3자 이상 등
  기존 STT 후처리 조건 통과)만 허용하고, VAD/STT 감지만으로는 TTS를 중단하지 않음.
- InterruptionTaskFrame(업스트림): STT 등이 푸시하면 Task가 InterruptionFrame으로 변환해
  다운스트림으로 큐잉 → TTS가 멈음. 따라서 InterruptionTaskFrame도 차단해야 함.
- InterruptionFrame / StartInterruptionFrame / StopInterruptionFrame(다운스트림) 차단.
- 실제 사용자 발화는 STT → TranscriptionFrame → RAG 후처리 필터(3자 이상 등) 통과 시에만 처리.
"""

import asyncio
from typing import Optional

import structlog

# Pipecat Pipeline은 모든 프로세서에 link() 메서드가 필요함. Import 실패 시 object로 폴백하면
# AttributeError: 'BargeInSuppressProcessor' object has no attribute 'link' 발생하므로,
# 여기서는 ImportError를 전파함 (파이프라인 빌드 시 pipecat 필수).
from pipecat.processors.frame_processor import FrameProcessor, FrameDirection
from pipecat.frames.frames import (
    Frame,
    InterruptionFrame,
    InterruptionTaskFrame,
)
from src.ai_voicebot.pipecat.interruption_compat import StartInterruptionFrame, StopInterruptionFrame

_PIPECAT_AVAILABLE = True

logger = structlog.get_logger(__name__)


class BargeInSuppressProcessor(FrameProcessor):
    """
    바지인은 켜두되, TTS 중단은 사용자 발화 인식 시에만.

    InterruptionFrame 계열을 하류로 전달하지 않아, VAD만으로는 TTS가 멈추지 않음.
    TTS가 멈추는 경우는 사용자 발화가 STT로 인식될 때(3자 이상 등 기존 조건)만.
    """

    def __init__(self, call_id: Optional[str] = None, **kwargs):
        super().__init__(**kwargs)
        self._call_id = call_id or "unknown"
        self._suppressed_count = 0
        self._passed_count = 0  # 디버깅: TTS 쪽으로 전달한 프레임 수

    async def process_frame(self, frame: Frame, direction: FrameDirection):
        # Pipecat FrameProcessor 계약: StartFrame 수신 시 _started 설정 및 _check_started 통과.
        # super() 미호출 시 "StartFrame not received yet" ERROR 발생 → 반드시 호출.
        await super().process_frame(frame, direction)
        # InterruptionTaskFrame(업스트림): STT 등이 푸시 시 Task가 InterruptionFrame으로 변환해
        # 다운스트림 큐잉 → TTS가 "Barge-in detected, stopping TTS" 수행. 반드시 차단.
        # InterruptionFrame(다운스트림) 계열 + 서브클래스(타입명에 "Interruption" 포함) 차단.
        _interruption_types = (
            InterruptionTaskFrame,
            InterruptionFrame,
            StartInterruptionFrame,
        )
        if StopInterruptionFrame is not None:
            _interruption_types = _interruption_types + (StopInterruptionFrame,)
        is_interruption = isinstance(frame, _interruption_types) or "Interruption" in type(frame).__name__
        if is_interruption:
            self._suppressed_count += 1
            logger.info(
                "barge_in_suppress_blocked",
                call_id=self._call_id,
                frame_type=type(frame).__name__,
                direction=getattr(direction, "name", str(direction)),
                suppressed_count=self._suppressed_count,
                note="바지인 차단 — TTS 중단은 사용자 발화 인식(STT 3자 이상 등) 시에만",
            )
            logger.debug(
                "pipecat_interruption_frame_reached_suppress",
                call_id=self._call_id,
                frame_type=type(frame).__name__,
                processor="BargeInSuppressProcessor",
                note="Pipecat 경로: Interruption* 프레임이 우리 프로세서에 도달함 → 차단함",
            )
            # 호출자(push_interruption_task_frame_and_wait)가 무한 대기하지 않도록 이벤트 설정
            if isinstance(frame, InterruptionTaskFrame) and getattr(frame, "event", None):
                frame.event.set()
            # 전달하지 않음 → Task에 안 가므로 InterruptionFrame 미발생 → TTS 안 멈춤
            return

        # 분석용: TTS로 전달되는 프레임 중 Interruption 계열이 있으면 안 됨 (위에서 return 함)
        if "Interruption" in type(frame).__name__:
            logger.error("barge_in_suppress_interruption_passed",
                         call_id=self._call_id,
                         frame_type=type(frame).__name__,
                         direction=getattr(direction, "name", str(direction)),
                         note="BUG: Interruption* 프레임이 TTS로 전달됨 — 차단 로직 확인 필요")
        self._passed_count += 1
        # 디버깅: 생각한 대로 동작하는지 — Interruption은 막고, 그 외는 TTS로 전달됨
        if self._passed_count == 1 or self._passed_count % 500 == 0:
            logger.info("barge_in_suppress_passed",
                        call_id=self._call_id,
                        frame_type=type(frame).__name__,
                        passed_count=self._passed_count,
                        suppressed_count=self._suppressed_count,
                        note="[바지인] Interruption 아님 → TTS 방향으로 전달 (정상)")
        await self.push_frame(frame, direction)
