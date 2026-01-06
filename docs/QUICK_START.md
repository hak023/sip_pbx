# 🚀 Quick Start Guide

AI Voicebot Control Center를 5분 안에 실행해보세요!

## 1단계: Backend 설치 (2분)

```powershell
# 저장소 클론
git clone https://github.com/your-org/sip-pbx.git
cd sip-pbx

# 가상환경 생성 및 활성화
python -m venv venv
.\venv\Scripts\Activate.ps1

# Backend 의존성 설치
pip install -r requirements.txt
```

## 2단계: Frontend 설치 (1분)

```powershell
# Frontend 의존성 설치
cd frontend
npm install
cd ..
```

## 3단계: 설정 (1분)

```powershell
# 설정 파일 확인 (이미 구성됨)
# config/config.yaml - Backend 설정
# frontend/.env.local - Frontend 환경 변수 (선택사항)
```

## 4단계: 전체 시스템 실행 (30초)

```powershell
# 통합 실행 스크립트
.\start-all.ps1
```

이 스크립트는 다음을 동시에 실행합니다:
1. **Frontend** (Next.js) - http://localhost:3000
2. **Backend API Gateway** (FastAPI) - http://localhost:8000
3. **WebSocket Server** (Socket.IO) - ws://localhost:8001
4. **SIP PBX** (선택사항)

## 4단계: 테스트

### Frontend 접속
```
브라우저에서 http://localhost:3000 접속
```

**Mock 로그인 정보:**
- Email: `operator@example.com`
- Password: `password`

### Backend API 문서 확인

```powershell
# 브라우저에서 API 문서 열기
start http://localhost:8000/docs
```

**예상 엔드포인트:**
- `GET /api/calls` - 통화 목록
- `GET /api/hitl/requests` - HITL 요청 목록
- `POST /api/knowledge` - 지식 베이스 추가
- `PUT /api/operator/status` - 운영자 상태 변경

### WebSocket 연결 확인

Frontend에 로그인하면 자동으로 WebSocket이 연결됩니다.
브라우저 콘솔(F12)에서 다음 메시지 확인:

```
WebSocket connected: <socket_id>
```

### Health Check

```powershell
# Backend API
curl http://localhost:8000/health

# 예상 응답
# {
#   "status": "healthy",
#   "timestamp": "2026-01-06T10:00:00Z"
# }
```

## 다음 단계

✅ **성공!** AI Voicebot Control Center가 실행 중입니다!

### 주요 기능 탐색

1. **실시간 통화 모니터링**
   - Dashboard에서 라이브 통화 확인
   - STT/TTS 실시간 트랜스크립트
   - AI 응답 상태 모니터링

2. **지식 베이스 관리**
   - Knowledge Base 페이지에서 문서 업로드
   - FAQ 추가/수정/삭제
   - Vector DB 검색 테스트

3. **Human-in-the-Loop (HITL)**
   - AI가 답변하기 어려운 질문 발생 시 알림
   - 실시간 운영자 응답
   - 응답 내용 지식 베이스 저장 옵션

4. **운영자 부재중 모드** ✨ NEW
   - Dashboard 우측 상단 토글로 상태 변경
   - 부재중 시 HITL 자동 처리
   - 미처리 요청 Call History에서 확인

### SIP 통화 시뮬레이션

1. **SIP 클라이언트 설정** (예: Zoiper, X-Lite, MicroSIP)
   - SIP Server: `localhost:5060`
   - 통화 시작 시 AI Voicebot 자동 응답

2. **AI 응답 테스트**
   - "안녕하세요" → AI가 인사 응답
   - "영업시간이 언제인가요?" → RAG 기반 답변
   - "잘 모르겠어요" (낮은 confidence) → HITL 요청 발생

### 이벤트 확인

Dashboard에서 실시간으로 다음 이벤트 확인:
- ✅ `call_started` - 통화 시작
- 💬 `stt_transcript` - 사용자 발화
- 🤖 `tts_started/ended` - AI 응답
- 🚨 `hitl_requested` - 운영자 개입 요청

## 문제 해결

### 의존성 설치 오류

```powershell
# Backend 의존성 재설치
pip install --upgrade pip
pip install -r requirements.txt

# Frontend 의존성 재설치
cd frontend
npm install
```

**자세한 문제 해결**: [TROUBLESHOOTING.md](TROUBLESHOOTING.md)

### 포트 충돌

```powershell
# 프로세스 종료
Get-NetTCPConnection -LocalPort 3000,8000,8001 | Select-Object OwningProcess
Stop-Process -Id <PID> -Force
```

### 디버그 모드

```yaml
# config/config.yaml
logging:
  level: DEBUG
```

## 더 알아보기

- 📘 [시스템 개요](SYSTEM_OVERVIEW.md)
- 🏗️ [AI Voicebot 아키텍처](ai-voicebot-architecture.md)
- 🖥️ [Frontend 아키텍처](frontend-architecture.md)
- 🔧 [문제 해결 가이드](TROUBLESHOOTING.md)
- 🐛 [디버깅 가이드](DEBUGGING.md)
- 📦 [운영자 부재중 모드 설정](OPERATOR_AWAY_MODE_SETUP.md)

---

**🎉 축하합니다! AI Voicebot Control Center가 실행되고 있습니다!**

