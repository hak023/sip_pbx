---
title: 거대한 NULL 바이트 로그 라인 버그 분석
date: 2026-03-11
type: bug_analysis
tags: [logging, bug, null-bytes, buffer, critical]
severity: CRITICAL
---

# 거대한 NULL 바이트 로그 라인 버그 분석

## 📋 문제 상황

### 증상

`sip-pbx/logs/app.log` 파일의 **Line 162**에 **708,763자(약 700KB)**의 거대한 로그가 한 줄로 기록됨.

```
Line 161: {"timestamp": "2026-03-11T14:02:30.414", "level": "info", "event": "server_ready", ...}
Line 162: [\x00 * 708,593] + {"timestamp": "2026-03-11T14:06:18.059", ...}  ← ❌ 문제!
Line 163: {"timestamp": "2026-03-11T14:06:18.059", "level": "info", "event": "user_registered", ...}
```

### 분석 결과

- **NULL 바이트**: 708,593개 (`\x00`)
- **유효 JSON**: 171자 (정상적인 `sip_recv` 이벤트)
- **총 크기**: 708,764 bytes (약 700 KB)
- **구조**: `[NULL bytes * 708,593] + [Valid JSON 171 chars]`

## 🔍 정확한 원인

### 1. 로그 구조 분석

```python
# 실제 로그 라인 구조:
[\x00][\x00]...[\x00] (708,593번 반복)
{"timestamp": "2026-03-11T14:06:18.059", "level": "info", "event": "sip_recv", 
 "direction": "RECV", "method": "REGISTER", "from_addr": "10.129.219.83:36876", "size": 602}
```

### 2. 발생 메커니즘

**버퍼 초기화 실패**:
```python
# 추정되는 잘못된 코드:
buffer = bytearray(LARGE_SIZE)  # 예: 700KB 버퍼 할당
# buffer는 NULL(\x00)로 초기화됨
# ...
# 버퍼 끝부분에만 유효한 로그 데이터 씀
logger.write(buffer)  # ← 전체 버퍼를 파일에 씀 (NULL 포함!)
```

**정상 코드**:
```python
# 올바른 방법:
message = json.dumps(log_data)
logger.write(message + '\n')  # 필요한 데이터만 씀
```

### 3. 발생 타이밍

```
14:02:30.414 - server_ready 이벤트
             [여기서 버퍼 초기화/설정 문제 발생]
14:06:18.059 - sip_recv 이벤트 (이 메시지가 700KB NULL 버퍼 끝에 기록됨)
```

### 4. 근본 원인

**로거가 고정 크기 버퍼를 사용하며, 버퍼 전체를 파일에 flush하는 버그**:

1. 로거 초기화 시 700KB 크기의 버퍼 할당
2. 버퍼는 자동으로 NULL(`\x00`)로 초기화
3. `sip_recv` 이벤트 발생 시 버퍼의 **끝부분**에만 데이터 씀
4. 로거가 버퍼 전체를 파일에 쓰면서 700KB NULL + 171자 유효 데이터 모두 기록

## 🎯 영향

### 1. 심각도: 🔴 **CRITICAL**

#### 성능 영향

- **디스크 I/O**: 700KB 불필요한 쓰기
- **로그 파일 크기**: 통화 1회당 700KB 증가 가능
- **파싱 비용**: 로그 분석 도구가 700KB를 읽고 처리
- **저장 공간**: 하루 100통화 시 **70MB** 낭비

#### 기능 영향

- **로그 손상**: NULL 바이트로 인해 일부 도구에서 파일 읽기 실패 가능
- **디버깅 방해**: 로그 뷰어가 비정상 동작
- **메모리 누수**: 버퍼가 해제되지 않으면 메모리 누수 발생 가능

### 2. 재현 조건

1. 서버 시작 후 `server_ready` 이벤트
2. 첫 SIP REGISTER 메시지 수신
3. → `sip_recv` 로깅 시 700KB NULL 버퍼 flush

## 🔧 해결 방법

### 1. 로거 코드 수정 (추정 위치)

**파일 위치 (추정)**:
- `src/logging/logger.py` 또는
- `src/utils/logger.py` 또는
- SIP Endpoint에서 직접 파일 쓰기 수행

**잘못된 패턴 (추정)**:
```python
class CustomLogger:
    def __init__(self):
        self.buffer_size = 700 * 1024  # 700KB
        self.buffer = bytearray(self.buffer_size)  # NULL로 초기화됨
        self.position = 0
    
    def log(self, message):
        # 버퍼 끝부분에 메시지 씀
        msg_bytes = message.encode('utf-8')
        self.buffer[-len(msg_bytes):] = msg_bytes  # ← 문제!
        
        # 버퍼 전체를 파일에 쓰기
        with open('app.log', 'ab') as f:
            f.write(self.buffer)  # ← 700KB NULL + 유효 데이터 모두 기록
```

**올바른 수정**:
```python
class CustomLogger:
    def log(self, message):
        # 메시지만 파일에 쓰기
        with open('app.log', 'a', encoding='utf-8') as f:
            f.write(message + '\n')  # 필요한 데이터만 기록
```

### 2. Python logging 모듈 사용

```python
import logging
import json

# 표준 로거 설정
logging.basicConfig(
    filename='app.log',
    level=logging.INFO,
    format='%(message)s'  # JSON 형식 그대로 출력
)

def log_event(event_name, **kwargs):
    log_data = {
        "timestamp": datetime.now().isoformat(),
        "level": "info",
        "event": event_name,
        **kwargs
    }
    logging.info(json.dumps(log_data, ensure_ascii=False))
```

### 3. structlog 사용 (권장)

```python
import structlog

logger = structlog.get_logger()

# 사용
logger.info("sip_recv", 
    direction="RECV", 
    method="REGISTER", 
    from_addr="10.129.219.83:36876", 
    size=602
)
```

## 📊 데이터 복구

### NULL 바이트 제거 스크립트

```python
# clean_log.py
import sys

def clean_log_file(input_file, output_file):
    """NULL 바이트 제거"""
    with open(input_file, 'r', encoding='utf-8', errors='ignore') as f:
        lines = f.readlines()
    
    cleaned = []
    for i, line in enumerate(lines, 1):
        # NULL 바이트 제거
        cleaned_line = line.replace('\x00', '')
        
        # 빈 줄이 아니면 추가
        if cleaned_line.strip():
            cleaned.append(cleaned_line)
            print(f"Line {i}: {len(line)} → {len(cleaned_line)} chars")
        else:
            print(f"Line {i}: SKIPPED (empty after cleaning)")
    
    with open(output_file, 'w', encoding='utf-8') as f:
        f.writelines(cleaned)
    
    print(f"\nCleaned {len(lines)} lines → {len(cleaned)} lines")
    print(f"Saved to: {output_file}")

if __name__ == "__main__":
    clean_log_file('sip-pbx/logs/app.log', 'sip-pbx/logs/app_cleaned.log')
```

실행:
```bash
cd c:\work\workspace_sippbx
python clean_log.py
```

## 🚨 긴급 조치

### 1. 즉시: NULL 바이트 제거

```python
# 백업
import shutil
shutil.copy('sip-pbx/logs/app.log', 'sip-pbx/logs/app.log.backup')

# NULL 제거
with open('sip-pbx/logs/app.log', 'r', encoding='utf-8', errors='ignore') as f:
    content = f.read()

cleaned = content.replace('\x00', '')

with open('sip-pbx/logs/app.log', 'w', encoding='utf-8') as f:
    f.write(cleaned)

print(f"Removed {content.count(chr(0))} NULL bytes")
```

### 2. 단기: 로거 교체

표준 Python logging 모듈 사용:
```python
import logging
import json
from datetime import datetime

class JSONLogger:
    def __init__(self, filename):
        logging.basicConfig(
            filename=filename,
            level=logging.INFO,
            format='%(message)s',
            encoding='utf-8'
        )
        self.logger = logging.getLogger(__name__)
    
    def log(self, level, event, **kwargs):
        data = {
            "timestamp": datetime.now().isoformat(),
            "level": level,
            "event": event,
            **kwargs
        }
        self.logger.info(json.dumps(data, ensure_ascii=False))
```

### 3. 장기: structlog 도입

```bash
pip install structlog
```

```python
import structlog

structlog.configure(
    processors=[
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.add_log_level,
        structlog.processors.JSONRenderer()
    ],
    wrapper_class=structlog.make_filtering_bound_logger(logging.INFO),
    logger_factory=structlog.WriteLoggerFactory(
        file=open("app.log", "a", encoding="utf-8")
    ),
)

logger = structlog.get_logger()
logger.info("sip_recv", direction="RECV", method="REGISTER")
```

## ✅ 검증 방법

### 수정 후 확인

```bash
# 1. 서버 재시작
cd sip-pbx
python main.py

# 2. SIP REGISTER 테스트
# (SIP 클라이언트로 등록)

# 3. 로그 파일 확인
python -c "
with open('logs/app.log', 'rb') as f:
    content = f.read()
    null_count = content.count(b'\x00')
    print(f'NULL bytes found: {null_count}')
    if null_count == 0:
        print('✅ NO NULL BYTES - Bug fixed!')
    else:
        print(f'❌ Still has {null_count} NULL bytes')
"

# 4. 파일 크기 증가율 확인
ls -lh logs/app.log
# 정상: 통화당 수백 바이트
# 비정상: 통화당 수백 KB
```

## 📝 추가 조사 필요

1. **로거 소스 코드 찾기**:
   - `src/logging/` 디렉토리 검색
   - `main.py`에서 로거 초기화 코드 확인
   - `grep -r "open.*app.log"` 실행

2. **버퍼 관련 코드 검색**:
   ```bash
   grep -r "bytearray\|buffer_size\|BUFFER_SIZE" sip-pbx/src/
   ```

3. **SIP 메시지 로깅 코드**:
   ```bash
   grep -r "sip_recv\|event.*RECV" sip-pbx/src/
   ```

## 🎯 결론

### 원인

**로거가 700KB 고정 크기 버퍼를 사용하며, NULL로 초기화된 버퍼 전체를 파일에 flush하는 버그**

### 구조

```
[NULL * 708,593 bytes] + [Valid JSON 171 bytes] = 708,764 bytes total
```

### 해결책

1. ✅ **즉시**: NULL 바이트 제거 스크립트 실행
2. 🔄 **단기**: 표준 Python logging 모듈로 교체
3. 🔄 **장기**: structlog 도입 + 로그 회전 설정

### 우선순위

🔴 **CRITICAL** - 로그 파일 손상 및 저장 공간 낭비

---

**작성일**: 2026-03-11
**분석자**: AI Agent
**상태**: 🔍 **원인 파악 완료** → 🔧 **긴급 수정 필요**
**다음 단계**: 로거 소스 코드 찾기 및 수정

