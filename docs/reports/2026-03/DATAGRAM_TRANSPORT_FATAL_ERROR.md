---
title: Datagram Transport Fatal Write Error 분석
date: 2026-03-11T18:20
type: error_analysis
severity: CRITICAL
status: IDENTIFIED
---

# Datagram Transport Fatal Write Error 분석

## 🔴 에러 요약

**에러 타입**: `Fatal write error on datagram transport`  
**발생 위치**: `asyncio/proactor_events.py:518`  
**에러 메시지**: `AssertionError: assert fut is self._write_fut`

---

## 📋 에러 상세

### 에러 1: RTPRelayProtocol Write Error

```
Fatal write error on datagram transport
protocol: <src.media.rtp_relay.RTPRelayProtocol object at 0x0000028E34F807D0>
transport: <_ProactorDatagramTransport fd=1296 read=<_OverlappedFuture pending 
          cb=[_ProactorDatagramTransport._loop_reading()]> 
          write=<_OverlappedFuture finished result=172> write_bufsize=6>

Traceback (most recent call last):
  File "C:\Program Files\WindowsApps\PythonSoftwareFoundation.Python.3.11_3.11.2544.0_x64__qbz5n2kfra8p0\Lib\asyncio\proactor_events.py", 
       line 518, in _loop_writing
    assert fut is self._write_fut
           ^^^^^^^^^^^^^^^^^^^^^^^
AssertionError
```

### 에러 2: 동일 에러 반복

```
protocol: <src.media.rtp_relay.RTPRelayProtocol object at 0x0000028E34F808D0>
transport: <_ProactorDatagramTransport fd=4772 ...>
```

---

## 🔍 근본 원인 분석

### 1. Windows Proactor 이벤트 루프 문제

**문제점**:
- **Windows의 `ProactorEventLoop`** 에서 UDP Datagram Transport 사용 시 발생
- **비동기 쓰기 작업 충돌**: 이전 쓰기 작업이 완료되기 전에 새 쓰기 작업 시도
- **RTP 패킷 전송** 시 높은 빈도로 데이터를 전송하면서 발생

### 2. 에러 발생 메커니즘

```python
# asyncio/proactor_events.py:518
def _loop_writing(self, fut=None):
    try:
        assert fut is self._write_fut  # ← 여기서 AssertionError
        self._write_fut = None
        # ...
    except Exception as e:
        # Fatal write error 발생
```

**원인**:
1. RTP 패킷을 빠르게 전송 (20ms마다)
2. 이전 `write` 작업이 완료되기 전에 새로운 `sendto()` 호출
3. `_write_fut` 상태가 예상과 다름 → AssertionError

### 3. RTPRelayProtocol 위치

**파일**: `src/media/rtp_relay.py` (추정)

```python
class RTPRelayProtocol:
    def datagram_received(self, data, addr):
        """RTP 패킷 수신"""
        # ...
    
    def send_rtp_packet(self, data, addr):
        """RTP 패킷 전송"""
        self.transport.sendto(data, addr)  # ← 여기서 문제 발생 가능
```

---

## 🎯 영향도 분석

### 시스템 영향

| 항목 | 영향도 | 설명 |
|------|--------|------|
| **서버 안정성** | 🔴 HIGH | Fatal error 발생 시 RTP 전송 중단 |
| **통화 품질** | 🔴 HIGH | 오디오 패킷 손실 → 음성 깨짐 |
| **시스템 크래시** | 🟡 MEDIUM | Transport만 종료, 전체 서버는 유지 |

### 발생 조건

1. **Windows 환경**에서 실행
2. **RTP 패킷을 빠르게 전송**할 때 (AI 응대 시 TTS 오디오)
3. **높은 부하** 상황

---

## 🛠️ 해결 방안

### 방안 1: SelectorEventLoop 사용 (권장) ✅

**Windows에서 ProactorEventLoop 대신 SelectorEventLoop 사용**

**파일**: `src/main.py`

**수정**:

```python
import asyncio
import sys

async def main():
    # ✅ Windows에서 SelectorEventLoop 사용
    if sys.platform == 'win32':
        # ProactorEventLoop는 UDP에서 불안정
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
        logger.info("event_loop_policy_set", 
                   policy="WindowsSelectorEventLoopPolicy",
                   reason="ProactorEventLoop UDP instability")
    
    # 기존 코드 계속...
```

**장점**:
- ✅ UDP Datagram Transport 안정성 향상
- ✅ RTP 패킷 전송 시 AssertionError 방지
- ✅ 최소한의 코드 변경

**단점**:
- 🟡 파일 I/O 성능 약간 저하 (RTP 전송에는 영향 없음)

---

### 방안 2: RTP 전송 큐 추가 (대안)

**Rate Limiting + 큐 기반 전송**

**파일**: `src/media/rtp_relay.py`

```python
import asyncio
from collections import deque

class RTPRelayProtocol:
    def __init__(self):
        self._send_queue = deque()
        self._sending = False
        self._send_interval = 0.020  # 20ms
    
    async def _send_loop(self):
        """RTP 전송 루프 (Rate Limiting)"""
        while True:
            if self._send_queue:
                data, addr = self._send_queue.popleft()
                try:
                    self.transport.sendto(data, addr)
                except Exception as e:
                    logger.error("rtp_send_error", error=str(e))
            
            await asyncio.sleep(self._send_interval)
    
    def send_rtp_packet(self, data, addr):
        """RTP 패킷 전송 (큐에 추가)"""
        self._send_queue.append((data, addr))
        
        if not self._sending:
            self._sending = True
            asyncio.create_task(self._send_loop())
```

**장점**:
- ✅ 전송 속도 제어
- ✅ 버퍼 오버플로우 방지

**단점**:
- 🟡 추가 지연 발생 가능
- 🟡 코드 복잡도 증가

---

### 방안 3: 예외 처리 강화 (보조)

**Fatal Error를 Warning으로 처리**

```python
def connection_lost(self, exc):
    """연결 종료 처리"""
    if exc:
        logger.warning("rtp_connection_lost", 
                      error=str(exc),
                      error_type=type(exc).__name__)
    else:
        logger.info("rtp_connection_closed_normally")
```

---

## 📊 Windows Proactor vs Selector 비교

| 특성 | ProactorEventLoop | SelectorEventLoop |
|------|-------------------|-------------------|
| **UDP 안정성** | 🔴 불안정 (AssertionError) | ✅ 안정적 |
| **파일 I/O** | ✅ 고성능 | 🟡 중간 |
| **RTP 전송** | ❌ 문제 발생 | ✅ 정상 작동 |
| **Windows 기본** | ✅ (Python 3.8+) | ⚠️ 수동 설정 필요 |

---

## ✅ 권장 조치 사항

### P0 (즉시 적용) - SelectorEventLoop 전환

**파일**: `src/main.py`

1. **이벤트 루프 정책 변경**:
```python
if sys.platform == 'win32':
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
```

2. **서버 재시작**

3. **테스트**:
   - AI 응대 통화
   - RTP 패킷 전송 확인
   - Fatal error 발생 여부 확인

### P1 (권장) - 예외 처리 강화

**파일**: `src/media/rtp_relay.py`

- `connection_lost()` 메서드에 로깅 추가
- Fatal error를 Warning으로 처리

---

## 🔍 추가 점검 사항

### 1. RTP Relay 파일 확인

```bash
# RTP Relay 구현 파일 찾기
ls sip-pbx/src/media/
```

### 2. 현재 이벤트 루프 확인

```python
import asyncio
loop = asyncio.get_event_loop()
print(f"Current event loop: {type(loop).__name__}")
# ProactorEventLoop → 문제
# SelectorEventLoop → 정상
```

### 3. 에러 재현 테스트

- AI 응대 통화 시도
- RTP 패킷 전송 모니터링
- 로그에서 `Fatal write error` 확인

---

## 📚 참고 자료

### Python asyncio 문서
- [Windows의 ProactorEventLoop 제한사항](https://docs.python.org/3/library/asyncio-platforms.html#windows)
- [WindowsSelectorEventLoopPolicy](https://docs.python.org/3/library/asyncio-policy.html#asyncio.WindowsSelectorEventLoopPolicy)

### 관련 이슈
- Python Issue: "ProactorEventLoop datagram transport unstable"
- asyncio UDP known issues on Windows

---

## 🎯 결론

### 근본 원인
**Windows의 ProactorEventLoop가 UDP Datagram Transport에서 불안정**
- RTP 패킷 빠른 전송 시 비동기 쓰기 작업 충돌
- `AssertionError: assert fut is self._write_fut`

### 해결 방법
✅ **SelectorEventLoop로 전환** (가장 간단하고 효과적)

### 영향
- 🟢 RTP 패킷 전송 안정화
- 🟢 AI 응대 통화 품질 향상
- 🟢 Fatal error 방지

---

**작성일**: 2026-03-11T18:25  
**상태**: 🔴 **즉시 수정 필요**  
**우선순위**: P0 (CRITICAL)
