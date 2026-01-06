# 🔧 Troubleshooting Guide

## 일반적인 문제 해결

### 1. Backend API Gateway 실행 오류

#### 문제: `ImportError: email-validator is not installed`

**원인**: pydantic의 email validation 의존성 누락

**해결방법**:
```bash
pip install email-validator
```

또는 전체 재설치:
```bash
pip install -r requirements.txt
```

---

#### 문제: `ModuleNotFoundError: No module named 'fastapi'`

**원인**: FastAPI 관련 의존성 누락

**해결방법**:
```bash
pip install fastapi uvicorn python-multipart python-jose passlib
```

---

### 2. WebSocket Server 실행 오류

#### 문제: `ModuleNotFoundError: No module named 'socketio'`

**원인**: python-socketio 패키지 누락

**해결방법**:
```bash
pip install python-socketio
```

---

### 3. Frontend 실행 오류

#### 문제: `Module not found: Can't resolve '@radix-ui/...'`

**원인**: Frontend 의존성 누락

**해결방법**:
```bash
cd frontend
npm install
```

---

#### 문제: `EADDRINUSE: address already in use :::3000`

**원인**: 포트 3000이 이미 사용 중

**해결방법**:

**Windows PowerShell**:
```powershell
# 프로세스 찾기
Get-NetTCPConnection -LocalPort 3000 | Select-Object OwningProcess
# 프로세스 종료
Stop-Process -Id <PID> -Force
```

또는 포트 변경:
```bash
cd frontend
# package.json에서 "dev": "next dev -p 3001"로 변경
npm run dev
```

---

### 4. Database 연결 오류

#### 문제: `Connection refused` (PostgreSQL)

**원인**: PostgreSQL이 실행 중이지 않음

**해결방법**:

**Windows**:
```powershell
# PostgreSQL 서비스 상태 확인
Get-Service -Name postgresql*

# 서비스 시작
Start-Service -Name postgresql-x64-14  # 버전에 맞게 수정
```

또는 Mock DB로 테스트 (개발 중):
```python
# src/api/main.py에서 DB 초기화 부분 주석 처리
# await init_db()  # Mock으로 대체
```

---

#### 문제: `Connection refused` (Redis)

**원인**: Redis가 실행 중이지 않음

**해결방법**:

**Windows (WSL 필요)**:
```bash
# WSL에서 Redis 시작
wsl
sudo service redis-server start
```

또는 Docker로 실행:
```bash
docker run -d -p 6379:6379 redis:7-alpine
```

또는 Mock Redis로 테스트:
```python
# config.yaml에서 Redis 비활성화
redis:
  enabled: false  # Mock으로 대체
```

---

### 5. Google Cloud API 오류

#### 문제: `google.auth.exceptions.DefaultCredentialsError`

**원인**: GCP Service Account 키 파일 누락

**해결방법**:
1. [Google Cloud Console](https://console.cloud.google.com/)에서 Service Account 키 생성
2. `config/gcp-key.json`에 저장
3. `config.yaml`에서 경로 확인:
   ```yaml
   ai_voicebot:
     google_cloud:
       credentials_path: "config/gcp-key.json"
   ```

---

#### 문제: `404 models/gemini-1.5-flash is not found`

**원인**: 잘못된 모델 이름 또는 API 키 문제

**해결방법**:
1. API 키 확인:
   ```yaml
   # config.yaml
   ai_voicebot:
     google_cloud:
       gemini:
         api_key: "AIzaSy..."  # 올바른 API 키 입력
   ```

2. 모델 이름 확인:
   ```yaml
   gemini:
     model: "gemini-2.5-flash"  # 최신 버전 사용
   ```

3. API 키 발급: https://aistudio.google.com/app/apikey

---

### 6. PowerShell 스크립트 실행 오류

#### 문제: `start-all.ps1 cannot be loaded because running scripts is disabled`

**원인**: PowerShell 실행 정책 제한

**해결방법**:
```powershell
# 관리자 권한으로 PowerShell 실행
Set-ExecutionPolicy -ExecutionPolicy RemoteSigned -Scope CurrentUser

# 또는 일회성 실행
powershell -ExecutionPolicy Bypass -File .\start-all.ps1
```

---

### 7. 의존성 충돌 문제

#### 문제: `ERROR: pip's dependency resolver does not currently take into account...`

**원인**: 패키지 버전 충돌

**해결방법**:

**옵션 1: 가상환경 재생성**
```bash
# 기존 가상환경 삭제
Remove-Item -Recurse -Force venv

# 새 가상환경 생성
python -m venv venv
.\venv\Scripts\Activate.ps1

# 의존성 재설치
pip install --upgrade pip
pip install -r requirements.txt
```

**옵션 2: 충돌 패키지 강제 업그레이드**
```bash
pip install --upgrade --force-reinstall pydantic pydantic-settings
```

---

### 8. Frontend 빌드 오류

#### 문제: `Type error: Cannot find module '@/...'`

**원인**: TypeScript 경로 별칭 문제

**해결방법**:
```bash
cd frontend
# tsconfig.json 확인
# node_modules 재설치
rm -rf node_modules package-lock.json
npm install
```

---

### 9. WebSocket 연결 실패

#### 문제: Frontend에서 `WebSocket connection failed`

**원인**: WebSocket 서버 미실행 또는 포트 불일치

**해결방법**:

1. WebSocket 서버 실행 확인:
   ```bash
   python -m src.websocket.server
   ```

2. 포트 확인:
   ```typescript
   // frontend/.env.local
   NEXT_PUBLIC_WS_URL=ws://localhost:8001
   ```

3. CORS 설정 확인:
   ```python
   # src/websocket/server.py
   sio = socketio.AsyncServer(
       cors_allowed_origins="*"  # 또는 "http://localhost:3000"
   )
   ```

---

### 10. 메모리 부족 오류

#### 문제: `MemoryError` 또는 시스템 느림

**원인**: AI 모델 (PyTorch, sentence-transformers) 메모리 사용량 높음

**해결방법**:

1. ChromaDB 메모리 제한:
   ```yaml
   # config.yaml
   ai_voicebot:
     vector_db:
       max_memory_mb: 512  # 메모리 제한 설정
   ```

2. PyTorch CPU 전용 사용:
   ```bash
   pip uninstall torch torchvision torchaudio
   pip install torch --index-url https://download.pytorch.org/whl/cpu
   ```

---

## 빠른 진단 체크리스트

### ✅ Backend API Gateway
```bash
# 1. 의존성 확인
pip list | grep fastapi

# 2. 포트 확인
netstat -an | findstr 8000

# 3. 수동 실행
python -m src.api.main
```

### ✅ WebSocket Server
```bash
# 1. 의존성 확인
pip list | grep socketio

# 2. 포트 확인
netstat -an | findstr 8001

# 3. 수동 실행
python -m src.websocket.server
```

### ✅ Frontend
```bash
cd frontend
# 1. 의존성 확인
npm list

# 2. 포트 확인
netstat -an | findstr 3000

# 3. 수동 실행
npm run dev
```

---

## 로그 확인

### Backend API
```bash
# logs/api-gateway.log 확인
tail -f logs/api-gateway.log  # Linux/Mac
Get-Content logs/api-gateway.log -Wait  # Windows
```

### WebSocket Server
```bash
# logs/websocket.log 확인
tail -f logs/websocket.log  # Linux/Mac
Get-Content logs/websocket.log -Wait  # Windows
```

### Frontend
```bash
cd frontend
# 브라우저 콘솔 (F12) 확인
# 또는 서버 로그 직접 확인
```

---

## 완전 초기화 (Clean Install)

모든 문제를 해결하기 위한 완전 초기화:

```powershell
# 1. 가상환경 재생성
Remove-Item -Recurse -Force venv
python -m venv venv
.\venv\Scripts\Activate.ps1

# 2. Backend 의존성 재설치
pip install --upgrade pip
pip install -r requirements.txt

# 3. Frontend 의존성 재설치
cd frontend
Remove-Item -Recurse -Force node_modules
Remove-Item package-lock.json
npm install
cd ..

# 4. 캐시 정리
pip cache purge
npm cache clean --force

# 5. 재실행
.\start-all.ps1
```

---

## 추가 도움말

- **공식 문서**: `./docs/README.md`
- **빠른 시작**: `./docs/QUICK_START.md`
- **API 문서**: http://localhost:8000/docs (서버 실행 후)
- **GitHub Issues**: [프로젝트 이슈 페이지]

---

## 문의

문제가 계속되면 다음 정보와 함께 이슈를 제출해주세요:
1. 운영체제 및 버전
2. Python 버전 (`python --version`)
3. Node.js 버전 (`node --version`)
4. 에러 메시지 전문
5. 로그 파일 (`logs/`)

