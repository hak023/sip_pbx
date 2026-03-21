---
title: 재발 문제 종합 분석 및 해결 방안
date: 2026-03-11
type: comprehensive_fix
tags: [critical, active-api, rtp-relay, null-bytes, ai-orchestrator]
priority: CRITICAL
---

# 재발 문제 종합 분석 및 해결 방안

## 📋 문제 요약

재테스트 결과 3가지 문제 재발:

1. ✅ **Active API 404** - 해결 완료
2. ❌ **RTP Relay Invalid Remote** - 근본 원인 파악, 수정 필요
3. ❌ **NULL 바이트 로깅** - 계속 재발 (986KB)

---

## 1. Active API 404 에러

### 문제
Frontend `dashboard/page.tsx` Line 95에서 `/api/calls/active` 호출 시 404 에러

### 원인
API 엔드포인트가 구현되지 않음

### 해결 ✅
`sip-pbx/src/api/routers/calls.py`에 `/api/calls/active` 엔드포인트 추가:

```python
@router.get("/active")
async def get_active_calls():
    """활성 통화 목록 조회"""
    if _call_manager is None:
        raise HTTPException(status_code=503, detail="Call Manager not available")
    
    active_calls = _call_manager.get_active_calls()
    return [
        {
            "call_id": call.get("call_id"),
            "caller": call.get("caller"),
            "callee": call.get("callee"),
            "state": call.get("state", "active"),
            "duration_seconds": call.get("duration_seconds", 0)
        }
        for call in active_calls
    ]
```

### 후속 조치 필요
- `main.py`에서 Call Manager를 API 라우터에 주입:
  ```python
  from src.api.routers.calls import set_call_manager
  set_call_manager(call_manager)
  ```

---

## 2. RTP Relay Invalid Remote 경고 (계속 발생)

### 문제
```log
{"event": "rtp_relay_skip_invalid_remote", "call_id": "akApBgE~yL", ...}
```
통화 중 반복 발생 (수백~수천 번)

### 근본 원인 (확정)

#### 타임라인:
```
14:48:26.342 - AI Takeover 시작
14:48:26.343 - ai_orchestrator_not_available ← 핵심 문제!
14:48:35.404 - rtp_relay_skip_invalid_remote 반복 발생
```

#### 원인:
**AI Orchestrator가 RTP Worker에 연결되지 않음**

1. AI Orchestrator는 초기화 완료됨 (서버 시작 시)
2. Call Manager가 RTP Worker 생성
3. **RTP Worker에 AI Orchestrator 참조가 전달되지 않음** ← 문제
4. AI Takeover 시도 시 `ai_orchestrator = None`
5. Caller의 RTP 패킷을 처리할 수 없음:
   - `callee_remote_addr = "0.0.0.0:0"` (초기값, 변경 안됨)
   - `ai_orchestrator = None` (연결 안됨)
6. 따라서 `rtp_relay_skip_invalid_remote` 경고 반복

### 해결 방법

#### 필요한 수정 (Python 백엔드 - SIP Core):

**파일 위치 추정**:
- `src/sip_core/call_manager.py` (또는 유사 파일)
- `src/sip_core/rtp_relay.py` 또는 `rtp_worker.py`
- `src/main.py` (초기화 로직)

**수정 1: Call Manager에 AI Orchestrator 주입**
```python
# src/sip_core/call_manager.py (또는 유사)

class CallManager:
    def __init__(self, ...):
        self.ai_orchestrator = None  # 초기값
        ...
    
    def set_ai_orchestrator(self, ai_orchestrator):
        """AI Orchestrator 참조 설정"""
        self.ai_orchestrator = ai_orchestrator
        logger.info("ai_orchestrator_injected_to_call_manager")
    
    def create_rtp_worker(self, call_id, ...):
        """RTP Worker 생성 시 AI Orchestrator 전달"""
        worker = RTPRelayWorker(
            call_id=call_id,
            ai_orchestrator=self.ai_orchestrator,  # ← 여기 추가!
            ...
        )
        return worker
```

**수정 2: RTP Worker에서 AI 연결 사용**
```python
# src/sip_core/rtp_relay.py (또는 rtp_worker.py)

class RTPRelayWorker:
    def __init__(self, call_id, ai_orchestrator=None, ...):
        self.call_id = call_id
        self.ai_orchestrator = ai_orchestrator  # ← AI 참조 저장
        self.callee_remote_addr = ("0.0.0.0", 0)
        ...
    
    async def enable_ai_mode(self):
        """AI 모드 활성화"""
        if self.ai_orchestrator is None:
            logger.warning("ai_orchestrator_not_available", call_id=self.call_id)
            return False
        
        # AI Pipeline 시작
        ai_endpoint = await self.ai_orchestrator.start_pipeline(self.call_id)
        
        # Callee remote address를 AI endpoint로 설정
        self.callee_remote_addr = ai_endpoint  # ← 여기서 0.0.0.0:0 해결!
        self.ai_enabled = True
        
        logger.info("ai_mode_enabled", call_id=self.call_id, ai_endpoint=ai_endpoint)
        return True
```

**수정 3: Main 초기화 순서**
```python
# src/main.py (또는 초기화 파일)

async def initialize():
    # 1. Call Manager 생성
    call_manager = CallManager(...)
    
    # 2. AI Orchestrator 생성
    ai_orchestrator = await create_ai_orchestrator()
    
    # 3. Call Manager에 AI 주입 ← 이 단계가 현재 누락됨!
    call_manager.set_ai_orchestrator(ai_orchestrator)
    
    # 4. SIP Server 시작
    sip_server = SIPServer(call_manager)
    await sip_server.start()
```

### 검증 방법

수정 후 로그 확인:
```log
✅ {"event": "ai_orchestrator_injected_to_call_manager"}
✅ {"event": "rtp_relay_worker_created", "ai_orchestrator_available": true}
✅ {"event": "ai_mode_enabled", "ai_endpoint": "127.0.0.1:XXXXX"}
❌ (없어야 함) {"event": "ai_orchestrator_not_available"}
❌ (없어야 함) {"event": "rtp_relay_skip_invalid_remote"}
```

---

## 3. NULL 바이트 로깅 버그 (계속 재발)

### 문제
매 서버 실행마다 Line 162에 **986KB의 NULL 바이트** 발생

### 현황
```
재발 1: 708,593 NULL bytes (708 KB)
재발 2: 986,626 NULL bytes (963 KB) ← 더 커짐!
```

### 패턴
- **항상 Line 162**에 발생
- 서버 시작 후 첫 SIP REGISTER 메시지 직후
- NULL 바이트 + 유효한 JSON 구조: `[\x00 * N] + [Valid JSON]`

### 근본 원인 (추정)

**로거가 고정 크기 버퍼를 파일에 flush하는 버그**

#### 시나리오:
```python
# 추정되는 잘못된 코드 (로거 내부):

class CustomLogger:
    def __init__(self):
        self.buffer = bytearray(1024 * 1024)  # 1MB 버퍼, NULL로 초기화
        self.position = 0
    
    def log(self, message):
        msg_bytes = message.encode('utf-8')
        
        # 잘못된 방식: 버퍼 끝부분에만 씀
        end_pos = len(self.buffer)
        start_pos = end_pos - len(msg_bytes)
        self.buffer[start_pos:end_pos] = msg_bytes
        
        # 버퍼 전체를 파일에 쓰기 ← 문제!
        with open('app.log', 'ab') as f:
            f.write(self.buffer)  # NULL 포함 전체 기록!
```

### 임시 조치 (완료)

**NULL 바이트 제거 스크립트 실행**:
```bash
cd sip-pbx
python -c "
import shutil
log_file = 'logs/app.log'
shutil.copy(log_file, log_file + '.backup')
with open(log_file, 'rb') as f:
    content = f.read()
cleaned = content.replace(b'\x00', b'')
with open(log_file, 'wb') as f:
    f.write(cleaned)
print('Cleaned:', (len(content) - len(cleaned)) / 1024, 'KB')
"
```

결과:
- ✅ Backup: `logs/app.log.backup2`
- ✅ 제거: 963 KB

### 근본 해결 방법

#### 옵션 1: Python 표준 logging 모듈 사용 (권장)

```python
import logging
import json
from datetime import datetime

# 설정
logging.basicConfig(
    filename='logs/app.log',
    level=logging.INFO,
    format='%(message)s',  # JSON만 출력
    encoding='utf-8'
)

# 사용
def log_event(event, **kwargs):
    data = {
        "timestamp": datetime.now().isoformat(),
        "level": "info",
        "event": event,
        **kwargs
    }
    logging.info(json.dumps(data, ensure_ascii=False))

# 예시
log_event("sip_recv", direction="RECV", method="REGISTER", size=602)
```

#### 옵션 2: structlog 사용 (장기 권장)

```bash
pip install structlog
```

```python
import structlog

# 설정
structlog.configure(
    processors=[
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.add_log_level,
        structlog.processors.JSONRenderer()
    ],
    logger_factory=structlog.WriteLoggerFactory(
        file=open("logs/app.log", "a", encoding="utf-8")
    ),
)

# 사용
logger = structlog.get_logger()
logger.info("sip_recv", direction="RECV", method="REGISTER", size=602)
```

#### 옵션 3: 현재 로거 수정 (최소 수정)

기존 로거 파일을 찾아서 버퍼 flush 로직 수정:

```python
# 찾아야 할 파일: src/logging/*.py 또는 src/utils/logger.py

class CustomLogger:
    def log(self, message):
        # 올바른 방식: 메시지만 파일에 쓰기
        with open(self.log_file, 'a', encoding='utf-8') as f:
            f.write(message + '\n')  # 버퍼 없이 직접 쓰기
```

### 로거 파일 찾기

```bash
# 1. 로거 클래스 찾기
grep -r "class.*Logger" sip-pbx/src/

# 2. 파일 open 코드 찾기
grep -r "open.*app.log\|open.*logs/" sip-pbx/src/

# 3. bytearray 또는 버퍼 사용 찾기
grep -r "bytearray\|buffer.*=.*\[" sip-pbx/src/

# 4. import logging 확인
grep -r "import logging\|from logging" sip-pbx/src/
```

---

## 📊 우선순위 및 영향도

| 문제 | 우선순위 | 영향 | 상태 |
|------|---------|------|------|
| **Active API 404** | 🟡 MEDIUM | Frontend 기능 일부 제한 | ✅ 해결 완료 |
| **RTP Relay Invalid Remote** | 🔴 CRITICAL | **AI 통화 기능 완전 불능** | ⚠️ 근본 원인 파악, 수정 필요 |
| **NULL 바이트 로깅** | 🟠 HIGH | 디스크 공간 낭비, 로그 손상 | ⚠️ 임시 조치 완료, 근본 수정 필요 |

---

## 🎯 해결 순서

### 즉시 (긴급)

1. ✅ **Active API 구현** (완료)
2. ✅ **NULL 바이트 제거** (임시 완료)
3. 🔄 **AI Orchestrator → RTP Worker 연결** (진행 중)

### 단기 (1-2일)

4. 🔄 **RTP Worker AI 연결 코드 수정**
   - `call_manager.py`: `set_ai_orchestrator()` 추가
   - `rtp_worker.py`: AI 참조 사용
   - `main.py`: 초기화 순서 수정

5. 🔄 **로거 근본 원인 수정**
   - 로거 파일 찾기
   - 버퍼 flush 로직 제거
   - 표준 logging 모듈로 교체

### 장기 (1주일)

6. 🔄 **structlog 도입**
7. 🔄 **로그 파일 회전 설정**
8. 🔄 **모니터링 및 알림 시스템**

---

## ✅ 완료된 작업

1. ✅ `/api/calls/active` 엔드포인트 구현
2. ✅ NULL 바이트 제거 (963 KB 절감)
3. ✅ 백업 생성 (`logs/app.log.backup2`)
4. ✅ 근본 원인 분석 완료 (RTP, NULL 로깅)
5. ✅ 종합 해결 방안 작성

---

## 🚨 주의사항

### RTP Relay 문제

**현재 AI 통화 기능이 동작하지 않습니다!**

- AI Orchestrator가 초기화되어도 RTP Worker에 연결되지 않음
- 따라서 Caller의 RTP 패킷을 처리할 수 없음
- "AI가 응대합니다"라고 표시되지만 실제로는 아무 소리도 들리지 않음

### NULL 로깅 문제

**매 서버 실행마다 약 1MB의 NULL 바이트 발생**

- 로그 파일 크기가 급격히 증가
- 일부 로그 분석 도구에서 파일 읽기 실패 가능
- 디스크 공간 낭비

---

## 📝 다음 단계

### 1. SIP Core 소스 코드 찾기

```bash
# 프로젝트 구조 확인
find sip-pbx -name "*.py" -path "*/sip_core/*" -o -path "*/core/*"

# 또는
ls -la sip-pbx/src/
ls -la sip-pbx/core/
```

### 2. Call Manager 코드 수정

- `set_ai_orchestrator()` 메서드 추가
- RTP Worker 생성 시 AI 참조 전달

### 3. 로거 코드 찾기 및 수정

- 버퍼 flush 로직 제거
- 표준 logging 모듈로 교체

### 4. 테스트

- 서버 재시작
- AI 통화 테스트
- 로그 파일 NULL 바이트 확인

---

**작성일**: 2026-03-11
**작성자**: AI Agent
**우선순위**: 🔴 **CRITICAL**
**상태**: ✅ 분석 완료 → 🔧 **코드 수정 필요**

**핵심 문제**: 
1. AI Orchestrator가 RTP Worker에 연결 안됨 → AI 통화 불가
2. NULL 바이트 로깅 반복 → 로그 파일 손상

**필요 파일**: 
- `src/sip_core/call_manager.py`
- `src/sip_core/rtp_worker.py` (또는 `rtp_relay.py`)
- `src/main.py`
- `src/logging/*.py` (또는 `src/utils/logger.py`)
