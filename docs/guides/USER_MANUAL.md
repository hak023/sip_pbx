# SIP PBX - 사용 매뉴얼

## 📋 목차

1. [소개](#소개)
2. [시스템 요구사항](#시스템-요구사항)
3. [설치](#설치)
4. [설정](#설정)
5. [서버 실행](#서버-실행)
6. [API 엔드포인트](#api-엔드포인트)
7. [모니터링](#모니터링)
8. [트러블슈팅](#트러블슈팅)
9. [FAQ](#faq)

---

## 소개

**SIP PBX**는 SIP B2BUA(Back-to-Back User Agent) 시스템입니다.

### 주요 기능

- ✅ **SIP B2BUA**: SIP 프로토콜 지원 (INVITE, BYE, UPDATE, PRACK, CANCEL, REGISTER)
- ✅ **미디어 처리**: RTP Bypass 모드
- ✅ **이벤트 알림**: Webhook을 통한 알림
- ✅ **통화 기록**: CDR (Call Detail Record) 생성
- ✅ **모니터링**: Prometheus 메트릭, 실시간 통계

---

## 시스템 요구사항

### 필수 요구사항

- **OS**: Windows 10/11, Linux (Ubuntu 20.04+), macOS
- **Python**: 3.11 이상
- **메모리**: 최소 2GB RAM (권장 4GB)
- **디스크**: 최소 1GB 여유 공간

### 의존성

- Python 3.11+
- aiohttp
- prometheus-client
- pydantic

---

## 설치

### 1. 저장소 클론

```bash
git clone https://github.com/your-org/sip-pbx.git
cd sip-pbx
```

### 2. 가상환경 생성 (권장)

#### Windows (PowerShell)
```powershell
python -m venv venv
.\venv\Scripts\Activate.ps1
```

#### Linux/macOS
```bash
python3 -m venv venv
source venv/bin/activate
```

### 3. 의존성 설치

```bash
pip install -r requirements.txt
```

### 4. 설정 파일 준비

```powershell
# Windows
Copy-Item config\config.example.yaml config\config.yaml

# Linux/macOS
cp config/config.example.yaml config/config.yaml
```

---

## 설정

### config/config.yaml 구조

```yaml
# SIP 서버 설정
sip:
  listen_ip: "0.0.0.0"
  listen_port: 5060
  transport: "udp"
  max_concurrent_calls: 100

# 미디어 설정
media:
  mode: "bypass"
  port_pool:
    start: 10000
    end: 20000
  rtp_timeout: 60

# 이벤트 설정
events:
  webhook_urls:
    - "http://your-webhook-endpoint.com/webhook"
  webhook_timeout: 10
  webhook_retries: 3

# CDR 설정
cdr:
  enabled: true
  output_dir: "./cdr"
  filename_pattern: "cdr-%Y-%m-%d.jsonl"
  rotation: "daily"
  retention_days: 90

# 로깅 설정
logging:
  level: "INFO"  # DEBUG, INFO, WARNING, ERROR, CRITICAL
  format: "json"  # json or text
  output: "stdout"

# 모니터링 설정
monitoring:
  prometheus_port: 9090
  health_check_port: 8080
```

### 주요 설정 항목 설명

#### SIP 설정
- `listen_ip`: SIP 서버가 바인딩할 IP 주소 (0.0.0.0 = 모든 인터페이스)
- `listen_port`: SIP 포트 (기본값: 5060)
- `max_concurrent_calls`: 최대 동시 통화 수

#### 미디어 설정
- `mode`: bypass (RTP 직접 릴레이)
- `port_pool`: RTP/RTCP 포트 범위
- `rtp_timeout`: RTP 무활동 타임아웃 (초)

#### 이벤트 설정
- `webhook_urls`: 이벤트 전송할 Webhook URL 목록
- `webhook_timeout`: HTTP 요청 타임아웃
- `webhook_retries`: 실패 시 재시도 횟수

---

## 서버 실행

### Windows (권장)

#### PowerShell 스크립트 사용

```powershell
# 기본 실행
.\start-server.ps1

# 커스텀 설정 파일
.\start-server.ps1 -Config "config/production.yaml"

# 포트 변경
.\start-server.ps1 -Port 5080

# 로그 레벨 변경
.\start-server.ps1 -LogLevel DEBUG
```

### Python 직접 실행

```bash
python src/main.py --config config/config.yaml
```

### Docker

```bash
docker build -t sip-pbx:latest -f docker/Dockerfile .
docker run -d \
  -p 5060:5060/udp \
  -p 8080:8080 \
  -p 9090:9090 \
  -v $(pwd)/config:/app/config \
  sip-pbx:latest
```

### Kubernetes

```bash
kubectl apply -f k8s/base/
```

---

## API 엔드포인트

### 헬스체크

#### GET /health
서버 상태 확인

**응답:**
```json
{
  "status": "healthy",
  "timestamp": "2025-10-27T10:00:00Z"
}
```

#### GET /ready
서비스 준비 상태 확인

**응답:**
```json
{
  "ready": true,
  "components": {
    "sip_server": "ready",
    "media_engine": "ready"
  }
}
```

### 통계 API

#### GET /api/stats
실시간 통계 조회

**응답:**
```json
{
  "active_calls": 5,
  "total_calls": 123,
  "active_sessions": 10,
  "uptime_seconds": 3600
}
```

### CDR API

#### GET /api/cdr/recent
최근 CDR 조회

**쿼리 파라미터:**
- `limit`: 결과 개수 (기본값: 10)

**응답:**
```json
{
  "records": [
    {
      "call_id": "abc123",
      "caller": "1001@domain",
      "callee": "1002@domain",
      "start_time": "2025-10-27T10:00:00Z",
      "end_time": "2025-10-27T10:05:00Z",
      "duration": 300
    }
  ]
}
```

---

## 모니터링

### Prometheus 메트릭

**엔드포인트**: `http://localhost:9090/metrics`

주요 메트릭:
- `sip_pbx_active_calls`: 현재 활성 통화 수
- `sip_pbx_total_calls`: 총 통화 수
- `sip_pbx_call_duration_seconds`: 통화 시간
- `sip_pbx_media_packets_total`: 처리된 RTP 패킷 수
- `sip_pbx_errors_total`: 에러 발생 횟수

### 로그 확인

#### Stdout (기본)
```powershell
# 서버 실행 시 콘솔에 출력
```

#### 파일 로그
```powershell
# logs/app.log 파일 확인
Get-Content logs\app.log -Tail 50 -Wait
```

#### SIP 트래픽 로그
```powershell
# logs/sip_traffic_YYYYMMDD.log 파일 확인
Get-Content logs\sip_traffic_20251027.log -Tail 50
```

### CDR 조회

```powershell
# 최신 CDR 확인
Get-Content cdr\cdr-$(Get-Date -Format 'yyyy-MM-dd').jsonl | Select-Object -Last 10

# JSON 파싱
Get-Content cdr\cdr-*.jsonl | ConvertFrom-Json | Format-Table
```

---

## 트러블슈팅

### 1. 서버가 시작되지 않음

**증상**: `python src/main.py` 실행 시 에러 발생

**해결 방법**:
```powershell
# 1. 가상환경 활성화 확인
.\venv\Scripts\Activate.ps1

# 2. 의존성 재설치
pip install -r requirements.txt --force-reinstall

# 3. 설정 파일 확인
Test-Path config\config.yaml

# 4. 디버그 모드로 실행
python src/main.py --config config/config.yaml --log-level DEBUG
```

### 2. 포트 충돌

**증상**: `Address already in use` 에러

**해결 방법**:
```powershell
# 사용 중인 포트 확인
netstat -ano | findstr :5060

# 다른 포트로 실행
.\start-server.ps1 -Port 5080
```

### 3. SIP 클라이언트가 연결되지 않음

**체크리스트**:
- [ ] 서버가 실행 중인가?
- [ ] 방화벽에서 5060 포트가 열려있는가?
- [ ] 클라이언트 설정이 올바른가?
  - Server: `서버IP:5060`
  - Transport: UDP

**디버그**:
```powershell
# SIP 트래픽 로그 실시간 확인
Get-Content logs\sip_traffic_*.log -Wait

# 네트워크 연결 확인
Test-NetConnection -ComputerName localhost -Port 5060
```

### 4. RTP 미디어가 전달되지 않음

**체크리스트**:
- [ ] 방화벽에서 10000-20000/UDP 포트가 열려있는가?
- [ ] NAT 환경인가? (추가 설정 필요할 수 있음)

**디버그**:
```powershell
# 미디어 세션 확인
curl http://localhost:8080/api/stats

# 로그에서 RTP 관련 에러 확인
Get-Content logs\app.log | Select-String "RTP"
```

### 5. 메모리 사용량이 높음

**해결 방법**:
```yaml
# config.yaml에서 동시 통화 수 제한
sip:
  max_concurrent_calls: 50  # 기본값 100에서 감소
```

---

## FAQ

### Q: GPU가 필요한가요?
A: 아니요, CPU만으로도 동작합니다.

### Q: Windows에서만 동작하나요?
A: 아니요, Linux와 macOS에서도 동작합니다.

### Q: 동시에 몇 개의 통화를 처리할 수 있나요?
A: 설정에 따라 다르지만, 기본적으로 100개의 동시 통화를 지원합니다. 시스템 리소스에 따라 조정 가능합니다.

### Q: 코덱은 무엇을 지원하나요?
A: G.711 (PCMA, PCMU), Opus를 지원합니다.

### Q: Webhook은 어떤 이벤트를 전송하나요?
A: 통화 시작, 통화 종료 등의 이벤트를 전송합니다.

### Q: CDR은 어디에 저장되나요?
A: 기본적으로 `cdr/` 디렉토리에 JSONL 형식으로 저장됩니다.

### Q: 프로덕션 환경에서 사용할 수 있나요?
A: 현재는 개발 단계입니다. 프로덕션 사용 전 충분한 테스트가 필요합니다.

---

## 지원

- 📘 [Quick Start Guide](../QUICK_START.md)
- 🐛 [Debugging Guide](DEBUGGING.md)
- 🔧 [B2BUA Status](../reports/2025-10/B2BUA_STATUS.md)
- 📂 [GitHub Issues](https://github.com/your-org/sip-pbx/issues)

