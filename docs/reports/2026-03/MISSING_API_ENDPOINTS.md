---
title: 누락된 API 엔드포인트 구현
date: 2026-03-11
type: api_implementation
tags: [api, 404, metrics, operator, follow-ups]
---

# 누락된 API 엔드포인트 구현

## 📋 발견된 404 에러

Frontend에서 호출하지만 구현되지 않은 API들:

1. `GET /api/metrics/dashboard?owner=1004` - 404
2. `GET /api/operator/status` - 404
3. `GET /api/call-history/follow-ups?callee=1004` - 404

## ✅ 구현 완료

### 1. Metrics API (`metrics.py`)

```python
GET /api/metrics/dashboard?owner={tenant_id}
```

**응답**:
```json
{
  "hitl_queue_size": 0,
  "avg_ai_confidence": 0.85,
  "today_calls_count": 10,
  "avg_response_time": 2.5,
  "knowledge_base_size": 100
}
```

**상태**: 더미 데이터 반환 (실제 메트릭 수집 로직은 TODO)

### 2. Operator API (`operator.py`)

```python
GET /api/operator/status?tenant_id={tenant_id}
POST /api/operator/status
```

**GET 응답**:
```json
{
  "available": true,
  "tenant_id": "1004"
}
```

**POST 요청**:
```json
{
  "available": true,
  "tenant_id": "1004"
}
```

**상태**: 인메모리 상태 저장 (실제로는 DB 연동 필요)

### 3. Follow-ups API (`call_history.py`)

```python
GET /api/call-history/follow-ups?callee={tenant_id}&status={status}
PATCH /api/call-history/follow-ups/{id}
```

**GET 응답**:
```json
{
  "items": [
    {
      "id": "...",
      "call_id": "...",
      "user_question": "...",
      "ai_response": "...",
      "status": "pending",
      "operator_note": null,
      "created_at": "..."
    }
  ],
  "total": 0
}
```

**PATCH 요청**:
```json
{
  "status": "noted",
  "operator_note": "확인함"
}
```

**상태**: 인메모리 저장소 (실제로는 DB 연동 필요)

## 📂 생성된 파일

```
✅ sip-pbx/src/api/routers/metrics.py - Metrics API
✅ sip-pbx/src/api/routers/operator.py - Operator API
✅ sip-pbx/src/api/routers/call_history.py - Follow-ups 추가
✅ sip-pbx/src/api/main.py - 라우터 등록
```

## 🔄 적용 방법

API 서버 재시작:

```bash
cd sip-pbx
uvicorn src.api.main:app --reload --host 0.0.0.0 --port 8000
```

## ✅ 검증

```bash
# Metrics API
curl http://localhost:8000/api/metrics/dashboard?owner=1004

# Operator API
curl http://localhost:8000/api/operator/status?tenant_id=1004

# Follow-ups API
curl http://localhost:8000/api/call-history/follow-ups?callee=1004
```

## 📝 TODO

1. **Metrics API**: 실제 메트릭 수집 로직 구현
   - CallManager에서 통화 통계 수집
   - AI Confidence 추적
   - Knowledge Base 크기 조회

2. **Operator API**: DB 연동
   - Redis 또는 PostgreSQL에 상태 저장
   - WebSocket으로 실시간 상태 전파

3. **Follow-ups API**: DB 연동
   - AI 응답 시 "모르는 내용" 감지
   - DB에 저장
   - 후처리 상태 추적

---

**작성일**: 2026-03-11
**상태**: ✅ **기본 구현 완료** (DB 연동은 TODO)
