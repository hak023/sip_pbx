"""
통화 녹음 수집 및 저장 Processor.

파이프라인에서 InputAudioRawFrame(발신자), OutputAudioRawFrame/TTSAudioRawFrame(AI)을
버퍼링하고 EndFrame 수신 시 recordings/{call_id}/mixed.wav 로 스테레오 WAV 저장.

파이프라인 삽입 위치: input transport 다음, VAD/STT 전에 넣거나;
  또는 output transport 직전에 넣어서 양쪽 오디오를 모두 볼 수 있는 위치.
  (Input만 보는 위치: input 다음; Output만 보는 위치: output 직전;
   양쪽 모두 보려면 파이프라인이 한 방향이므로 Input은 input 다음, Output은 output 직전에
   각각 하나씩 넣거나, 한 프로세서가 양방향을 보는 구조가 필요.
   Pipecat은 보통 단방향 flow이므로, 한 프로세서에서 Input 프레임과 Output 프레임을
   모두 보려면 input과 output 사이에 하나 넣으면 Input은 upstream에서 오고
   Output은 downstream TTS에서 오므로, 이 프로세서는 input 쪽 오디오는 보지만
   output 쪽 오디오는 TTS 이후에 나오므로 안 보임.)
  따라서: RecordingProcessor를 **두 개** 쓰는 방식이 맞음.
  - 하나는 Input 오디오만 수집 (input transport 다음)
  - 하나는 Output 오디오만 수집 (output transport 직전)
  그리고 EndFrame 시점에 둘을 합쳐서 저장하려면 공유 저장소가 필요.

간단한 방식: **한 프로세서만** 사용하고, 파이프라인에서 **input transport 다음**에 넣음.
  그러면 발신자(Input) 오디오만 수집됨. AI(TTS) 오디오는 이 프로세서를 통과하지 않음.
  대안: **output transport 직전**에 넣으면 TTS 오디오만 수집됨.

가장 단순한 구현: **한 프로세서가 Input + Output 둘 다 수집**하려면, 파이프라인 상
  Input -> [RecordingProcessor] -> VAD -> STT -> ... -> TTS -> [RecordingProcessor?] -> Output
  이렇게 하면 RecordingProcessor 하나로는 Input만 보임. TTS 출력은 이 프로세서를 지나지 않음.

  올바른 방법: **두 개의 프로세서**. 하나는 input 근처에서 InputAudioRawFrame 수집,
  다른 하나는 output 근처에서 OutputAudioRawFrame 수집. EndFrame은 파이프라인 끝에서
  한 번만 오므로, "수집기"를 별도 객체로 두고 두 프로세서가 같은 수집기에 append한 뒤,
  EndFrame을 보는 쪽(예: output 근처 프로세서)에서 저장하면 됨.

  구현: CallRecordingCollector 클래스 (user_chunks, ai_chunks 리스트 보관).
  - RecordingInputProcessor: InputAudioRawFrame -> collector.user_chunks.append, push frame.
  - RecordingOutputProcessor: OutputAudioRawFrame/TTS -> collector.ai_chunks.append, push frame.
  - RecordingOutputProcessor: EndFrame -> save_mixed_wav(collector), push frame.
  파이프라인: input -> RecordingInputProcessor -> ... -> RecordingOutputProcessor -> output.
  두 프로세서에 같은 collector와 call_id 전달.
"""
# 위 주석대로 두 프로세서 + 공유 수집기로 구현합니다.

import asyncio
from typing import List, Optional

import structlog

from pipecat.frames.frames import (
    EndFrame,
    Frame,
    InputAudioRawFrame,
    OutputAudioRawFrame,
)
from pipecat.processors.frame_processor import FrameDirection, FrameProcessor

try:
    from pipecat.frames.frames import TTSAudioRawFrame
except ImportError:
    TTSAudioRawFrame = type(None)

logger = structlog.get_logger(__name__)


class CallRecordingCollector:
    """통화당 오디오 청크 수집. Input(발신자) / Output(AI) 별도 리스트."""

    def __init__(self, call_id: str):
        self.call_id = call_id
        self.user_chunks: List[bytes] = []
        self.ai_chunks: List[bytes] = []
        self._saved = False

    def add_user_audio(self, data: bytes) -> None:
        if data:
            self.user_chunks.append(data)

    def add_ai_audio(self, data: bytes) -> None:
        if data:
            self.ai_chunks.append(data)

    def mark_saved(self) -> None:
        self._saved = True

    @property
    def is_saved(self) -> bool:
        return self._saved


def _get_audio_bytes(frame: Frame) -> Optional[bytes]:
    if not hasattr(frame, "audio"):
        return None
    a = getattr(frame, "audio", None)
    return a if isinstance(a, bytes) and len(a) > 0 else None


class RecordingInputProcessor(FrameProcessor):
    """
    Input 오디오(발신자) 수집. InputAudioRawFrame을 collector에 추가하고 통과.
    """

    def __init__(self, call_id: str, collector: CallRecordingCollector, **kwargs):
        super().__init__(**kwargs)
        self._call_id = call_id
        self._collector = collector

    async def process_frame(self, frame: Frame, direction: FrameDirection):
        await super().process_frame(frame, direction)
        if isinstance(frame, InputAudioRawFrame):
            data = _get_audio_bytes(frame)
            if data:
                self._collector.add_user_audio(data)
        await self.push_frame(frame, direction)


class RecordingOutputProcessor(FrameProcessor):
    """
    Output 오디오(AI/TTS) 수집. EndFrame 수신 시 save_mixed_wav 호출 후 통과.
    """

    def __init__(self, call_id: str, collector: CallRecordingCollector, **kwargs):
        super().__init__(**kwargs)
        self._call_id = call_id
        self._collector = collector

    async def process_frame(self, frame: Frame, direction: FrameDirection):
        await super().process_frame(frame, direction)

        # 오디오 수집
        is_audio = (
            isinstance(frame, OutputAudioRawFrame)
            or (TTSAudioRawFrame is not type(None) and isinstance(frame, TTSAudioRawFrame))
        )
        if is_audio:
            data = _get_audio_bytes(frame)
            if data:
                self._collector.add_ai_audio(data)

        # EndFrame 시 저장
        if isinstance(frame, EndFrame) and not self._collector.is_saved:
            try:
                from src.recording.wav_writer import save_mixed_wav
                save_mixed_wav(
                    self._call_id,
                    self._collector.user_chunks,
                    self._collector.ai_chunks,
                )
                self._collector.mark_saved()
            except Exception as e:
                logger.warning(
                    "recording_save_failed",
                    call_id=self._call_id,
                    error=str(e),
                )

        await self.push_frame(frame, direction)


def create_recording_processors(call_id: str):
    """
    통화 녹음을 위한 (collector, input_processor, output_processor) 생성.
    파이프라인 조립 시:
      collector, rec_input, rec_output = create_recording_processors(call_id)
      pipeline = Pipeline([
        transport.input(),
        rec_input,   # 발신자 오디오 수집
        vad, stt, ..., tts,
        rec_output, # AI 오디오 수집 + EndFrame 시 mixed.wav 저장
        transport.output(),
      ])
    """
    collector = CallRecordingCollector(call_id)
    input_proc = RecordingInputProcessor(call_id, collector, name="RecordingInput")
    output_proc = RecordingOutputProcessor(call_id, collector, name="RecordingOutput")
    return collector, input_proc, output_proc
