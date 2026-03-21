---
title: NULL 바이트 로깅 문제 근본 원인 재분석
date: 2026-03-11
type: critical_bug
severity: CRITICAL
status: IN_PROGRESS
---

# NULL 바이트 로깅 문제 근본 원인 재분석

## 🔴 현재 상황

**발견**: `app.log`에 **1,786,432개의 NULL 바이트** 존재 (전체 파일의 86%)

```
File size: 2,074,967 bytes
NULL bytes: 1,786,432  ← 86%가 NULL!
```

## ❌ 이전 진단이 틀렸음

**이전 가설**: Loguru와 structlog의 파일 핸들 충돌
**조치**: Loguru 파일 출력 주석 처리 (`logger.py:190-200`)
**결과**: ❌ **실패** - NULL 바이트 여전히 발생

## 🔍 진짜 원인 찾기

### 가능한 원인들

1. **`print_immediate()` 함수의 문제**
   - `sys.stdout`에 출력
   - `flush=True` 사용
   - Windows에서 `msvcrt` 핸들 접근
   - **의심**: stdout이 로그 파일로 리다이렉트될 때 문제?

2. **structlog의 `write` 모드 문제**
   - `open(log_file_path, "w", ...)` - 서버 시작 시 새로 생성
   - `buffering=1` - 라인 버퍼링
   - **의심**: 버퍼 크기 부족? 동시 쓰기?

3. **비동기 로깅 워커 문제**
   - `start_async_logging()` 사용
   - 큐 기반 비동기 쓰기
   - **의심**: 큐가 가득 차서 NULL 바이트 발생?

4. **Python의 stdout/stderr 리다이렉션 문제**
   - 서버를 백그라운드로 실행할 때
   - `> logs/app.log 2>&1` 형태로 리다이렉트
   - **의심**: print와 structlog 동시 쓰기 충돌?

5. **Pipecat의 내부 로깅**
   - Loguru 콘솔 출력 (`sys.stderr`)
   - structlog과 별개
   - **의심**: stderr가 리다이렉트될 때 문제?

## 🧪 검증 필요

### 1. print_immediate 제거 테스트

모든 `print_immediate()` → `logger.info()` 변환

### 2. 비동기 로깅 비활성화 테스트

`start_async_logging()` 주석 처리

### 3. 로그 파일 열기 모드 변경

`"w"` → `"a"` (append)

### 4. 버퍼링 변경

`buffering=1` → `buffering=0` (unbuffered)

---

**다음 단계**: 각 가설을 순차적으로 테스트
