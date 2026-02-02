"""
STT (Speech-to-Text) 기능 테스트 스크립트

이 스크립트는:
1. GCP 인증 확인
2. Google Cloud Speech-to-Text API 연결 테스트
3. 샘플 WAV 파일로 STT 테스트
4. 화자 분리(diarization) 테스트
"""

import asyncio
import os
import sys
from pathlib import Path
import yaml

# 프로젝트 루트
project_root = Path(__file__).parent / "sip-pbx"


async def test_stt():
    """STT 기능 테스트"""
    
    print("=" * 80)
    print("STT (Speech-to-Text) 테스트 시작")
    print("=" * 80)
    
    # 1. 설정 로드
    print("\n[1단계] 설정 로드 중...")
    try:
        config_path = project_root / "config" / "config.yaml"
        with open(config_path, 'r', encoding='utf-8') as f:
            config = yaml.safe_load(f)
        
        print("✅ 설정 로드 완료")
        
        # STT 설정 확인
        ai_voicebot_config = config.get('ai_voicebot', {})
        recording_config = ai_voicebot_config.get('recording', {})
        post_stt_config = recording_config.get('post_processing_stt', {})
        
        stt_enabled = post_stt_config.get('enabled', False)
        stt_language = post_stt_config.get('language', 'ko-KR')
        enable_diarization = post_stt_config.get('enable_diarization', True)
        
        print(f"   - STT 활성화: {stt_enabled}")
        print(f"   - 언어: {stt_language}")
        print(f"   - 화자 분리: {enable_diarization}")
        
        if not stt_enabled:
            print("❌ STT가 비활성화되어 있습니다. config.yaml에서 활성화해주세요.")
            return
            
    except Exception as e:
        print(f"❌ 설정 로드 실패: {e}")
        return
    
    # 2. GCP 인증 확인
    print("\n[2단계] GCP 인증 확인 중...")
    try:
        google_cloud_config = config.get('ai_voicebot', {}).get('google_cloud', {})
        credentials_path = google_cloud_config.get('credentials_path', None)
        
        if not credentials_path:
            print("❌ credentials_path가 설정되지 않았습니다.")
            return
        
        # 상대 경로를 절대 경로로 변환
        if not os.path.isabs(credentials_path):
            credentials_path = os.path.join(project_root, credentials_path)
        
        if not os.path.exists(credentials_path):
            print(f"❌ GCP 인증 파일이 없습니다: {credentials_path}")
            print("\nGCP 인증 파일 설정 방법:")
            print("1. Google Cloud Console에서 서비스 계정 생성")
            print("2. Speech-to-Text API 권한 부여")
            print("3. JSON 키 파일 다운로드")
            print("4. config/gcp-key.json으로 저장")
            return
        
        print(f"✅ GCP 인증 파일 확인: {credentials_path}")
        
        # 환경변수 설정
        os.environ["GOOGLE_APPLICATION_CREDENTIALS"] = credentials_path
        
    except Exception as e:
        print(f"❌ GCP 인증 확인 실패: {e}")
        return
    
    # 3. Google Cloud Speech-to-Text 클라이언트 초기화
    print("\n[3단계] Google Cloud Speech-to-Text 클라이언트 초기화 중...")
    try:
        from google.cloud import speech
        
        client = speech.SpeechClient()
        print("✅ STT 클라이언트 초기화 완료")
        
    except ImportError:
        print("❌ google-cloud-speech가 설치되지 않았습니다.")
        print("\n설치 명령:")
        print("pip install google-cloud-speech")
        return
    except Exception as e:
        print(f"❌ STT 클라이언트 초기화 실패: {e}")
        return
    
    # 4. 최근 녹음 파일 찾기
    print("\n[4단계] 최근 녹음 파일 찾기...")
    try:
        recordings_dir = project_root / "recordings"
        if not recordings_dir.exists():
            print(f"❌ 녹음 디렉토리가 없습니다: {recordings_dir}")
            print("\n먼저 통화를 진행하여 녹음 파일을 생성해주세요.")
            return
        
        # 가장 최근 녹음 디렉토리 찾기
        recording_dirs = [d for d in recordings_dir.iterdir() if d.is_dir()]
        if not recording_dirs:
            print("❌ 녹음 파일이 없습니다.")
            print("\n먼저 통화를 진행하여 녹음 파일을 생성해주세요.")
            return
        
        latest_recording = max(recording_dirs, key=lambda d: d.stat().st_mtime)
        mixed_wav = latest_recording / "mixed.wav"
        
        if not mixed_wav.exists():
            print(f"❌ mixed.wav 파일이 없습니다: {latest_recording}")
            return
        
        print(f"✅ 녹음 파일 발견: {mixed_wav}")
        print(f"   - 디렉토리: {latest_recording.name}")
        print(f"   - 파일 크기: {mixed_wav.stat().st_size / 1024:.1f} KB")
        
    except Exception as e:
        print(f"❌ 녹음 파일 찾기 실패: {e}")
        return
    
    # 5. STT 실행
    print("\n[5단계] STT 실행 중...")
    print("   (이 작업은 파일 크기에 따라 몇 초 ~ 수십 초 소요될 수 있습니다)")
    try:
        # 오디오 파일 읽기
        with open(mixed_wav, 'rb') as audio_file:
            audio_content = audio_file.read()
        
        print(f"   - 오디오 데이터 읽기 완료: {len(audio_content)} bytes")
        
        # Speech-to-Text 설정
        audio = speech.RecognitionAudio(content=audio_content)
        
        config_stt = speech.RecognitionConfig(
            encoding=speech.RecognitionConfig.AudioEncoding.LINEAR16,
            sample_rate_hertz=8000,  # 전화 품질
            language_code=stt_language,
            enable_automatic_punctuation=True,
            enable_word_time_offsets=True,
            diarization_config=speech.SpeakerDiarizationConfig(
                enable_speaker_diarization=enable_diarization,
                min_speaker_count=2,
                max_speaker_count=2,
            ) if enable_diarization else None,
            model="telephony",  # 전화 통화 최적화 모델
        )
        
        print("   - Google STT API 호출 중...")
        response = client.recognize(config=config_stt, audio=audio)
        
        print("✅ STT 완료")
        
    except Exception as e:
        print(f"❌ STT 실행 실패: {e}")
        import traceback
        traceback.print_exc()
        return
    
    # 6. 결과 출력
    print("\n[6단계] STT 결과")
    print("=" * 80)
    
    if not response.results:
        print("⚠️  인식된 음성이 없습니다.")
        print("\n가능한 원인:")
        print("1. WAV 파일에 실제 음성이 없음 (무음 또는 잡음만)")
        print("2. 음성이 너무 작거나 불명확함")
        print("3. 언어 설정이 실제 음성과 맞지 않음")
        return
    
    # 전체 전사 텍스트
    transcript_parts = []
    words_with_speakers = []
    
    for i, result in enumerate(response.results):
        alternative = result.alternatives[0]
        transcript_parts.append(alternative.transcript)
        
        print(f"\n[결과 {i+1}]")
        print(f"전사: {alternative.transcript}")
        print(f"신뢰도: {alternative.confidence:.2%}")
        
        # 단어별 정보
        if enable_diarization and hasattr(alternative, 'words'):
            for word_info in alternative.words:
                speaker_tag = word_info.speaker_tag if hasattr(word_info, 'speaker_tag') else 1
                start_time = word_info.start_time.total_seconds() if hasattr(word_info.start_time, 'total_seconds') else 0.0
                end_time = word_info.end_time.total_seconds() if hasattr(word_info.end_time, 'total_seconds') else 0.0
                
                words_with_speakers.append({
                    "word": word_info.word,
                    "speaker_tag": speaker_tag,
                    "start_time": start_time,
                    "end_time": end_time,
                })
    
    full_transcript = ' '.join(transcript_parts)
    
    print("\n" + "=" * 80)
    print("전체 전사:")
    print("-" * 80)
    print(full_transcript)
    print("=" * 80)
    
    # 화자별 전사 (diarization 활성화 시)
    if enable_diarization and words_with_speakers:
        print("\n화자별 전사:")
        print("-" * 80)
        
        current_speaker = None
        current_line = []
        
        for word_info in words_with_speakers:
            speaker_tag = word_info["speaker_tag"]
            word = word_info["word"]
            
            if speaker_tag != current_speaker:
                if current_line:
                    speaker_label = "발신자" if current_speaker == 1 else "착신자"
                    print(f"{speaker_label}: {' '.join(current_line)}")
                    current_line = []
                
                current_speaker = speaker_tag
            
            current_line.append(word)
        
        # 마지막 라인
        if current_line:
            speaker_label = "발신자" if current_speaker == 1 else "착신자"
            print(f"{speaker_label}: {' '.join(current_line)}")
        
        print("=" * 80)
    
    # 7. transcript.txt 저장
    print("\n[7단계] transcript.txt 저장 중...")
    try:
        transcript_path = latest_recording / "transcript.txt"
        with open(transcript_path, 'w', encoding='utf-8') as f:
            if enable_diarization and words_with_speakers:
                # 화자별 포맷
                current_speaker = None
                current_line = []
                
                for word_info in words_with_speakers:
                    speaker_tag = word_info["speaker_tag"]
                    word = word_info["word"]
                    
                    if speaker_tag != current_speaker:
                        if current_line:
                            speaker_label = "발신자" if current_speaker == 1 else "착신자"
                            f.write(f"{speaker_label}: {' '.join(current_line)}\n")
                            current_line = []
                        
                        current_speaker = speaker_tag
                    
                    current_line.append(word)
                
                if current_line:
                    speaker_label = "발신자" if current_speaker == 1 else "착신자"
                    f.write(f"{speaker_label}: {' '.join(current_line)}\n")
            else:
                # 전체 전사만
                f.write(full_transcript)
        
        print(f"✅ transcript.txt 저장 완료: {transcript_path}")
        
    except Exception as e:
        print(f"⚠️  transcript.txt 저장 실패: {e}")
    
    print("\n" + "=" * 80)
    print("✅ STT 테스트 완료!")
    print("=" * 80)


if __name__ == "__main__":
    asyncio.run(test_stt())
