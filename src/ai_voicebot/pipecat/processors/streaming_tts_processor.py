"""
Streaming RAG → TTS Processor (Phase 3).

LLM 응답의 첫 문장이 완성되는 즉시 TTS로 전달하여
사용자 체감 응답 시간을 최소화한다.

설계서 섹션 7.6 Streaming RAG 구현:
  "LLM이 답변을 생성하는 동안 기다리지 말고,
   첫 번째 문장이 완성되는 즉시 TTS로 보내기 시작"

Pipeline 위치:
  RAG-LLM → [StreamingTTSGateway] → TTS

동작 방식:
  - LLMFullResponseStartFrame: 스트리밍 모드 시작
  - TextFrame: 텍스트 누적 → 문장 완성 시 즉시 TTS에 전달
  - LLMFullResponseEndFrame: 잔여 텍스트 플러시
"""

import asyncio
import re
import time
from datetime import datetime

import structlog

from pipecat.frames.frames import (
    Frame,
    LLMFullResponseEndFrame,
    LLMFullResponseStartFrame,
    TextFrame,
)
from pipecat.processors.frame_processor import FrameDirection, FrameProcessor

logger = structlog.get_logger(__name__)

# 문장 종결 패턴 (한국어 + 일반)
SENTENCE_END_PATTERN = re.compile(
    r'[.?!。？！]\s*$'   # 마침표, 물음표, 느낌표 + 공백
    r'|[.?!。？！]\s+'    # 문장 끝 뒤에 공백 (다음 문장 시작)
    r'|(?<=다)\.\s*'      # 한국어 "~합니다." 패턴
    r'|(?<=요)\.\s*'      # 한국어 "~해요." 패턴
    r'|(?<=죠)\.\s*'      # 한국어 "~하죠." 패턴
)


class StreamingTTSGateway(FrameProcessor):
    """
    LLM 응답 스트리밍 → TTS 게이트웨이.

    TextFrame을 누적하다가 문장이 완성되면 즉시 TTS로 전달.
    이를 통해 전체 응답 생성을 기다리지 않고 첫 문장부터 발화 시작.
    """

    def __init__(
        self,
        min_chunk_chars: int = 15,
        max_buffer_chars: int = 200,
        flush_timeout: float = 1.0,
        **kwargs,
    ):
        """
        Args:
            min_chunk_chars: TTS에 전달할 최소 문자 수 (너무 짧으면 TTS 품질 저하)
            max_buffer_chars: 이 길이를 넘으면 강제 플러시
            flush_timeout: 이 시간(초) 동안 새 텍스트가 없으면 강제 플러시
        """
        super().__init__(**kwargs)
        self._min_chunk_chars = min_chunk_chars
        self._max_buffer_chars = max_buffer_chars
        self._flush_timeout = flush_timeout

        self._buffer = ""
        self._streaming = False
        self._first_chunk_time: float = 0
        self._chunks_sent = 0
        self._flush_task: asyncio.Task = None
        self._text_frame_count = 0  # Start 이후 받은 TextFrame 수 (인사말은 1개면 분할 안 함)

    async def process_frame(self, frame: Frame, direction: FrameDirection):
        await super().process_frame(frame, direction)

        if isinstance(frame, LLMFullResponseStartFrame):
            # 스트리밍 시작
            self._streaming = True
            self._buffer = ""
            self._first_chunk_time = 0
            self._chunks_sent = 0
            self._text_frame_count = 0
            await self.push_frame(frame, direction)
            return

        if isinstance(frame, LLMFullResponseEndFrame):
            # 잔여 버퍼 플러시
            await self._flush_buffer()
            self._streaming = False
            self._cancel_flush_timer()
            self._text_frame_count = 0

            # Gateway가 TTS로 전달 완료한 시점 (재생 완료 아님 — Phase1/2 동기화는 TTSCompleteNotifier 사용)
            if self._first_chunk_time > 0:
                total_time = time.time() - self._first_chunk_time
                logger.info("streaming_tts_gateway_flushed",
                           call=True,
                           progress="tts",
                           chunks_sent=self._chunks_sent,
                           total_time=f"{total_time:.2f}s",
                           note="gateway→TTS 전달 완료, TTS 합성/재생 완료 아님")

            await self.push_frame(frame, direction)
            return

        if isinstance(frame, TextFrame) and self._streaming:
            # 텍스트 누적
            self._buffer += frame.text
            self._text_frame_count += 1

            if self._first_chunk_time == 0:
                self._first_chunk_time = time.time()

            # 인사말 등 TextFrame 1개만 오는 응답은 문장 분할하지 않고 End에서 한 번에 전달 (Phase1 잘림 방지)
            if self._text_frame_count > 1:
                await self._try_send_sentences()

            # 최대 버퍼 초과 시 강제 플러시
            if len(self._buffer) >= self._max_buffer_chars:
                await self._flush_buffer()

            # 타임아웃 플러시 예약 (스트리밍 응답만; 인사말은 End에서 flush)
            if self._text_frame_count > 1:
                self._schedule_flush_timer()
            return

        # 기타 프레임 통과
        await self.push_frame(frame, direction)

    async def _try_send_sentences(self):
        """버퍼에서 완성된 문장을 찾아 TTS로 전달"""
        while True:
            # 문장 종결 위치 찾기
            match = SENTENCE_END_PATTERN.search(self._buffer)
            if not match:
                break

            # 문장 끝까지 추출
            end_pos = match.end()
            sentence = self._buffer[:end_pos].strip()
            self._buffer = self._buffer[end_pos:].lstrip()

            if len(sentence) >= self._min_chunk_chars:
                await self._send_chunk(sentence)
            elif sentence:
                # 너무 짧으면 다시 버퍼에 넣고 대기
                self._buffer = sentence + " " + self._buffer
                break

    async def _flush_buffer(self):
        """잔여 버퍼 강제 전달"""
        text = self._buffer.strip()
        self._buffer = ""
        if text:
            await self._send_chunk(text)

    async def _send_chunk(self, text: str):
        """TTS로 청크 전달"""
        self._chunks_sent += 1
        elapsed = time.time() - self._first_chunk_time if self._first_chunk_time else 0
        if self._chunks_sent == 1:
            logger.info("tts_first_chunk_sent_to_engine",
                        call=True,
                        progress="tts",
                        ts_iso=datetime.now().isoformat(timespec="milliseconds"),
                        note="TTS 엔진에 첫 텍스트 전달 시점")

        logger.debug("streaming_tts_chunk",
                    progress="tts",
                    chunk_num=self._chunks_sent,
                    chars=len(text),
                    elapsed=f"{elapsed:.2f}s",
                    preview=text[:60])

        await self.push_frame(TextFrame(text=text))

    def _schedule_flush_timer(self):
        """타임아웃 플러시 타이머 예약"""
        self._cancel_flush_timer()

        async def _flush_after_timeout():
            await asyncio.sleep(self._flush_timeout)
            if self._streaming and self._buffer.strip():
                await self._flush_buffer()

        self._flush_task = asyncio.create_task(_flush_after_timeout())

    def _cancel_flush_timer(self):
        """타이머 취소"""
        if self._flush_task and not self._flush_task.done():
            self._flush_task.cancel()
            self._flush_task = None
