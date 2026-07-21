# SIP PBX Agent Skills

이 파일은 Cursor Agent가 프로젝트별 컨텍스트를 학습하는 데 사용됩니다.

## 🧭 문서·BMAD 개발·테스트 하네스 (필독, 2026-07-16 추가)

기능 요청 분석, 설계 문서(PRD/architecture) 갱신, BMAD 스토리 작성, 테스트/QA 리포트 작성 시
아래 두 문서를 **먼저** 확인한다(Cursor/Copilot 공통 규칙, 아래 내용의 상세판):

- [.github/instructions/sip-pbx-bmad-harness.instructions.md](../.github/instructions/sip-pbx-bmad-harness.instructions.md)
  — ① 모를 때 `docs/INDEX.md`부터 찾는 규칙, ② 요청→PRD→architecture→story→구현 순서(경로 매핑
  표 포함), ③ `tests/`·`tests_new/` 테스트 하네스 + BMAD QA 에이전트(Quinn) 리뷰/게이트 + 완료
  리포트 연동 절차.
- [docs/architecture/coding-standards.md](docs/architecture/coding-standards.md) — 로깅 컨벤션,
  DB 스키마 실제 소스, LLM Tool-calling 함정 등 실제로 검증된 코드 컨벤션(BMAD Dev 에이전트가
  `core-config.yaml`을 통해 항상 로드).

`sip-pbx/bmad/.bmad-core/`는 BMAD 에이전트(analyst/pm/architect/sm/dev/qa) 정의가 있는 곳이지만,
`sip-pbx/bmad/docs/`는 2025년 초기 스캐폴드로 이미 stale하다 — **실제 설계 문서는 전부
`sip-pbx/docs/` 아래에 있다**(`core-config.yaml`은 이를 가리키도록 2026-07-16에 상대경로로
수정됨).

## 프로젝트 개요
- **타입**: Python 기반 SIP B2BUA 서버
- **목적**: 기업용 전화 교환기 (PBX)
- **핵심 기능**: SIP 시그널링, RTP 미디어 릴레이, AI 음성봇, 통화 녹음, STT/TTS

## 아키텍처

```
[SIP Client A] <--SIP--> [B2BUA Server] <--SIP--> [SIP Client B]
                              |
                         [RTP Relay]
                              |
                    [Call Recorder + STT]
                              |
                       [Google Cloud API]
```

## 주요 모듈

### 1. SIP Core (`src/sip_core/`)
- **sip_endpoint.py**: B2BUA 메인 서버, UDP 소켓 처리
- **sip_message.py**: SIP 메시지 파싱/생성
- **sip_call_recorder.py**: 통화 녹음 + Google STT 통합

### 2. Media (`src/media/`)
- **rtp_relay.py**: RTP 패킷 릴레이 + 녹음 버퍼링
- **rtp_parser.py**: RTP 헤더 파싱

### 3. Config (`src/config/`)
- **models.py**: Pydantic 설정 모델
- **config_loader.py**: YAML 로드 + 검증

## 핵심 절차

### 통화 흐름
1. SIP INVITE 수신 (Caller → B2BUA)
2. B2BUA가 새 Call-ID 생성
3. SIP INVITE 전달 (B2BUA → Callee)
4. 200 OK 수신 → RTP 포트 추출
5. RTP Relay 시작 (양방향 패킷 중계)
6. 통화 중 RTP 패킷을 버퍼에 저장
7. BYE 수신 → 통화 종료
8. WAV 파일 생성 (caller.wav, callee.wav, mixed.wav)
9. Google Cloud STT API 호출 (후처리)
10. transcript.txt 생성

### RTP 처리 파이프라인
```
RTP 패킷 수신
  → RTP 헤더 파싱 (12 bytes)
  → Payload 추출 (G.711 인코딩)
  → audioop.ulaw2lin() 디코딩
  → PCM 16-bit 변환
  → 녹음 버퍼에 추가
  → 상대방에게 릴레이
```

### STT 처리 절차
```
통화 종료
  → mixed.wav 생성 (caller + callee 믹싱)
  → Google Cloud Speech-to-Text API 호출
  → Diarization (화자 분리)
  → transcript.txt 저장
  → metadata.json 업데이트 (has_transcript: true)
```

## 중요 설정 경로

### STT 활성화
```yaml
# config/config.yaml
ai_voicebot:
  recording:
    post_processing_stt:
      enabled: true        # ← STT 활성화
      language: "ko-KR"
      enable_diarization: true
```

### GCP 인증
```yaml
ai_voicebot:
  google_cloud:
    credentials_path: "config/gcp-key.json"  # ← Service Account 키
```

## 디버깅 체크리스트

### STT가 작동하지 않을 때
1. ✅ `config.ai_voicebot.recording.post_processing_stt.enabled: true` 확인
2. ✅ `config/gcp-key.json` 파일 존재 확인
3. ✅ 로그에서 `"enable_post_stt": true` 확인
4. ✅ 로그에서 `"stt_config_loaded"` 이벤트 확인
5. ✅ 통화 시간 10초 이상 확인
6. ✅ `has_transcript: true` in metadata.json

### 음질이 나쁠 때
1. ✅ RTP 헤더(12 bytes) 제거 확인
2. ✅ G.711 디코딩 정상 동작 확인 (audioop)
3. ✅ 샘플링 레이트: 8000Hz 확인
4. ✅ RTP 파싱 실패 시 fallback 로직 확인

### 통화 연결 실패 시
1. ✅ SIP 메시지 로그 확인 (`sip_send`, `sip_recv`)
2. ✅ Via, Contact 헤더의 IP 확인
3. ✅ Transaction timeout 확인
4. ✅ RTP 포트 바인딩 성공 확인

## 테스트 명령어

### 서버 시작
```powershell
cd C:\work\workspace_sippbx\sip-pbx
.\start-server.ps1
```

### 로그 실시간 모니터링
```powershell
Get-Content logs\app.log -Wait -Tail 20
```

### 최근 녹음 확인
```powershell
cd recordings
dir | Sort-Object LastWriteTime -Descending | Select-Object -First 1
```

### STT 결과 확인
```powershell
# 최신 디렉토리로 이동
cd (최신_디렉토리)
cat transcript.txt
cat metadata.json
```

## 코드 스타일

### 로깅
```python
# Good
logger.info("call_started", 
           call_id=call_id, 
           caller=caller, 
           callee=callee)

# Bad
print(f"Call started: {call_id}")
```

### 에러 처리
```python
# Good
try:
    result = process()
except Exception as e:
    logger.error("process_failed", 
                error=str(e), 
                exc_info=True)

# Bad
try:
    result = process()
except:
    pass
```

### Config 접근
```python
# Good
enable_stt = getattr(
    getattr(
        getattr(config, 'ai_voicebot', None), 
        'recording', 
        None
    ), 
    'post_processing_stt', 
    None
)

# Bad
enable_stt = config.ai_voicebot.recording.post_processing_stt  # AttributeError 위험
```

## 외부 의존성

### Python 라이브러리
- `pydantic`: 설정 검증
- `pyyaml`: YAML 파싱
- `structlog`: 구조화 로깅
- `google-cloud-speech`: STT
- `google-cloud-texttospeech`: TTS
- `audioop`: 오디오 코덱

### 외부 서비스
- **Google Cloud Speech-to-Text**: STT API
- **Google Cloud Text-to-Speech**: TTS API
- **Google Gemini**: LLM API

## 프로젝트 히스토리

### 해결된 주요 이슈
1. **STT 미작동 (2026-01-30)**
   - 원인: `Config` 모델에 `ai_voicebot` 필드 미정의
   - 해결: Pydantic 모델에 `AIVoicebotConfig` 클래스 추가

2. **음성 왜곡 (2026-01-29)**
   - 원인: RTP 파싱 실패 시 헤더 포함하여 디코딩
   - 해결: Fallback 로직에서 헤더(12 bytes) 건너뛰기

3. **Config 로드 실패**
   - 원인: `config.recording` 경로 오류
   - 해결: 올바른 경로 `config.ai_voicebot.recording` 사용

## 앞으로 추가될 기능 (TODO)

- [ ] Voicemail 기능
- [ ] Call Transfer (Blind/Attended)
- [ ] Conference (3자 통화)
- [ ] IVR (Interactive Voice Response)
- [ ] Presence (통화 가능 상태)
- [ ] Call Parking
- [ ] Music on Hold

---

이 SKILL.md는 Agent가 프로젝트를 이해하고 작업하는 데 필요한 모든 컨텍스트를 제공합니다.
