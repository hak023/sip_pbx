# ✅ 의존성 설치 완료 가이드

## 설치된 패키지 목록

### Backend 핵심 패키지 ✅
- `email-validator` 2.3.0
- `python-socketio` 5.16.0
- `fastapi` 0.104.1 (이미 설치됨)
- `uvicorn` 0.24.0 (이미 설치됨)
- `python-jose` 3.5.0
- `passlib` 1.7.4
- `redis` 7.1.0
- `asyncpg` 0.31.0
- `python-multipart` 0.0.21

### 지원 패키지 ✅
- `bidict` 0.23.1
- `python-engineio` 4.13.0
- `dnspython` 2.8.0
- `ecdsa` 0.19.1
- `simple-websocket` 1.1.0

---

## 📝 업데이트된 requirements.txt

다음 항목이 추가되었습니다:

```txt
# Async & Web Framework
fastapi==0.109.0              # FastAPI framework for API Gateway
uvicorn[standard]==0.27.0     # ASGI server for FastAPI
python-socketio==5.11.0       # Socket.IO server for WebSocket
python-multipart==0.0.6       # File upload support for FastAPI

# Configuration & Validation
pydantic[email]==2.5.2  # Email validation support

# Utilities
python-jose[cryptography]==3.3.0  # JWT authentication
passlib[bcrypt]==1.7.4            # Password hashing
redis==5.0.1                      # Redis client for caching/pub-sub
asyncpg==0.29.0                   # PostgreSQL async driver
```

---

## 🚀 다시 실행하기

### 옵션 1: start-all.ps1 (권장)

```powershell
.\start-all.ps1
```

### 옵션 2: 수동 실행

**새 PowerShell 창 1 - Backend API**:
```powershell
cd c:\work\workspace_sippbx\sip-pbx
python -m src.api.main
```

**새 PowerShell 창 2 - WebSocket Server**:
```powershell
cd c:\work\workspace_sippbx\sip-pbx
python -m src.websocket.server
```

**새 PowerShell 창 3 - Frontend**:
```powershell
cd c:\work\workspace_sippbx\sip-pbx\frontend
npm run dev
```

---

## ✅ 예상 결과

### Frontend (Port 3000) ✅
```
▲ Next.js 14.2.35
- Local:        http://localhost:3000
✓ Ready in 2.3s
```

### Backend API (Port 8000) ✅
```
INFO:     Uvicorn running on http://0.0.0.0:8000 (Press CTRL+C to quit)
INFO:     Started reloader process
INFO:     Started server process
INFO:     Waiting for application startup.
INFO:     Application startup complete.
```

### WebSocket Server (Port 8001) ✅
```
INFO:     Uvicorn running on http://0.0.0.0:8001 (Press CTRL+C to quit)
INFO:     Started server process
INFO:     WebSocket server initialized
INFO:     Waiting for application startup.
INFO:     Application startup complete.
```

---

## 🔍 접속 확인

1. **Frontend**: http://localhost:3000
2. **API 문서**: http://localhost:8000/docs
3. **WebSocket**: ws://localhost:8001 (자동 연결)

---

## 🔐 Mock 로그인 정보

- **Email**: `operator@example.com`
- **Password**: `password`

---

## ⚠️ 여전히 문제가 있다면?

`./docs/TROUBLESHOOTING.md` 참조

---

**생성일**: 2026-01-06
**버전**: 1.0.0

