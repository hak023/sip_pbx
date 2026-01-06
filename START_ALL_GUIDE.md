# ✅ start-all.ps1 실행 가이드

## 📋 체크리스트

실행 전 다음을 확인하세요:

### ✅ 필수 의존성 설치 완료
- [x] Backend Python 패키지 설치
- [x] Frontend npm 패키지 설치
- [x] 누락된 의존성 추가 설치 완료

### ✅ 서비스 준비 (선택사항)
- [ ] PostgreSQL 실행 중 (Mock DB 사용 시 불필요)
- [ ] Redis 실행 중 (Mock Redis 사용 시 불필요)
- [ ] Google Cloud API 키 설정 (AI 기능 사용 시 필요)

---

## 🚀 실행 방법

### 옵션 1: 통합 실행 (권장)

```powershell
cd c:\work\workspace_sippbx\sip-pbx
.\start-all.ps1
```

이 명령은 다음을 자동으로 실행합니다:
1. ✅ **Frontend** (Next.js) - http://localhost:3000
2. ✅ **Backend API Gateway** (FastAPI) - http://localhost:8000
3. ✅ **WebSocket Server** (Socket.IO) - ws://localhost:8001
4. ❓ **SIP PBX** (선택사항) - 프롬프트에서 y/n 선택

각 서비스는 **별도의 PowerShell 창**에서 실행됩니다.

---

### 옵션 2: 수동 실행

개별적으로 제어가 필요한 경우:

**터미널 1 - Backend API**:
```powershell
cd c:\work\workspace_sippbx\sip-pbx
python -m src.api.main
```

**터미널 2 - WebSocket Server**:
```powershell
cd c:\work\workspace_sippbx\sip-pbx
python -m src.websocket.server
```

**터미널 3 - Frontend**:
```powershell
cd c:\work\workspace_sippbx\sip-pbx\frontend
npm run dev
```

**터미널 4 - SIP PBX (선택사항)**:
```powershell
cd c:\work\workspace_sippbx\sip-pbx
python src/main.py
```

---

## 📊 예상 실행 결과

### ✅ Frontend (정상)
```
▲ Next.js 14.2.35
- Local:        http://localhost:3000
✓ Ready in 2.3s
```

### ✅ Backend API Gateway (정상)
```
INFO:     Uvicorn running on http://0.0.0.0:8000
INFO:     Started server process [PID]
INFO:     Application startup complete.
```

### ✅ WebSocket Server (정상)
```
INFO:     Uvicorn running on http://0.0.0.0:8001
INFO:     WebSocket Server initialized
INFO:     Application startup complete.
```

---

## ❌ 실행 실패 시 해결 방법

### 문제 1: Backend API - `ImportError: email-validator`

**해결**:
```powershell
pip install email-validator
```

### 문제 2: WebSocket - `ModuleNotFoundError: socketio`

**해결**:
```powershell
pip install python-socketio
```

### 문제 3: 전체 의존성 누락

**해결 (완전 재설치)**:
```powershell
# 가상환경 재활성화
.\venv\Scripts\Activate.ps1

# Backend 의존성 재설치
pip install --upgrade pip
pip install -r requirements.txt

# Frontend 의존성 재설치
cd frontend
npm install
cd ..

# 다시 실행
.\start-all.ps1
```

---

## 🔍 실행 확인

### 1. Frontend 접속
브라우저에서 http://localhost:3000 접속

**로그인 정보 (Mock)**:
- Email: `operator@example.com`
- Password: `password`

### 2. Backend API 문서
브라우저에서 http://localhost:8000/docs 접속

### 3. WebSocket 연결
Frontend 로그인 후 브라우저 콘솔(F12)에서 다음 확인:
```
WebSocket connected: <socket_id>
```

### 4. Health Check (옵션)
```powershell
# Backend API
curl http://localhost:8000/health

# 예상 응답: {"status": "healthy", ...}
```

---

## 🛑 서버 종료

### 옵션 1: 각 창에서 Ctrl+C

각 PowerShell 창에서 `Ctrl+C`를 눌러 종료

### 옵션 2: 프로세스 강제 종료

```powershell
# 포트로 프로세스 찾기
Get-NetTCPConnection -LocalPort 3000,8000,8001 | Select-Object OwningProcess

# 프로세스 종료
Stop-Process -Id <PID> -Force
```

### 옵션 3: 모든 관련 프로세스 종료 (주의!)

```powershell
# Node.js 프로세스 모두 종료
Stop-Process -Name "node" -Force

# Python 프로세스 모두 종료 (주의: 다른 Python 앱도 종료됨)
Stop-Process -Name "python" -Force
```

---

## 📁 생성되는 파일/폴더

실행 후 다음 파일/폴더가 자동 생성될 수 있습니다:

```
sip-pbx/
├── logs/                    # 로그 파일
│   ├── api-gateway.log
│   ├── websocket.log
│   └── sip-pbx.log
├── data/                    # 데이터 파일
│   ├── vector_db/           # ChromaDB 데이터
│   └── recordings/          # 통화 녹음
└── frontend/.next/          # Next.js 빌드 캐시
```

---

## 🎯 다음 단계

서버가 정상 실행되면:

1. **Dashboard 탐색**
   - http://localhost:3000/dashboard
   - 실시간 통화 모니터링

2. **지식 베이스 추가**
   - Knowledge Base 메뉴
   - FAQ 추가/관리

3. **HITL 테스트**
   - AI 응답 모니터링
   - 운영자 개입 시뮬레이션

4. **운영자 부재중 모드 테스트**
   - Dashboard 상단 토글
   - 미처리 요청 Call History 확인

---

## 📚 추가 문서

- **문제 해결**: [TROUBLESHOOTING.md](./docs/TROUBLESHOOTING.md)
- **빠른 시작**: [QUICK_START.md](./docs/QUICK_START.md)
- **시스템 개요**: [SYSTEM_OVERVIEW.md](./docs/SYSTEM_OVERVIEW.md)
- **API 문서**: http://localhost:8000/docs (서버 실행 후)

---

## ✅ 현재 상태

**2026-01-06 기준**:
- ✅ Backend API Gateway 의존성 설치 완료
- ✅ WebSocket Server 의존성 설치 완료
- ✅ Frontend 의존성 이미 설치됨
- ✅ start-all.ps1 실행 준비 완료

**다음 명령으로 바로 실행 가능**:
```powershell
.\start-all.ps1
```

---

**생성일**: 2026-01-06  
**버전**: 1.0.0  
**상태**: ✅ Ready to Run

