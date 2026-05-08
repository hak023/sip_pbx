# 운영자 부재중 모드 - 빠른 시작 가이드 (Quick Start)

## 🚀 1분 만에 시작하기

### 자동 설정 스크립트 실행
```bash
cd sip-pbx
python scripts/setup_operator_away_mode.py
```

이 스크립트가 자동으로:
- ✅ 필수 도구 확인 (Python, Node, PostgreSQL)
- ✅ Database Migration 실행 (선택)
- ✅ Frontend 의존성 설치
- ✅ API 라우터 등록 확인

---

## 📦 수동 설정 (3단계)

### 1단계: Database Migration
```bash
psql -U postgres -d sip_pbx -f migrations/001_create_unresolved_hitl_requests.sql
```

### 2단계: Frontend 의존성 설치
```bash
cd frontend
npm install
```

### 3단계: 서버 실행

**Backend API:**
```bash
python -m src.api.main
```
→ http://localhost:8000

**Frontend:**
```bash
cd frontend
npm run dev
```
→ http://localhost:3000

---

## ✅ 기능 확인

### 1. Dashboard 접속
http://localhost:3000/dashboard

### 2. 운영자 상태 토글 확인
상단에 "🟢 대기중 ↔ 🔴 부재중" 토글 확인

### 3. 통화 이력 페이지 접속
http://localhost:3000/call-history

"미처리 HITL" 탭 확인

---

## 📚 자세한 문서

- 📄 [상세 실행 가이드](OPERATOR_AWAY_MODE_SETUP.md)
- 📄 [구현 완료 보고서](../reports/2026-01/IMPLEMENTATION_COMPLETE.md)
- 📄 [설계 문서](../design/OPERATOR-AWAY-MODE-DESIGN.md)

---

**문제 발생 시:** `docs/OPERATOR_AWAY_MODE_SETUP.md`의 "문제 해결" 섹션 참조

