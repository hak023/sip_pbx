# AI 응대 모드 (AI Attendant Mode)

## 📖 개요

착신자가 부재중일 때 AI Voicebot이 자동으로 응답하는 기능입니다.

---

## 🎯 활성화 조건

### **방법 1: 타이머 기반 (자동)**

착신자가 일정 시간 내에 응답하지 않으면 AI가 자동으로 응답합니다.

**설정 파일:** `config/config.yaml`

```yaml
sip:
  timers:
    no_answer_timeout: 10  # 초 (기본값: 10초)
```

**동작 방식:**
1. 발신자 → 착신자 INVITE 전송
2. 착신자 단말로 INVITE 전달
3. **10초 동안 응답 없음** (180 Ringing은 받을 수 있음)
4. 200 OK 수신 전에 타임아웃
5. **AI Voicebot 자동 활성화**

---

### **방법 2: 수동 부재중 설정 (웹 API)**

웹/앱에서 사용자가 직접 "부재중" 상태로 변경하면 즉시 AI가 응답합니다.

#### **API 엔드포인트**

**부재중 설정 (AWAY):**

```http
PUT /api/operator/status
Content-Type: application/json
Authorization: Bearer {JWT_TOKEN}

{
  "status": "away",
  "away_message": "회의 중입니다. AI 비서가 도와드리겠습니다."
}
```

**부재중 해제 (AVAILABLE):**

```http
PUT /api/operator/status
Content-Type: application/json
Authorization: Bearer {JWT_TOKEN}

{
  "status": "available"
}
```

**현재 상태 조회:**

```http
GET /api/operator/status
Authorization: Bearer {JWT_TOKEN}
```

#### **cURL 예제**

```bash
# 부재중 설정
curl -X PUT http://localhost:8000/api/operator/status \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer YOUR_JWT_TOKEN" \
  -d '{
    "status": "away",
    "away_message": "현재 자리를 비웠습니다. AI 비서가 도와드리겠습니다."
  }'

# 부재중 해제
curl -X PUT http://localhost:8000/api/operator/status \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer YOUR_JWT_TOKEN" \
  -d '{
    "status": "available"
  }'
```

#### **Python 예제**

```python
import requests

API_BASE = "http://localhost:8000"
JWT_TOKEN = "your_jwt_token_here"

# 부재중 설정
response = requests.put(
    f"{API_BASE}/api/operator/status",
    headers={
        "Authorization": f"Bearer {JWT_TOKEN}",
        "Content-Type": "application/json"
    },
    json={
        "status": "away",
        "away_message": "회의 중입니다. AI 비서가 도와드리겠습니다."
    }
)
print(response.json())
```

**동작 방식:**
1. 웹/앱에서 "부재중" 버튼 클릭
2. `/api/operator/status` API 호출
3. SIP PBX 서버에 상태 동기화
4. 이후 들어오는 **모든 수신 통화를 AI가 즉시 응답**

---

## 📊 상태 종류

| 상태 | 값 | 설명 |
|------|---|------|
| 🟢 **근무 중** | `available` | 정상 통화 (기본값) |
| 🔴 **부재중** | `away` | AI 자동 응답 모드 |
| 🟡 **통화 중** | `busy` | 통화 중 (향후 구현) |
| ⚫ **오프라인** | `offline` | 미등록 상태 |

---

## 🔍 로그 확인

### **타이머 기반 활성화 로그**

```json
{"event": "no_answer_timer_started", "call_id": "...", "timeout": 10}
{"event": "no_answer_timeout_activating_ai", "callee": "1004"}
{"event": "ai_mode_activated", "call_id": "...", "callee": "1004"}
```

### **수동 부재중 설정 로그**

```json
{"event": "operator_status_updated", "user_id": "1004", "status": "away"}
{"event": "SIP PBX status synced", "user_id": "1004"}
{"event": "callee_is_away_activating_ai", "callee": "1004"}
{"event": "ai_mode_activated_by_away_status", "callee": "1004"}
```

---

## 🧪 테스트 방법

### **Test 1: 타이머 기반**

1. `config/config.yaml`에서 `no_answer_timeout: 10` 확인
2. 서버 재시작
3. 발신 전화 걸기
4. **착신 전화를 받지 않고 10초 대기**
5. 콘솔에 `⏰ No Answer Timeout!` 메시지 확인

### **Test 2: 수동 부재중**

1. Backend API 서버 실행 (`http://localhost:8000`)
2. 부재중 설정 API 호출:
   ```bash
   curl -X PUT http://localhost:8000/api/operator/status \
     -H "Content-Type: application/json" \
     -d '{"status": "away"}'
   ```
3. 발신 전화 걸기
4. 콘솔에 `🔴 Callee is AWAY` 메시지 확인

---

## ⚠️ 주의사항

1. **현재 제한사항:**
   - AI Orchestrator가 `None`이므로 실제 AI 응답은 아직 구현되지 않음
   - 로그만 출력되고 일반 호 처리 계속 진행

2. **향후 구현 필요:**
   - AI Orchestrator 초기화
   - AI 모드일 때 착신자 단말로 INVITE 전송하지 않기
   - AI → 발신자 직접 응답 처리

3. **부재중 상태 관리:**
   - 현재 인메모리 방식 (서버 재시작 시 초기화)
   - 향후 Redis로 영구 저장 권장

---

## 🔗 관련 파일

- `src/sip_core/sip_endpoint.py` - 타이머 시작/취소, 부재중 체크
- `src/sip_core/call_manager.py` - AI 모드 전환 핸들러
- `src/sip_core/operator_status.py` - 부재중 상태 관리
- `src/api/routers/operator.py` - 부재중 설정 API
- `config/config.yaml` - no_answer_timeout 설정

---

## 📞 지원

문제가 발생하면 `logs/app.log`를 확인하세요:

```bash
# AI 응대 관련 로그 필터링
grep "no_answer\|away\|ai_mode" logs/app.log
```
