# STT 비활성화 문제 수정

## 🔍 문제 발견

### 증상
마지막 통화 (`20260130_135805_1004_to_1003`)에서:
- ❌ `transcript.txt` 파일 생성되지 않음
- ❌ `metadata.json`에 `"has_transcript": false`
- ❌ 로그에 `"enable_post_stt": false"`

### 원인
**파일:** `sip-pbx/src/sip_core/sip_endpoint.py` (Line 80)

```python
# ❌ 잘못된 코드
recording_config = getattr(config, 'recording', None)
```

**문제:**
- 최상위 `recording` 키를 찾으려 했으나, 실제로는 `ai_voicebot.recording`에 있음
- `recording_config`가 `None`이 되어 STT 설정을 읽지 못함
- 기본값 `enable_post_stt = False`가 사용됨

### config.yaml 구조

```yaml
# ❌ 최상위에 recording 키가 없음
sip:
  ...

media:
  ...

# ✅ recording은 ai_voicebot 하위에 있음
ai_voicebot:
  enabled: true
  google_cloud:
    credentials_path: "config/gcp-key.json"
    stt:
      language_code: "ko-KR"
  
  recording:  # ← 여기!
    enabled: true
    post_processing_stt:
      enabled: true  # ← 이것을 못 읽음
      language: "ko-KR"
```

---

## ✅ 수정 내용

**파일:** `sip-pbx/src/sip_core/sip_endpoint.py` (Line 79-106)

### Before (잘못된 순서)
```python
# 1. recording_config를 먼저 찾음 (실패)
recording_config = getattr(config, 'recording', None)

# 2. ai_voicebot_config를 나중에 찾음
ai_voicebot_config = getattr(config, 'ai_voicebot', None)
```

### After (올바른 순서)
```python
# 1. ai_voicebot_config를 먼저 찾음
ai_voicebot_config = getattr(config, 'ai_voicebot', None)

# 2. ai_voicebot 하위의 recording_config를 찾음
if ai_voicebot_config:
    recording_config = getattr(ai_voicebot_config, 'recording', None)
    
    # GCP 인증 경로도 함께 가져옴
    google_cloud_config = getattr(ai_voicebot_config, 'google_cloud', None)
    if google_cloud_config:
        gcp_credentials_path = getattr(google_cloud_config, 'credentials_path', None)

# 3. STT 설정 읽기
if recording_config:
    post_stt_config = getattr(recording_config, 'post_processing_stt', None)
    if post_stt_config:
        enable_post_stt = getattr(post_stt_config, 'enabled', False)
        stt_language = getattr(post_stt_config, 'language', "ko-KR")
        
        # 디버깅용 로그 추가
        logger.info("stt_config_loaded",
                   enable_post_stt=enable_post_stt,
                   stt_language=stt_language,
                   has_gcp_credentials=gcp_credentials_path is not None)
```

---

## 📊 수정 후 예상 동작

### 서버 시작 시 로그
```json
{
  "output_dir": "recordings",
  "sample_rate": 8000,
  "enable_post_stt": true,  // ✅ true로 변경!
  "enable_diarization": true,
  "event": "SIPCallRecorder initialized"
}

{
  "enable_post_stt": true,
  "stt_language": "ko-KR",
  "has_gcp_credentials": true,
  "event": "stt_config_loaded"  // ✅ 새로운 로그
}
```

### 통화 종료 시 로그
```json
{
  "call_id": "xxx",
  "audio_file": "recordings/xxx/mixed.wav",
  "event": "Starting STT transcription"
}

{
  "call_id": "xxx",
  "transcript_length": 45,
  "words_count": 12,
  "event": "STT transcription completed"
}

{
  "call_id": "xxx",
  "file_path": "recordings/xxx/transcript.txt",
  "event": "Transcript saved to file"
}
```

### 생성되는 파일
```
recordings/YYYYMMDD_HHMMSS_caller_to_callee/
├── caller.wav
├── callee.wav
├── mixed.wav
├── transcript.txt  ✅ 생성됨!
└── metadata.json   (has_transcript: true)
```

---

## 🧪 테스트 방법

### 1. 서버 재시작
```powershell
cd C:\work\workspace_sippbx\sip-pbx
.\start-server.ps1
```

**확인 항목:**
- 로그에 `"enable_post_stt": true` 출력
- 로그에 `"stt_config_loaded"` 이벤트 출력

### 2. 통화 진행
- Caller: 1004
- Callee: 1003
- **통화 시간:** 최소 10초 이상
- **음성:** 명확한 한국어 발화
  - 예: "안녕하세요, STT 테스트 중입니다"

### 3. 통화 종료 후 확인

#### 파일 확인
```powershell
# 최근 녹음 디렉토리
cd C:\work\workspace_sippbx\sip-pbx\recordings
dir | Sort-Object LastWriteTime -Descending | Select-Object -First 1

# 파일 목록 확인
cd (최근_디렉토리)
dir
# transcript.txt가 있어야 함!
```

#### transcript.txt 내용 확인
```powershell
cat transcript.txt
```

**예상 출력:**
```
발신자: 안녕하세요 STT 테스트 중입니다
착신자: 네 잘 들립니다
```

#### metadata.json 확인
```powershell
cat metadata.json
```

**확인 항목:**
- `"has_transcript": true` ✅
- `"files": { "transcript": "xxx/transcript.txt" }` ✅

### 4. 로그 확인
```powershell
# STT 관련 로그 검색
Select-String -Path "logs\app.log" -Pattern "stt|transcription" -CaseSensitive:$false | Select-Object -Last 20
```

**확인 항목:**
- `"Starting STT transcription"`
- `"STT transcription completed"`
- `"Transcript saved to file"`

---

## 🎯 핵심 변경 사항 요약

| 항목 | Before | After |
|------|--------|-------|
| **config 경로** | `config.recording` (없음) | `config.ai_voicebot.recording` (존재) |
| **enable_post_stt** | `False` (기본값) | `True` (config에서 읽음) |
| **STT 동작** | ❌ 비활성화 | ✅ 활성화 |
| **transcript.txt** | ❌ 생성 안됨 | ✅ 생성됨 |
| **로그** | 간단 | 상세 (stt_config_loaded) |

---

## 📝 관련 파일

- **수정:** `sip-pbx/src/sip_core/sip_endpoint.py` (Line 79-106)
- **설정:** `sip-pbx/config/config.yaml` (ai_voicebot.recording.post_processing_stt)
- **테스트:** `test_stt.py`

---

## 다음 단계

1. ✅ 코드 수정 완료
2. ⏳ **서버 재시작** (수정 적용)
3. ⏳ **통화 테스트** (10초 이상)
4. ⏳ **STT 결과 확인** (transcript.txt)

**지금 할 일:**
```powershell
# 서버 재시작
cd C:\work\workspace_sippbx\sip-pbx
.\start-server.ps1

# 로그 확인 (다른 터미널)
Get-Content logs\app.log -Wait -Tail 20

# 통화 진행 후 결과 확인
cd recordings
dir | Sort-Object LastWriteTime -Descending | Select-Object -First 1
```
