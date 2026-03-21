---
title: AI 응대 시 서버 크래시 및 NULL 바이트 근본 원인
date: 2026-03-11
type: critical_bug_analysis
severity: CRITICAL
status: IDENTIFIED
---

# AI 응대 시 서버 크래시 및 NULL 바이트 근본 원인

## 🔴 문제 정확한 이해

**사용자 보고**:
> "전화 테스트를 해서 AI응대 시나리오가 되면  
> 1) 의도되지 않은 종료가 발생하면서  
> 2) log에 과다한 NULL이 출력된다."

## 🎯 근본 원인 발견

### 순환 참조 문제 (Circular Causation)

```
1. AI Orchestrator 초기화 시도
   ↓
2. logger.py에서 파일 핸들 열기 (append 모드)
   ↓
3. 하지만 _log_file_stream 전역 변수 설정 안됨 (Line 148 누락)
   ↓
4. AI 초기화 중 에러 발생
   ↓
5. finally 블록 실행 (main.py:610-626)
   ↓
6. stop_async_logging() 호출 (Line 621)
   ↓
7. _log_file_stream이 None → 파일 핸들 접근 실패
   ↓
8. 로그 파일이 제대로 닫히지 않음
   ↓
9. Windows 파일 시스템: 열린 채로 남은 파일 → NULL 바이트 패딩
   ↓
10. 서버 재시작 시도
   ↓
11. 같은 파일에 append → NULL 바이트 누적
   ↓
12. 파일 손상 → 다음 초기화 실패
   ↓
(반복)
```

### 코드 분석

#### 문제 1: 전역 변수 설정 누락

**`src/common/logger.py:23`**:
```python
_log_file_stream: Optional[Any] = None  # ⭐ 선언됨
```

**`src/common/logger.py:148`**:
```python
# ⭐ 전역 변수에 저장 (종료 시 명시적으로 닫기 위해)
global _log_file_stream
_log_file_stream = log_stream if output == "file" else None
```

**문제**: 이 코드가 **실제로 실행되지 않음**!

왜? `setup_logging()` 함수가 호출될 때 `output`이 `"file"`이 아닐 수 있음

#### 문제 2: stop_async_logging()의 가정

**`src/common/logger.py:329-351`**:
```python
async def stop_async_logging() -> None:
    global _log_queue, _log_worker_task, _log_file_stream
    
    # ...
    
    # ⭐ 로그 파일 명시적으로 닫기
    if _log_file_stream and _log_file_stream not in (sys.stdout, sys.stderr):
        try:
            _log_file_stream.flush()  # ❌ None이면 실행 안됨
            _log_file_stream.close()  # ❌ None이면 실행 안됨
        except Exception as e:
            print(f"Warning: Failed to close log file: {e}", file=sys.stderr)
```

**문제**: `_log_file_stream`이 None이면 **파일이 닫히지 않음**

#### 문제 3: structlog의 파일 핸들

**`src/common/logger.py:142-144`**:
```python
log_stream = open(log_file_path, "a", encoding="utf-8", buffering=1)
# ...
structlog.configure(
    # ...
    logger_factory=structlog.PrintLoggerFactory(file=log_stream),
    # ...
)
```

**문제**: 
- `log_stream`은 지역 변수
- `_log_file_stream`에 저장 안됨
- `stop_async_logging()`에서 접근 불가
- **파일이 열린 채로 남음**

### 크래시 시나리오

#### 시나리오 1: AI 초기화 에러

```python
# main.py:305-405
try:
    ai_orchestrator = await create_ai_orchestrator(ai_config_dict)
except Exception as e:  # ← 에러 발생
    logger.error("ai_voicebot_background_init_error", ...)
    print_immediate(f"❌ [AI Background] AI Voicebot 초기화 예외: {e}")

# main.py:610-626 (finally 블록)
finally:
    try:
        await stop_async_logging()  # ← 파일 닫기 실패
    except Exception as e:
        print_immediate(f"Warning: Failed to stop async logging: {e}")
    
    logger.info("server_stopped", message="SIP PBX stopped")  # ← 파일이 열린 채로 쓰기
```

#### 시나리오 2: 파일 핸들 누수

```
1. 서버 시작 → log_stream 열림 (fd=10)
2. AI 초기화 에러
3. finally → stop_async_logging()
4. _log_file_stream = None → 파일 안닫힘
5. fd=10 여전히 열림
6. 프로세스 종료 시 OS가 강제로 닫음
7. Windows: 파일 크기 유지 → NULL 패딩
```

## ✅ 완전한 수정

### 수정 1: 파일 핸들 저장 보장

**`src/common/logger.py:128-160`**:

```python
def setup_logging(...):
    global _log_file_stream  # ⭐ 함수 시작 부분에 선언
    
    # ...
    
    # 파일 출력 설정
    log_file_path = None
    log_stream = None
    if output == "file":
        # ... 파일 경로 설정 ...
        log_stream = open(log_file_path, "a", encoding="utf-8", buffering=1)
        _log_file_stream = log_stream  # ⭐ 즉시 저장
    else:
        log_stream = sys.stdout
        _log_file_stream = None  # ⭐ stdout 사용 시 None
    
    # structlog 설정
    structlog.configure(
        # ...
        logger_factory=structlog.PrintLoggerFactory(file=log_stream),
        # ...
    )
```

### 수정 2: 안전한 파일 닫기

**`src/common/logger.py:327-355`**:

```python
async def stop_async_logging() -> None:
    global _log_queue, _log_worker_task, _log_file_stream
    
    if _log_queue is None:
        # ⭐ 로그 파일만 닫기 (큐가 없어도)
        _close_log_file()
        return
    
    # 종료 신호 전송
    await _log_queue.put(None)
    
    # 워커 태스크 완료 대기
    if _log_worker_task:
        try:
            await asyncio.wait_for(_log_worker_task, timeout=5.0)
        except asyncio.TimeoutError:
            _log_worker_task.cancel()
            try:
                await _log_worker_task
            except asyncio.CancelledError:
                pass
    
    _log_queue = None
    _log_worker_task = None
    
    # ⭐ 로그 파일 닫기 (별도 함수)
    _close_log_file()


def _close_log_file() -> None:
    """로그 파일 안전하게 닫기"""
    global _log_file_stream
    
    if _log_file_stream is None:
        return
    
    # stdout/stderr는 닫지 않음
    if _log_file_stream in (sys.stdout, sys.stderr):
        _log_file_stream = None
        return
    
    try:
        _log_file_stream.flush()
        _log_file_stream.close()
        print(f"✅ Log file closed successfully", file=sys.stderr)
    except Exception as e:
        print(f"⚠️ Warning: Failed to close log file: {e}", file=sys.stderr)
    finally:
        _log_file_stream = None
```

### 수정 3: 프로세스 종료 시 강제 정리

**`src/main.py:610-627`**:

```python
finally:
    # 정리
    if sip_endpoint and sip_endpoint.is_running():
        logger.info("stopping_server", message="Stopping SIP server")
        try:
            sip_endpoint.stop()
        except Exception as e:
            logger.error("stop_failed", error=str(e))
    
    # 비동기 로깅 중지 (파일 닫기 포함)
    try:
        await stop_async_logging()
    except Exception as e:
        print_immediate(f"⚠️ Warning: Failed to stop async logging: {e}", file=sys.stderr)
        # ⭐ 에러가 발생해도 파일 닫기 시도
        try:
            from src.common.logger import _close_log_file
            _close_log_file()
        except:
            pass
    
    # ⭐ 최종 로그는 print로 (파일이 이미 닫혔을 수 있음)
    try:
        logger.info("server_stopped", message="SIP PBX stopped")
    except:
        pass
    
    print_immediate("\n✅ Server stopped successfully.\n")
```

## 🧪 검증 방법

### 1. 파일 핸들 추적

```bash
# Windows
handle.exe app.log

# 또는 Process Explorer로 열린 파일 핸들 확인
```

### 2. 크래시 재현

```bash
cd sip-pbx

# 기존 로그 삭제
del logs\app.log

# 서버 시작
python -m src.main

# AI 응대 전화 테스트
# 전화 종료 후 서버 상태 확인
```

### 3. NULL 바이트 확인

```bash
# 서버 정상 종료 후
python -c "with open('logs/app.log', 'rb') as f: print('NULL bytes:', f.read().count(b'\x00'))"
```

---

**작성일**: 2026-03-11  
**상태**: 🔴 **근본 원인 파악 완료, 수정 필요**
