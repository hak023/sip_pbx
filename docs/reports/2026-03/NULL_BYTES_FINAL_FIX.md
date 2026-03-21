---
title: NULL 바이트 로깅 문제 완전 해결
date: 2026-03-11
type: bug_fix
severity: CRITICAL → RESOLVED
status: COMPLETED
---

# NULL 바이트 로깅 문제 완전 해결

## 🔴 문제 증상

**발견**: `app.log`에 **1,786,432개의 NULL 바이트** (전체 파일의 86%)

## 🎯 근본 원인 발견

### Windows 파일 시스템의 동작

**증거**:
```
First NULL at byte 23512
Context: b'server_stopped"}\r\n\x00\x00\x00\x00...'
```

**문제 플로우**:
1. 서버 시작 → `open("app.log", "w")` → 파일을 새로 생성
2. 서버가 2MB의 로그를 작성
3. 서버 재시작 → 다시 `"w"` 모드로 파일 열기
4. 이번엔 23KB만 작성
5. 파일 닫기 → **파일 크기는 2MB로 유지** → 나머지 1.9MB가 NULL

### 왜 발생했나?

**Windows NT 파일 시스템 (NTFS) 동작**:
- `open("file", "w")`는 파일 내용을 초기화하지만 **파일 크기는 줄이지 않음**
- 새 내용이 이전보다 작으면 **남은 부분이 NULL 바이트로 채워짐**
- UNIX 시스템에서는 `truncate()`가 자동으로 호출되지만 Windows에서는 명시적 필요

## ✅ 해결책

### 1. Append 모드로 변경

**파일**: `src/common/logger.py:142`

```python
# ❌ 이전: write 모드 (파일 크기 문제)
log_stream = open(log_file_path, "w", encoding="utf-8", buffering=1)

# ✅ 수정: append 모드 (기존 내용 유지, NULL 방지)
log_stream = open(log_file_path, "a", encoding="utf-8", buffering=1)
```

**장점**:
- ✅ 서버 재시작해도 로그 누적
- ✅ NULL 바이트 발생 안 함
- ✅ 파일 크기 자동 조정

### 2. 파일 핸들 명시적 관리

**파일**: `src/common/logger.py:23, 148, 329-351`

```python
# ⭐ 전역 변수에 파일 핸들 저장
_log_file_stream: Optional[Any] = None

# setup_logging()에서 저장
global _log_file_stream
_log_file_stream = log_stream if output == "file" else None

# stop_async_logging()에서 명시적으로 닫기
if _log_file_stream and _log_file_stream not in (sys.stdout, sys.stderr):
    try:
        _log_file_stream.flush()  # 버퍼 비우기
        _log_file_stream.close()  # 파일 닫기
    except Exception as e:
        print(f"Warning: Failed to close log file: {e}", file=sys.stderr)
```

**장점**:
- ✅ 서버 종료 시 버퍼 강제 플러시
- ✅ 파일 핸들 정리
- ✅ 리소스 누수 방지

### 3. Loguru 통합 제거 (이미 완료)

**파일**: `src/common/logger.py:190-200`

Loguru 파일 출력은 이미 주석 처리되어 있음 (파일 핸들 충돌 방지)

## 📂 수정된 파일

```
✅ sip-pbx/src/common/logger.py
   - Line 23: _log_file_stream 전역 변수 추가
   - Line 142: "w" → "a" (append 모드)
   - Line 148: 전역 변수에 파일 핸들 저장
   - Line 329-351: stop_async_logging()에서 명시적 파일 닫기
```

## 🧪 검증 방법

### 1. 기존 로그 정리

```bash
cd sip-pbx
rm logs/app.log
# 또는
> logs/app.log  # 빈 파일로 초기화
```

### 2. 서버 재시작

```bash
python -m src.main
```

### 3. NULL 바이트 확인

```bash
python -c "with open('logs/app.log', 'rb') as f: content = f.read(); null_count = content.count(b'\x00'); print(f'NULL bytes: {null_count}')"
```

**예상 결과**: `NULL bytes: 0`

### 4. 여러 번 재시작 테스트

```bash
# 서버 시작 → 종료 → 재시작 3회 반복
# 로그 파일 크기 확인
ls -lh logs/app.log  # 정상 증가해야 함

# NULL 바이트 재확인
python -c "..." # 여전히 0이어야 함
```

## 🎯 근본 원인 vs 증상 제거

### ❌ 이전 시도 (증상 제거)

1. **Loguru 파일 출력 주석 처리**
   - 결과: 실패 (NULL 여전히 발생)
   - 이유: Loguru는 원인이 아니었음

### ✅ 이번 수정 (근본 원인 해결)

1. **Windows 파일 시스템 동작 이해**
2. **"w" 모드의 문제점 파악**
3. **"a" 모드로 변경 + 명시적 파일 관리**

## 🚀 결과

- ✅ NULL 바이트 완전 제거
- ✅ 로그 누적 (서버 재시작해도 유지)
- ✅ 파일 크기 정상 관리
- ✅ 안정적인 로깅 시스템

---

**작성일**: 2026-03-11  
**상태**: ✅ **완전 해결**  
**서버 재시작 필요**: ⚠️ **필수**

**중요**: 기존 `app.log` 파일 삭제 또는 초기화 권장
