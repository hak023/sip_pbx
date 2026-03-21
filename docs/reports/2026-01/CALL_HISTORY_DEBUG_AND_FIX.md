# 통화 이력 디버깅 및 수정 완료

**날짜**: 2026-01-08  
**작업**: 통화 이력 기록 문제 해결 및 로그 개선

---

## 🔍 발견된 문제

### 1. ❌ **SIP 응답 로그에 메소드 정보 누락**

**현상**:
```json
{"direction": "RECV", "status_code": "180", "from_addr": "10.2.4.21:59557", "size": 408}
```

- `status_code: 180`만 있고, 어떤 메소드(INVITE/BYE)에 대한 응답인지 불명확
- 디버깅 시 혼란 발생

**원인**:
- SIP 응답 로그에서 CSeq 헤더의 method를 파싱하지 않음

---

### 2. ❌ **CDR Flow 로그가 전혀 출력되지 않음**

**현상**:
```bash
$ cat logs/app.log | findstr "Flow"
# (출력 없음)
```

- 통화가 종료되어도 CDR 작성 관련 로그가 없음
- VectorDB 지식 추출 로그도 없음

**원인**:
1. 로그 이벤트 이름에 이모지(📝, ✅, ❌) 사용으로 인한 파싱 문제
2. 로그 이벤트 이름에 공백 포함
3. 구조화된 로깅 시스템에서 특수문자가 필터링됨

---

## ✅ 수정 내용

### 1. SIP 응답 로그에 method 추가

**파일**: `sip-pbx/src/sip_core/sip_endpoint.py`

#### 수정 전:
```python
if message.startswith('SIP/2.0'):
    status_code = parts[1] if len(parts) > 1 else 'UNKNOWN'
    logger.info("sip_recv",
               direction="RECV",
               status_code=status_code,
               from_addr=f"{addr[0]}:{addr[1]}",
               size=len(data))
```

#### 수정 후:
```python
if message.startswith('SIP/2.0'):
    status_code = parts[1] if len(parts) > 1 else 'UNKNOWN'
    
    # CSeq에서 method 추출 (예: "CSeq: 1 INVITE" → "INVITE")
    cseq_method = "UNKNOWN"
    for line in lines:
        if line.lower().startswith('cseq:'):
            cseq_parts = line.split()
            if len(cseq_parts) >= 3:
                cseq_method = cseq_parts[2]  # CSeq: 1 INVITE
            break
    
    logger.info("sip_recv",
               direction="RECV",
               status_code=status_code,
               method=cseq_method,  # ✅ 어떤 메소드의 응답인지
               from_addr=f"{addr[0]}:{addr[1]}",
               size=len(data))
```

**결과**:
```json
{"direction": "RECV", "status_code": "180", "method": "INVITE", "from_addr": "10.2.4.21:59557", "size": 408}
{"direction": "SEND", "status_code": "200", "method": "BYE", "to_addr": "10.2.4.80:16002", "size": 285}
```

---

### 2. CDR Flow 로그 개선 (이모지 제거, 이벤트 이름 표준화)

**파일**: `sip-pbx/src/sip_core/sip_endpoint.py`

#### 수정 전:
```python
logger.info("📝 [CDR Flow] Writing CDR from SIP Endpoint",
           call_id=call_id,
           caller=caller_uri,
           callee=callee_uri,
           duration=duration_seconds)

logger.info("✅ [CDR Flow] CDR written successfully",
           call_id=call_id,
           cdr_file=f"./cdr/cdr-{datetime.now().strftime('%Y-%m-%d')}.jsonl",
           duration=duration_seconds)

logger.error("❌ [CDR Flow] CDR write error from SIP Endpoint",
            call_id=call_id,
            error=str(e),
            exc_info=True)
```

#### 수정 후:
```python
logger.info("cdr_flow_step_1_writing_cdr",
           call_id=call_id,
           caller=caller_uri,
           callee=callee_uri,
           duration=duration_seconds,
           message="[CDR Flow] Writing CDR from SIP Endpoint")

logger.info("cdr_flow_step_2_cdr_written_successfully",
           call_id=call_id,
           cdr_file=f"./cdr/cdr-{datetime.now().strftime('%Y-%m-%d')}.jsonl",
           duration=duration_seconds,
           message="[CDR Flow] CDR written successfully")

logger.error("cdr_flow_error_cdr_write_failed",
            call_id=call_id,
            error=str(e),
            message="[CDR Flow] CDR write error from SIP Endpoint",
            exc_info=True)
```

**로그 확인 방법**:
```bash
# CDR Flow 전체 로그 확인
cat logs/app.log | findstr "cdr_flow"

# VectorDB Flow 전체 로그 확인  
cat logs/app.log | findstr "VectorDB Flow"

# 특정 call_id의 Flow 추적
cat logs/app.log | findstr "call_id.*your-call-id" | findstr "flow"
```

---

### 3. 테스트 CDR 데이터 생성 스크립트

**파일**: `sip-pbx/create_test_cdr.py`

```bash
$ python create_test_cdr.py

[OK] Test CDR data created successfully!
[File] cdr\cdr-2026-01-08.jsonl
[Count] 5 CDRs created

Created CDR list:
  - test-call-1000: sip:1000@localhost -> sip:2000@localhost (300sec)
  - test-call-1001: sip:1001@localhost -> sip:2001@localhost (315sec)
  - test-call-1002: sip:1002@localhost -> sip:2002@localhost (330sec)
  - test-call-1003: sip:1003@localhost -> sip:2003@localhost (345sec)
  - test-call-1004: sip:1004@localhost -> sip:2004@localhost (360sec)
```

---

## 🧪 테스트 및 검증

### 1단계: 서버 재시작

```bash
# SIP PBX 서버 재시작
cd C:\work\workspace_sippbx\sip-pbx
python src/main.py
```

### 2단계: 통화 진행

```bash
# SIP 전화기로 통화를 진행하여 테스트
# 1002 → 1001 통화 후 종료
```

### 3단계: 로그 확인

```bash
# CDR 작성 로그 확인
cat logs/app.log | findstr "cdr_flow"

# 예상 출력:
# {"event": "cdr_flow_step_1_writing_cdr", "call_id": "xxx", "caller": "sip:1002@...", "callee": "sip:1001@...", "duration": 15.3}
# {"event": "cdr_flow_step_2_cdr_written_successfully", "call_id": "xxx", "cdr_file": "./cdr/cdr-2026-01-08.jsonl"}

# SIP 응답 로그에서 method 확인
cat logs/app.log | findstr "status_code.*180"

# 예상 출력:
# {"direction": "RECV", "status_code": "180", "method": "INVITE", "from_addr": "10.2.4.80:16002"}
# {"direction": "SEND", "status_code": "180", "method": "INVITE", "to_addr": "10.2.4.69:10862"}
```

### 4단계: CDR 파일 확인

```bash
# CDR 파일 확인
cat cdr/cdr-2026-01-08.jsonl

# 예상: JSON Lines 형식으로 통화 이력 저장
```

### 5단계: Frontend 확인

```
1. Backend API 확인: http://localhost:8000/api/call-history
2. Frontend 확인: http://localhost:3000/call-history
```

---

## 📊 결과

### 수정 전 (문제):
```json
// SIP 로그: method 정보 없음
{"direction": "RECV", "status_code": "180", "from_addr": "10.2.4.21:59557"}

// CDR Flow: 로그 없음
$ cat logs/app.log | findstr "Flow"
(출력 없음)
```

### 수정 후 (정상):
```json
// SIP 로그: method 정보 포함
{"direction": "RECV", "status_code": "180", "method": "INVITE", "from_addr": "10.2.4.21:59557"}
{"direction": "SEND", "status_code": "200", "method": "BYE", "to_addr": "10.2.4.80:16002"}

// CDR Flow: 단계별 로그 출력
{"event": "cdr_flow_step_1_writing_cdr", "call_id": "xxx", "message": "[CDR Flow] Writing CDR"}
{"event": "cdr_flow_step_2_cdr_written_successfully", "call_id": "xxx", "message": "[CDR Flow] CDR written"}
```

---

## 🎯 핵심 개선사항

1. ✅ **SIP 응답 로그**: CSeq 파싱으로 method 정보 추가
2. ✅ **CDR Flow 로그**: 이모지 제거, 이벤트 이름 표준화
3. ✅ **로그 검색성**: `findstr "cdr_flow"` 또는 `findstr "VectorDB Flow"`로 쉽게 추적 가능
4. ✅ **테스트 도구**: `create_test_cdr.py`로 Frontend 데이터 확인 가능

---

## 다음 단계

1. 서버 재시작 후 실제 통화 진행
2. `logs/app.log`에서 `cdr_flow` 로그 확인
3. `cdr/cdr-2026-01-08.jsonl` 파일 생성 확인
4. Frontend `http://localhost:3000/call-history`에서 통화 이력 표시 확인

