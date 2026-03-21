# 지식 베이스 404 에러 진단 가이드

**날짜**: 2026-03-16

---

## 문제 증상

지식 베이스 페이지(`/knowledge`) 접근 시 404 에러 발생

---

## 가능한 원인

### 1. 프론트엔드 라우팅 문제
- **증상**: 페이지 자체가 로드되지 않음
- **확인**: 브라우저 개발자도구 Console에서 "Failed to load resource: 404" 확인
- **원인**: Next.js 개발 서버가 제대로 실행되지 않음

**해결**:
```powershell
# 프론트엔드 재시작
cd c:\work\workspace_sippbx\sip-pbx\frontend
npm run dev
```

---

### 2. 백엔드 API 404 에러
- **증상**: 페이지는 로드되지만 데이터 로딩 실패
- **확인**: Network 탭에서 `/api/knowledge` 요청이 404 반환
- **원인**: 백엔드 router가 제대로 등록되지 않음

**진단**:

#### A. 백엔드 로그 확인
```powershell
# 시작 로그에서 router 로드 확인
Select-String -Path "c:\work\workspace_sippbx\sip-pbx\logs\app.log" -Pattern "knowledge_router|NEW knowledge_router" | Select-Object -Last 5
```

**정상 출력**:
```
🔥 knowledge_router MODULE LOADED (version=v2_no_tenant_id)
🔥 NEW knowledge_router loaded (v2_no_tenant_id)
```

**비정상 출력** (출력 없음 또는 에러):
- router 로드 실패
- Import 에러

#### B. 수동 API 테스트
```powershell
# PowerShell에서 직접 호출
Invoke-RestMethod -Uri "http://localhost:8000/api/knowledge?owner=1004" -Method GET
```

**정상 응답**:
```json
{
  "items": [...],
  "total": 0
}
```

**404 응답**:
```
Invoke-RestMethod : 404 Not Found
```

---

### 3. CORS 문제
- **증상**: 브라우저 Console에 CORS 에러
- **원인**: 백엔드 CORS 설정 문제

**확인**:
```javascript
// 브라우저 Console
fetch('http://localhost:8000/api/knowledge?owner=1004')
  .then(r => r.json())
  .then(console.log)
  .catch(console.error)
```

---

## 단계별 진단

### Step 1: 프론트엔드 상태 확인

```powershell
# 프론트엔드 프로세스 확인
Get-Process -Name node -ErrorAction SilentlyContinue | Where-Object { $_.Path -like "*frontend*" }
```

**없으면**: 프론트엔드가 실행 중이 아님 → 재시작 필요

---

### Step 2: 백엔드 상태 확인

```powershell
# 백엔드 프로세스 확인
Get-Process -Name python -ErrorAction SilentlyContinue | Where-Object { $_.CommandLine -like "*src.main*" }
```

**없으면**: 백엔드가 실행 중이 아님 → 재시작 필요

---

### Step 3: 백엔드 로그 확인

```powershell
# 최신 로그 확인
Get-Content "c:\work\workspace_sippbx\sip-pbx\logs\app.log" -Tail 50
```

**확인 사항**:
- ✅ `🔥 knowledge_router MODULE LOADED`
- ✅ `🔥 NEW knowledge_router loaded`
- ❌ `Failed to load new knowledge_router`
- ❌ `ImportError`

---

### Step 4: API 엔드포인트 확인

```powershell
# FastAPI 문서 확인
Start-Process "http://localhost:8000/docs"
```

**정상**: `/api/knowledge` GET, POST 엔드포인트가 보임  
**비정상**: 엔드포인트가 없거나 다른 prefix

---

### Step 5: 프론트엔드 캐시 제거

```powershell
cd c:\work\workspace_sippbx\sip-pbx\frontend
Remove-Item -Recurse -Force .next
npm run dev
```

브라우저:
- `Ctrl + Shift + R` (Hard Refresh)
- 또는 `Ctrl + Shift + Delete` → 캐시 삭제

---

## 빠른 수정

### 전체 재시작

```powershell
# 1. 백엔드 중지 (Ctrl+C)
# 2. 프론트엔드 중지 (Ctrl+C)

# 3. 프론트엔드 캐시 삭제
cd c:\work\workspace_sippbx\sip-pbx\frontend
Remove-Item -Recurse -Force .next

# 4. 백엔드 재시작
cd c:\work\workspace_sippbx\sip-pbx
python -m src.main

# 5. 새 터미널에서 프론트엔드 재시작
cd c:\work\workspace_sippbx\sip-pbx\frontend
npm run dev

# 6. 브라우저 Hard Refresh (Ctrl+Shift+R)
```

---

## 로그 분석

### 정상 시작 로그 예시

```
{"event": "🔥 knowledge_router MODULE LOADED", "version": "v2_no_tenant_id"}
{"event": "🔥 NEW knowledge_router loaded (v2_no_tenant_id)"}
{"event": "api_server_started_in_process", "port": 8000}
```

### 비정상 시작 로그 예시

```
{"event": "Failed to load new knowledge_router", "error": "ImportError: ..."}
```

---

## 관련 파일

- `src/api/main.py` - Router 로딩 로직
- `src/api/knowledge_router.py` - 신버전 knowledge API
- `frontend/app/knowledge/page.tsx` - 프론트엔드 페이지
- `docs/KNOWLEDGE_ROUTER_MIGRATION.md` - Router 변경 가이드

---

## 자주 묻는 질문

**Q: 422 에러와 404 에러의 차이는?**

- **422**: API 엔드포인트는 존재하지만, request body validation 실패
- **404**: API 엔드포인트 자체를 찾을 수 없음

**Q: 프론트엔드만 재시작하면 되나요?**

- 백엔드 코드를 수정했다면 백엔드도 재시작 필요
- 프론트엔드 코드만 수정했다면 프론트엔드만 재시작 (또는 HMR 자동 반영)

**Q: .next 폴더를 삭제해야 하나요?**

- 코드 변경이 반영되지 않을 때만 필요
- 일반적으로는 재시작만으로 충분
