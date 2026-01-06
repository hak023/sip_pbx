#!/usr/bin/env python3
"""
Google Cloud 인증 및 API 테스트 스크립트

이 스크립트는 다음을 테스트합니다:
1. Google Cloud 인증 확인
2. Speech-to-Text API (STT)
3. Text-to-Speech API (TTS)
4. Gemini LLM API

사용법:
    python tests/test_google_auth.py
"""

import os
import sys
from pathlib import Path
import asyncio
from datetime import datetime
import yaml

# 프로젝트 루트 경로 추가
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

# 환경 변수 로드
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    print("⚠️ python-dotenv가 설치되지 않았습니다. 환경 변수를 수동으로 설정하세요.")
    pass


class GoogleCloudTester:
    """Google Cloud API 테스터"""
    
    def __init__(self):
        # 설정 파일 로드
        config_path = project_root / "config" / "config.yaml"
        with open(config_path, "r", encoding="utf-8") as f:
            self.config = yaml.safe_load(f)
        
        self.ai_config = self.config["ai_voicebot"]
        
        # 인증 정보
        self.credentials_path = self.ai_config["google_cloud"]["credentials_path"]
        
        # Gemini API 키 (우선순위: config.yaml > 환경 변수)
        gemini_config = self.ai_config["google_cloud"]["gemini"]
        self.gemini_api_key = (
            gemini_config.get("api_key") or           # 1순위: config.yaml
            os.getenv("GEMINI_API_KEY") or            # 2순위: 환경 변수
            os.getenv("GOOGLE_API_KEY")               # 3순위: 환경 변수
        )
        
        self.results = {
            "auth": None,
            "stt": None,
            "tts": None,
            "gemini": None
        }
    
    def print_header(self, title: str):
        """헤더 출력"""
        print("\n" + "=" * 80)
        print(f"  {title}")
        print("=" * 80 + "\n")
    
    def print_result(self, test_name: str, success: bool, message: str = "", data: dict = None):
        """테스트 결과 출력"""
        icon = "[OK]" if success else "[FAIL]"
        print(f"{icon} {test_name}: {'성공' if success else '실패'}")
        if message:
            print(f"   {message}")
        if data:
            for key, value in data.items():
                print(f"   - {key}: {value}")
        print()
    
    def test_auth(self) -> bool:
        """Google Cloud 인증 테스트"""
        self.print_header("1. Google Cloud 인증 테스트")
        
        try:
            # Service Account 키 파일 확인
            if not os.path.exists(self.credentials_path):
                self.print_result(
                    "인증 파일 확인",
                    False,
                    f"Service Account 키 파일을 찾을 수 없습니다: {self.credentials_path}"
                )
                self.results["auth"] = False
                return False
            
            print(f"[OK] Service Account 키 파일 발견: {self.credentials_path}")
            
            # 환경 변수 설정
            os.environ["GOOGLE_APPLICATION_CREDENTIALS"] = self.credentials_path
            
            # Google Cloud 인증 확인
            from google.cloud import speech
            from google.cloud import texttospeech
            
            # Speech 클라이언트 생성 (인증 확인)
            speech_client = speech.SpeechClient()
            print("[OK] Speech-to-Text 클라이언트 생성 성공")
            
            # TTS 클라이언트 생성 (인증 확인)
            tts_client = texttospeech.TextToSpeechClient()
            print("[OK] Text-to-Speech 클라이언트 생성 성공")
            
            # Gemini API 키 확인
            if not self.gemini_api_key or self.gemini_api_key == "your-gemini-api-key-here":
                self.print_result(
                    "Gemini API 키 확인",
                    False,
                    "Gemini API 키가 설정되지 않았습니다. config.yaml 또는 환경 변수를 확인하세요."
                )
                self.results["auth"] = False
                return False
            
            # API 키 소스 확인
            gemini_config = self.ai_config["google_cloud"]["gemini"]
            key_source = "config.yaml" if gemini_config.get("api_key") else "환경 변수"
            print(f"[OK] Gemini API 키 발견: {self.gemini_api_key[:20]}... (소스: {key_source})")
            
            self.print_result(
                "인증 테스트",
                True,
                "모든 인증 정보가 정상적으로 확인되었습니다.",
                {
                    "Project ID": self.ai_config["google_cloud"]["project_id"],
                    "Credentials": self.credentials_path,
                    "Gemini API Key": f"{self.gemini_api_key[:20]}..."
                }
            )
            self.results["auth"] = True
            return True
            
        except Exception as e:
            self.print_result(
                "인증 테스트",
                False,
                f"인증 오류: {str(e)}"
            )
            self.results["auth"] = False
            return False
    
    async def test_stt(self) -> bool:
        """Speech-to-Text API 테스트"""
        self.print_header("2. Speech-to-Text (STT) API 테스트")
        
        try:
            from google.cloud import speech
            
            # 클라이언트 생성
            client = speech.SpeechClient()
            print("[OK] STT 클라이언트 생성 성공")
            
            # 테스트용 샘플 오디오 (16-bit PCM, 16kHz, Mono)
            # "안녕하세요" 음성 샘플 (실제로는 실제 오디오 파일 필요)
            # 여기서는 API 호출만 테스트
            
            # 설정
            stt_config = self.ai_config["google_cloud"]["stt"]
            config = speech.RecognitionConfig(
                encoding=speech.RecognitionConfig.AudioEncoding.LINEAR16,
                sample_rate_hertz=16000,
                language_code=stt_config["language_code"],
                model=stt_config["model"],
            )
            
            print(f"[OK] STT 설정:")
            print(f"   - Model: {stt_config['model']}")
            print(f"   - Language: {stt_config['language_code']}")
            print(f"   - Sample Rate: {stt_config['sample_rate']}Hz")
            
            # 테스트용 빈 오디오로 API 호출 테스트 (실패 예상이지만 API 연결 확인)
            try:
                # 짧은 침묵 오디오 생성 (1초)
                sample_rate = 16000
                duration = 1
                silence = bytes([0] * (sample_rate * duration * 2))  # 16-bit = 2 bytes
                
                audio = speech.RecognitionAudio(content=silence)
                
                # 동기 인식 (테스트용)
                response = client.recognize(config=config, audio=audio)
                
                # 응답이 없어도 API 호출 성공
                print("[OK] STT API 호출 성공 (침묵 오디오 테스트)")
                
            except Exception as api_error:
                # API 호출 실패가 아닌 오디오 문제는 정상
                if "audio" in str(api_error).lower():
                    print("[OK] STT API 연결 성공 (오디오 내용 문제는 정상)")
                else:
                    raise api_error
            
            stt_config = self.ai_config["google_cloud"]["stt"]
            self.print_result(
                "STT 테스트",
                True,
                "STT API가 정상적으로 작동합니다.",
                {
                    "Model": stt_config["model"],
                    "Language": stt_config["language_code"],
                    "Enhanced": stt_config["enable_enhanced"]
                }
            )
            self.results["stt"] = True
            return True
            
        except Exception as e:
            self.print_result(
                "STT 테스트",
                False,
                f"STT 오류: {str(e)}"
            )
            self.results["stt"] = False
            return False
    
    async def test_tts(self) -> bool:
        """Text-to-Speech API 테스트"""
        self.print_header("3. Text-to-Speech (TTS) API 테스트")
        
        try:
            from google.cloud import texttospeech
            
            # 클라이언트 생성
            client = texttospeech.TextToSpeechClient()
            print("[OK] TTS 클라이언트 생성 성공")
            
            # 테스트용 텍스트
            test_text = "안녕하세요, AI 비서입니다. 음성 합성 테스트 중입니다."
            
            # 입력
            synthesis_input = texttospeech.SynthesisInput(text=test_text)
            
            tts_config = self.ai_config["google_cloud"]["tts"]
            stt_config = self.ai_config["google_cloud"]["stt"]
            
            # 음성 설정
            voice = texttospeech.VoiceSelectionParams(
                language_code=stt_config["language_code"],
                name=tts_config["voice_name"],
                ssml_gender=texttospeech.SsmlVoiceGender.FEMALE
            )
            
            # 오디오 설정
            audio_config = texttospeech.AudioConfig(
                audio_encoding=texttospeech.AudioEncoding.LINEAR16,
                sample_rate_hertz=16000,
                speaking_rate=tts_config["speaking_rate"],
                pitch=tts_config["pitch"],
            )
            
            print(f"[OK] TTS 설정:")
            print(f"   - Voice: {tts_config['voice_name']}")
            print(f"   - Speaking Rate: {tts_config['speaking_rate']}")
            print(f"   - Pitch: {tts_config['pitch']}")
            print(f"   - Test Text: {test_text}")
            
            # 음성 합성 요청
            response = client.synthesize_speech(
                input=synthesis_input,
                voice=voice,
                audio_config=audio_config
            )
            
            # 오디오 데이터 확인
            audio_content = response.audio_content
            audio_size = len(audio_content)
            
            print(f"[OK] TTS 음성 합성 성공")
            print(f"   - 생성된 오디오 크기: {audio_size:,} bytes ({audio_size / 1024:.2f} KB)")
            
            # 테스트 오디오 파일 저장 (선택 사항)
            output_dir = Path("./test_outputs")
            output_dir.mkdir(exist_ok=True)
            output_file = output_dir / f"tts_test_{datetime.now().strftime('%Y%m%d_%H%M%S')}.wav"
            
            with open(output_file, "wb") as out:
                out.write(audio_content)
            
            print(f"[OK] 테스트 오디오 저장: {output_file}")
            
            tts_config = self.ai_config["google_cloud"]["tts"]
            self.print_result(
                "TTS 테스트",
                True,
                "TTS API가 정상적으로 작동합니다.",
                {
                    "Voice": tts_config["voice_name"],
                    "Audio Size": f"{audio_size:,} bytes",
                    "Output File": str(output_file)
                }
            )
            self.results["tts"] = True
            return True
            
        except Exception as e:
            self.print_result(
                "TTS 테스트",
                False,
                f"TTS 오류: {str(e)}"
            )
            self.results["tts"] = False
            return False
    
    async def test_gemini(self) -> bool:
        """Gemini LLM API 테스트"""
        self.print_header("4. Gemini LLM API 테스트")
        
        try:
            import google.generativeai as genai
            
            # API 키 설정
            genai.configure(api_key=self.gemini_api_key)
            print("[OK] Gemini API 키 설정 완료")
            
            gemini_config = self.ai_config["google_cloud"]["gemini"]
            
            # 모델 생성
            model_name = gemini_config["model"]
            model = genai.GenerativeModel(model_name=model_name)
            print(f"[OK] Gemini 모델 생성: {model_name}")
            
            # 생성 설정
            generation_config = genai.types.GenerationConfig(
                temperature=gemini_config["temperature"],
                max_output_tokens=gemini_config["max_output_tokens"],
            )
            
            print(f"[OK] 생성 설정:")
            print(f"   - Model: {model_name}")
            print(f"   - Temperature: {gemini_config['temperature']}")
            print(f"   - Max Tokens: {gemini_config['max_output_tokens']}")
            
            # 테스트 질문
            test_prompt = "안녕하세요. 간단히 자기소개를 1문장으로 해주세요."
            print(f"\n테스트 질문: {test_prompt}")
            
            # 응답 생성
            start_time = asyncio.get_event_loop().time()
            response = model.generate_content(
                test_prompt,
                generation_config=generation_config
            )
            end_time = asyncio.get_event_loop().time()
            
            response_time = (end_time - start_time) * 1000  # ms
            response_text = response.text.strip()
            
            print(f"\nGemini 응답:")
            print(f"   {response_text}")
            print(f"\n[OK] 응답 시간: {response_time:.0f}ms")
            
            # 토큰 수 추정 (한글은 대략 1자 = 2토큰)
            estimated_tokens = len(test_prompt) * 2 + len(response_text) * 2
            print(f"[OK] 추정 토큰 수: ~{estimated_tokens} 토큰")
            
            # 비용 추정 (Gemini 1.5 Flash 기준)
            if "flash" in model_name.lower():
                input_cost = (len(test_prompt) * 2 / 1_000_000) * 0.075  # $0.075 per 1M tokens
                output_cost = (len(response_text) * 2 / 1_000_000) * 0.30  # $0.30 per 1M tokens
                total_cost = input_cost + output_cost
                print(f"[OK] 추정 비용: ${total_cost:.6f} (이번 호출)")
            
            self.print_result(
                "Gemini 테스트",
                True,
                "Gemini API가 정상적으로 작동합니다.",
                {
                    "Model": model_name,
                    "Response Time": f"{response_time:.0f}ms",
                    "Response": response_text[:100] + "..." if len(response_text) > 100 else response_text,
                    "Estimated Tokens": f"~{estimated_tokens}"
                }
            )
            self.results["gemini"] = True
            return True
            
        except Exception as e:
            self.print_result(
                "Gemini 테스트",
                False,
                f"Gemini 오류: {str(e)}"
            )
            self.results["gemini"] = False
            return False
    
    def print_summary(self):
        """전체 테스트 결과 요약"""
        self.print_header("전체 테스트 결과 요약")
        
        total = len(self.results)
        passed = sum(1 for v in self.results.values() if v is True)
        failed = sum(1 for v in self.results.values() if v is False)
        
        print(f"총 테스트: {total}")
        print(f"[OK] 성공: {passed}")
        print(f"[FAIL] 실패: {failed}")
        print()
        
        for test_name, result in self.results.items():
            icon = "[OK]" if result else "[FAIL]" if result is False else "[SKIP]"
            status = "성공" if result else "실패" if result is False else "건너뜀"
            print(f"{icon} {test_name.upper()}: {status}")
        
        print()
        
        if failed == 0:
            print("모든 테스트가 성공했습니다!")
            print("Google Cloud API가 정상적으로 작동하고 있습니다.")
        else:
            print("[경고] 일부 테스트가 실패했습니다.")
            print("실패한 항목을 확인하고 다음을 점검하세요:")
            print("  1. Google Cloud 프로젝트 ID 확인")
            print("  2. Service Account 키 파일 확인")
            print("  3. API 활성화 여부 확인 (Speech-to-Text, Text-to-Speech)")
            print("  4. Gemini API 키 확인")
            print("  5. 결제 정보 등록 여부 확인")
        
        print()


async def main():
    """메인 실행 함수"""
    print("\n" + "=" * 80)
    print("  Google Cloud 인증 및 API 테스트")
    print("=" * 80)
    print()
    print(f"시작 시간: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print()
    
    tester = GoogleCloudTester()
    
    # 1. 인증 테스트
    auth_ok = tester.test_auth()
    if not auth_ok:
        print("\n[경고] 인증 실패로 인해 나머지 테스트를 건너뜁니다.")
        tester.print_summary()
        return
    
    # 2. STT 테스트
    await tester.test_stt()
    
    # 3. TTS 테스트
    await tester.test_tts()
    
    # 4. Gemini 테스트
    await tester.test_gemini()
    
    # 5. 결과 요약
    tester.print_summary()
    
    print(f"종료 시간: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print()


if __name__ == "__main__":
    asyncio.run(main())

