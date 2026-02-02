# STT (Speech-to-Text) 기능 테스트 가이드

## 테스트 결과

### ✅ 1단계: 설정 확인
- **STT 활성화:** `True` (config.yaml 확인)
- **언어:** `ko-KR`
- **화자 분리:** `True` (Caller/Callee 구분)

### ✅ 2단계: GCP 인증 확인
- **GCP 키 파일:** `sip-pbx/config/gcp-key.json` 존재 확인
- **인증:** 정상

### ✅ 3단계: Google Cloud STT 클라이언트
- **초기화:** 성공
- **API 연결:** 정상

### ⚠️  4단계: 기존 녹음 파일 테스트
- **파일:** `20260127_101457_1004_to_1003/mixed.wav` (101.8 KB)
- **STT 결과:** 인식된 음성 없음

**원인:** 이전 녹음 파일은 RTP 헤더 포함 문제로 음성이 왜곡되어 있음

---

## 다음 단계: 새로운 통화 녹음 및 STT 테스트

### 1. SIP PBX 서버 재시작 (수정된 코드 적용)

```bash
cd C:\work\workspace_sippbx\sip-pbx
python main.py
```

**적용된 수정사항:**
- ✅ RTP 헤더 파싱 실패 시 12 bytes 헤더 제거 (`rtp_relay.py`)
- ✅ STT 활성화 확인 (`config.yaml`)

### 2. 통화 진행

**요구사항:**
- **Caller:** 1004 (또는 다른 내선)
- **Callee:** 1003 (또는 다른 내선)
- **통화 시간:** 최소 10초 이상
- **음성:** 한국어로 **명확하게 발화**
  - 예: "안녕하세요, 테스트 중입니다"
  - 예: "날씨가 좋네요, 어떻게 지내세요?"

**중요:**
- 조용한 환경에서 테스트
- 잡음 최소화
- 명확한 발음으로 대화

### 3. 통화 종료 후 녹음 파일 확인

```bash
cd C:\work\workspace_sippbx\sip-pbx\recordings
dir
```

**확인 사항:**
- 새로운 디렉토리 생성 (`YYYYMMDD_HHMMSS_caller_to_callee`)
- `caller.wav`, `callee.wav`, `mixed.wav` 파일 생성
- `metadata.json` 파일 생성

### 4. WAV 파일 재생 확인

```bash
# Windows Media Player 또는 VLC로 재생
mixed.wav
```

**기대 결과:**
- 음성이 **명확하게** 들림
- 왜곡 없음
- 양쪽 발화자 음성 모두 들림

### 5. STT 테스트 실행

```bash
cd C:\work\workspace_sippbx
$env:PYTHONIOENCODING='utf-8'
python test_stt.py
```

**기대 결과:**
```
================================================================================
[6단계] STT 결과
================================================================================

[결과 1]
전사: 안녕하세요 테스트 중입니다
신뢰도: 98.50%

================================================================================
전체 전사:
--------------------------------------------------------------------------------
안녕하세요 테스트 중입니다 날씨가 좋네요 어떻게 지내세요
================================================================================

화자별 전사:
--------------------------------------------------------------------------------
발신자: 안녕하세요 테스트 중입니다
착신자: 날씨가 좋네요 어떻게 지내세요
================================================================================

[7단계] transcript.txt 저장 중...
✅ transcript.txt 저장 완료: recordings/YYYYMMDD_HHMMSS/transcript.txt
```

### 6. 서버 로그 확인

```bash
tail -f C:\work\workspace_sippbx\sip-pbx\logs\app.log
```

**확인 항목:**
- `SIP call recording started`
- `rtp_packet_received_raw` (패킷 수신)
- `Mixed WAV file saved`
- `Starting STT transcription`
- `STT transcription completed`
- `Transcript saved to file`

---

## STT 설정 위치

**파일:** `sip-pbx/config/config.yaml`

```yaml
ai_voicebot:
  recording:
    enabled: true
    output_dir: "./recordings"
    format: "wav"
    sample_rate: 16000
    
    # 후처리 STT (Speech-to-Text)
    post_processing_stt:
      enabled: true  # ✅ 활성화됨
      language: "ko-KR"  # 한국어
      enable_diarization: true  # 화자 분리
      model: "telephony"  # 전화 통화 최적화
      enable_automatic_punctuation: true  # 자동 구두점
      enable_word_time_offsets: true  # 타임스탬프
```

---

## 트러블슈팅

### 문제 1: STT 결과가 여전히 "인식된 음성 없음"

**원인:**
1. WAV 파일에 실제 음성이 없음
2. 음성이 너무 작음
3. 언어 설정 불일치 (한국어 음성인데 en-US 설정)

**해결:**
```bash
# WAV 파일 재생하여 음성 확인
mixed.wav

# 로그 확인
grep "rtp_packet_received" sip-pbx/logs/app.log | wc -l
# 0이면 RTP 패킷이 수신되지 않음

# 샘플 레이트 확인
python -c "import wave; w=wave.open('mixed.wav','rb'); print(f'Sample rate: {w.getframerate()}')"
# 8000Hz 여야 함
```

### 문제 2: "google-cloud-speech not installed"

**해결:**
```bash
pip install google-cloud-speech
```

### 문제 3: GCP 인증 실패

**해결:**
```bash
# GCP 키 파일 확인
Test-Path C:\work\workspace_sippbx\sip-pbx\config\gcp-key.json

# 환경 변수 설정
$env:GOOGLE_APPLICATION_CREDENTIALS="C:\work\workspace_sippbx\sip-pbx\config\gcp-key.json"
```

### 문제 4: "Quota exceeded" 에러

**원인:** Google Cloud STT API 무료 할당량 초과

**해결:**
1. Google Cloud Console에서 사용량 확인
2. 유료 플랜 활성화 또는 다음 달 기다리기
3. 다른 GCP 프로젝트 사용

---

## 코드 수정 사항 요약

### 1. RTP 헤더 처리 수정 (`rtp_relay.py`)

**Before:**
```python
except:
    audio_payload = data  # ❌ 12 bytes 헤더 포함
```

**After:**
```python
except Exception as parse_error:
    if len(data) > 12:
        audio_payload = data[12:]  # ✅ 헤더 제거
```

### 2. STT 설정 활성화 (`config.yaml`)

```yaml
post_processing_stt:
  enabled: true  # ✅ 이미 활성화됨
```

---

## 다음 작업

1. ✅ 설정 확인 완료
2. ✅ GCP 인증 확인 완료
3. ✅ STT 클라이언트 초기화 완료
4. ⏳ **새로운 통화 녹음 필요**
5. ⏳ **STT 결과 확인**

**지금 할 일:**
```bash
# 1. SIP PBX 재시작
cd C:\work\workspace_sippbx\sip-pbx
python main.py

# 2. 통화 진행 (10초 이상, 명확한 한국어 발화)

# 3. STT 테스트
cd C:\work\workspace_sippbx
$env:PYTHONIOENCODING='utf-8'
python test_stt.py
```
