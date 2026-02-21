"""
SIP Call Recorder

SIP PBX 일반 통화 (사람-사람) 녹음
RTP Relay 레벨에서 패킷 캡처 및 WAV 파일 저장
후처리 STT로 transcript 생성
"""

import asyncio
import wave
import struct
from pathlib import Path
from typing import Optional, Dict, List
from datetime import datetime
import json
import structlog

logger = structlog.get_logger(__name__)


class SIPCallRecorder:
    """
    SIP 통화 녹음 (RTP Relay 레벨)
    
    - RTP 패킷 캡처
    - G.711 → PCM 변환
    - WAV 파일 저장
    - 화자 분리 (caller/callee)
    - 후처리 STT (Google Speech-to-Text)
    """
    
    def __init__(
        self, 
        output_dir: str = "./recordings", 
        sample_rate: int = 8000,
        enable_post_stt: bool = True,
        enable_diarization: bool = True,
        stt_language: str = "ko-KR",
        gcp_credentials_path: Optional[str] = None
    ):
        """
        Args:
            output_dir: 녹음 파일 저장 디렉토리
            sample_rate: 샘플레이트 (Hz) - 일반적으로 8000 (telephony)
            enable_post_stt: 후처리 STT 활성화 여부
            enable_diarization: 화자 분리(diarization) 활성화 여부
            stt_language: STT 언어 코드
            gcp_credentials_path: GCP 인증 파일 경로
        """
        self.output_dir = Path(output_dir)
        self.sample_rate = sample_rate
        self.channels = 1  # Mono
        self.sample_width = 2  # 16-bit
        
        # 후처리 STT 설정
        self.enable_post_stt = enable_post_stt
        self.enable_diarization = enable_diarization
        self.stt_language = stt_language
        self.gcp_credentials_path = gcp_credentials_path
        
        # 활성 녹음 세션
        self.active_recordings: Dict[str, dict] = {}
        
        # 출력 디렉토리 생성
        self.output_dir.mkdir(parents=True, exist_ok=True)
        
        # Google Speech-to-Text 클라이언트 초기화 (선택적)
        self.stt_client = None
        if self.enable_post_stt:
            self._init_stt_client()
        
        logger.info("SIPCallRecorder initialized", 
                   output_dir=str(self.output_dir),
                   sample_rate=sample_rate,
                   enable_post_stt=enable_post_stt,
                   enable_diarization=enable_diarization)
    
    async def start_recording(
        self, 
        call_id: str,
        caller_id: str,
        callee_id: str
    ):
        """
        통화 녹음 시작
        
        Args:
            call_id: 통화 ID
            caller_id: 발신자 ID
            callee_id: 수신자 ID
        """
        if call_id in self.active_recordings:
            logger.warning("Recording already active", call_id=call_id)
            return
        
        logger.info("SIP call recording started", 
                   call_id=call_id,
                   caller=caller_id,
                   callee=callee_id)
        
        # 녹음 디렉토리 생성 (타임스탬프 기반)
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        dir_name = f"{timestamp}_{caller_id}_to_{callee_id}"
        call_dir = self.output_dir / dir_name
        call_dir.mkdir(parents=True, exist_ok=True)
        
        logger.info("Recording directory created",
                   call_id=call_id,
                   directory=str(call_dir))
        
        # 녹음 세션 초기화
        self.active_recordings[call_id] = {
            "start_time": datetime.now(),
            "caller_id": caller_id,
            "callee_id": callee_id,
            "caller_buffer": [],
            "callee_buffer": [],
            "caller_frames": 0,
            "callee_frames": 0,
            "call_dir": call_dir,
            "dir_name": dir_name  # 디렉토리 이름 저장 (metadata용)
        }
    
    async def add_rtp_packet(
        self,
        call_id: str,
        audio_data: bytes,
        direction: str,
        codec: str = "PCMU"
    ):
        """
        RTP 패킷 추가 (RTP Relay에서 호출)
        
        Args:
            call_id: 통화 ID
            audio_data: RTP 페이로드 (오디오 데이터)
            direction: "caller" | "callee"
            codec: "PCMU" | "PCMA" | "opus"
        """
        recording = self.active_recordings.get(call_id)
        if not recording:
            # 통화 종료 후 잔여 RTP 패킷은 정상적으로 무시 (debug 레벨)
            # BYE 처리 후 Pipecat TTS가 잔여 패킷을 보낼 수 있음
            if not hasattr(self, '_no_recording_warned'):
                self._no_recording_warned = set()
            if call_id not in self._no_recording_warned:
                self._no_recording_warned.add(call_id)
                logger.debug("RTP packet after recording stopped (expected after BYE)",
                            call_id=call_id,
                            direction=direction)
            return
        
        # ✅ 빈 데이터 체크
        if not audio_data or len(audio_data) == 0:
            logger.warning("Empty RTP payload received",
                          call_id=call_id,
                          direction=direction)
            return
        
        # 코덱 디코딩 (G.711 → PCM)
        if codec == "PCMU":
            pcm_data = self._decode_g711_ulaw(audio_data)
        elif codec == "PCMA":
            pcm_data = self._decode_g711_alaw(audio_data)
        else:
            # Opus 등 다른 코덱은 추후 구현
            logger.warning("Unsupported codec, using raw data",
                          codec=codec,
                          call_id=call_id)
            pcm_data = audio_data
        
        # ✅ 디코딩 결과 체크
        if not pcm_data or len(pcm_data) == 0:
            logger.warning("Decoding resulted in empty PCM data",
                          call_id=call_id,
                          direction=direction,
                          codec=codec,
                          input_size=len(audio_data))
            return
        
        # 버퍼에 추가
        if direction == "caller":
            recording["caller_buffer"].append(pcm_data)
            recording["caller_frames"] += 1
            
            # 첫 10개 패킷만 디버그 로그
            if recording["caller_frames"] <= 10:
                logger.debug("Caller RTP packet added",
                            call_id=call_id,
                            frame=recording["caller_frames"],
                            pcm_size=len(pcm_data))
        elif direction == "callee":
            recording["callee_buffer"].append(pcm_data)
            recording["callee_frames"] += 1
            
            # 첫 10개 패킷만 디버그 로그
            if recording["callee_frames"] <= 10:
                logger.debug("Callee RTP packet added",
                            call_id=call_id,
                            frame=recording["callee_frames"],
                            pcm_size=len(pcm_data))
    
    def _decode_g711_ulaw(self, ulaw_data: bytes) -> bytes:
        """
        G.711 μ-law → PCM 변환
        
        Args:
            ulaw_data: μ-law 인코딩된 데이터
            
        Returns:
            PCM 16-bit 데이터
        """
        import audioop
        try:
            return audioop.ulaw2lin(ulaw_data, 2)  # 2 = 16-bit
        except Exception as e:
            logger.error("G.711 μ-law decode error", error=str(e))
            return b''
    
    def _decode_g711_alaw(self, alaw_data: bytes) -> bytes:
        """
        G.711 A-law → PCM 변환
        
        Args:
            alaw_data: A-law 인코딩된 데이터
            
        Returns:
            PCM 16-bit 데이터
        """
        import audioop
        try:
            return audioop.alaw2lin(alaw_data, 2)  # 2 = 16-bit
        except Exception as e:
            logger.error("G.711 A-law decode error", error=str(e))
            return b''
    
    async def stop_recording(self, call_id: str) -> dict:
        """
        녹음 중지 및 파일 저장
        
        Args:
            call_id: 통화 ID
            
        Returns:
            저장된 파일 정보 dict
        """
        recording = self.active_recordings.pop(call_id, None)
        if not recording:
            logger.warning("No active recording", call_id=call_id)
            return {}
        
        end_time = datetime.now()
        duration = (end_time - recording["start_time"]).total_seconds()
        
        call_dir = recording["call_dir"]
        
        # 파일 경로
        caller_path = call_dir / "caller.wav"
        callee_path = call_dir / "callee.wav"
        mixed_path = call_dir / "mixed.wav"
        metadata_path = call_dir / "metadata.json"
        transcript_path = call_dir / "transcript.txt"
        
        # WAV 파일 저장 (병렬)
        await asyncio.gather(
            self._save_wav(caller_path, recording["caller_buffer"]),
            self._save_wav(callee_path, recording["callee_buffer"]),
            self._save_mixed_wav(mixed_path, recording)
        )
        
        # 후처리 STT 실행 (선택적, 비동기)
        transcript_text = ""
        if self.enable_post_stt and mixed_path.exists():
            try:
                logger.info("stt_post_process_start",
                           category="stt",
                           progress="stt",
                           call_id=call_id,
                           audio_file=str(mixed_path),
                           diarization_enabled=self.enable_diarization)
                
                stt_result = await self._transcribe_audio(
                    mixed_path,
                    enable_diarization=self.enable_diarization
                )
                
                logger.info("stt_post_process_completed",
                           category="stt",
                           progress="stt",
                           call_id=call_id,
                           has_words=bool(stt_result.get("words")),
                           has_speakers=bool(stt_result.get("speakers")),
                           word_count=len(stt_result.get("words", [])))
                
                # 화자별 포맷팅
                if self.enable_diarization and stt_result.get("words"):
                    logger.info("stt_diarization_format",
                               category="stt",
                               call_id=call_id)
                    
                    transcript_text = self._format_transcript_with_speakers(
                        stt_result["words"],
                        stt_result["speakers"]
                    )
                else:
                    transcript_text = stt_result.get("transcript", "")
                
                # transcript.txt 저장
                if transcript_text:
                    with open(transcript_path, 'w', encoding='utf-8') as f:
                        f.write(transcript_text)
                    
                    logger.info("stt_transcript_saved",
                               call=True,
                               category="stt",
                               call_id=call_id,
                               file_path=str(transcript_path),
                               transcript_length=len(transcript_text),
                               preview=transcript_text[:100] + "..." if len(transcript_text) > 100 else transcript_text)
                else:
                    logger.warning("stt_empty_transcript", call=True, category="stt", call_id=call_id)
                    
            except Exception as e:
                logger.error("❌ [STT Flow] Post-processing STT error",
                            call_id=call_id,
                            error=str(e),
                            exc_info=True)
        
        # 메타데이터 생성
        metadata = {
            "call_id": call_id,
            "directory": recording["dir_name"],  # ✅ 디렉토리 이름 추가
            "caller_id": recording["caller_id"],
            "callee_id": recording["callee_id"],
            "start_time": recording["start_time"].isoformat(),
            "end_time": end_time.isoformat(),
            "duration": duration,
            "type": "sip_call",  # vs "ai_call"
            "sample_rate": self.sample_rate,
            "channels": self.channels,
            "caller_frames": recording["caller_frames"],
            "callee_frames": recording["callee_frames"],
            "has_transcript": transcript_path.exists(),
            "files": {
                "caller": str(caller_path.relative_to(self.output_dir)),
                "callee": str(callee_path.relative_to(self.output_dir)),
                "mixed": str(mixed_path.relative_to(self.output_dir)),
                "transcript": str(transcript_path.relative_to(self.output_dir)) if transcript_path.exists() else None
            }
        }
        
        # 메타데이터 저장
        with open(metadata_path, "w") as f:
            json.dump(metadata, f, indent=2)
        
        logger.info("SIP call recording stopped", 
                   call_id=call_id,
                   duration=duration,
                   caller_frames=recording["caller_frames"],
                   callee_frames=recording["callee_frames"],
                   has_transcript=metadata["has_transcript"])
        
        return metadata
    
    async def _save_wav(self, path: Path, buffer: list):
        """
        WAV 파일 저장
        
        Args:
            path: 저장 경로
            buffer: PCM 데이터 버퍼
        """
        if not buffer:
            logger.warning("Empty buffer, skipping WAV save", path=str(path))
            return
        
        try:
            # 버퍼 결합
            pcm_data = b''.join(buffer)
            
            # WAV 파일 생성
            with wave.open(str(path), 'wb') as wav_file:
                wav_file.setnchannels(self.channels)
                wav_file.setsampwidth(self.sample_width)
                wav_file.setframerate(self.sample_rate)
                wav_file.writeframes(pcm_data)
            
            logger.debug("WAV file saved", 
                        path=str(path),
                        size=len(pcm_data))
        except Exception as e:
            logger.error("WAV save error", 
                        path=str(path),
                        error=str(e),
                        exc_info=True)
    
    async def _save_mixed_wav(self, path: Path, recording: dict):
        """
        믹싱된 WAV 파일 저장 (caller + callee)
        
        Args:
            path: 저장 경로
            recording: 녹음 세션 정보
        """
        caller_buffer = recording["caller_buffer"]
        callee_buffer = recording["callee_buffer"]
        
        # ✅ 둘 다 비어있으면 스킵
        if not caller_buffer and not callee_buffer:
            logger.warning("Empty buffers, skipping mixed WAV", path=str(path))
            return
        
        try:
            # ✅ 한쪽만 있는 경우 처리
            if not caller_buffer:
                logger.info("Only callee audio available, using callee only", path=str(path))
                mixed_data = b''.join(callee_buffer)
            elif not callee_buffer:
                logger.info("Only caller audio available, using caller only", path=str(path))
                mixed_data = b''.join(caller_buffer)
            else:
                # ✅ 둘 다 있는 경우 믹싱
                caller_data = b''.join(caller_buffer)
                callee_data = b''.join(callee_buffer)
                
                logger.info("Mixing caller and callee audio",
                           caller_size=len(caller_data),
                           callee_size=len(callee_data),
                           caller_frames=len(caller_buffer),
                           callee_frames=len(callee_buffer))
                
                mixed_data = self._mix_audio(caller_data, callee_data)
            
            # ✅ 믹싱된 데이터가 비어있으면 에러
            if not mixed_data:
                logger.error("Mixed data is empty after processing", path=str(path))
                return
            
            # WAV 파일 생성
            with wave.open(str(path), 'wb') as wav_file:
                wav_file.setnchannels(self.channels)
                wav_file.setsampwidth(self.sample_width)
                wav_file.setframerate(self.sample_rate)
                wav_file.writeframes(mixed_data)
            
            logger.info("Mixed WAV file saved", 
                        path=str(path),
                        size=len(mixed_data),
                        duration_sec=len(mixed_data) / (self.sample_rate * self.sample_width))
        except Exception as e:
            logger.error("Mixed WAV save error", 
                        path=str(path),
                        error=str(e),
                        exc_info=True)
    
    def _mix_audio(self, audio1: bytes, audio2: bytes) -> bytes:
        """
        두 오디오 스트림 믹싱 (평균)
        
        Args:
            audio1: 첫 번째 PCM 데이터
            audio2: 두 번째 PCM 데이터
            
        Returns:
            믹싱된 PCM 데이터
        """
        # ✅ 길이 맞추기 (긴 쪽을 짧은 쪽에 맞춤, 또는 긴 쪽 유지)
        max_len = max(len(audio1), len(audio2))
        
        # ✅ 짧은 쪽을 silence(0)로 패딩
        if len(audio1) < max_len:
            audio1 = audio1 + (b'\x00' * (max_len - len(audio1)))
        if len(audio2) < max_len:
            audio2 = audio2 + (b'\x00' * (max_len - len(audio2)))
        
        # ✅ 16-bit PCM으로 언팩 (길이가 홀수면 마지막 바이트 제거)
        if len(audio1) % 2 != 0:
            audio1 = audio1[:-1]
        if len(audio2) % 2 != 0:
            audio2 = audio2[:-1]
        
        try:
            samples1 = struct.unpack(f'{len(audio1)//2}h', audio1)
            samples2 = struct.unpack(f'{len(audio2)//2}h', audio2)
            
            # ✅ 평균 믹싱 (clipping 방지)
            mixed_samples = []
            for s1, s2 in zip(samples1, samples2):
                mixed = (s1 + s2) // 2
                # Clipping 방지 (-32768 ~ 32767)
                mixed = max(-32768, min(32767, mixed))
                mixed_samples.append(mixed)
            
            # 다시 패킹
            mixed_data = struct.pack(f'{len(mixed_samples)}h', *mixed_samples)
            
            return mixed_data
            
        except struct.error as e:
            logger.error("Audio mixing struct error",
                        audio1_len=len(audio1),
                        audio2_len=len(audio2),
                        error=str(e))
            # 믹싱 실패 시 첫 번째 오디오만 반환
            return audio1
    
    def is_recording(self, call_id: str) -> bool:
        """
        통화가 녹음 중인지 확인
        
        Args:
            call_id: 통화 ID
            
        Returns:
            녹음 중이면 True
        """
        return call_id in self.active_recordings
    
    def get_recording_duration(self, call_id: str) -> float:
        """
        현재 녹음 시간 조회
        
        Args:
            call_id: 통화 ID
            
        Returns:
            녹음 시간 (초)
        """
        recording = self.active_recordings.get(call_id)
        if not recording:
            return 0.0
        
        return (datetime.now() - recording["start_time"]).total_seconds()
    
    def _init_stt_client(self):
        """
        Google Speech-to-Text 클라이언트 초기화
        """
        try:
            from google.cloud import speech
            import os
            
            # ✅ 빠른 실패: 인증 파일이 없으면 즉시 종료
            if not self.gcp_credentials_path:
                logger.warning("Google Cloud credentials path not provided, post-processing STT disabled")
                self.enable_post_stt = False
                return
            
            if not os.path.exists(self.gcp_credentials_path):
                logger.warning("Google Cloud credentials file not found, post-processing STT disabled", 
                             path=self.gcp_credentials_path)
                self.enable_post_stt = False
                return
            
            # GCP 인증 설정
            os.environ["GOOGLE_APPLICATION_CREDENTIALS"] = self.gcp_credentials_path
            
            # ✅ 타임아웃 설정 (5초)
            import socket
            old_timeout = socket.getdefaulttimeout()
            socket.setdefaulttimeout(5.0)
            
            try:
                self.stt_client = speech.SpeechClient()
                logger.info("Google Speech-to-Text client initialized")
            finally:
                socket.setdefaulttimeout(old_timeout)
                
        except ImportError:
            logger.warning("google-cloud-speech not installed, post-processing STT disabled")
            self.enable_post_stt = False
        except Exception as e:
            logger.error("Failed to initialize STT client", error=str(e))
            self.enable_post_stt = False
    
    async def _transcribe_audio(
        self, 
        audio_path: Path,
        enable_diarization: bool = True
    ) -> Dict[str, any]:
        """
        WAV 파일을 STT로 전사 (후처리)
        
        전화 통화의 경우, caller.wav와 callee.wav를 각각 STT 처리하여 결합합니다.
        이 방법이 mixed.wav의 화자 분리보다 훨씬 정확합니다.
        
        Args:
            audio_path: WAV 파일 경로 (mixed.wav)
            enable_diarization: 화자 분리 활성화 (caller/callee 개별 처리 시 무시됨)
            
        Returns:
            {
                "transcript": "전체 전사 텍스트",
                "words": [{"word": "단어", "speaker_tag": 1, "start_time": 0.0, "end_time": 0.5}],
                "speakers": {1: "caller", 2: "callee"}
            }
        """
        if not self.stt_client:
            logger.warning("STT client not initialized")
            return {"transcript": "", "words": [], "speakers": {}}
        
        # ⭐ Caller/Callee 개별 파일이 있으면 각각 STT 처리 (더 정확함)
        caller_path = audio_path.parent / "caller.wav"
        callee_path = audio_path.parent / "callee.wav"
        
        if caller_path.exists() and callee_path.exists():
            logger.info("🎯 [STT Flow] Using separate caller/callee STT (more accurate)",
                       caller_path=str(caller_path),
                       callee_path=str(callee_path))
            return await self._transcribe_separate_channels(caller_path, callee_path)
        
        # Mixed 파일만 있으면 diarization 사용 (덜 정확함)
        logger.info("⚠️ [STT Flow] Using mixed audio with diarization (less accurate)",
                   audio_path=str(audio_path))
        
        try:
            from google.cloud import speech
            
            # 오디오 파일 읽기
            with open(audio_path, 'rb') as audio_file:
                audio_content = audio_file.read()
            
            # Speech-to-Text 설정
            audio = speech.RecognitionAudio(content=audio_content)
            
            config = speech.RecognitionConfig(
                encoding=speech.RecognitionConfig.AudioEncoding.LINEAR16,
                sample_rate_hertz=self.sample_rate,
                language_code=self.stt_language,
                enable_automatic_punctuation=True,
                enable_word_time_offsets=True,
                # 화자 분리 설정
                diarization_config=speech.SpeakerDiarizationConfig(
                    enable_speaker_diarization=enable_diarization,
                    min_speaker_count=2,
                    max_speaker_count=2,
                ) if enable_diarization else None,
                model="telephony",  # 전화 통화 최적화 모델
            )
            
            logger.info("Starting STT transcription", 
                       audio_path=str(audio_path),
                       file_size=len(audio_content))
            
            # STT 실행 (동기 → 비동기 래핑)
            loop = asyncio.get_event_loop()
            response = await loop.run_in_executor(
                None,
                lambda: self.stt_client.recognize(config=config, audio=audio)
            )
            
            # 결과 파싱
            transcript_parts = []
            words_with_speakers = []
            
            logger.info("📊 [STT Debug] Parsing response", 
                       results_count=len(response.results))
            
            # ⭐ Diarization 결과는 마지막 result에 있음
            # Google STT API는 화자 분리 정보를 마지막 result에 통합하여 반환
            for idx, result in enumerate(response.results):
                alternative = result.alternatives[0]
                transcript_parts.append(alternative.transcript)
            
            # ⭐ 화자 분리가 활성화된 경우, 마지막 result에서 단어별 화자 정보 추출
            if enable_diarization and response.results:
                last_result = response.results[-1]
                last_alternative = last_result.alternatives[0]
                
                logger.info(f"📊 [STT Debug] Last result analysis",
                           has_words=hasattr(last_alternative, 'words'),
                           words_count=len(last_alternative.words) if hasattr(last_alternative, 'words') else 0)
                
                if hasattr(last_alternative, 'words'):
                    # 처음 10개 단어의 speaker_tag 확인
                    sample_words = []
                    for i, word_info in enumerate(last_alternative.words[:10]):
                        has_tag = hasattr(word_info, 'speaker_tag')
                        tag = word_info.speaker_tag if has_tag else None
                        sample_words.append({
                            "word": word_info.word,
                            "has_speaker_tag": has_tag,
                            "speaker_tag": tag
                        })
                    
                    logger.info(f"📊 [STT Debug] Sample words (first 10)", 
                               sample_words=sample_words[:5])
                    
                    # 모든 단어 추출
                    for word_info in last_alternative.words:
                        words_with_speakers.append({
                            "word": word_info.word,
                            "speaker_tag": word_info.speaker_tag if hasattr(word_info, 'speaker_tag') else 1,
                            "start_time": word_info.start_time.total_seconds() if hasattr(word_info.start_time, 'total_seconds') else 0.0,
                            "end_time": word_info.end_time.total_seconds() if hasattr(word_info.end_time, 'total_seconds') else 0.0,
                        })
                    
                    # 화자별 단어 수 카운트
                    speaker_counts = {}
                    for w in words_with_speakers:
                        tag = w.get("speaker_tag", 1)
                        speaker_counts[tag] = speaker_counts.get(tag, 0) + 1
                    
                    logger.info("📊 [STT Debug] Speaker distribution",
                               speaker_counts=speaker_counts)
            
            full_transcript = ' '.join(transcript_parts)
            
            # 화자 매핑 (가정: speaker_tag 1 = caller, 2 = callee)
            speakers = {1: "caller", 2: "callee"} if enable_diarization else {}
            
            logger.info("STT transcription completed",
                       progress="stt",
                       audio_path=str(audio_path),
                       transcript_length=len(full_transcript),
                       words_count=len(words_with_speakers),
                       speaker_tags_present=len(set(w.get("speaker_tag", 1) for w in words_with_speakers)) if words_with_speakers else 0,
                       first_10_speakers=[w.get("speaker_tag", 1) for w in words_with_speakers[:10]] if words_with_speakers else [])
            
            return {
                "transcript": full_transcript,
                "words": words_with_speakers,
                "speakers": speakers
            }
            
        except Exception as e:
            logger.error("STT transcription error",
                        progress="stt",
                        audio_path=str(audio_path),
                        error=str(e),
                        exc_info=True)
            return {"transcript": "", "words": [], "speakers": {}}
    
    def _format_transcript_with_speakers(
        self, 
        words: List[Dict],
        speakers: Dict[int, str]
    ) -> str:
        """
        화자별로 전사 텍스트 포맷팅
        
        Args:
            words: 단어 리스트 (speaker_tag 포함)
            speakers: 화자 매핑
            
        Returns:
            포맷팅된 전사 텍스트
            예: "발신자: 안녕하세요\n착신자: 네 안녕하세요"
        """
        if not words:
            return ""
        
        # 화자별로 그룹화
        current_speaker = None
        transcript_lines = []
        current_line = []
        
        # Google STT가 반환하는 서브워드 마커(▁ U+2581) 제거 — transcript 가독성
        def _norm(w: str) -> str:
            return (w or "").replace("\u2581", "").strip()

        for word_info in words:
            speaker_tag = word_info.get("speaker_tag", 1)
            word = _norm(word_info.get("word", ""))
            
            if speaker_tag != current_speaker:
                # 화자 변경 시 새로운 라인 시작
                if current_line:
                    speaker_label = self._get_speaker_label(current_speaker, speakers)
                    transcript_lines.append(f"{speaker_label}: {' '.join(current_line)}")
                    current_line = []
                
                current_speaker = speaker_tag
            
            if word:
                current_line.append(word)
        
        # 마지막 라인 추가
        if current_line:
            speaker_label = self._get_speaker_label(current_speaker, speakers)
            transcript_lines.append(f"{speaker_label}: {' '.join(current_line)}")
        
        return '\n'.join(transcript_lines)
    
    def _get_speaker_label(self, speaker_tag: int, speakers: Dict[int, str]) -> str:
        """
        화자 태그를 한글 레이블로 변환
        
        Args:
            speaker_tag: 화자 태그 (1, 2, ...)
            speakers: 화자 매핑
            
        Returns:
            "발신자" | "착신자"
        """
        speaker_role = speakers.get(speaker_tag, "caller")
        return "발신자" if speaker_role == "caller" else "착신자"
    
    async def _transcribe_separate_channels(
        self,
        caller_path: Path,
        callee_path: Path
    ) -> Dict[str, any]:
        """
        Caller와 Callee를 각각 STT 처리하여 결합
        
        이 방법이 mixed audio의 diarization보다 훨씬 정확합니다.
        
        Args:
            caller_path: caller.wav 경로
            callee_path: callee.wav 경로
            
        Returns:
            {
                "transcript": "전체 전사 텍스트",
                "words": [{"word": "단어", "speaker_tag": 1 or 2, "start_time": 0.0, "end_time": 0.5}],
                "speakers": {1: "caller", 2: "callee"}
            }
        """
        try:
            from google.cloud import speech
            
            # Caller STT
            logger.info("📞 [STT Flow] Transcribing caller audio", path=str(caller_path))
            caller_words = await self._transcribe_single_channel(
                caller_path, 
                speaker_tag=1,  # Caller = speaker 1
                speaker_role="caller"
            )
            
            # Callee STT
            logger.info("📞 [STT Flow] Transcribing callee audio", path=str(callee_path))
            callee_words = await self._transcribe_single_channel(
                callee_path,
                speaker_tag=2,  # Callee = speaker 2
                speaker_role="callee"
            )
            
            # 시간 순서대로 정렬
            all_words = caller_words + callee_words
            all_words.sort(key=lambda w: w.get("start_time", 0.0))
            
            # 전체 전사 텍스트 생성
            transcript = ' '.join([w.get("word", "") for w in all_words])
            
            # 화자별 단어 수 카운트
            speaker_counts = {}
            for w in all_words:
                tag = w.get("speaker_tag", 1)
                speaker_counts[tag] = speaker_counts.get(tag, 0) + 1
            
            logger.info("✅ [STT Flow] Separate channel transcription completed",
                       total_words=len(all_words),
                       caller_words=len(caller_words),
                       callee_words=len(callee_words),
                       speaker_distribution=speaker_counts)
            
            return {
                "transcript": transcript,
                "words": all_words,
                "speakers": {1: "caller", 2: "callee"}
            }
            
        except Exception as e:
            logger.error("Separate channel transcription failed", error=str(e), exc_info=True)
            return {"transcript": "", "words": [], "speakers": {}}
    
    async def _transcribe_single_channel(
        self,
        audio_path: Path,
        speaker_tag: int,
        speaker_role: str
    ) -> List[Dict]:
        """
        단일 채널(caller 또는 callee) STT 처리
        
        Args:
            audio_path: WAV 파일 경로
            speaker_tag: 화자 태그 (1=caller, 2=callee)
            speaker_role: 화자 역할 ("caller" or "callee")
            
        Returns:
            단어 리스트 [{"word": "단어", "speaker_tag": 1, "start_time": 0.0, "end_time": 0.5}]
        """
        try:
            from google.cloud import speech
            import os
            
            # 오디오 파일 정보
            file_size = os.path.getsize(audio_path)
            duration_sec = file_size / (self.sample_rate * 2)  # 16-bit = 2 bytes
            
            logger.info(f"📊 [STT] Audio file info",
                       audio_path=str(audio_path),
                       file_size=file_size,
                       duration_sec=round(duration_sec, 2))
            
            # 1분 이상이면 long_running_recognize 사용
            if duration_sec > 60:
                logger.info("🔄 [STT] Using LongRunningRecognize for audio > 60s",
                           duration=round(duration_sec, 2))
                return await self._transcribe_long_audio(audio_path, speaker_tag, speaker_role)
            
            # 오디오 파일 읽기
            with open(audio_path, 'rb') as audio_file:
                audio_content = audio_file.read()
            
            # Speech-to-Text 설정 (diarization 없이)
            audio = speech.RecognitionAudio(content=audio_content)
            config = speech.RecognitionConfig(
                encoding=speech.RecognitionConfig.AudioEncoding.LINEAR16,
                sample_rate_hertz=self.sample_rate,
                language_code=self.stt_language,
                enable_automatic_punctuation=True,
                enable_word_time_offsets=True,
                model="telephony",  # 전화 통화 최적화 모델
            )
            
            # STT 실행
            loop = asyncio.get_event_loop()
            response = await loop.run_in_executor(
                None,
                lambda: self.stt_client.recognize(config=config, audio=audio)
            )
            
            # 결과 파싱
            words = []
            for result in response.results:
                alternative = result.alternatives[0]
                if hasattr(alternative, 'words'):
                    for word_info in alternative.words:
                        words.append({
                            "word": word_info.word,
                            "speaker_tag": speaker_tag,  # Caller=1, Callee=2
                            "start_time": word_info.start_time.total_seconds() if hasattr(word_info.start_time, 'total_seconds') else 0.0,
                            "end_time": word_info.end_time.total_seconds() if hasattr(word_info.end_time, 'total_seconds') else 0.0,
                        })
            
            logger.info(f"✅ [{speaker_role.upper()}] STT completed",
                       words_count=len(words),
                       audio_path=str(audio_path))
            
            return words
            
        except Exception as e:
            logger.error(f"Single channel transcription failed for {speaker_role}",
                        audio_path=str(audio_path),
                        error=str(e),
                        exc_info=True)
            return []
    
    async def _transcribe_long_audio(
        self,
        audio_path: Path,
        speaker_tag: int,
        speaker_role: str
    ) -> List[Dict]:
        """
        긴 오디오(1분 이상)를 60초 단위로 chunk 처리
        
        Args:
            audio_path: WAV 파일 경로
            speaker_tag: 화자 태그 (1=caller, 2=callee)
            speaker_role: 화자 역할 ("caller" or "callee")
            
        Returns:
            단어 리스트
        """
        try:
            from google.cloud import speech
            import wave
            
            all_words = []
            
            with wave.open(str(audio_path), 'rb') as wav_file:
                framerate = wav_file.getframerate()
                n_frames = wav_file.getnframes()
                
                # 60초 단위로 chunk 처리
                chunk_duration = 60  # seconds
                chunk_frames = int(framerate * chunk_duration)
                
                time_offset = 0.0
                chunk_num = 0
                
                while wav_file.tell() < n_frames:
                    chunk_num += 1
                    chunk_data = wav_file.readframes(min(chunk_frames, n_frames - wav_file.tell()))
                    
                    if not chunk_data:
                        break
                    
                    logger.info(f"🔄 [STT] Processing chunk {chunk_num}",
                               chunk_start=round(time_offset, 2),
                               speaker=speaker_role)
                    
                    # STT API 호출
                    audio = speech.RecognitionAudio(content=chunk_data)
                    config = speech.RecognitionConfig(
                        encoding=speech.RecognitionConfig.AudioEncoding.LINEAR16,
                        sample_rate_hertz=framerate,
                        language_code=self.stt_language,
                        enable_automatic_punctuation=True,
                        enable_word_time_offsets=True,
                        model="telephony",
                    )
                    
                    loop = asyncio.get_event_loop()
                    response = await loop.run_in_executor(
                        None,
                        lambda c=chunk_data: self.stt_client.recognize(config=config, audio=speech.RecognitionAudio(content=c))
                    )
                    
                    # 결과 수집 (time offset 조정)
                    for result in response.results:
                        alternative = result.alternatives[0]
                        if hasattr(alternative, 'words'):
                            for word_info in alternative.words:
                                all_words.append({
                                    "word": word_info.word,
                                    "speaker_tag": speaker_tag,
                                    "start_time": time_offset + (word_info.start_time.total_seconds() if hasattr(word_info.start_time, 'total_seconds') else 0.0),
                                    "end_time": time_offset + (word_info.end_time.total_seconds() if hasattr(word_info.end_time, 'total_seconds') else 0.0)
                                })
                    
                    time_offset += chunk_duration
                
                logger.info(f"✅ [STT] Long audio completed",
                           speaker=speaker_role,
                           chunks=chunk_num,
                           total_words=len(all_words))
                
                return all_words
                
        except Exception as e:
            logger.error(f"Long audio transcription failed for {speaker_role}",
                        audio_path=str(audio_path),
                        error=str(e),
                        exc_info=True)
            return []

