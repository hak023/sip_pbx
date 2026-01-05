# 🐛 디버깅 가이드

SIP PBX 디버깅 및 로그 확인 방법을 안내합니다.

## 📍 로그는 어디에?

### 기본 설정 (콘솔 출력)

기본적으로 **모든 로그는 콘솔(터미널)에 실시간으로 출력**됩니다!

```powershell
# 서버 실행
.\start-server.ps1

# 출력 예시:
# {"event": "server_starting", "timestamp": "2025-10-27T10:00:00Z", "level": "info"}
# {"event": "sip_server_initialized", "port": 5060, "level": "info"}
# {"event": "call_started", "call_id": "abc-123", "level": "info"}
```

### 파일로 저장하기

로그를 파일로 저장하려면:

```powershell
# 방법 1: 리다이렉션 (간단)
.\start-server.ps1 > logs\server.log 2>&1

# 방법 2: Tee (콘솔 + 파일 동시 출력)
.\start-server.ps1 | Tee-Object -FilePath logs\server.log

# 방법 3: 날짜별 로그 파일
$logFile = "logs\server-$(Get-Date -Format 'yyyy-MM-dd').log"
.\start-server.ps1 | Tee-Object -FilePath $logFile
```

---

## 🔍 로그 레벨 설정

### 레벨별 의미

| 레벨 | 용도 | 출력량 |
|------|------|--------|
| **DEBUG** | 상세한 디버깅 정보 | 매우 많음 ⚠️ |
| **INFO** | 일반 작동 정보 | 적당 ✅ (기본값) |
| **WARNING** | 경고 | 적음 |
| **ERROR** | 에러 | 매우 적음 |

### 레벨 변경 방법

#### 방법 1: start-server.ps1 파라미터

```powershell
# DEBUG 모드 (가장 상세)
.\start-server.ps1 -LogLevel DEBUG

# INFO 모드 (기본, 권장)
.\start-server.ps1 -LogLevel INFO

# ERROR 모드 (에러만)
.\start-server.ps1 -LogLevel ERROR
```

#### 방법 2: config.yaml 수정

```yaml
logging:
  level: "DEBUG"  # DEBUG, INFO, WARNING, ERROR, CRITICAL
  format: "text"  # text (읽기 쉬움) 또는 json (파싱 쉬움)
  output: "stdout"
```

---

## 🎨 로그 포맷

### JSON 포맷 (기본)

```json
{
  "event": "call_started",
  "call_id": "abc-123",
  "caller": "sip:alice@example.com",
  "timestamp": "2025-10-27T10:00:00Z",
  "level": "info"
}
```

**장점:** 파싱 쉬움, 로그 분석 도구 사용 가능

### TEXT 포맷 (디버깅용)

```
2025-10-27 10:00:00 [info] call_started call_id=abc-123 caller=sip:alice@example.com
```

**장점:** 사람이 읽기 쉬움

**변경 방법:**
```yaml
# config.yaml
logging:
  format: "text"  # json → text
```

---

## 🔧 실전 디버깅 시나리오

### 1. 통화가 연결되지 않을 때

```powershell
# DEBUG 모드로 실행
.\start-server.ps1 -LogLevel DEBUG | Tee-Object -FilePath logs\debug.log

# 로그에서 "INVITE" 검색
Get-Content logs\debug.log | Select-String "INVITE"

# 특정 Call-ID 추적
Get-Content logs\debug.log | Select-String "call-abc-123"
```

**확인할 로그:**
- `sip_request_received` - SIP 요청 수신
- `call_session_created` - 통화 세션 생성
- `media_session_created` - 미디어 세션 생성
- `rtp_relay_started` - RTP 릴레이 시작

### 2. RTP 패킷이 오지 않을 때

```powershell
.\start-server.ps1 -LogLevel DEBUG

# 로그에서 확인:
# - "port_allocated" - 포트 할당됨
# - "rtp_packet_received" - RTP 패킷 수신됨
# - "media_session_timeout" - 타임아웃 (문제!)
```

**문제 해결:**
- 방화벽 확인
- NAT 설정 확인
- 포트 범위 확인 (config.yaml)

### 3. AI 분석이 작동하지 않을 때

```powershell
.\start-server.ps1 -LogLevel DEBUG

# 로그에서 확인:
# - "ai_model_loaded" - 모델 로딩
# - "stt_transcription_started" - STT 시작
# - "emotion_analysis_completed" - 감정 분석 완료
# - "event_generated" - 이벤트 생성
```

### 4. 메모리/성능 문제

```powershell
# DEBUG 모드 + 성능 메트릭
.\start-server.ps1 -LogLevel DEBUG

# 별도 터미널에서 메트릭 확인
curl http://localhost:9090/metrics | Select-String "memory"
curl http://localhost:9090/metrics | Select-String "gpu"
```

---

## 📊 로그 분석 도구

### PowerShell로 로그 분석

```powershell
# 1. 에러만 필터링
Get-Content logs\server.log | Select-String "error"

# 2. 특정 Call-ID 추적
Get-Content logs\server.log | Select-String "call-abc-123"

# 3. 최근 100줄
Get-Content logs\server.log -Tail 100

# 4. 실시간 모니터링 (tail -f)
Get-Content logs\server.log -Wait

# 5. JSON 로그 파싱 (jq 필요)
# jq 설치: choco install jq
Get-Content logs\server.log | jq 'select(.level == "error")'
Get-Content logs\server.log | jq 'select(.call_id == "abc-123")'
```

### 통화별 로그 추출

```powershell
# 특정 통화의 모든 로그 추출
$callId = "abc-123"
Get-Content logs\server.log | Select-String $callId | 
    Out-File "logs\call-$callId.log"
```

### 시간대별 로그 분석

```powershell
# 특정 시간대 로그
Get-Content logs\server.log | 
    Select-String "2025-10-27T10:"  # 10시대 로그

# 에러 발생 시각 확인
Get-Content logs\server.log | 
    Select-String "error" | 
    Select-Object -First 10
```

---

## 🎯 주요 로그 이벤트

### SIP 관련

| 이벤트 | 의미 | 레벨 |
|--------|------|------|
| `sip_request_received` | SIP 요청 수신 | INFO |
| `sip_response_sent` | SIP 응답 전송 | INFO |
| `call_session_created` | 통화 세션 생성 | INFO |
| `call_session_ended` | 통화 종료 | INFO |
| `register_received` | REGISTER 수신 | DEBUG |

### 미디어 관련

| 이벤트 | 의미 | 레벨 |
|--------|------|------|
| `port_allocated` | RTP 포트 할당 | DEBUG |
| `port_released` | 포트 해제 | DEBUG |
| `rtp_packet_received` | RTP 패킷 수신 | DEBUG |
| `media_session_timeout` | RTP 타임아웃 | WARNING |
| `session_cleaned` | 세션 정리됨 | INFO |

### AI 관련

| 이벤트 | 의미 | 레벨 |
|--------|------|------|
| `ai_model_loaded` | AI 모델 로딩 완료 | INFO |
| `stt_transcription_started` | STT 시작 | DEBUG |
| `stt_transcription_completed` | STT 완료 | DEBUG |
| `emotion_analysis_completed` | 감정 분석 완료 | DEBUG |
| `event_generated` | 이벤트 생성 | INFO |

### 이벤트 관련

| 이벤트 | 의미 | 레벨 |
|--------|------|------|
| `webhook_sent_successfully` | Webhook 전송 성공 | INFO |
| `webhook_failed` | Webhook 실패 | ERROR |
| `cdr_written` | CDR 기록됨 | INFO |

---

## 🚨 일반적인 에러 메시지

### "Port already in use"

```
ERROR: Port 5060 is already in use
```

**해결:**
```powershell
# 포트 사용 프로세스 확인
netstat -ano | findstr :5060

# 다른 포트로 실행
.\start-server.ps1 -Port 5080
```

### "CUDA out of memory"

```
ERROR: CUDA out of memory
```

**해결:**
```yaml
# config.yaml
ai:
  stt:
    device: "cpu"  # cuda → cpu
    model_size: "tiny"  # 또는 모델 크기 축소
```

### "No RTP packets received"

```
WARNING: media_session_timeout call_id=abc-123
```

**해결:**
- 방화벽 확인
- NAT 설정 확인
- 클라이언트 RTP 포트 확인

---

## 💡 디버깅 팁

### Tip 1: Call-ID로 전체 흐름 추적

```powershell
# 1. 통화 시작 로그 찾기
Get-Content logs\server.log | Select-String "call_started"

# 2. Call-ID 확인 (예: abc-123)

# 3. 해당 Call-ID의 모든 로그 추출
Get-Content logs\server.log | Select-String "abc-123"
```

### Tip 2: 에러 발생 전후 로그 확인

```powershell
# 에러 발생 줄 번호 찾기
$errorLine = (Get-Content logs\server.log | 
    Select-String "error" | 
    Select-Object -First 1).LineNumber

# 전후 50줄 확인
Get-Content logs\server.log | 
    Select-Object -Index (($errorLine-50)..($errorLine+50))
```

### Tip 3: 성능 분석

```powershell
# 처리 시간이 긴 작업 찾기
Get-Content logs\server.log | 
    Select-String "latency" | 
    Select-String "seconds"

# AI 처리 시간 확인
Get-Content logs\server.log | 
    Select-String "ai_.*_latency"
```

### Tip 4: 통계 확인

```powershell
# 에러 개수 세기
(Get-Content logs\server.log | Select-String "error").Count

# 통화 개수
(Get-Content logs\server.log | Select-String "call_started").Count

# 이벤트 개수
(Get-Content logs\server.log | Select-String "event_generated").Count
```

---

## 🔗 관련 문서

- [사용 매뉴얼](USER_MANUAL.md) - 설치 및 설정
- [빠른 시작](QUICK_START.md) - 5분 안에 실행
- [Architecture](../../bmad/docs/architecture.md) - 시스템 아키텍처

---

## 📞 지원

문제가 해결되지 않으면:
1. 로그 파일 저장: `.\start-server.ps1 -LogLevel DEBUG > logs\debug.log 2>&1`
2. GitHub Issues에 로그와 함께 이슈 등록
3. Call-ID와 에러 메시지 포함

**Happy Debugging! 🐛**

