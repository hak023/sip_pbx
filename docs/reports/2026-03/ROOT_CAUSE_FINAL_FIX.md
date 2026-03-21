---
title: 근본 원인 분석 완료 - 최종 수정 가이드
date: 2026-03-11
type: root_cause_analysis
tags: [critical, ai-orchestrator, null-bytes, loguru, solution]
priority: CRITICAL
---

# 근본 원인 분석 완료 - 최종 수정 가이드

## 🎯 핵심 발견사항

### ✅ 모든 코드가 이미 구현되어 있음!

1. **AI Orchestrator 주입**: `call_manager.set_ai_orchestrator()` 구현됨
2. **RTP Worker AI 연결**: `RTPRelayWorker.__init__(ai_orchestrator=...)` 구현됨  
3. **Main 초기화**: `main.py` Line 342에서 `set_ai_orchestrator()` 호출 중

**문제**: 코드는 완벽하지만, 실행 타이밍 문제 또는 None 체크 실패로 AI가 전달되지 않음

---

## 1. RTP Worker AI Orchestrator 문제

### 🔍 근본 원인 (확정)

**파일**: `src/main.py` Line 297-350

```python
# Line 297
ai_orchestrator = None  # ← 글로벌 변수

async def initialize_ai_in_background():
    # Line 333
    ai_orchestrator = await create_ai_orchestrator(...)  # ← 로컬 변수!
    
    if ai_orchestrator:
        if sip_endpoint and sip_endpoint.call_manager:
            sip_endpoint.call_manager.set_ai_orchestrator(ai_orchestrator)
```

**문제**: 
- Line 333에서 `ai_orchestrator =`로 **로컬 변수를 생성**함
- `global ai_orchestrator` 선언이 없어서 글로벌 변수가 업데이트되지 않음
- `set_ai_orchestrator()`는 호출되지만, 로컬 변수가 함수 종료 시 사라짐

### ✅ 해결 방법

**수정 1**: `src/main.py` Line 302 아래에 추가

```python
async def initialize_ai_in_background():
    global ai_orchestrator  # ← 이 줄 추가!
    nonlocal ai_ready  # ← 이것도 추가 (ai_ready 업데이트용)
    
    ai_start = time.time()
    ...
```

**또는 수정 2**: 클로저 사용 (더 깔끔)

```python
# Line 297
ai_state = {"orchestrator": None, "ready": False}  # ← dict 사용

async def initialize_ai_in_background():
    ai_start = time.time()
    ...
    orchestrator = await create_ai_orchestrator(ai_config_dict)
    
    if orchestrator:
        ai_state["orchestrator"] = orchestrator  # ← dict 업데이트
        ai_state["ready"] = True
        
        if sip_endpoint and sip_endpoint.call_manager:
            sip_endpoint.call_manager.set_ai_orchestrator(orchestrator)
```

### 검증 로그

수정 후 이 로그들이 나타나야 함:

```log
✅ {"event": "ai_orchestrator_connected_to_call_manager"}
✅ {"event": "ai_orchestrator_injected_into_call_manager"}
✅ {"event": "rtp_relay_worker_created", "ai_enabled": true}
✅ {"event": "ai_mode_enabled"}
❌ (없어야 함) {"event": "ai_orchestrator_not_available"}
❌ (없어야 함) {"event": "rtp_relay_skip_invalid_remote"}
```

---

## 2. NULL 바이트 로깅 문제

### 🔍 근본 원인 (확정)

**파일**: `src/common/logger.py`

```python
# Line 142: structlog - write 모드 (파일 초기화)
log_stream = open(log_file_path, "w", encoding="utf-8", buffering=1)

# Line 192-200: loguru (Pipecat) - append 모드
loguru_logger.add(
    str(log_file_path),
    level=level.upper(),
    format="[PIPECAT] ...",
    rotation=None,
    mode="a",  # ← append 모드!
    encoding="utf-8",
)
```

**문제**:
1. structlog이 파일을 `"w"` 모드로 열고 buffering=1 (라인 버퍼) 사용
2. loguru가 같은 파일을 `"a"` 모드로 다시 열어서 append
3. **두 스트림이 동일한 파일을 동시에 쓰고 있음**
4. 버퍼 충돌로 인해 NULL 바이트가 기록됨

### 패턴

```
server_ready (structlog) → 로그 기록
    ↓
첫 SIP REGISTER 수신 (sip_endpoint.py Line 664)
    ↓
structlog이 sip_recv 로그 기록 시도
    ↓
loguru 버퍼와 충돌
    ↓
986KB NULL 바이트 기록 (Line 162)
```

### ✅ 해결 방법

**옵션 1: loguru 비활성화 (권장)**

```python
# src/common/logger.py Line 162-204 수정

def _setup_loguru_integration(level: str, log_file_path: Optional[Path]) -> None:
    """Pipecat(loguru) 로그를 app.log 파일에도 기록하도록 설정"""
    try:
        from loguru import logger as loguru_logger
        
        # 기존 loguru 핸들러 제거
        loguru_logger.remove()
        
        # 콘솔 출력만 유지 (파일 출력 제거)
        loguru_logger.add(
            sys.stderr,
            level=level.upper(),
            format="<green>{time:YYYY-MM-DD HH:mm:ss.SSS}</green> | "
                   "<level>{level: <8}</level> | "
                   "<cyan>{name}</cyan>:<cyan>{function}</cyan>:<cyan>{line}</cyan> - "
                   "<level>{message}</level>",
            colorize=True,
        )
        
        # ❌ app.log 파일 출력 제거 (structlog과 충돌 방지)
        # if log_file_path:
        #     loguru_logger.add(...)  ← 이 부분 주석 처리 또는 삭제
        
    except ImportError:
        pass
    except Exception:
        pass
```

**옵션 2: 별도 파일 사용**

```python
# loguru를 별도 파일에 기록
if log_file_path:
    pipecat_log_path = log_file_path.parent / "pipecat.log"
    loguru_logger.add(
        str(pipecat_log_path),  # ← 별도 파일
        level=level.upper(),
        ...
    )
```

**옵션 3: loguru를 structlog로 리다이렉트 (가장 깔끔)**

```python
# loguru 메시지를 structlog으로 전달
import logging

class StructlogHandler(logging.Handler):
    def emit(self, record):
        logger = structlog.get_logger("pipecat")
        logger.log(
            record.levelno,
            record.getMessage(),
            module=record.module,
            function=record.funcName,
            line=record.lineno,
        )

# loguru를 Python logging으로 브리지
from loguru import logger as loguru_logger
loguru_logger.remove()
loguru_logger.add(
    StructlogHandler(),
    level=level.upper(),
)
```

---

## 📊 문제 요약

| 문제 | 근본 원인 | 상태 | 해결책 |
|------|----------|------|--------|
| **Active API 404** | 엔드포인트 미구현 | ✅ 해결 | `calls.py`에 추가 완료 |
| **RTP Relay Invalid** | `global` 키워드 누락 | ⚠️ 코드 수정 필요 | `main.py` Line 302에 `global ai_orchestrator` 추가 |
| **NULL 바이트 로깅** | structlog/loguru 파일 충돌 | ⚠️ 코드 수정 필요 | `logger.py` Line 192-200 제거 또는 수정 |

---

## 🔧 즉시 적용 가능한 수정

### 수정 1: main.py

```python
# src/main.py Line 302 (initialize_ai_in_background 함수 시작 부분)

async def initialize_ai_in_background():
    global ai_orchestrator  # ← 추가!
    nonlocal ai_ready  # ← 추가!
    
    ai_start = time.time()
    ...
```

### 수정 2: logger.py

```python
# src/common/logger.py Line 190-200

# app.log 파일에도 기록 ← 이 부분 전체 주석 처리!
# if log_file_path:
#     loguru_logger.add(
#         str(log_file_path),
#         level=level.upper(),
#         format="[PIPECAT] {time:YYYY-MM-DD HH:mm:ss.SSS} | {level: <8} | "
#                "{name}:{function}:{line} - {message}",
#         rotation=None,
#         mode="a",
#         encoding="utf-8",
#     )
```

---

## ✅ 수정 후 테스트

### 1. 서버 재시작

```bash
cd sip-pbx
python -m src.main
```

### 2. 로그 확인

```bash
# AI Orchestrator 주입 확인
grep "ai_orchestrator_connected_to_call_manager" logs/app.log

# NULL 바이트 확인
python -c "
with open('logs/app.log', 'rb') as f:
    content = f.read()
    nulls = content.count(b'\x00')
    print(f'NULL bytes: {nulls}')
    if nulls == 0:
        print('✅ NO NULL BYTES!')
    else:
        print(f'❌ Still has {nulls} NULL bytes')
"
```

### 3. AI 통화 테스트

1. SIP 클라이언트(1003)에서 1004로 전화
2. 10초 대기 (no-answer timeout)
3. AI가 자동으로 응답해야 함
4. 로그 확인:
   ```bash
   grep "ai_mode_enabled" logs/app.log
   grep -v "rtp_relay_skip_invalid_remote" logs/app.log | wc -l  # 경고가 없어야 함
   ```

---

## 📝 파일별 변경 요약

### ✅ 완료된 수정
- `src/api/routers/calls.py` - `/api/calls/active` 엔드포인트 추가

### 🔧 필요한 수정
1. **`src/main.py`** Line 302:
   ```python
   + global ai_orchestrator
   + nonlocal ai_ready
   ```

2. **`src/common/logger.py`** Line 190-200:
   ```python
   - loguru_logger.add(str(log_file_path), mode="a", ...)  # 제거 또는 주석
   ```

---

## 🎯 결론

### 문제 1: AI Orchestrator
- **원인**: `global` 키워드 누락으로 로컬 변수가 생성됨
- **영향**: AI 통화 기능 완전 불능
- **수정**: 1줄 추가 (`global ai_orchestrator`)

### 문제 2: NULL 바이트
- **원인**: structlog과 loguru가 동일 파일에 동시 쓰기
- **영향**: 약 1MB NULL 바이트 발생
- **수정**: loguru 파일 출력 제거 (10줄 주석 처리)

### 우선순위
1. 🔴 **즉시**: `main.py` 수정 (AI 통화 복원)
2. 🟠 **즉시**: `logger.py` 수정 (로그 손상 방지)
3. 🟢 **완료**: Active API (Frontend 로그인)

---

**작성일**: 2026-03-11
**작성자**: AI Agent  
**상태**: 🎯 **근본 원인 파악 완료**
**다음 단계**: 2개 파일 각 1줄씩 수정
