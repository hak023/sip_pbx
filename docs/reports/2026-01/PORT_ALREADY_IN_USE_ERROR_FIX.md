# 포트 중복 바인딩 에러 수정 완료

**날짜**: 2026-01-15  
**에러**: `[WinError 10048] 각 소켓 주소(프로토콜/네트워크 주소/포트)는 하나만 사용할 수 있습니다`  
**상태**: ✅ **수정 완료**

---

## 🐛 문제 상황

### 에러 로그

```
📥 SIP RECV from 10.242.118.83:13702 (561 bytes)
SIP/2.0 200 OK
...
CSeq: 1 INVITE  ← 동일한 CSeq (재전송)

🎵 Starting RTP Relay (at 200 OK)...
🔍 DEBUG: Creating RTP Worker...
🔍 DEBUG: Starting RTP Worker...
❌ RTP Worker start failed: [WinError 10048] 각 소켓 주소(프로토콜/네트워크 주소/포트)는 하나만 사용할 수 있습니다
❌ RTP Relay start failed at 200 OK!
```

**WinError 10048**: 이미 사용 중인 소켓 주소에 다시 바인딩을 시도하는 에러

---

## 🔍 원인 분석

### 타임라인

#### 1. 첫 번째 200 OK (정상)
```
📥 SIP Response: 200 for Call-ID: b2bua-811123-18e82699
✅ Relaying 200 OK to caller...
🎵 Starting RTP Relay (at 200 OK)...
✅ RTP Worker started successfully!
🎙️  Recording started: 1001 ↔ 1002
✅ RTP Relay started successfully!
```

**결과**: 
- RTP Worker가 정상적으로 시작됨
- 포트 10000, 10001, 10004, 10005가 **사용 중**

#### 2. ACK 전송
```
✅ ACK received for call 18e8269952359908399966k10222rmwp

======================================================================
📤 SIP SEND to 10.242.118.83:13702
======================================================================
ACK sip:1002@10.242.118.83:13702 SIP/2.0
...

✅ Call is now ACTIVE! (RTP already relaying)
   1001 <-> 1002
```

**결과**: 통화 활성화됨

#### 3. 두 번째 200 OK (재전송, 문제 발생!)
```
📥 SIP RECV from 10.242.118.83:13702 (561 bytes)
SIP/2.0 200 OK
Via: SIP/2.0/UDP 10.242.118.233:5060;branch=z9hG4bK841301
From: <sip:1001@10.242.118.233>;tag=b2bua-6779
To: <sip:1002@10.242.118.233>;tag=497p1323172871177952200h
Call-ID: b2bua-811123-18e82699
CSeq: 1 INVITE  ← 동일한 CSeq! (재전송임)
...

🎵 Starting RTP Relay (at 200 OK)...
🔍 DEBUG: Attempting to start RTP relay for call_id: 18e8269952359908399966k10222rmwp
🔍 DEBUG: MediaSession found: True
🔍 DEBUG: Caller IP: 10.242.118.183, Port: 15804
🔍 DEBUG: Callee IP: 10.242.118.83, Port: 13704
🔍 DEBUG: Creating RTP Worker...
🔍 DEBUG: Starting RTP Worker...
❌ RTP Worker start failed: [WinError 10048] 각 소켓 주소(프로토콜/네트워크 주소/포트)는 하나만 사용할 수 있습니다
```

**원인**: 
- Callee가 ACK를 못 받았다고 판단하고 200 OK를 재전송
- 코드가 200 OK를 받을 때마다 RTP Relay를 무조건 시작하려고 시도
- 이미 사용 중인 포트 10000, 10001, 10004, 10005에 다시 바인딩을 시도
- **WinError 10048** 발생!

---

## 📚 SIP RFC 3261 - 200 OK 재전송

### 정상적인 동작

SIP 프로토콜에서는 **200 OK가 여러 번 재전송될 수 있습니다**:

```
Caller                    B2BUA                     Callee
  |                         |                          |
  |      INVITE             |       INVITE             |
  |------------------------>|------------------------->|
  |                         |                          |
  |      180 Ringing        |      180 Ringing         |
  |<------------------------|<-------------------------|
  |                         |                          |
  |      200 OK (1st)       |      200 OK (1st)        |
  |<------------------------|<-------------------------|
  |                         |                          |
  |      ACK                |                          |
  |------------------------>|                          |
  |                         |   ACK (네트워크 지연!)    |
  |                         |------------------------->|
  |                         |                          |
  |                         |      200 OK (2nd) ← 재전송!
  |                         |<-------------------------|
  |                         |                          |
```

**재전송 이유**:
1. Callee가 ACK를 일정 시간 내에 받지 못함
2. 200 OK가 유실되었다고 판단
3. **200 OK를 재전송** (RFC 3261 Section 13.3.1.4)

**재전송 간격** (Timer T1 기반):
- 1st: 0ms
- 2nd: 500ms (T1)
- 3rd: 1000ms (2*T1)
- 4th: 2000ms (4*T1)
- ...최대 64*T1까지

---

## 🔧 코드 문제

### Before (수정 전)

`sip_endpoint.py` - `_start_rtp_relay()` 메서드:

```python
async def _start_rtp_relay(self, call_id: str) -> bool:
    """RTP Relay 시작 (비동기)"""
    try:
        print(f"🔍 DEBUG: Attempting to start RTP relay for call_id: {call_id}")
        media_session = self.media_session_manager.get_session(call_id)
        # ❌ 이미 실행 중인지 체크하지 않음!
        
        # RTP Worker 생성
        rtp_worker = RTPRelayWorker(...)
        
        # RTP Worker 시작 (이미 실행 중이면 포트 에러!)
        await rtp_worker.start()  # ❌ WinError 10048!
```

**문제**:
- 200 OK를 받을 때마다 무조건 RTP Relay를 시작하려고 시도
- `self._rtp_workers` 딕셔너리에 이미 있는지 체크하지 않음
- 이미 사용 중인 포트에 바인딩을 시도 → **에러**

---

### After (수정 후)

```python
async def _start_rtp_relay(self, call_id: str) -> bool:
    """RTP Relay 시작 (비동기)
    
    Args:
        call_id: Call-ID
        
    Returns:
        성공 여부 (True: 성공, False: 실패)
    """
    try:
        # ✅ 이미 RTP Relay가 실행 중인지 체크 (200 OK 재전송 대응)
        if call_id in self._rtp_workers:
            logger.info("rtp_relay_already_running", call_id=call_id)
            print(f"✅ RTP Relay already running for call {call_id} (200 OK retransmission)")
            return True
        
        print(f"🔍 DEBUG: Attempting to start RTP relay for call_id: {call_id}")
        media_session = self.media_session_manager.get_session(call_id)
        # ...
```

**수정 내용**:
1. ✅ `call_id in self._rtp_workers` 체크 추가
2. ✅ 이미 실행 중이면 즉시 `True` 리턴
3. ✅ 로그에 "200 OK retransmission" 명시

---

## ✅ 수정 완료

### 변경 사항

**파일**: `sip-pbx/src/sip_core/sip_endpoint.py`  
**메서드**: `_start_rtp_relay()`

**코드 diff**:
```diff
  async def _start_rtp_relay(self, call_id: str) -> bool:
      """RTP Relay 시작 (비동기)"""
      try:
+         # ✅ 이미 RTP Relay가 실행 중인지 체크 (200 OK 재전송 대응)
+         if call_id in self._rtp_workers:
+             logger.info("rtp_relay_already_running", call_id=call_id)
+             print(f"✅ RTP Relay already running for call {call_id} (200 OK retransmission)")
+             return True
+         
          print(f"🔍 DEBUG: Attempting to start RTP relay for call_id: {call_id}")
          media_session = self.media_session_manager.get_session(call_id)
          # ...
```

---

## 🧪 테스트 시나리오

### 1. 정상 시나리오 (200 OK 1회)

```
INVITE → 180 Ringing → 200 OK → ACK

예상 결과:
✅ RTP Worker started successfully!
✅ Call is now ACTIVE!
```

### 2. 200 OK 재전송 시나리오

```
INVITE → 180 Ringing → 200 OK (1st) → ACK (지연) → 200 OK (2nd)
                           ↓                              ↓
                    RTP Relay 시작                  이미 실행 중!

예상 결과:
✅ RTP Worker started successfully!  (1st)
✅ RTP Relay already running for call ... (200 OK retransmission)  (2nd)
✅ Call is now ACTIVE!
```

### 3. 로그 출력 예시

**Before (수정 전)**:
```
🎵 Starting RTP Relay (at 200 OK)...
✅ RTP Worker started successfully!

🎵 Starting RTP Relay (at 200 OK)...  ← 두 번째 200 OK
❌ RTP Worker start failed: [WinError 10048] ...
```

**After (수정 후)**:
```
🎵 Starting RTP Relay (at 200 OK)...
✅ RTP Worker started successfully!

🎵 Starting RTP Relay (at 200 OK)...  ← 두 번째 200 OK
✅ RTP Relay already running for call 18e8269952359908399966k10222rmwp (200 OK retransmission)
✅ RTP Relay started successfully!
```

---

## 📊 통화 성공 확인

로그에서 **통화는 정상적으로 완료**되었음을 확인:

```
======================================================================
📥 SIP RECV from 10.242.118.83:13702 (434 bytes)
======================================================================
BYE sip:1001@10.242.118.233:5060 SIP/2.0
...

👋 BYE received for call b2bua-811123-18e82699
...
👋 Call terminated
🧹 Cleaning up call: b2bua-811123-18e82699 (original: 18e8269952359908399966k10222rmwp)
   🎙️ Recording stopped: 18e8269952359908399966k10222rmwp\mixed.wav
   [CDR] Written: sip:1001@10.242.118.183 -> sip:1002@10.242.118.83 (8s)
   🎵 RTP Relay stopped
✅ Call cleaned up
```

**결과**:
- ✅ 통화 시간: 8초
- ✅ 녹음 완료: `18e8269952359908399966k10222rmwp\mixed.wav`
- ✅ CDR 작성 완료
- ✅ RTP Relay 정상 종료

**즉, WinError 10048 에러가 발생했지만 통화 자체는 영향을 받지 않았음!**  
(첫 번째 200 OK에서 이미 RTP Relay가 시작되었기 때문)

---

## 🎯 결론

### 문제
- ❌ 200 OK 재전송 시 RTP Worker를 중복으로 시작하려고 시도
- ❌ 이미 사용 중인 포트에 바인딩 → **WinError 10048**

### 해결
- ✅ `_start_rtp_relay()` 메서드에 중복 실행 체크 추가
- ✅ `call_id in self._rtp_workers` 확인
- ✅ 이미 실행 중이면 즉시 `True` 리턴

### 영향
- ✅ 통화 품질: **영향 없음** (첫 RTP Relay가 정상 동작)
- ✅ 에러 로그: **제거됨**
- ✅ 안정성: **향상됨** (200 OK 재전송 대응)

---

## 🚀 배포

### 서버 재시작 필요

```powershell
cd C:\work\workspace_sippbx\sip-pbx
python src/main.py
```

### 테스트 방법

1. 1001 → 1002 통화
2. **네트워크를 약간 지연시켜 200 OK 재전송 유도** (선택)
3. 로그 확인:
   ```
   ✅ RTP Relay already running for call ... (200 OK retransmission)
   ```

### 확인 사항

- ✅ WinError 10048 에러 발생하지 않음
- ✅ 통화 정상 연결
- ✅ 녹음 정상 동작

---

## 📝 관련 RFC

- **RFC 3261 Section 13.3.1.4**: INVITE Client Transaction (200 OK 재전송)
- **RFC 6026**: Correct Transaction Handling for 2xx Responses to Session Initiation Protocol (SIP) INVITE Requests

---

## 🔗 관련 이슈

- 이전 보고서: `RTP_NO_AUDIO_INVESTIGATION.md` (RTP 패킷 0개 문제)
- 이번 수정: **200 OK 재전송 대응** (포트 중복 바인딩 에러 해결)

---

**수정 완료일**: 2026-01-15  
**수정자**: AI Assistant  
**테스트 상태**: ✅ Lint 통과, 배포 대기 중
