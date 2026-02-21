"""
Google Cloud Text-to-Speech gRPC Client

텍스트 → 음성 스트리밍 생성
"""

from google.cloud import texttospeech
import asyncio
from typing import AsyncGenerator, Optional
import structlog

logger = structlog.get_logger(__name__)


class TTSClient:
    """
    Google Cloud Text-to-Speech gRPC Client
    
    텍스트 → 음성 스트리밍 생성을 제공합니다.
    """
    
    def __init__(self, config: dict):
        """
        Args:
            config: TTS 설정
                - voice_name: "ko-KR-Chirp3-HD-Kore" (Chirp3 HD 음성 권장)
                - language_code: "ko-KR"
                - speaking_rate: 1.0
                - pitch: 0.0
                - volume_gain_db: 0.0
        """
        self.config = config
        self.client = texttospeech.TextToSpeechClient()
        
        # 음성 설정
        voice_name = config.get("voice_name", "ko-KR-Chirp3-HD-Kore")
        language_code = config.get("language_code", "ko-KR")
        
        # SSML Gender 자동 결정
        # Chirp3 HD 음성은 이름 기반으로 성별 결정
        _chirp3_female = {"Achernar", "Aoede", "Autonoe", "Callirrhoe", "Despina", 
                          "Erinome", "Gacrux", "Kore", "Laomedeia", "Leda",
                          "Pulcherrima", "Sulafat", "Vindemiatrix", "Zephyr"}
        voice_suffix = voice_name.rsplit("-", 1)[-1] if "-" in voice_name else ""
        if voice_suffix in _chirp3_female or voice_name.endswith("A") or voice_name.endswith("C"):
            ssml_gender = texttospeech.SsmlVoiceGender.FEMALE
        else:
            ssml_gender = texttospeech.SsmlVoiceGender.MALE
        
        self.voice = texttospeech.VoiceSelectionParams(
            language_code=language_code,
            name=voice_name,
            ssml_gender=ssml_gender
        )
        
        # 오디오 설정
        self.audio_config = texttospeech.AudioConfig(
            audio_encoding=texttospeech.AudioEncoding.LINEAR16,
            sample_rate_hertz=16000,
            speaking_rate=config.get("speaking_rate", 1.0),
            pitch=config.get("pitch", 0.0),
            volume_gain_db=config.get("volume_gain_db", 0.0),
        )
        
        # 상태
        self._is_generating = False
        self._stop_flag = False
        
        # 통계
        self.total_syntheses = 0
        self.total_chars = 0
        
        logger.info("TTSClient initialized", 
                   voice=voice_name,
                   language=language_code,
                   speaking_rate=config.get("speaking_rate", 1.0))
    
    async def synthesize_stream(
        self, 
        text: str,
        chunk_size: int = 4096
    ) -> AsyncGenerator[bytes, None]:
        """
        텍스트를 음성으로 변환 (스트리밍)
        
        Args:
            text: 변환할 텍스트
            chunk_size: 청크 크기 (bytes)
            
        Yields:
            오디오 청크 (bytes)
        """
        if self._is_generating:
            logger.warning("TTS already generating")
            return
        
        self._is_generating = True
        self._stop_flag = False
        
        try:
            # TTS 요청
            synthesis_input = texttospeech.SynthesisInput(text=text)
            
            # 동기 API를 비동기로 실행
            loop = asyncio.get_event_loop()
            response = await loop.run_in_executor(
                None,
                lambda: self.client.synthesize_speech(
                    input=synthesis_input,
                    voice=self.voice,
                    audio_config=self.audio_config
                )
            )
            
            # 오디오 데이터를 청크로 분할하여 스트리밍
            audio_data = response.audio_content
            
            for i in range(0, len(audio_data), chunk_size):
                # 중지 플래그 확인 (Barge-in)
                if self._stop_flag:
                    logger.info("TTS stopped (barge-in)")
                    break
                
                chunk = audio_data[i:i + chunk_size]
                yield chunk
                
                # 스트리밍 효과를 위한 짧은 대기
                await asyncio.sleep(0.01)
            
            self.total_syntheses += 1
            self.total_chars += len(text)
            
            logger.debug("TTS synthesis completed", 
                        text_length=len(text),
                        audio_length=len(audio_data))
            
        except Exception as e:
            logger.error("TTS synthesis error", error=str(e), exc_info=True)
        finally:
            self._is_generating = False
            self._stop_flag = False
    
    async def synthesize(self, text: str) -> bytes:
        """
        텍스트를 음성으로 변환 (전체)
        
        Args:
            text: 변환할 텍스트
            
        Returns:
            전체 오디오 데이터 (bytes)
        """
        try:
            synthesis_input = texttospeech.SynthesisInput(text=text)
            
            loop = asyncio.get_event_loop()
            response = await loop.run_in_executor(
                None,
                lambda: self.client.synthesize_speech(
                    input=synthesis_input,
                    voice=self.voice,
                    audio_config=self.audio_config
                )
            )
            
            self.total_syntheses += 1
            self.total_chars += len(text)
            
            logger.debug("TTS synthesis completed", text_length=len(text))
            
            return response.audio_content
            
        except Exception as e:
            logger.error("TTS synthesis error", error=str(e), exc_info=True)
            return b''
    
    def stop(self):
        """
        TTS 생성 중지 (Barge-in용)
        
        현재 생성 중인 TTS를 즉시 중지합니다.
        """
        if self._is_generating:
            self._stop_flag = True
            logger.info("TTS stop requested")
    
    def is_generating(self) -> bool:
        """
        현재 생성 중인지 확인
        
        Returns:
            생성 중 여부
        """
        return self._is_generating
    
    def get_stats(self) -> dict:
        """TTS 통계 반환"""
        return {
            "total_syntheses": self.total_syntheses,
            "total_chars": self.total_chars,
            "is_generating": self._is_generating,
            "avg_chars_per_synthesis": (
                self.total_chars / self.total_syntheses 
                if self.total_syntheses > 0 else 0
            ),
        }

