"""
Smart Turn Detection Processor for Pipecat Pipeline.

Pipecat의 LocalSmartTurnAnalyzerV3를 파이프라인 FrameProcessor로 래핑.

기존 Pipecat에서는 TransportParams.turn_analyzer로 설정하지만,
SIPPBXTransport는 커스텀 구조이므로 별도 프로세서로 통합한다.

Pipeline 위치: RTPInput → SileroVAD → [SmartTurnProcessor] → GoogleSTT → ...

동작:
  1. VAD가 UserStoppedSpeakingFrame을 보내면 (0.5초 침묵, pipeline_builder에서 설정)
  2. 누적된 오디오를 Smart Turn 모델에 입력
  3. 모델이 "발화 완료"로 판단 → 프레임 통과 (STT에서 최종 결과 생성)
  4. 모델이 "발화 미완"으로 판단 → 프레임 억제 (사용자가 생각 중)
  5. 이후 추가 오디오가 오거나 max_wait 초과 시 강제 통과

설계서 섹션 4. Smart Turn Detection 구현.
"""

import asyncio
import time
from typing import Optional

import structlog

from pipecat.frames.frames import (
    Frame,
    InputAudioRawFrame,
    UserStartedSpeakingFrame,
    UserStoppedSpeakingFrame,
)
from pipecat.processors.frame_processor import FrameDirection, FrameProcessor

logger = structlog.get_logger(__name__)


class SmartTurnProcessor(FrameProcessor):
    """
    Smart Turn v3.2 기반 발화 종료 판단 프로세서.

    VAD의 UserStoppedSpeakingFrame을 가로채서
    Smart Turn 모델로 실제 발화 완료 여부를 판단한다.

    - 발화 완료 → UserStoppedSpeakingFrame 통과 (STT 최종 결과 트리거)
    - 발화 미완 → 프레임 억제 (이후 오디오 계속 수신)
    - max_hold_secs 초과 → 강제 통과 (무한 대기 방지)
    """

    def __init__(
        self,
        turn_analyzer,
        max_hold_secs: float = 2.0,
        **kwargs,
    ):
        """
        Args:
            turn_analyzer: LocalSmartTurnAnalyzerV3 인스턴스
            max_hold_secs: 발화 미완 시 최대 대기 시간 (초). 초과하면 강제 통과.
        """
        super().__init__(**kwargs)
        self._analyzer = turn_analyzer
        self._max_hold_secs = max_hold_secs

        # 오디오 버퍼 (현재 발화 세그먼트)
        self._audio_buffer = bytearray()
        self._is_speaking = False
        self._hold_start: Optional[float] = None
        self._held_frame: Optional[UserStoppedSpeakingFrame] = None

        # 통계
        self._stats = {
            "total_vad_stops": 0,
            "smart_turn_complete": 0,
            "smart_turn_incomplete": 0,
            "forced_release": 0,
        }

    async def process_frame(self, frame: Frame, direction: FrameDirection):
        await super().process_frame(frame, direction)

        # ── 발화 시작 ──
        if isinstance(frame, UserStartedSpeakingFrame):
            self._is_speaking = True
            self._audio_buffer = bytearray()
            self._held_frame = None
            self._hold_start = None
            await self.push_frame(frame, direction)
            return

        # ── 오디오 프레임: 버퍼에 누적 ──
        if isinstance(frame, InputAudioRawFrame):
            if self._is_speaking:
                self._audio_buffer.extend(frame.audio)

            # 대기 중(held)이면 max_hold 체크
            if self._held_frame and self._hold_start:
                elapsed = time.time() - self._hold_start
                if elapsed >= self._max_hold_secs:
                    # 최대 대기 초과 → 강제 릴리스
                    self._stats["forced_release"] += 1
                    logger.info("smart_turn_forced_release",
                               held_secs=f"{elapsed:.2f}")
                    await self._release_held_frame()

            # 오디오 프레임은 항상 통과 (STT가 계속 받아야 함)
            await self.push_frame(frame, direction)
            return

        # ── VAD 발화 종료 감지 ──
        if isinstance(frame, UserStoppedSpeakingFrame):
            self._is_speaking = False
            self._stats["total_vad_stops"] += 1

            # Smart Turn 모델로 발화 완료 판단
            is_complete = await self._analyze_turn()

            if is_complete:
                self._stats["smart_turn_complete"] += 1
                logger.debug("smart_turn_complete",
                            audio_bytes=len(self._audio_buffer))
                # 발화 완료 → 프레임 통과
                await self.push_frame(frame, direction)
                self._audio_buffer = bytearray()
            else:
                self._stats["smart_turn_incomplete"] += 1
                logger.debug("smart_turn_incomplete_holding",
                            audio_bytes=len(self._audio_buffer))
                # 발화 미완 → 프레임 보류 (다음 오디오 대기)
                self._held_frame = frame
                self._hold_start = time.time()
            return

        # ── 기타 프레임 통과 ──
        await self.push_frame(frame, direction)

    async def _analyze_turn(self) -> bool:
        """
        Smart Turn 모델로 발화 완료 여부 분석.

        Returns:
            True: 발화 완료 (turn complete)
            False: 발화 미완 (사용자가 생각 중, 다음 말 예상)
        """
        audio_data = bytes(self._audio_buffer)

        if len(audio_data) < 1600:  # 최소 0.1초 (16kHz, 16-bit)
            return True  # 너무 짧으면 완료로 간주

        try:
            # LocalSmartTurnAnalyzerV3.analyze()는 audio bytes를 받아 결과 반환
            # 결과: "complete" 또는 "incomplete"
            if hasattr(self._analyzer, 'analyze'):
                result = await asyncio.get_event_loop().run_in_executor(
                    None,
                    lambda: self._analyzer.analyze(audio_data),
                )

                if hasattr(result, 'turn_complete'):
                    return result.turn_complete
                elif isinstance(result, bool):
                    return result
                elif isinstance(result, str):
                    return result.lower() in ("complete", "true", "yes")
                else:
                    return True
            else:
                # analyze 메서드가 없으면 완료로 간주
                return True

        except Exception as e:
            logger.warning("smart_turn_analysis_error",
                          error=str(e),
                          message="Falling back to VAD-only (turn complete)")
            return True

    async def _release_held_frame(self):
        """보류된 UserStoppedSpeakingFrame 릴리스"""
        if self._held_frame:
            await self.push_frame(self._held_frame)
            self._held_frame = None
            self._hold_start = None
            self._audio_buffer = bytearray()

    def get_stats(self) -> dict:
        return dict(self._stats)
