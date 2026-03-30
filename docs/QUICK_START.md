# Quick Start Guide

AI SIP PBX 시스템을 설치하고 실행하는 가이드.

---

## 사전 요구사항

| 항목 | 버전 |
|---|---|
| Python | 3.11+ |
| Node.js | 18+ |
| npm | 9+ |
| OS | Windows 10/11 (PowerShell 5.1+) |
| Google Cloud | STT/TTS/Gemini API 키 |

---

## 1단계: 설치

### Backend

```powershell
cd sip-pbx

# 가상환경 생성 및 활성화
python -m venv venv
.\venv\Scripts\Activate.ps1

# 의존성 설치
pip install -r requirements.txt
pip install -r requirements-websocket.txt
```

### Frontend

```powershell
cd frontend
npm install
cd ..
```

---

## 2단계: 설정

### Google Cloud API 키 설정

`config/config.yaml`에서 다음 항목을 설정한다:

```yaml
ai_voicebot:
  google_cloud:
    gemini:
      api_key: "YOUR_GEMINI_API_KEY"       # 또는 환경변수 GEMINI_API_KEY
    credentials_path: "path/to/service-account.json"  # STT/TTS용
```

또는 환경변수로 설정:

```powershell
$env:GEMINI_API_KEY = "YOUR_API_KEY"
$env:GOOGLE_APPLICATION_CREDENTIALS = "path/to/service-account.json"
```

### 주요 설정 항목

| 설정 | 파일 | 설명 |
|---|---|---|
| SIP 포트 | `config/config.yaml` → `sip.port` | 기본 5060 |
| AI 전환 타임아웃 | `config/config.yaml` → `sip.no_answer_timeout` | 기본 10초 |
| Gemini 모델 | `config/config.yaml` → `ai_voicebot.google_cloud.gemini.model` | 기본 `gemini-2.5-flash` |
| ChromaDB 경로 | `config/config.yaml` → `ai_voicebot.vector_db.chromadb.persist_directory` | 기본 `./data/chromadb` |

---

## 3단계: 실행

### 통합 실행 (권장)

```powershell
.\start-all.ps1
```

이 스크립트는 다음을 자동으로 처리한다:
1. Python venv 확인 및 의존성 자동 설치 (변경 감지)
2. Frontend node_modules 확인 및 자동 설치
3. Frontend를 백그라운드 Job으로 시작
4. Backend를 포그라운드에서 시작 (SIP + API + WebSocket 통합)

### 접속 정보

| 서비스 | URL / 포트 |
|---|---|
| **Frontend 대시보드** | http://localhost:3000 |
| **REST API** | http://localhost:8000 |
| **WebSocket** | ws://localhost:8001 |
| **SIP** | UDP 5060 |
| **RTP** | UDP 10000-10100 |

### 종료

```powershell
# Ctrl+C로 종료 (Frontend Job도 함께 정리됨)

# 또는 stop-all.ps1 사용
.\stop-all.ps1
```

---

## 4단계: 테스트

### 4.1 Frontend 접속

1. 브라우저에서 http://localhost:3000 접속
2. 로그인 화면에서 테넌트(내선번호) 선택
3. 대시보드 진입

### 4.2 SIP 통화 테스트

SIP 클라이언트(MicroSIP, Zoiper 등)를 설정한다:

| 설정 | 값 |
|---|---|
| SIP Server | `localhost` |
| SIP Port | `5060` |
| Transport | UDP |

**테스트 시나리오**:

1. SIP 클라이언트에서 등록된 내선번호로 전화
2. 착신자가 `no_answer_timeout`(기본 10초) 내 미응답
3. AI 봇이 자동으로 전화를 받아 인사
4. 대시보드에서 실시간 STT/TTS 모니터링

### 4.3 지식베이스 설정

1. 대시보드 → 지식베이스 메뉴
2. "지식 추가"로 FAQ 등록
   - 카테고리: weather, disaster, faq 등
   - 텍스트: 질문과 답변 내용
3. 페르소나 설정 (AI 봇 성격 정의)

### 4.4 Health Check

```powershell
# Backend 상태 확인
Invoke-RestMethod http://localhost:8000/health

# 활성 통화 확인
Invoke-RestMethod http://localhost:8000/api/calls/active
```

---

## 문제 해결

### 포트 충돌

```powershell
# 사용 중인 포트 확인
Get-NetTCPConnection -LocalPort 3000,8000,8001 -ErrorAction SilentlyContinue |
    Select-Object LocalPort, OwningProcess

# 프로세스 종료
.\stop-all.ps1
```

### 의존성 설치 오류

```powershell
# pip 업그레이드 후 재설치
pip install --upgrade pip
pip install -r requirements.txt
pip install -r requirements-websocket.txt

# Frontend 재설치
cd frontend
Remove-Item -Recurse node_modules -Force
npm install
```

### 디버그 모드

```yaml
# config/config.yaml
logging:
  level: DEBUG
```

로그 파일: `logs/app.log`
CDR 파일: `logs/call_data_record_YYYYMMDD.log`

---

## 관련 문서

| 문서 | 설명 |
|---|---|
| [SYSTEM_OVERVIEW.md](SYSTEM_OVERVIEW.md) | 시스템 전체 개요 및 기능 상세 |
| [INDEX.md](INDEX.md) | 전체 문서 인덱스 |
| [design/AI_VOICEBOT_ARCHITECTURE.md](design/AI_VOICEBOT_ARCHITECTURE.md) | AI 음성봇 아키텍처 |
| [design/FRONTEND_ARCHITECTURE.md](design/FRONTEND_ARCHITECTURE.md) | Frontend 아키텍처 |
| [guides/TROUBLESHOOTING.md](guides/TROUBLESHOOTING.md) | 상세 문제 해결 가이드 |
