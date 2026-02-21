"""
후처리 STT 테스트 스크립트

일반 SIP 통화 녹음 후 자동 전사 테스트
"""

import asyncio
import sys
import os
from pathlib import Path

# 프로젝트 루트를 Python 경로에 추가
sys.path.insert(0, str(Path(__file__).parent.parent))

from src.sip_core.sip_call_recorder import SIPCallRecorder
import structlog

logger = structlog.get_logger(__name__)


async def test_post_processing_stt():
    """
    후처리 STT 테스트
    
    시나리오:
    1. SIPCallRecorder 초기화 (후처리 STT 활성화)
    2. 통화 시작
    3. 더미 오디오 패킷 추가
    4. 통화 종료 및 STT 실행
    5. transcript.txt 확인
    """
    
    print("=" * 70)
    print("🎤 후처리 STT 테스트 시작")
    print("=" * 70)
    
    # 1. SIPCallRecorder 초기화
    print("\n[1단계] SIPCallRecorder 초기화...")
    
    recorder = SIPCallRecorder(
        output_dir="./test_recordings",
        sample_rate=8000,
        enable_post_stt=True,
        enable_diarization=True,
        stt_language="ko-KR",
        gcp_credentials_path="./config/gcp-key.json"
    )
    
    print(f"  ✅ 후처리 STT 활성화: {recorder.enable_post_stt}")
    print(f"  ✅ 화자 분리 활성화: {recorder.enable_diarization}")
    print(f"  ✅ STT 언어: {recorder.stt_language}")
    
    # 2. 통화 시작
    print("\n[2단계] 통화 녹음 시작...")
    
    test_call_id = "test-call-001"
    caller_id = "1001@test.com"
    callee_id = "1002@test.com"
    
    await recorder.start_recording(
        call_id=test_call_id,
        caller_id=caller_id,
        callee_id=callee_id
    )
    
    print(f"  ✅ 통화 ID: {test_call_id}")
    print(f"  ✅ 발신자: {caller_id}")
    print(f"  ✅ 착신자: {callee_id}")
    
    # 3. 더미 오디오 패킷 추가 (실제 환경에서는 RTP Relay에서 자동으로 전달)
    print("\n[3단계] 오디오 패킷 추가 (시뮬레이션)...")
    
    # 실제 테스트를 위해서는 실제 WAV 파일이 필요합니다.
    # 여기서는 구조만 확인
    
    # 더미 G.711 패킷 (실제로는 RTP Relay에서 전달)
    # dummy_audio = b'\xFF' * 160  # 20ms @ 8kHz
    # for i in range(100):  # 2초 시뮬레이션
    #     await recorder.add_rtp_packet(
    #         call_id=test_call_id,
    #         audio_data=dummy_audio,
    #         direction="caller" if i % 2 == 0 else "callee",
    #         codec="PCMU"
    #     )
    
    print("  ⚠️  실제 오디오 패킷 추가는 RTP Relay에서 자동으로 처리됩니다.")
    print("  ⚠️  테스트를 위해 기존 녹음 파일을 사용하거나 실제 통화가 필요합니다.")
    
    # 4. 통화 종료 (실제 환경 시뮬레이션)
    print("\n[4단계] 통화 종료 및 후처리 STT 실행...")
    print("  ⏳ 실제 통화가 있는 경우, 여기서 STT가 실행됩니다...")
    print("  ⏳ 처리 시간: 통화 길이에 따라 몇 초 ~ 몇 분")
    
    # 실제 녹음이 있는 경우에만 STT 실행
    # metadata = await recorder.stop_recording(test_call_id)
    
    # 5. 결과 확인
    print("\n[5단계] 결과 확인...")
    
    # 실제 테스트 파일 경로 예시
    test_recording_path = Path("./recordings/existing-call-id")
    
    if test_recording_path.exists():
        transcript_path = test_recording_path / "transcript.txt"
        
        if transcript_path.exists():
            print(f"  ✅ Transcript 생성됨: {transcript_path}")
            
            with open(transcript_path, 'r', encoding='utf-8') as f:
                transcript_content = f.read()
            
            print(f"\n  📄 Transcript 내용 (처음 500자):")
            print("  " + "-" * 66)
            print(f"  {transcript_content[:500]}")
            print("  " + "-" * 66)
        else:
            print(f"  ❌ Transcript 파일이 없습니다: {transcript_path}")
    else:
        print(f"  ℹ️  테스트 녹음 파일이 없습니다: {test_recording_path}")
        print(f"  ℹ️  실제 통화를 진행하거나 기존 녹음 파일로 테스트하세요.")
    
    print("\n" + "=" * 70)
    print("✅ 후처리 STT 테스트 완료")
    print("=" * 70)
    
    # 6. 추가 정보
    print("\n📌 후처리 STT 작동 방식:")
    print("  1. 통화 종료 시 WAV 파일 생성 (caller.wav, callee.wav, mixed.wav)")
    print("  2. mixed.wav를 Google Speech-to-Text API로 전송")
    print("  3. 화자 분리(diarization)로 발신자/착신자 구분")
    print("  4. transcript.txt 생성 (형식: '발신자: ...\n착신자: ...')")
    print("  5. KnowledgeExtractor가 자동으로 지식 추출 시작")
    
    print("\n📌 필요한 설정:")
    print("  - config/gcp-key.json (Google Cloud 인증)")
    print("  - config.yaml의 post_processing_stt.enabled: true")
    print("  - google-cloud-speech 패키지 설치")
    
    print("\n📌 예상 비용:")
    print("  - Google Speech-to-Text: $0.006/분 (전화 통화 모델)")
    print("  - 화자 분리(diarization): 추가 비용 없음")
    print("  - 1분 통화 = 약 $0.006 = 약 7원")


async def test_existing_recording():
    """
    기존 녹음 파일로 후처리 STT 테스트
    
    사용법:
    1. recordings/ 디렉토리에 통화 녹음 폴더 확인
    2. mixed.wav 파일이 있는 경우 STT 실행
    """
    
    print("\n" + "=" * 70)
    print("🔍 기존 녹음 파일 검색...")
    print("=" * 70)
    
    recordings_dir = Path("./recordings")
    
    if not recordings_dir.exists():
        print("  ❌ recordings 디렉토리가 없습니다.")
        return
    
    # 모든 통화 폴더 스캔
    call_dirs = [d for d in recordings_dir.iterdir() if d.is_dir()]
    
    if not call_dirs:
        print("  ℹ️  녹음 파일이 없습니다.")
        return
    
    print(f"  ✅ {len(call_dirs)}개의 녹음 발견\n")
    
    # SIPCallRecorder 초기화
    recorder = SIPCallRecorder(
        output_dir="./recordings",
        enable_post_stt=True,
        enable_diarization=True,
        stt_language="ko-KR",
        gcp_credentials_path="./config/gcp-key.json"
    )
    
    for call_dir in call_dirs[:1]:  # 첫 번째 녹음만 테스트
        mixed_wav = call_dir / "mixed.wav"
        transcript_txt = call_dir / "transcript.txt"
        
        if not mixed_wav.exists():
            print(f"  ⚠️  {call_dir.name}: mixed.wav 없음, 건너뜀")
            continue
        
        if transcript_txt.exists():
            print(f"  ℹ️  {call_dir.name}: transcript.txt 이미 존재")
            print(f"  📄 기존 내용 (처음 200자):")
            with open(transcript_txt, 'r', encoding='utf-8') as f:
                print(f"     {f.read()[:200]}")
            continue
        
        print(f"  🎤 {call_dir.name}: 후처리 STT 실행 중...")
        
        try:
            # STT 실행
            stt_result = await recorder._transcribe_audio(
                mixed_wav,
                enable_diarization=True
            )
            
            # 화자별 포맷팅
            transcript_text = recorder._format_transcript_with_speakers(
                stt_result["words"],
                stt_result["speakers"]
            )
            
            # 저장
            with open(transcript_txt, 'w', encoding='utf-8') as f:
                f.write(transcript_text)
            
            print(f"  ✅ Transcript 생성 완료!")
            print(f"  📄 내용 (처음 300자):")
            print("     " + "-" * 60)
            print(f"     {transcript_text[:300]}")
            print("     " + "-" * 60)
            
        except Exception as e:
            print(f"  ❌ STT 실행 실패: {e}")


if __name__ == "__main__":
    print("\n🚀 후처리 STT 테스트 스크립트\n")
    
    # 테스트 모드 선택
    print("테스트 모드를 선택하세요:")
    print("  1. 구조 테스트 (더미 데이터)")
    print("  2. 기존 녹음 파일로 실제 STT 테스트")
    
    try:
        choice = input("\n선택 (1/2): ").strip()
        
        if choice == "1":
            asyncio.run(test_post_processing_stt())
        elif choice == "2":
            asyncio.run(test_existing_recording())
        else:
            print("❌ 잘못된 선택입니다.")
    except KeyboardInterrupt:
        print("\n\n⚠️  테스트 중단됨")
    except Exception as e:
        print(f"\n❌ 오류 발생: {e}")
        import traceback
        traceback.print_exc()

