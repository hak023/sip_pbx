# 🚀 Frontend Control Center 빠른 시작

## 📋 목차

1. [시스템 요구사항](#시스템-요구사항)
2. [빠른 실행](#빠른-실행)
3. [개별 실행](#개별-실행)
4. [로그인 및 사용](#로그인-및-사용)
5. [문제 해결](#문제-해결)

---

## 시스템 요구사항

### 필수 소프트웨어

- **Node.js**: 18.0 이상
- **Python**: 3.11 이상
- **PowerShell**: 7.0 이상 (Windows)

### 설치 확인

```powershell
node --version   # v18.0.0 이상
python --version # Python 3.11 이상
pwsh --version   # PowerShell 7.0 이상
```

---

## 빠른 실행

### 전체 시스템 한 번에 실행

```powershell
# 프로젝트 루트에서
.\start-all.ps1
```

이 스크립트는 다음을 자동으로 실행합니다:

1. **Frontend (Next.js)** - http://localhost:3000
2. **Backend API (FastAPI)** - http://localhost:8000
3. **WebSocket Server (Socket.IO)** - ws://localhost:8001

각 서버는 **별도의 PowerShell 창**에서 실행됩니다.

### 실행 순서

```
1️⃣  Frontend 서버 시작 중...
   ✅ Frontend: http://localhost:3000

2️⃣  Backend API Gateway 시작 중...
   ✅ API Gateway: http://localhost:8000/docs

3️⃣  WebSocket Server 시작 중...
   ✅ WebSocket: ws://localhost:8001

✅ 모든 서버가 시작되었습니다!
```

### SIP PBX 추가 실행 (선택 사항)

스크립트 실행 중 다음 질문이 나타납니다:

```
❓ 기존 SIP PBX 서버도 실행하시겠습니까? (y/N):
```

- `y` 입력: SIP PBX도 함께 실행
- `n` 또는 Enter: Frontend/Backend만 실행

---

## 개별 실행

각 서버를 수동으로 실행할 수도 있습니다.

### 1. Frontend (Next.js)

```powershell
cd frontend
npm install        # 최초 1회만
npm run dev
```

- 접속: http://localhost:3000
- 빌드: `npm run build`
- 프로덕션 실행: `npm start`

### 2. Backend API (FastAPI)

```powershell
# 프로젝트 루트에서
python -m src.api.main
```

- API 문서: http://localhost:8000/docs
- Health Check: http://localhost:8000/health

### 3. WebSocket Server (Socket.IO)

```powershell
# 프로젝트 루트에서
python -m src.websocket.server
```

- WebSocket 엔드포인트: ws://localhost:8001

### 4. SIP PBX (선택 사항)

```powershell
# 프로젝트 루트에서
python src/main.py
```

- SIP: 5060 (UDP)
- RTP: 10000-10100 (UDP)

---

## 로그인 및 사용

### 1. Frontend 접속

브라우저에서 http://localhost:3000 접속

### 2. 로그인

**Mock 계정** (개발용):
- **Email**: `operator@example.com`
- **Password**: `password`

### 3. Dashboard

로그인 후 자동으로 대시보드로 이동합니다.

#### 주요 기능

1. **메트릭 카드**
   - 활성 통화 수
   - HITL 대기 수
   - AI 신뢰도
   - 오늘 통화 수

2. **실시간 통화 목록**
   - 현재 진행 중인 통화
   - 통화 클릭 시 → 실시간 트랜스크립트 표시

3. **HITL 큐**
   - AI가 도움을 요청한 목록
   - 🆘 "답변하기" 버튼 클릭

4. **HITL 응답 다이얼로그**
   - 질문 및 컨텍스트 확인
   - 답변 작성
   - 지식 베이스 저장 옵션

---

## 실시간 기능 테스트

### WebSocket 연결 확인

Dashboard 우측 상단:
- 🟢 **WebSocket 연결됨** (정상)
- 🔴 **WebSocket 연결 안됨** (오류)

### 실시간 이벤트

1. **통화 시작 이벤트**: 새 통화가 목록에 추가됨
2. **STT 트랜스크립트**: 사용자 발화 실시간 표시
3. **TTS 시작**: AI 응답 실시간 표시
4. **HITL 요청**: 🆘 알림 + 큐에 추가

---

## 환경 변수 (선택 사항)

### Frontend (.env.local)

```env
NEXT_PUBLIC_API_URL=http://localhost:8000
NEXT_PUBLIC_WS_URL=ws://localhost:8001
```

### Backend (.env)

```env
# 기존 설정 유지
GOOGLE_APPLICATION_CREDENTIALS=./credentials/gcp-key.json
GEMINI_API_KEY=your-key-here

# 신규 (선택 사항)
JWT_SECRET_KEY=your-secret-key
REDIS_URL=redis://localhost:6379/0
```

---

## 문제 해결

### 1. Frontend가 실행되지 않음

```powershell
# node_modules 재설치
cd frontend
rm -r -force node_modules
rm package-lock.json
npm install
npm run dev
```

### 2. Backend API 오류

```powershell
# Python 의존성 확인
pip install -r requirements.txt

# FastAPI 수동 실행
cd src/api
uvicorn main:app --reload --host 0.0.0.0 --port 8000
```

### 3. WebSocket 연결 안됨

**증상**: Dashboard에 "WebSocket 연결 안됨" 표시

**해결 방법**:

1. WebSocket 서버가 실행 중인지 확인
   ```powershell
   # 프로세스 확인
   Get-Process | Where-Object {$_.CommandLine -like "*websocket*"}
   ```

2. 포트 8001이 사용 가능한지 확인
   ```powershell
   netstat -ano | findstr :8001
   ```

3. 방화벽 확인 (Windows Defender)

### 4. "Cannot find module" 오류 (Frontend)

```powershell
# TypeScript 재컴파일
cd frontend
npm run build

# 또는 개발 서버 재시작
npm run dev
```

### 5. Python Import 오류

```powershell
# PYTHONPATH 설정 (프로젝트 루트에서)
$env:PYTHONPATH = "$(pwd)"

# 또는 start-all.ps1 수정하여 추가:
# $env:PYTHONPATH = "$RootDir"
```

### 6. 포트 충돌

다른 프로그램이 포트를 사용 중인 경우:

```powershell
# 포트 사용 확인
netstat -ano | findstr :3000
netstat -ano | findstr :8000
netstat -ano | findstr :8001

# 프로세스 종료 (PID 확인 후)
taskkill /F /PID <PID>
```

또는 환경 변수로 포트 변경:

```env
# Frontend
PORT=3001

# Backend (코드에서 수정 필요)
# src/api/main.py: uvicorn.run(app, port=8001)
```

---

## 다음 단계

### 개발 진행 사항

✅ **완료**:
- Frontend 기본 UI
- Backend API Gateway
- WebSocket 실시간 통신
- HITL 기본 기능

⏳ **진행 중**:
- 실시간 통화 모니터링 (70%)
- HITL UI 완성 (90%)

🔜 **예정**:
- PostgreSQL 연동
- Redis 연동
- JWT 실제 인증
- Vector DB UI

### 추가 문서

- [전체 시스템 개요](../SYSTEM_OVERVIEW.md)
- [구현 현황](../reports/2026-01/IMPLEMENTATION_STATUS.md)
- [Frontend 아키텍처](../architecture/frontend-architecture.md)
- [AI 보이스봇 아키텍처](../architecture/ai-voicebot-architecture.md)

---

## 🎉 성공!

모든 서버가 정상 실행 중이면:

```
✅ Frontend:   http://localhost:3000
✅ API 문서:   http://localhost:8000/docs  
✅ WebSocket:  ws://localhost:8001 (자동 연결)

🔐 로그인: operator@example.com / password
```

**Happy Coding!** 🚀

