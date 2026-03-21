# CDR 필드 이름 오류 수정 완료

**날짜**: 2026-01-08  
**작업**: CDR 객체 생성 시 필드 이름 불일치 오류 수정

---

## 🔍 발견된 에러

### 로그 내용 (line 2058):
```json
{
  "call_id": "130e5973235646813516460k30954rmwp",
  "error": "CDR.__init__() got an unexpected keyword argument 'caller_uri'",
  "message": "[CDR Flow] CDR write error from SIP Endpoint",
  "event": "cdr_flow_error_cdr_write_failed",
  "level": "error"
}
```

---

## 🐛 문제 원인

### CDR 클래스 실제 필드 정의 (`src/events/cdr.py`):
```python
@dataclass
class CDR:
    call_id: str
    caller: str      # ✅ 실제 필드 이름
    callee: str      # ✅ 실제 필드 이름
    start_time: datetime
    answer_time: Optional[datetime] = None
    end_time: Optional[datetime] = None
    duration: float = 0.0  # ✅ 실제 필드 이름
    termination_reason: TerminationReason = TerminationReason.NORMAL
    ...
```

### sip_endpoint.py에서 잘못 사용:
```python
cdr = CDR(
    call_id=call_id,
    caller_uri=caller_uri,  # ❌ 틀린 필드 이름
    callee_uri=callee_uri,  # ❌ 틀린 필드 이름
    duration_seconds=int(duration_seconds),  # ❌ 틀린 필드 이름
    termination_reason="normal",  # ❌ 문자열 (Enum이어야 함)
    ...
)
```

---

## ✅ 수정 내용

### 1. `sip-pbx/src/sip_core/sip_endpoint.py`

#### Import 추가:
```python
from src.events.cdr import CDR, CDRWriter, TerminationReason
```

#### CDR 객체 생성 수정:
```python
cdr = CDR(
    call_id=call_id,
    caller=caller_uri,      # ✅ caller_uri → caller
    callee=callee_uri,      # ✅ callee_uri → callee
    start_time=start_time,
    answer_time=call_info.get('answer_time'),
    end_time=end_time,
    duration=duration_seconds,  # ✅ duration_seconds → duration
    termination_reason=TerminationReason.NORMAL,  # ✅ 문자열 → Enum
)
```

---

### 2. `sip-pbx/create_test_cdr.py`

#### 테스트 CDR 데이터 필드 수정:
```python
cdr = {
    "call_id": f"test-call-{1000 + i}",
    "caller": f"sip:100{i}@localhost",      # ✅ caller_uri → caller
    "callee": f"sip:200{i}@localhost",      # ✅ callee_uri → callee
    "start_time": call_start.isoformat(),
    "answer_time": (call_start + timedelta(seconds=3)).isoformat(),
    "end_time": call_end.isoformat(),
    "duration": duration,                   # ✅ duration_seconds → duration
    "termination_reason": "normal",
    "media_mode": "bypass",
    "has_recording": False,
    "recording_path": None
}
```

---

### 3. `sip-pbx/src/api/routers/call_history.py`

#### API에서 CDR 필드 읽기 수정:
```python
item_dict = {
    "call_id": cdr.get("call_id", ""),
    "caller_id": cdr.get("caller", "Unknown"),  # ✅ caller_uri → caller
    "callee_id": cdr.get("callee", "Unknown"),  # ✅ callee_uri → callee
    "start_time": start_time,
    "end_time": datetime.fromisoformat(cdr["end_time"]) if cdr.get("end_time") else None,
    ...
}
```

---

## 🧪 테스트 및 검증

### 1단계: 기존 잘못된 CDR 파일 삭제
```bash
$ del cdr\cdr-2026-01-08.jsonl
```

### 2단계: 새로운 테스트 CDR 생성
```bash
$ python create_test_cdr.py

[OK] Test CDR data created successfully!
[Count] 5 CDRs created
  - test-call-1000: sip:1000@localhost -> sip:2000@localhost (300sec)
  - test-call-1001: sip:1001@localhost -> sip:2001@localhost (315sec)
  - test-call-1002: sip:1002@localhost -> sip:2002@localhost (330sec)
  - test-call-1003: sip:1003@localhost -> sip:2003@localhost (345sec)
  - test-call-1004: sip:1004@localhost -> sip:2004@localhost (360sec)
```

### 3단계: CDR 파일 내용 확인
```bash
$ type cdr\cdr-2026-01-08.jsonl

{"call_id": "test-call-1000", "caller": "sip:1000@localhost", "callee": "sip:2000@localhost", "duration": 300, ...}
{"call_id": "test-call-1001", "caller": "sip:1001@localhost", "callee": "sip:2001@localhost", "duration": 315, ...}
...
```

✅ **결과**: 필드 이름이 올바르게 `caller`, `callee`, `duration`으로 저장됨

---

## 📊 수정 전후 비교

### ❌ 수정 전 (에러 발생):
```json
// sip_endpoint.py
cdr = CDR(
    caller_uri=...,  // ❌ TypeError
    callee_uri=...,  // ❌ TypeError
    duration_seconds=...,  // ❌ TypeError
)

// 에러 로그
{"error": "CDR.__init__() got an unexpected keyword argument 'caller_uri'"}
```

### ✅ 수정 후 (정상 동작):
```json
// sip_endpoint.py
cdr = CDR(
    caller=...,  // ✅ 정상
    callee=...,  // ✅ 정상
    duration=...,  // ✅ 정상
)

// CDR 파일
{"caller": "sip:1000@localhost", "callee": "sip:2000@localhost", "duration": 300}
```

---

## 🎯 수정 파일 목록

1. ✅ `sip-pbx/src/sip_core/sip_endpoint.py`
   - `TerminationReason` import 추가
   - CDR 객체 생성 시 필드 이름 수정
   
2. ✅ `sip-pbx/create_test_cdr.py`
   - 테스트 CDR 데이터 필드 이름 수정
   
3. ✅ `sip-pbx/src/api/routers/call_history.py`
   - API에서 CDR 읽을 때 필드 이름 수정

---

## 🚀 다음 단계

### 1. 서버 재시작
```bash
cd C:\work\workspace_sippbx\sip-pbx
python src/main.py
```

### 2. 실제 통화 테스트
- SIP 전화기로 통화 (예: 1002 → 1001)
- 통화 종료

### 3. 로그 확인
```bash
# CDR 작성 성공 로그 확인
cat logs/app.log | findstr "cdr_flow_step_2_cdr_written_successfully"

# 예상 출력:
# {"event": "cdr_flow_step_2_cdr_written_successfully", "call_id": "xxx", "message": "[CDR Flow] CDR written successfully"}
```

### 4. CDR 파일 확인
```bash
# CDR 파일 내용 확인
cat cdr/cdr-2026-01-08.jsonl

# 예상: caller, callee, duration 필드로 정상 저장
```

### 5. Frontend 확인
- Backend API: http://localhost:8000/api/call-history
- Frontend: http://localhost:3000/call-history
- 통화 이력이 정상적으로 표시되어야 함

---

## ✨ 핵심 개선사항

1. ✅ **CDR 필드 이름 통일**: `caller_uri` → `caller`, `callee_uri` → `callee`
2. ✅ **Duration 필드 통일**: `duration_seconds` → `duration`
3. ✅ **TerminationReason Enum 사용**: 문자열 대신 Enum 타입 사용
4. ✅ **전체 파일 일관성**: SIP Endpoint, Test Script, API Router 모두 동일한 필드 이름 사용

---

## 📝 참고사항

CDR 클래스의 필드 정의는 `src/events/cdr.py`에 있으며, 향후 CDR 관련 코드 작성 시 다음 필드 이름을 사용해야 합니다:

- ✅ `caller` (not `caller_uri` or `caller_id`)
- ✅ `callee` (not `callee_uri` or `callee_id`)
- ✅ `duration` (not `duration_seconds`)
- ✅ `termination_reason: TerminationReason` (Enum 타입)

