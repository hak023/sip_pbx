# 운영자 부재중 모드 - 실행 가이드

## 📋 사전 준비

### 1. Database Migration 실행

PostgreSQL 데이터베이스에 `unresolved_hitl_requests` 테이블을 생성합니다.

```bash
cd sip-pbx

# PostgreSQL 접속 정보 확인 (config.yaml 또는 환경 변수)
# 기본값: localhost:5432, database: sip_pbx

psql -U postgres -d sip_pbx -f migrations/001_create_unresolved_hitl_requests.sql
```

**성공 메시지:**
```
CREATE TABLE
CREATE INDEX
CREATE INDEX
CREATE INDEX
CREATE INDEX
CREATE FUNCTION
CREATE TRIGGER
COMMENT
COMMENT
COMMENT
```

### 2. Frontend 의존성 설치

```bash
cd frontend
npm install date-fns
```

---

## 🚀 서버 실행

### Option 1: 개별 실행

#### Backend API Gateway
```bash
cd sip-pbx
python -m src.api.main
```
서버 시작: http://localhost:8000
API Docs: http://localhost:8000/docs

#### Frontend
```bash
cd frontend
npm run dev
```
서버 시작: http://localhost:3000

#### SIP PBX (선택)
```bash
cd sip-pbx
python src/main.py
```

### Option 2: 통합 실행 (PowerShell)

```powershell
cd sip-pbx
.\start-all.ps1
```

---

## ✅ 기능 테스트

### 1. 운영자 상태 토글 테스트

1. Frontend 접속: http://localhost:3000/dashboard
2. 상단에 **운영자 상태 토글** 확인
3. 🟢 대기중 ↔ 🔴 부재중 전환 테스트
4. 브라우저 콘솔에서 API 호출 확인:
   ```
   PUT /api/operator/status
   ```

### 2. 부재중 모드 HITL 테스트

**시나리오:**
1. 운영자 상태를 **부재중**으로 설정
2. SIP 통화 시작 (착신자 부재)
3. AI가 자동 응답
4. AI 신뢰도 낮은 질문 발생 (HITL 트리거)
5. AI 응답: "죄송합니다. 확인 후 별도로 안내드리겠습니다."
6. 통화 종료

**확인 사항:**
- 운영자에게 실시간 알림이 **가지 않음** (부재중이므로)
- 미처리 HITL 요청이 DB에 저장됨

### 3. 미처리 HITL 관리 테스트

1. 운영자 상태를 **대기중**으로 전환
2. Dashboard에 **미처리 HITL 알림** 배지 표시 확인
3. "확인하기" 버튼 클릭 → 통화 이력 페이지 이동
4. **미처리 HITL** 탭에서 요청 목록 확인
5. 특정 통화 "상세 보기" 클릭
6. 통화 내용 확인 + 메모 작성
7. "후속 조치 필요" 체크 + "처리 완료" 클릭

**확인 사항:**
- 통화 이력 페이지: `/call-history?filter=unresolved`
- 미처리 요청 목록 표시
- 메모 저장 후 상태 변경 (unresolved → noted → resolved)

---

## 🔍 API 엔드포인트 테스트

### 운영자 상태 관리

**상태 조회:**
```bash
curl -X GET "http://localhost:8000/api/operator/status" \
  -H "Authorization: Bearer YOUR_TOKEN"
```

**상태 변경:**
```bash
curl -X PUT "http://localhost:8000/api/operator/status" \
  -H "Authorization: Bearer YOUR_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "status": "away",
    "away_message": "잠시 자리를 비웠습니다. 확인 후 연락드리겠습니다."
  }'
```

### 통화 이력 조회

**전체 통화 이력:**
```bash
curl -X GET "http://localhost:8000/api/call-history?page=1&limit=20" \
  -H "Authorization: Bearer YOUR_TOKEN"
```

**미처리 HITL 필터:**
```bash
curl -X GET "http://localhost:8000/api/call-history?unresolved_hitl=unresolved" \
  -H "Authorization: Bearer YOUR_TOKEN"
```

**통화 상세 조회:**
```bash
curl -X GET "http://localhost:8000/api/call-history/{call_id}" \
  -H "Authorization: Bearer YOUR_TOKEN"
```

**메모 추가:**
```bash
curl -X POST "http://localhost:8000/api/call-history/{call_id}/note" \
  -H "Authorization: Bearer YOUR_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "operator_note": "고객에게 회신 완료",
    "follow_up_required": true,
    "follow_up_phone": "010-1234-5678"
  }'
```

**처리 완료:**
```bash
curl -X PUT "http://localhost:8000/api/call-history/{call_id}/resolve" \
  -H "Authorization: Bearer YOUR_TOKEN"
```

---

## 📊 데이터베이스 확인

### 미처리 HITL 요청 확인

```sql
-- 전체 미처리 HITL 요청
SELECT * FROM unresolved_hitl_requests 
WHERE status = 'unresolved' 
ORDER BY timestamp DESC;

-- 상태별 집계
SELECT status, COUNT(*) as count 
FROM unresolved_hitl_requests 
GROUP BY status;

-- 최근 10개 요청
SELECT 
  request_id, 
  caller_id, 
  user_question, 
  ai_confidence, 
  status, 
  timestamp 
FROM unresolved_hitl_requests 
ORDER BY timestamp DESC 
LIMIT 10;
```

### 운영자 상태 확인 (Redis)

```bash
# Redis CLI 접속
redis-cli

# 운영자 상태 확인
GET operator:status
GET operator:away_message
GET operator:status_changed_at

# 미처리 HITL 큐 확인
LRANGE unresolved_hitl_queue 0 -1
```

---

## 🐛 문제 해결

### 1. Database 연결 오류

**증상:** `psycopg2.OperationalError: could not connect to server`

**해결:**
```bash
# PostgreSQL 실행 확인
sudo systemctl status postgresql

# PostgreSQL 시작
sudo systemctl start postgresql

# 연결 정보 확인
psql -U postgres -l
```

### 2. Migration 실패

**증상:** `ERROR: relation "unresolved_hitl_requests" already exists`

**해결:**
```sql
-- 기존 테이블 삭제 (데이터 손실 주의!)
DROP TABLE IF EXISTS unresolved_hitl_requests CASCADE;

-- Migration 재실행
\i migrations/001_create_unresolved_hitl_requests.sql
```

### 3. Frontend 빌드 오류

**증상:** `Module not found: Can't resolve 'date-fns'`

**해결:**
```bash
cd frontend
rm -rf node_modules package-lock.json
npm install
npm install date-fns
```

### 4. API 404 오류

**증상:** `404 Not Found` on `/api/operator/status`

**해결:**
1. Backend API 서버 실행 확인: http://localhost:8000/docs
2. 라우터 등록 확인: `src/api/main.py`
3. 서버 재시작

---

## 📝 로그 확인

### Backend 로그
```bash
# API Gateway 로그
tail -f logs/api.log

# HITL Service 로그
tail -f logs/hitl.log

# AI Orchestrator 로그
tail -f logs/orchestrator.log
```

### Frontend 로그
```bash
# 브라우저 개발자 도구 콘솔
# 또는 터미널에서 Next.js 로그 확인
```

---

## ✨ 성공 확인 체크리스트

- [ ] Database Migration 완료
- [ ] Backend API 서버 실행 (http://localhost:8000/docs)
- [ ] Frontend 서버 실행 (http://localhost:3000)
- [ ] Dashboard에 운영자 상태 토글 표시
- [ ] 부재중 모드 전환 가능
- [ ] 미처리 HITL 알림 배지 표시
- [ ] 통화 이력 페이지 접근 가능
- [ ] 미처리 HITL 필터 작동
- [ ] 통화 상세 조회 가능
- [ ] 메모 작성 및 저장 가능
- [ ] 처리 완료 기능 작동

---

**모든 체크리스트가 완료되면 운영자 부재중 모드가 정상 작동합니다!** 🎉

