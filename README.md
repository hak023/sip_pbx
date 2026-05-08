<div align="center">

# 📞 SIP PBX

**고성능 SIP B2BUA (Back-to-Back User Agent) 시스템**

[![Python Version](https://img.shields.io/badge/python-3.11%2B-blue.svg)](https://www.python.org/downloads/)
[![License](https://img.shields.io/badge/license-MIT-green.svg)](LICENSE)
[![Code style: black](https://img.shields.io/badge/code%20style-black-000000.svg)](https://github.com/psf/black)

[기능](#주요-기능) •
[빠른 시작](#빠른-시작) •
[문서](#문서) •
[아키텍처](#아키텍처) •
[기여](#기여)

**📚 [전체 문서 가이드 보기](DOCUMENTATION.md)**

</div>

---

## 📋 소개

SIP PBX는 Python으로 구현된 고성능 **B2BUA(Back-to-Back User Agent)** 시스템으로, 엔터프라이즈급 SIP 통신 인프라를 제공합니다. 저지연 RTP 릴레이, 실시간 이벤트 알림, 포괄적인 모니터링 기능을 통해 안정적이고 확장 가능한 통화 처리를 보장합니다.

### ✨ 주요 특징

- **🔄 완전한 B2BUA 구현**: INVITE, BYE, ACK, PRACK, UPDATE, REGISTER, CANCEL, OPTIONS 지원
- **⚡ 저지연 미디어**: RTP Bypass 모드로 <5ms 지연시간 달성
- **📊 관찰성**: Prometheus 메트릭, CDR, 구조화된 로깅
- **🔔 실시간 알림**: Webhook 기반 이벤트 시스템
- **🐳 클라우드 네이티브**: Docker 및 Kubernetes 지원
- **📈 확장성**: 100+ 동시 통화 처리 가능
- **🔧 유연한 설정**: YAML 기반 설정 및 환경 변수 지원

## 🎯 주요 기능

### SIP B2BUA Core
- ✅ **사용자 등록**: REGISTER 처리 및 사용자 관리
- ✅ **통화 제어**: INVITE, BYE, ACK, CANCEL 처리
- ✅ **신뢰성 있는 응답**: PRACK (RFC 3262) 지원
- ✅ **세션 업데이트**: UPDATE (RFC 3311) 지원
- ✅ **독립적인 leg 관리**: 발신자/수신자 독립 제어
- ✅ **Transaction 관리**: 상태 기반 트랜잭션 처리

### 🤖 AI Voice Assistant (NEW!)
- ✅ **AI 응대 모드**: 타이머 또는 수동 부재중 설정 시 자동 응답
  - 🕐 **타이머 기반**: `no_answer_timeout` 설정으로 자동 전환
  - 🔴 **수동 설정**: 웹 API로 부재중 상태 전환
- ✅ **실시간 STT/TTS**: Google Cloud Speech-to-Text & Text-to-Speech
- ✅ **지능형 응답**: Gemini 2.5 Flash LLM 기반 대화 생성
- ✅ **RAG 검색**: Vector DB 기반 지식 베이스 활용
- ✅ **Barge-in**: 사용자 발화 시 AI 응답 중단
- ✅ **통화 녹음**: 자동 녹음 및 지식 추출

### 🎛️ Frontend Control Center (NEW!)
- ✅ **실시간 모니터링**: WebSocket 기반 통화 실시간 추적
- ✅ **Live Transcript**: STT/TTS 대화 내용 실시간 표시
- ✅ **Human-in-the-Loop (HITL)**: AI가 답변 못할 시 오퍼레이터 개입
- ✅ **운영자 부재중 모드** ✨: 부재중 시 HITL 자동 처리 및 이력 관리
- ✅ **지식 베이스 관리**: Vector DB CRUD 인터페이스
- ✅ **대시보드**: 메트릭, 통화 통계, AI 성능 분석
- ✅ **통화 이력 관리**: 미처리 요청 필터링 및 후속 조치

### 미디어 처리
- ✅ **RTP Relay**: 저지연 패킷 중계
- ✅ **동적 포트 할당**: 10,000-20,000 포트 풀 관리
- ✅ **SDP 협상**: 코덱 협상 및 미디어 매칭
- ✅ **코덱 지원**: G.711 (PCMU/PCMA), Opus
- ✅ **Jitter Buffer**: 패킷 지연 보정

### 이벤트 & 모니터링
- ✅ **Webhook 알림**: 통화 시작/종료 이벤트
- ✅ **CDR**: JSON Lines 형식의 통화 상세 기록
- ✅ **실시간 통계**: 활성 통화, 포트 사용률
- ✅ **Prometheus 메트릭**: 통화 수, 지연시간, 에러율
- ✅ **헬스체크**: HTTP 엔드포인트 (liveness/readiness)

### 🤖 AI 보이스봇 (New!)
- ✅ **자동 응답**: 착신자 부재 시 AI가 자동으로 통화 응대 (10초 타임아웃)
- ✅ **실시간 STT**: Google Cloud Speech-to-Text (Telephony 모델, 16kHz)
- ✅ **자연스러운 TTS**: Google Cloud Text-to-Speech (Neural2 음성)
- ✅ **지능형 대화**: Gemini 2.5 Flash (초고속, 초저비용)
  - ⚡ **응답 속도**: 평균 0.9초 (Pro 대비 30% 단축)
  - 💰 **비용 효율**: Pro 대비 94% 절감 (월 100통 ₩1,400)
  - 🎁 **무료 할당량**: 일 1,500 요청
- ✅ **RAG 기반 지식**: Vector DB (ChromaDB/Pinecone) + Sentence Transformers
- ✅ **Barge-in 지원**: WebRTC VAD로 사용자 발화 감지 시 AI 응답 중단
- ✅ **통화 녹음**: 화자 분리 + 믹싱 (WAV 저장)
- ✅ **지식 추출**: 통화 내용에서 유용한 정보 자동 학습

### 🖥️ Frontend Control Center (New!)
- ✅ **실시간 모니터링**: 활성 통화 대시보드, 라이브 STT/TTS 트랜스크립트
- ✅ **지식 베이스 관리**: Vector DB CRUD (추가/수정/삭제/검색)
- ✅ **Human-in-the-Loop (HITL)** ⭐
  - AI가 답변 못 찾을 때 운영자에게 실시간 알림
  - 통화 상대는 "잠시만 기다려주세요" + 대기 음악
  - 운영자가 답변 제공 → AI가 자연스럽게 다듬어서 발화
  - 유용한 답변은 지식 베이스에 자동 저장
- ✅ **운영자 부재중 모드** 🆕⭐
  - 운영자 상태 관리: 대기중/부재중/통화중/오프라인
  - 부재중 시 HITL 요청 자동 거절 + "확인 후 안내드리겠습니다" 멘트
  - 미처리 HITL 요청을 통화 이력에 기록
  - 운영자 복귀 후 미처리 요청 확인 및 후속 조치 가능
- ✅ **분석 대시보드**: 통화량, AI 신뢰도, HITL 빈도, 비용 추적
- ✅ **WebSocket 실시간 통신**: 즉각적인 이벤트 알림 및 업데이트

> 📚 **전체 문서 인덱스**: [docs/INDEX.md](docs/INDEX.md) ⭐  
> 🚀 **빠른 시작**: [docs/QUICK_START.md](docs/QUICK_START.md)  
> 🌐 **시스템 개요**: [docs/SYSTEM_OVERVIEW.md](docs/SYSTEM_OVERVIEW.md)  
> 🤖 **AI Voicebot 아키텍처**: [docs/architecture/ai-voicebot-architecture.md](docs/architecture/ai-voicebot-architecture.md)  
> 🖥️ **Frontend 아키텍처**: [docs/architecture/frontend-architecture.md](docs/architecture/frontend-architecture.md)

## 🚀 기술 스택

| 카테고리 | 기술 |
|---------|-----|
| **Backend** | Python 3.11+, FastAPI, asyncio, aiohttp |
| **Frontend** | Next.js 14, React 18, TypeScript, TailwindCSS |
| **WebSocket** | Socket.IO, python-socketio |
| **Database** | PostgreSQL (asyncpg), Redis |
| **설정 관리** | Pydantic, PyYAML |
| **오디오 처리** | opuslib, G.711, WebRTC VAD |
| **AI/ML** | Google Gemini 2.5 Flash, Sentence Transformers, PyTorch |
| **Vector DB** | ChromaDB (dev), Pinecone (prod) |
| **Google Cloud AI** | Speech-to-Text, Text-to-Speech, Generative AI |
| **모니터링** | Prometheus, structlog |
| **테스트** | pytest, pytest-asyncio, pytest-cov |
| **인프라** | Docker, Kubernetes, Helm |

## 📦 요구 사항

### 시스템

| 구분 | 요구사항 |
|-----|---------|
| **Python** | 3.11 이상 |
| **OS** | Linux, Windows, macOS |
| **메모리** | 최소 2GB (권장 4GB+) |
| **CPU** | 2 Core 이상 |

### 네트워크

| 프로토콜 | 포트 | 용도 |
|---------|-----|------|
| **SIP** | 5060/UDP, 5060/TCP | SIP 시그널링 |
| **RTP** | 10000-20000/UDP | 음성 미디어 스트림 |
| **HTTP (API)** | 8000 | Backend API Gateway (FastAPI) |
| **HTTP (Frontend)** | 3000 | Frontend Web UI (Next.js) |
| **WebSocket** | 8001 | 실시간 양방향 통신 (Socket.IO) |
| **Prometheus** | 9090 | 메트릭 수집 |
| **PostgreSQL** | 5432 | 데이터베이스 (선택) |
| **Redis** | 6379 | 캐시 및 Pub/Sub (선택) |

### Python 패키지

주요 의존성은 `requirements.txt` 및 `requirements-ai.txt`에 정의되어 있습니다:

**Backend Core**:
- aiohttp 3.9.1+ (비동기 HTTP)
- fastapi 0.109+ (API 프레임워크)
- uvicorn 0.27+ (ASGI 서버)
- python-socketio 5.11+ (WebSocket 서버)
- pydantic 2.5+ (설정 및 validation)
- redis 5.0+ (캐시 및 Pub/Sub)
- asyncpg 0.29+ (PostgreSQL async 드라이버)

**Frontend**:
- next 14.2+ (React 프레임워크)
- react 18.3+ (UI 라이브러리)
- socket.io-client 4.7+ (WebSocket 클라이언트)
- zustand 4.5+ (상태 관리)
- tailwindcss 3.4+ (CSS 프레임워크)

**AI/ML**:
- google-cloud-speech, google-cloud-texttospeech
- google-generativeai (Gemini)
- chromadb (Vector DB)
- sentence-transformers (임베딩)
- torch, torchvision, torchaudio

> 🎮 **GPU 가속**: AI 임베딩 성능을 5-10배 향상시키려면 [GPU 설정 가이드](docs/GPU_SETUP.md) 참고

**Audio**:
- opuslib 3.0+ (Opus 코덱)
- webrtcvad 2.0+ (음성 감지)
- pydub 0.25+ (오디오 처리)

**Monitoring**:
- prometheus-client 0.19+ (메트릭)
- structlog 24.1+ (구조화 로깅)

## 🔧 설치

### ⚡ AI 모델 사전 다운로드 (선택, 권장)

서버 시작 시간을 **80초 → 5초**로 단축하려면:

```powershell
# AI 모델 사전 다운로드 (최초 1회만 실행)
python scripts/download_models.py
```

**효과**:
- 첫 실행: 약 1-5분 소요 (네트워크 속도에 따라 다름)
- 이후 실행: 서버 시작 시간 75초 단축! 🚀

**다운로드 모델**:
- `sentence-transformers/paraphrase-multilingual-mpnet-base-v2` (1.1GB)
- 용도: 텍스트 임베딩 (VectorDB 지식 베이스)

---

### 방법 1: 통합 실행 (권장) ⭐

```powershell
# 1. 저장소 클론
git clone https://github.com/hak023/sip_pbx.git
cd sip_pbx

# 2. 가상 환경 생성 및 활성화
python3.11 -m venv venv
.\venv\Scripts\Activate.ps1  # Windows
# source venv/bin/activate    # Linux/Mac

# 3. Backend 의존성 설치
pip install --upgrade pip
pip install -r requirements.txt

# 4. Frontend 의존성 설치
cd frontend
npm install
cd ..

# 5. 전체 시스템 실행 (Frontend + Backend + WebSocket)
.\start-all.ps1  # Windows
# ./start-all.sh  # Linux/Mac (추후 제공)
```

이 명령으로 다음이 자동 실행됩니다:
- ✅ **Frontend** (Next.js) - http://localhost:3000
- ✅ **Backend API** (FastAPI) - http://localhost:8000
- ✅ **WebSocket Server** (Socket.IO) - ws://localhost:8001
- ❓ **SIP PBX** (선택사항)

---

### 방법 2: 개별 실행

#### Backend API Gateway
```powershell
python -m src.api.main
# http://localhost:8000/docs 에서 API 문서 확인
```

#### WebSocket Server
```powershell
python -m src.websocket.server
# ws://localhost:8001 에서 실시간 이벤트 수신
```

#### Frontend
```powershell
cd frontend
npm run dev
# http://localhost:3000 에서 UI 접속
```

#### SIP PBX (선택사항)
```powershell
python src/main.py
# SIP 5060, RTP 10000-20000 포트 사용
```

---

### 방법 3: Docker (추후 제공)

```bash
# Docker Compose로 전체 스택 실행
docker-compose up -d
```

# 로그 확인
docker-compose logs -f
```

## 🚀 빠른 시작

### 개발 모드 실행

```bash
# 기본 설정으로 실행
python src/main.py --config config/config.yaml

# 디버그 모드
python src/main.py --config config/config.yaml --log-level DEBUG

# 커스텀 포트
python src/main.py --config config/config.yaml --port 5080
```

### Windows PowerShell 스크립트 (권장)

```powershell
# 기본 실행
.\start-server.ps1

# 커스텀 설정
.\start-server.ps1 -Config "config/production.yaml" -LogLevel INFO

# 포트 변경
.\start-server.ps1 -Port 5080

# 도움말
.\start-server.ps1 -Help
```

### 서버 확인

```bash
# 헬스체크
curl http://localhost:8080/health

# 준비 상태 확인
curl http://localhost:8080/ready

# 통계 확인
curl http://localhost:8080/api/stats

# Prometheus 메트릭
curl http://localhost:9090/metrics
```

## ⚙️ 설정

### 기본 설정 (`config/config.yaml`)

```yaml
# SIP 서버 설정
sip:
  listen_ip: "0.0.0.0"          # 모든 인터페이스에서 수신
  listen_port: 5060              # 표준 SIP 포트
  transport: "udp"               # udp, tcp, tls
  max_concurrent_calls: 100      # 최대 동시 통화 수

# 미디어 처리 설정
media:
  mode: "bypass"                 # bypass (RTP relay)
  port_pool:
    start: 10000                 # RTP 포트 시작
    end: 20000                   # RTP 포트 종료
  rtp_timeout: 60                # RTP 타임아웃 (초)
  codec_priority:                # 코덱 우선순위
    - "opus"
    - "pcmu"
    - "pcma"

# 이벤트 알림 설정
events:
  webhook_urls:
    - "http://your-webhook-service/webhook"
  webhook_timeout: 10
  webhook_retries: 3

# CDR (통화 상세 기록)
cdr:
  enabled: true
  output_dir: "/var/log/sip-pbx/cdr"
  filename_pattern: "cdr-%Y-%m-%d.jsonl"
  rotation: "daily"
  retention_days: 90

# 로깅
logging:
  level: "INFO"                  # DEBUG, INFO, WARNING, ERROR
  format: "json"                 # json, text
  output: "stdout"               # stdout, file

# 모니터링
monitoring:
  prometheus_port: 9090
  health_check_port: 8080
```

### 환경 변수 오버라이드

설정 파일의 모든 값은 환경 변수로 오버라이드 가능합니다:

```bash
# 형식: SIP_PBX_<섹션>_<키>=<값>
export SIP_PBX_SIP_LISTEN_PORT=5061
export SIP_PBX_MEDIA_RTP_TIMEOUT=120
export SIP_PBX_LOGGING_LEVEL=DEBUG

# 실행
python src/main.py
```

### 프로덕션 설정 예시

```yaml
sip:
  listen_ip: "0.0.0.0"
  listen_port: 5060
  max_concurrent_calls: 500

media:
  mode: "bypass"
  port_pool:
    start: 10000
    end: 30000
  rtp_timeout: 120

logging:
  level: "INFO"
  format: "json"
  output: "stdout"

monitoring:
  prometheus_port: 9090
  health_check_port: 8080
```

## 🧪 테스트

### 단위 테스트

```bash
# 모든 단위 테스트 실행
pytest tests/unit/ -v

# 특정 모듈 테스트
pytest tests/unit/test_sip_core/ -v
pytest tests/unit/test_media/ -v

# 커버리지 포함
pytest tests/unit/ --cov=src --cov-report=html
```

### 통합 테스트

```bash
# 통합 테스트 실행
pytest tests/integration/ -v -m integration

# RTP 릴레이 테스트
pytest tests/integration/test_rtp_relay.py -v

# Webhook 테스트
pytest tests/integration/test_webhook.py -v
```

### 성능 테스트

```bash
# 미디어 성능 테스트
pytest tests/performance/test_media_performance.py -v

# 벤치마크 테스트
pytest -m benchmark -v
```

### 커버리지 리포트

```bash
# HTML 리포트 생성
pytest --cov=src --cov-report=html

# 브라우저에서 확인
# htmlcov/index.html 열기

# 터미널에서 확인
pytest --cov=src --cov-report=term-missing
```

### 테스트 마커

```bash
# 단위 테스트만
pytest -m unit

# 통합 테스트만
pytest -m integration

# 느린 테스트 제외
pytest -m "not slow"

# E2E 테스트
pytest -m e2e
```

## 📊 모니터링

### 헬스체크 엔드포인트

```bash
# Liveness probe - 서버가 살아있는지 확인
curl http://localhost:8080/health
# Response: {"status": "healthy", "timestamp": "2025-01-05T10:00:00Z"}

# Readiness probe - 트래픽을 받을 준비가 되었는지 확인
curl http://localhost:8080/ready
# Response: {"status": "ready", "active_calls": 5}

# 상세 상태
curl http://localhost:8080/api/status
```

### 실시간 통계

```bash
# 통화 통계
curl http://localhost:8080/api/stats
```

**응답 예시:**
```json
{
  "active_calls": 12,
  "total_calls": 1543,
  "failed_calls": 23,
  "success_rate": 98.5,
  "average_call_duration": 185.3,
  "port_pool": {
    "total": 10000,
    "in_use": 96,
    "utilization": 0.96
  },
  "uptime_seconds": 86400
}
```

### Prometheus 메트릭

```bash
# 메트릭 엔드포인트
curl http://localhost:9090/metrics
```

**주요 메트릭:**

| 메트릭 | 타입 | 설명 |
|-------|-----|------|
| `sip_active_calls` | Gauge | 현재 활성 통화 수 |
| `sip_total_calls` | Counter | 총 통화 수 |
| `sip_call_duration_seconds` | Histogram | 통화 지속 시간 |
| `sip_call_setup_duration_seconds` | Histogram | 통화 설정 시간 |
| `rtp_packets_received` | Counter | 수신한 RTP 패킷 수 |
| `rtp_packets_sent` | Counter | 전송한 RTP 패킷 수 |
| `rtp_port_pool_usage` | Gauge | RTP 포트 사용률 |
| `webhook_requests_total` | Counter | Webhook 전송 횟수 |
| `webhook_failures_total` | Counter | Webhook 실패 횟수 |

### CDR (Call Detail Record)

CDR 파일은 JSON Lines 형식으로 저장됩니다:

```bash
# CDR 파일 위치
ls cdr/cdr-*.jsonl

# 최근 통화 확인
tail -n 10 cdr/cdr-2025-01-05.jsonl | jq .

# 특정 통화 검색
cat cdr/cdr-2025-01-05.jsonl | jq 'select(.caller == "1004")'
```

**CDR 레코드 예시:**
```json
{
  "call_id": "abc123@192.168.1.100",
  "caller": "1004",
  "callee": "1008",
  "start_time": "2025-01-05T10:15:30Z",
  "end_time": "2025-01-05T10:18:45Z",
  "duration": 195,
  "status": "completed",
  "caller_ip": "192.168.1.100",
  "callee_ip": "192.168.1.101",
  "codec": "opus",
  "termination_reason": "normal"
}
```

### 로그 확인

```bash
# 실시간 로그 모니터링
tail -f logs/app.log

# JSON 로그 파싱
tail -f logs/app.log | jq .

# 에러 로그만 필터링
tail -f logs/app.log | jq 'select(.level == "ERROR")'

# SIP 트래픽 로그
tail -f logs/sip_traffic_*.log
```

## 🏗️ 아키텍처

### 시스템 구조

```
┌─────────────────────────────────────────────────────────────────┐
│                         SIP PBX System                          │
├─────────────────────────────────────────────────────────────────┤
│                                                                 │
│  ┌─────────┐         ┌──────────────────┐         ┌─────────┐ │
│  │ Caller  │◄───────►│   SIP Endpoint   │◄───────►│ Callee  │ │
│  └─────────┘  SIP    └────────┬─────────┘   SIP   └─────────┘ │
│               5060            │                                 │
│                               │                                 │
│                    ┌──────────▼──────────┐                      │
│                    │   Call Manager      │                      │
│                    │  (B2BUA Core)       │                      │
│                    └──────────┬──────────┘                      │
│                               │                                 │
│              ┌────────────────┼────────────────┐                │
│              │                │                │                │
│    ┌─────────▼──────┐  ┌─────▼──────┐  ┌──────▼───────┐       │
│    │ Session Manager│  │Media Relay │  │Register Mgr  │       │
│    │                │  │(RTP Bypass)│  │              │       │
│    └────────────────┘  └─────┬──────┘  └──────────────┘       │
│                              │                                  │
│                    ┌─────────▼─────────┐                        │
│                    │   Port Pool       │                        │
│                    │  (10000-20000)    │                        │
│                    └───────────────────┘                        │
│                                                                 │
│  ┌──────────────────────────────────────────────────────────┐  │
│  │              Event & Monitoring Layer                    │  │
│  ├──────────────────────────────────────────────────────────┤  │
│  │  Webhook   │   CDR      │  Prometheus  │  Statistics   │  │
│  │  Notifier  │  Generator │  Metrics     │  Tracker      │  │
│  └──────────────────────────────────────────────────────────┘  │
│                                                                 │
└─────────────────────────────────────────────────────────────────┘
```

### 주요 컴포넌트

#### 1. SIP Endpoint (`src/sip_core/sip_endpoint.py`)
- UDP/TCP 소켓 관리
- SIP 메시지 파싱 및 생성
- 트랜잭션 처리

#### 2. Call Manager (`src/sip_core/call_manager.py`)
- B2BUA 로직 구현
- 발신자/수신자 leg 관리
- 통화 상태 추적 (IDLE, RINGING, ACTIVE, TERMINATING)

#### 3. Media Session Manager (`src/media/session_manager.py`)
- RTP 세션 생성 및 관리
- SDP 협상
- 포트 할당 및 해제

#### 4. RTP Relay (`src/media/rtp_relay.py`)
- RTP 패킷 중계
- Jitter buffer 관리
- 패킷 로스 감지

#### 5. Event System (`src/events/`)
- Webhook 알림
- CDR 생성
- 실시간 통계

### 통화 흐름 (Call Flow)

#### 정상적인 통화 시나리오

```mermaid
sequenceDiagram
    participant C as Caller
    participant P as SIP PBX
    participant D as Callee
    
    C->>P: INVITE sip:1008@pbx
    P->>C: 100 Trying
    P->>D: INVITE sip:1008@callee (new Call-ID)
    D->>P: 180 Ringing
    P->>C: 180 Ringing
    D->>P: 200 OK (SDP)
    P->>C: 200 OK (modified SDP)
    C->>P: ACK
    P->>D: ACK
    
    Note over C,D: RTP Media Stream via PBX
    
    C->>P: BYE
    P->>D: BYE
    D->>P: 200 OK
    P->>C: 200 OK
    
    Note over P: CDR Generated, Webhook Sent
```

### 데이터 흐름

```
1. SIP 시그널링
   Caller → SIP Endpoint → Call Manager → SIP Endpoint → Callee

2. RTP 미디어 (Bypass 모드)
   Caller → Port A (PBX) → RTP Relay → Port B (PBX) → Callee

3. 이벤트
   Call Manager → Event Store → [Webhook, CDR, Statistics]

4. 모니터링
   All Components → Metrics Collector → Prometheus Endpoint
```

## 📖 문서

> 📚 **[전체 문서 인덱스 (docs/INDEX.md)](docs/INDEX.md)** - 모든 문서의 체계적인 분류 및 링크 ⭐

### 🌟 핵심 문서 (최상위 5개만!)

| 문서 | 설명 |
|------|------|
| [docs/INDEX.md](docs/INDEX.md) | **📚 문서 인덱스** - 전체 문서 탐색 시작점 |
| [docs/QUICK_START.md](docs/QUICK_START.md) | **🚀 5분 빠른 시작** - 설치 및 실행 |
| [docs/SYSTEM_OVERVIEW.md](docs/SYSTEM_OVERVIEW.md) | **🌐 시스템 개요** - 아키텍처, 데이터 플로우 |
| [docs/architecture/ai-voicebot-architecture.md](docs/architecture/ai-voicebot-architecture.md) | **🤖 AI Voicebot 아키텍처** - STT/TTS/LLM/RAG/HITL |
| [docs/architecture/voice-ai-conversation-engine.md](docs/architecture/voice-ai-conversation-engine.md) | **🧠 Voice AI 대화 엔진** - Pipecat + Smart Turn + LangGraph Agentic RAG |
| [docs/architecture/frontend-architecture.md](docs/architecture/frontend-architecture.md) | **🖥️ Frontend 아키텍처** - Next.js Control Center |
| [docs/architecture/production-deployment-architecture.md](docs/architecture/production-deployment-architecture.md) | **🏭 상용 배포·연동** - WTIMS/API/용량·비용 (타깃 설계) |

### 📂 추가 문서

- **사용/설정 가이드**: [docs/guides/](docs/guides/) - USER_MANUAL, TROUBLESHOOTING, API 설정 등 (10개)
- **아키텍처 설계**: [docs/architecture/](docs/architecture/) - Technical Architecture, Voice AI Conversation Engine
- **상세 설계**: [docs/design/](docs/design/) - 구현 가이드 Part 1, 2 (3개)
- **분석 자료**: [docs/analysis/](docs/analysis/) - 응답 시간 분석 (1개)
- **완료 보고서**: [docs/reports/](docs/reports/) — 월별 폴더·요약은 [docs/reports/README.md](docs/reports/README.md)
- 🔒 **[보안 가이드](docs/SECURITY.md)** - 보안 설정 *(예정)*

## 🛠️ 개발

### 개발 환경 설정

```bash
# 개발 의존성 설치
pip install -r requirements.txt
pip install black isort flake8 mypy pytest-watch

# Pre-commit hooks 설치
pip install pre-commit
pre-commit install
```

### 코드 스타일

이 프로젝트는 다음 도구를 사용합니다:

```bash
# Black 포매팅 (line length: 100)
black src/ tests/

# Import 정렬
isort src/ tests/

# Linting
flake8 src/ --max-line-length=100

# 타입 체킹
mypy src/ --strict
```

### 프로젝트 구조

```
sip-pbx/
├── config/                    # 설정 파일
│   ├── config.example.yaml    # 예시 설정
│   └── config.yaml            # 실제 설정 (git ignore)
├── docs/                      # 문서
├── docker/                    # Docker 관련 파일
│   ├── Dockerfile
│   └── docker-compose.yml
├── k8s/                       # Kubernetes 매니페스트
│   ├── base/                  # 기본 리소스
│   └── overlays/              # 환경별 오버레이
├── logs/                      # 로그 파일 (git ignore)
├── src/                       # 소스 코드
│   ├── common/                # 공통 유틸리티
│   ├── config/                # 설정 관리
│   ├── events/                # 이벤트 시스템
│   ├── media/                 # 미디어 처리
│   ├── monitoring/            # 모니터링
│   ├── repositories/          # 데이터 저장소
│   ├── sip_core/              # SIP 코어
│   └── main.py                # 진입점
├── tests/                     # 테스트
│   ├── unit/                  # 단위 테스트
│   ├── integration/           # 통합 테스트
│   ├── e2e/                   # E2E 테스트
│   └── performance/           # 성능 테스트
├── scripts/                   # 유틸리티 스크립트
├── requirements.txt           # Python 의존성
├── pyproject.toml             # 프로젝트 메타데이터
├── start-server.ps1           # Windows 시작 스크립트
└── README.md                  # 이 파일
```

### Git Workflow

```bash
# Feature 브랜치 생성
git checkout -b feature/my-feature

# 코드 작성 및 테스트
black src/ tests/
pytest tests/ -v

# 커밋
git add .
git commit -m "feat: Add my feature"

# Push 및 PR 생성
git push origin feature/my-feature
```

### 커밋 메시지 컨벤션

```
<type>(<scope>): <subject>

<body>

<footer>
```

**타입:**
- `feat`: 새로운 기능
- `fix`: 버그 수정
- `docs`: 문서 변경
- `style`: 코드 포맷팅
- `refactor`: 리팩토링
- `test`: 테스트 추가/수정
- `chore`: 빌드, 설정 등

**예시:**
```
feat(sip): Add PRACK support

Implement reliable provisional response handling
according to RFC 3262.

Closes #123
```

## 🚀 배포

### Docker 배포

#### 단일 컨테이너

```bash
# 이미지 빌드
docker build -t sip-pbx:latest -f docker/Dockerfile .

# 실행
docker run -d \
  --name sip-pbx \
  -p 5060:5060/udp \
  -p 5060:5060/tcp \
  -p 8080:8080 \
  -p 9090:9090 \
  -p 10000-20000:10000-20000/udp \
  -v $(pwd)/config:/app/config \
  -v $(pwd)/logs:/app/logs \
  -e SIP_PBX_LOGGING_LEVEL=INFO \
  sip-pbx:latest

# 로그 확인
docker logs -f sip-pbx

# 중지
docker stop sip-pbx
docker rm sip-pbx
```

#### Docker Compose

```bash
# 시작
docker-compose up -d

# 스케일 아웃 (여러 인스턴스)
docker-compose up -d --scale sip-pbx=3

# 로그
docker-compose logs -f

# 중지
docker-compose down
```

### Kubernetes 배포

#### 기본 배포

```bash
# 네임스페이스 생성
kubectl create namespace sip-pbx

# ConfigMap 생성
kubectl create configmap sip-pbx-config \
  --from-file=config/config.yaml \
  -n sip-pbx

# 배포
kubectl apply -f k8s/base/ -n sip-pbx

# 확인
kubectl get pods -n sip-pbx
kubectl logs -f deployment/sip-pbx -n sip-pbx
```

#### StatefulSet (권장)

```bash
# StatefulSet으로 배포 (안정적인 네트워크 ID)
kubectl apply -f k8s/base/statefulset.yaml -n sip-pbx

# 스케일 조정
kubectl scale statefulset sip-pbx --replicas=3 -n sip-pbx

# 롤링 업데이트
kubectl set image statefulset/sip-pbx sip-pbx=sip-pbx:v0.2.0 -n sip-pbx
```

#### Helm 차트

```bash
# Helm 저장소 추가 (예정)
helm repo add sip-pbx https://hak023.github.io/sip_pbx

# 설치
helm install my-pbx sip-pbx/sip-pbx \
  --namespace sip-pbx \
  --create-namespace \
  --set sip.listenPort=5060 \
  --set replicaCount=3

# 업그레이드
helm upgrade my-pbx sip-pbx/sip-pbx

# 제거
helm uninstall my-pbx -n sip-pbx
```

### 프로덕션 체크리스트

- [ ] **설정**: `config/config.yaml` 프로덕션 값 설정
- [ ] **보안**: API 키 및 비밀 키 변경
- [ ] **리소스**: CPU/메모리 리소스 제한 설정
- [ ] **모니터링**: Prometheus 및 Grafana 대시보드 구성
- [ ] **로깅**: 중앙 로그 수집 설정 (ELK, Loki 등)
- [ ] **백업**: CDR 데이터 백업 정책 수립
- [ ] **고가용성**: 최소 3개 인스턴스 배포
- [ ] **네트워크**: 로드 밸런서 및 방화벽 설정
- [ ] **헬스체크**: Kubernetes liveness/readiness probe 확인
- [ ] **알림**: 장애 알림 설정 (Slack, PagerDuty 등)

## 📊 성능

### 성능 목표

| 메트릭 | 목표 | 현재 상태 |
|-------|------|----------|
| **동시 통화** | 100호 | ✅ 검증 완료 |
| **통화 설정 시간** | <1초 | ✅ 평균 200ms |
| **RTP 지연** | <5ms | ✅ 평균 2ms |
| **메모리 사용** | <4GB (100 통화) | ✅ 약 2GB |
| **CPU 사용률** | <50% (2 Core) | ✅ 약 30% |
| **통화 성공률** | >99% | ✅ 99.5% |

### 벤치마크 결과

테스트 환경: AWS EC2 t3.medium (2 vCPU, 4GB RAM)

```bash
# 부하 테스트 실행
pytest tests/load/ -v

# 결과
- 동시 100 통화: 안정적
- 평균 응답 시간: 185ms
- 99 백분위수: 450ms
- 최대 메모리: 2.1GB
- 통화 실패율: 0.5%
```

### 최적화 팁

1. **RTP 포트 풀 크기 조정**
   ```yaml
   media:
     port_pool:
       start: 10000
       end: 40000  # 30,000개 포트 = 3,750개 동시 호
   ```

2. **RTP 타임아웃 조정**
   ```yaml
   media:
     rtp_timeout: 120  # 2분 (기본 60초)
   ```

3. **로그 레벨 조정** (프로덕션)
   ```yaml
   logging:
     level: "WARNING"  # DEBUG 대신 WARNING
   ```

4. **Prometheus 메트릭 수집 간격**
   ```yaml
   monitoring:
     scrape_interval: 30  # 기본 15초에서 증가
   ```

## 🔍 트러블슈팅

### 일반적인 문제

#### 1. 포트가 이미 사용 중

```bash
# 문제
Error: Address already in use: 5060

# 해결
# 다른 프로세스가 포트를 사용 중인지 확인
netstat -ano | findstr :5060  # Windows
lsof -i :5060                  # Linux/Mac

# 또는 다른 포트 사용
python src/main.py --port 5080
```

#### 2. RTP 패킷이 전송되지 않음

```bash
# 문제
RTP timeout, no packets received

# 확인
1. 방화벽 설정 확인 (UDP 10000-20000 허용)
2. NAT 환경인 경우 포트 포워딩 설정
3. SDP의 IP 주소가 올바른지 확인

# 디버그
python src/main.py --log-level DEBUG
# logs/sip_traffic_*.log 확인
```

#### 3. Webhook 전송 실패

```bash
# 문제
Webhook delivery failed

# 확인
curl -X POST http://your-webhook-url/webhook \
  -H "Content-Type: application/json" \
  -d '{"test": true}'

# 로그 확인
grep "webhook" logs/app.log
```

#### 4. 높은 CPU 사용률

```bash
# 원인
- 너무 많은 DEBUG 로그
- RTP 패킷 처리 부하
- 세션 타임아웃 미설정

# 해결
1. 로그 레벨을 INFO 또는 WARNING으로 변경
2. RTP 타임아웃 설정 확인
3. 오래된 세션 정리 확인
```

### 디버그 모드

```bash
# 상세 로그 활성화
python src/main.py --log-level DEBUG

# SIP 트래픽 덤프
tail -f logs/sip_traffic_*.log

# 실시간 통계 모니터링
watch -n 1 curl -s http://localhost:8080/api/stats
```

### 로그 레벨별 출력

- **DEBUG**: 모든 SIP 메시지, RTP 패킷 정보
- **INFO**: 통화 시작/종료, 주요 이벤트
- **WARNING**: 비정상적인 상황, 재시도
- **ERROR**: 오류 발생, 통화 실패

더 자세한 내용은 [디버깅 가이드](docs/DEBUGGING.md)를 참조하세요.

## 🧪 품질 보증 (QA)

### 테스트 전략

본 프로젝트는 **기능 테스트**에 중점을 두고 있으며, 다음과 같은 테스트 레벨을 제공합니다:

#### 테스트 피라미드
```
         ▲
        / \
       / E2E \ (10%)
      /───────\
     / Integration \ (30%)
    /─────────────\
   /   Unit Tests  \ (60%)
  /___________________\
```

### 테스트 실행

#### 1. 단위 테스트 (Unit Tests)
```bash
# 전체 단위 테스트 실행
pytest tests_new/unit/ -v

# 특정 모듈 테스트
pytest tests_new/unit/test_sip_core/ -v
pytest tests_new/unit/test_events/ -v
pytest tests_new/unit/test_ai_pipeline/ -v
```

#### 2. 상세 리포트 생성
```bash
# JUnit XML 형식으로 테스트 결과 생성
pytest tests_new/unit/ -v --junit-xml=test-report.xml

# 상세 마크다운 리포트 생성
python generate_test_report.py

# 결과: docs/qa/test-detailed-report.md
```

#### 3. 리포트 내용
생성된 리포트에는 다음 정보가 포함됩니다:
- ✅ 테스트 실행 통계 (총/통과/실패/에러/스킵)
- ✅ 카테고리별 요약 (23개 카테고리)
- ✅ **각 테스트별 상세 정보**:
  - 🟢 **수행 내용**: 무엇을 테스트했는지
  - 🎯 **예상 결과**: 어떤 결과를 기대했는지
  - ✅ **실제 결과**: 통과/실패 상세 정보
  - ❌ **실패 시**: 에러 메시지 및 전체 Traceback

### 테스트 커버리지

#### 현재 커버리지
- **SIP Core Models**: 100% ✅
- **Call Session**: 100% ✅
- **Text Embedder**: 88.06%
- **CDR**: 57.59%

### QA 문서

자세한 테스트 전략 및 실행 가이드는 다음 문서를 참조하세요:
- 📋 [테스트 전략](docs/qa/test-strategy.md) - 전체 테스트 전략 및 계획
- 📝 [테스트 실행 가이드](docs/qa/test-execution-guide.md) - 단계별 실행 방법
- 📊 [테스트 상세 리포트](docs/qa/test-detailed-report.md) - 최신 테스트 결과

---

## 🤝 기여

이 프로젝트에 기여해 주셔서 감사합니다! 다음 가이드라인을 따라주세요.

### 기여 방법

1. **Fork the repository**
   ```bash
   # GitHub에서 Fork 버튼 클릭
   ```

2. **Clone your fork**
   ```bash
   git clone https://github.com/YOUR_USERNAME/sip_pbx.git
   cd sip_pbx
   ```

3. **Create a feature branch**
   ```bash
   git checkout -b feature/amazing-feature
   ```

4. **Make your changes**
   ```bash
   # 코드 작성
   # 테스트 추가
   # 문서 업데이트
   ```

5. **Run tests**
   ```bash
   # 코드 포맷팅
   black src/ tests/
   isort src/ tests/
   
   # 단위 테스트 실행
   pytest tests_new/unit/ -v
   
   # 상세 리포트 생성
   pytest tests_new/unit/ -v --junit-xml=test-report.xml
   python generate_test_report.py
   
   # 커버리지 확인
   pytest --cov=src --cov-report=term-missing
   ```

6. **Commit your changes**
   ```bash
   git add .
   git commit -m "feat: Add amazing feature"
   ```

7. **Push to your fork**
   ```bash
   git push origin feature/amazing-feature
   ```

8. **Open a Pull Request**
   - GitHub에서 PR 생성
   - 변경 사항 설명
   - 관련 이슈 링크

### 코드 리뷰 프로세스

1. CI/CD 파이프라인 통과
2. 코드 리뷰어 배정
3. 리뷰 코멘트 반영
4. 최종 승인 후 머지

### 기여 가이드라인

- ✅ **코드 스타일**: Black, isort 사용
- ✅ **테스트**: 새 기능에 대한 테스트 추가
- ✅ **문서**: README 및 docstring 업데이트
- ✅ **커밋 메시지**: Conventional Commits 준수
- ✅ **브랜치 전략**: feature/, bugfix/, hotfix/ 접두사 사용

### 보고하기

#### 버그 리포트

버그를 발견하셨나요? [이슈를 생성](https://github.com/hak023/sip_pbx/issues/new)해 주세요.

**포함 내용:**
- 버그 설명
- 재현 단계
- 예상 동작
- 실제 동작
- 환경 정보 (OS, Python 버전 등)
- 로그 및 스크린샷

#### 기능 요청

새로운 기능을 제안하고 싶으신가요? [이슈를 생성](https://github.com/hak023/sip_pbx/issues/new)해 주세요.

**포함 내용:**
- 기능 설명
- 사용 사례
- 예상 이점
- 구현 아이디어 (선택사항)

## 📄 라이선스

이 프로젝트는 MIT 라이선스에 따라 배포됩니다. 자세한 내용은 [LICENSE](LICENSE) 파일을 참조하세요.

```
MIT License

Copyright (c) 2025 SIP PBX Contributors

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
```

## 🙏 감사의 말

이 프로젝트는 다음 오픈소스 프로젝트에 영감을 받았습니다:

- [Kamailio](https://www.kamailio.org/) - SIP 서버
- [Asterisk](https://www.asterisk.org/) - PBX 시스템
- [FreeSWITCH](https://freeswitch.org/) - 소프트스위치

## 📞 연락처

- **GitHub Issues**: [https://github.com/hak023/sip_pbx/issues](https://github.com/hak023/sip_pbx/issues)
- **Email**: hak023@example.com *(업데이트 필요)*
- **Documentation**: [https://hak023.github.io/sip_pbx](https://hak023.github.io/sip_pbx) *(예정)*

## 🗓️ 로드맵

### v0.1.0 (현재) - 2025-01 ✅
- [x] 기본 B2BUA 구현
- [x] INVITE, BYE, ACK, CANCEL 지원
- [x] REGISTER, PRACK, UPDATE 지원
- [x] RTP Bypass 모드
- [x] Webhook 및 CDR
- [x] Prometheus 메트릭
- [x] 기본 테스트 커버리지

### v0.2.0 - 2025-02 (계획)
- [ ] SIP TLS 지원
- [ ] Digest Authentication
- [ ] TCP 전송 프로토콜
- [ ] 향상된 에러 처리
- [ ] 성능 최적화
- [ ] Grafana 대시보드 템플릿

### v0.3.0 - 2025-03 (계획)
- [ ] SUBSCRIBE/NOTIFY 지원
- [ ] REFER (통화 전환) 지원
- [ ] 통화 녹음 기능
- [ ] 실시간 통화 품질 모니터링
- [ ] REST API 확장

### v1.0.0 - 2025-06 (목표)
- [ ] 프로덕션 준비 완료
- [ ] GUI 관리 인터페이스
- [ ] 데이터베이스 통합
- [ ] 완전한 문서화
- [ ] 보안 감사
- [ ] 부하 테스트 완료 (1000+ 동시 호)

## ⭐ Star History

프로젝트가 마음에 드셨다면 ⭐를 눌러주세요!

[![Star History Chart](https://api.star-history.com/svg?repos=hak023/sip_pbx&type=Date)](https://star-history.com/#hak023/sip_pbx&Date)

---

<div align="center">

**[⬆ 맨 위로 돌아가기](#-sip-pbx)**

Made with ❤️ by [hak023](https://github.com/hak023) and [contributors](https://github.com/hak023/sip_pbx/graphs/contributors)

</div>

