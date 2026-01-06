"""
Call Recorder

통화 녹음 및 저장
"""

import asyncio
import wave
import os
from pathlib import Path
from typing import Optional
from datetime import datetime
import json
import structlog

from ..models.recording import RecordingMetadata, RecordingStats

logger = structlog.get_logger(__name__)


class CallRecorder:
    """
    통화 녹음 및 저장
    
    - 양방향 RTP 스트림 녹음
    - 화자 분리 (caller/callee 별도 WAV)
    - 믹싱 (단일 WAV)
    - 메타데이터 저장
    """
    
    def __init__(
        self,
        output_dir: str = "./recordings",
        sample_rate: int = 16000,
        channels: int = 1,
        sample_width: int = 2  # 16-bit
    ):
        """
        Args:
            output_dir: 녹음 파일 저장 디렉토리
            sample_rate: 샘플레이트 (Hz)
            channels: 채널 수 (1=mono)
            sample_width: 샘플 너비 (bytes, 2=16-bit)
        """
        self.output_dir = Path(output_dir)
        self.sample_rate = sample_rate
        self.channels = channels
        self.sample_width = sample_width
        
        # 녹음 버퍼
        self.caller_buffer: list[bytes] = []
        self.callee_buffer: list[bytes] = []
        self.mixed_buffer: list[bytes] = []
        
        # 녹음 상태
        self.is_recording = False
        self.call_id: Optional[str] = None
        self.start_time: Optional[datetime] = None
        
        # 통계
        self.total_recordings = 0
        
        # 출력 디렉토리 생성
        self.output_dir.mkdir(parents=True, exist_ok=True)
        
        logger.info("CallRecorder initialized", 
                   output_dir=str(self.output_dir),
                   sample_rate=sample_rate)
    
    def start_recording(self, call_id: str):
        """
        녹음 시작
        
        Args:
            call_id: 통화 ID
        """
        if self.is_recording:
            logger.warning("Already recording", call_id=self.call_id)
            return
        
        self.is_recording = True
        self.call_id = call_id
        self.start_time = datetime.now()
        
        # 버퍼 초기화
        self.caller_buffer.clear()
        self.callee_buffer.clear()
        self.mixed_buffer.clear()
        
        logger.info("Recording started", call_id=call_id)
    
    def add_caller_audio(self, audio_data: bytes):
        """
        발신자 오디오 추가
        
        Args:
            audio_data: 오디오 데이터 (16-bit PCM)
        """
        if not self.is_recording:
            return
        
        self.caller_buffer.append(audio_data)
        
        # 믹싱 버퍼에도 추가
        self._add_to_mixed(audio_data, is_caller=True)
    
    def add_callee_audio(self, audio_data: bytes):
        """
        착신자 오디오 추가
        
        Args:
            audio_data: 오디오 데이터 (16-bit PCM)
        """
        if not self.is_recording:
            return
        
        self.callee_buffer.append(audio_data)
        
        # 믹싱 버퍼에도 추가
        self._add_to_mixed(audio_data, is_caller=False)
    
    def _add_to_mixed(self, audio_data: bytes, is_caller: bool):
        """
        믹싱 버퍼에 오디오 추가
        
        간단한 믹싱: 순차적으로 append
        실제로는 타임스탬프 기반 동기화가 필요할 수 있음
        
        Args:
            audio_data: 오디오 데이터
            is_caller: 발신자 여부
        """
        # TODO: 타임스탬프 기반 동기화
        self.mixed_buffer.append(audio_data)
    
    async def stop_recording(self) -> dict:
        """
        녹음 중지 및 파일 저장
        
        Returns:
            저장된 파일 정보 dict
        """
        if not self.is_recording:
            logger.warning("Not recording")
            return {}
        
        self.is_recording = False
        end_time = datetime.now()
        duration = (end_time - self.start_time).total_seconds()
        
        # 저장 디렉토리 생성 (call_id별)
        call_dir = self.output_dir / self.call_id
        call_dir.mkdir(parents=True, exist_ok=True)
        
        # 파일 경로
        caller_path = call_dir / "caller.wav"
        callee_path = call_dir / "callee.wav"
        mixed_path = call_dir / "mixed.wav"
        transcript_path = call_dir / "transcript.txt"
        metadata_path = call_dir / "metadata.json"
        
        # WAV 파일 저장 (병렬)
        await asyncio.gather(
            self._save_wav(caller_path, self.caller_buffer),
            self._save_wav(callee_path, self.callee_buffer),
            self._save_wav(mixed_path, self.mixed_buffer)
        )
        
        # 통계 생성
        stats = RecordingStats(
            total_turns=0,  # TODO: 실제 턴 수 계산
            caller_speak_time=0.0,  # TODO: 실제 발화 시간 계산
            callee_speak_time=0.0,
            total_duration=duration,
            caller_frames=len(self.caller_buffer),
            callee_frames=len(self.callee_buffer),
            mixed_frames=len(self.mixed_buffer)
        )
        
        # 메타데이터 생성
        metadata = {
            "call_id": self.call_id,
            "recording_id": self.call_id,
            "start_time": self.start_time.isoformat(),
            "end_time": end_time.isoformat(),
            "duration_seconds": duration,
            "sample_rate": self.sample_rate,
            "channels": self.channels,
            "files": {
                "caller": str(caller_path),
                "callee": str(callee_path),
                "mixed": str(mixed_path),
                "transcript": str(transcript_path)
            },
            "stats": stats.to_dict()
        }
        
        # 메타데이터 저장
        with open(metadata_path, 'w', encoding='utf-8') as f:
            json.dump(metadata, f, indent=2, ensure_ascii=False)
        
        self.total_recordings += 1
        
        logger.info("Recording saved",
                   call_id=self.call_id,
                   duration=duration,
                   caller_frames=len(self.caller_buffer),
                   callee_frames=len(self.callee_buffer),
                   output_dir=str(call_dir))
        
        # 버퍼 정리
        self.caller_buffer.clear()
        self.callee_buffer.clear()
        self.mixed_buffer.clear()
        
        return metadata
    
    async def _save_wav(self, filepath: Path, audio_buffer: list[bytes]):
        """
        WAV 파일 저장
        
        Args:
            filepath: 저장할 파일 경로
            audio_buffer: 오디오 데이터 버퍼
        """
        if not audio_buffer:
            logger.warning("Empty audio buffer", path=str(filepath))
            return
        
        try:
            # 비동기 파일 쓰기
            loop = asyncio.get_event_loop()
            await loop.run_in_executor(
                None,
                self._write_wav_file,
                filepath,
                audio_buffer
            )
            
            logger.debug("WAV file saved", 
                        path=str(filepath),
                        frames=len(audio_buffer))
            
        except Exception as e:
            logger.error("WAV save error", 
                        path=str(filepath), 
                        error=str(e),
                        exc_info=True)
    
    def _write_wav_file(self, filepath: Path, audio_buffer: list[bytes]):
        """
        WAV 파일 쓰기 (동기)
        
        Args:
            filepath: 저장할 파일 경로
            audio_buffer: 오디오 데이터 버퍼
        """
        with wave.open(str(filepath), 'wb') as wav_file:
            wav_file.setnchannels(self.channels)
            wav_file.setsampwidth(self.sample_width)
            wav_file.setframerate(self.sample_rate)
            
            # 모든 오디오 데이터 쓰기
            for audio_data in audio_buffer:
                wav_file.writeframes(audio_data)
    
    async def save_transcript(self, call_id: str, transcript: str):
        """
        전사 텍스트 저장
        
        Args:
            call_id: 통화 ID
            transcript: 전사 텍스트
        """
        try:
            call_dir = self.output_dir / call_id
            call_dir.mkdir(parents=True, exist_ok=True)
            
            transcript_path = call_dir / "transcript.txt"
            
            with open(transcript_path, 'w', encoding='utf-8') as f:
                f.write(transcript)
            
            logger.info("Transcript saved", 
                       call_id=call_id,
                       path=str(transcript_path))
            
        except Exception as e:
            logger.error("Transcript save error", 
                        call_id=call_id, 
                        error=str(e))
    
    def get_stats(self) -> dict:
        """녹음 통계 반환"""
        return {
            "total_recordings": self.total_recordings,
            "is_recording": self.is_recording,
            "current_call_id": self.call_id,
            "output_dir": str(self.output_dir),
            "sample_rate": self.sample_rate,
        }

