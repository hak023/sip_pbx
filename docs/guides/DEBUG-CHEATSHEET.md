# 🔥 디버깅 치트시트 (빠른 참조)

## 📍 로그는 어디에?

**기본: 콘솔에 실시간 출력!**

```powershell
# DEBUG 모드로 실행
.\start-server.ps1 -LogLevel DEBUG

# 파일로 저장 (콘솔 + 파일)
.\start-server.ps1 | Tee-Object -FilePath logs\server.log
```

---

## 🔍 자주 쓰는 명령어

### 로그 실시간 보기
```powershell
# 실행하면 콘솔에 바로 보임
.\start-server.ps1 -LogLevel INFO
```

### 로그 파일에서 검색
```powershell
# 에러만 보기
Get-Content logs\server.log | Select-String "error"

# 특정 Call-ID 추적
Get-Content logs\server.log | Select-String "call-abc-123"

# 최근 100줄
Get-Content logs\server.log -Tail 100

# 실시간 모니터링 (tail -f)
Get-Content logs\server.log -Wait
```

### 통계 확인
```powershell
# 에러 개수
(Get-Content logs\server.log | Select-String "error").Count

# 통화 개수
(Get-Content logs\server.log | Select-String "call_started").Count
```

---

## 🚨 문제별 빠른 해결

### 통화가 안 될 때
```powershell
.\start-server.ps1 -LogLevel DEBUG | Tee-Object logs\debug.log
# "INVITE", "call_session_created" 검색
```

### RTP 패킷 안 올 때
```powershell
# 로그에서 확인: "rtp_packet_received"
# 없으면 방화벽 문제!
netsh advfirewall firewall add rule name="SIP PBX RTP" dir=in action=allow protocol=UDP localport=20000-30000
```

### AI 분석 안 될 때
```powershell
# "ai_model_loaded" 확인
# "stt_transcription" 확인
# GPU 메모리 확인
curl http://localhost:9090/metrics | Select-String "gpu"
```

---

## 📊 주요 로그 이벤트

| 찾을 키워드 | 의미 |
|-------------|------|
| `sip_request_received` | SIP 요청 들어옴 |
| `call_session_created` | 통화 시작됨 |
| `port_allocated` | RTP 포트 할당됨 |
| `rtp_packet_received` | RTP 패킷 수신 |
| `ai_model_loaded` | AI 모델 로딩 완료 |
| `event_generated` | 이벤트 발생! |
| `webhook_sent` | Webhook 전송됨 |
| `cdr_written` | CDR 기록됨 |
| `error` | 에러 발생 ⚠️ |

---

## 💡 빠른 팁

### Call-ID로 전체 추적
```powershell
# 1. Call-ID 찾기
Get-Content logs\server.log | Select-String "call_started" | Select-Object -First 1

# 2. 해당 Call의 모든 로그
Get-Content logs\server.log | Select-String "YOUR-CALL-ID"
```

### 성능 체크
```powershell
# API로 통계 확인
curl http://localhost:8080/api/stats

# Prometheus 메트릭
curl http://localhost:9090/metrics

# Health check
curl http://localhost:8080/health
```

---

## 📖 상세 가이드

**더 자세한 정보:**
- [디버깅 가이드 (전체)](docs/DEBUGGING.md)
- [사용 매뉴얼](docs/USER_MANUAL.md)

