# 중복 INVITE 처리 에러 수정 완료

**날짜**: 2026-01-08  
**작업**: "Media session already exists" 에러 해결

---

## 🔍 발견된 문제

### 에러 로그:
```json
{
  "error": "Media session already exists: 138e74032983445888627k30956rmwp",
  "exc_info": true,
  "event": "b2bua_invite_error",
  "level": "error",
  "timestamp": "2026-01-08T19:39:41.394322+09:00"
}
```

### 타임라인 분석:
```
19:39:37 - ✅ 첫 번째 INVITE 도착
           └─> b2bua_call_setup (new_call_id: b2bua-439656-138e7403)
           └─> Media session 생성 성공
           └─> INVITE transaction 시작

19:39:39 - ✅ 200 OK 수신, 통화 established

19:39:41 - ❌ 두 번째 INVITE 도착 (중복!)
           └─> b2bua_call_setup (new_call_id: b2bua-257641-138e7403)
           └─> 에러: "Media session already exists"

19:39:52 - BYE 수신
```

---

## 🐛 문제 원인

### 1. **중복 INVITE 재전송**

SIP RFC 3261에 따르면, 클라이언트는 다음 이유로 INVITE를 재전송할 수 있습니다:

1. **응답이 늦을 때**: Timer A에 따라 재전송 (0.5초, 1초, 2초, ...)
2. **네트워크 패킷 손실**: UDP 특성상 패킷이 손실되면 재전송
3. **클라이언트 버그**: 잘못된 구현으로 중복 전송

### 2. **서버의 멱등성 처리 부족**

**수정 전 코드**:
```python
async def _handle_invite_b2bua(self, request: str, caller_addr: tuple):
    # 헤더 추출
    call_id = self._extract_header(request, 'Call-ID')
    
    # ❌ 중복 체크 없음!
    
    # MediaSession 생성 시도
    media_session = self.media_session_manager.create_session(
        call_id=call_id,  # 이미 존재하는 call_id
        caller_sdp=sdp,
        mode=None
    )
    # → 에러 발생: "Media session already exists"
```

**문제점**:
- 동일한 `call_id`로 이미 처리 중인지 체크하지 않음
- 무조건 새로운 Media Session을 생성하려고 시도
- `MediaSessionManager`에서 중복 생성 시 예외 발생

---

## ✅ 수정 내용

### INVITE 중복 체크 로직 추가

```python
async def _handle_invite_b2bua(self, request: str, caller_addr: tuple):
    # 헤더 추출
    call_id = self._extract_header(request, 'Call-ID')
    
    print(f"\n📞 B2BUA INVITE: {caller_username} → {callee_username}")
    print(f"   Original Call-ID: {call_id}")
    
    # ✅ 중복 INVITE 체크 (재전송 방지)
    if call_id in self._active_calls:
        existing_call = self._active_calls[call_id]
        state = existing_call.get('state', 'unknown')
        
        logger.info("invite_retransmission_detected",
                   call_id=call_id,
                   state=state,
                   caller=caller_username,
                   callee=callee_username)
        print(f"⚠️  INVITE retransmission detected (state: {state})")
        print(f"   Ignoring duplicate INVITE for existing call")
        
        # 이미 처리 중이면 100 Trying 재전송 (멱등성)
        if state == 'inviting':
            trying_response = (
                "SIP/2.0 100 Trying\r\n"
                f"Via: {via}\r\n"
                f"From: {from_hdr}\r\n"
                f"To: {to_hdr}\r\n"
                f"Call-ID: {call_id}\r\n"
                f"CSeq: {cseq}\r\n"
                "Content-Length: 0\r\n"
                "\r\n"
            )
            self._send_response(trying_response, caller_addr)
        
        # 중복 요청은 더 이상 처리하지 않음
        return
    
    # ✅ 여기서부터 정상적인 새 INVITE 처리
    # 수신자가 등록되어 있는지 확인
    if callee_username not in self._registered_users:
        ...
```

---

## 📊 동작 방식

### Case 1: 첫 번째 INVITE (정상)
```
1. INVITE 수신 (Call-ID: abc123)
2. call_id in self._active_calls? → NO
3. ✅ 정상 처리:
   - Media Session 생성
   - 100 Trying 전송
   - Callee로 INVITE 전달
   - _active_calls에 저장
```

### Case 2: 두 번째 INVITE (중복 재전송)
```
1. INVITE 수신 (Call-ID: abc123) - 동일한 Call-ID!
2. call_id in self._active_calls? → YES (state: 'inviting')
3. ✅ 중복 처리:
   - 로그: "invite_retransmission_detected"
   - 콘솔: "⚠️  INVITE retransmission detected"
   - 100 Trying 재전송 (멱등성)
   - return (더 이상 처리 안 함)
4. ❌ 에러 발생 없음!
```

---

## 🧪 검증

### 수정 전 로그:
```json
{"event": "b2bua_call_setup", "call_id": "138e74032983445888627k30956rmwp", "new_call_id": "b2bua-439656-138e7403"}
{"event": "media_session_created", "call_id": "138e74032983445888627k30956rmwp"}
{"event": "call_established", "call_id": "138e74032983445888627k30956rmwp"}

// 중복 INVITE 도착
{"event": "b2bua_call_setup", "call_id": "138e74032983445888627k30956rmwp", "new_call_id": "b2bua-257641-138e7403"}
{"error": "Media session already exists: 138e74032983445888627k30956rmwp", "event": "b2bua_invite_error"}  ❌
```

### 수정 후 예상 로그:
```json
{"event": "b2bua_call_setup", "call_id": "138e74032983445888627k30956rmwp", "new_call_id": "b2bua-439656-138e7403"}
{"event": "media_session_created", "call_id": "138e74032983445888627k30956rmwp"}
{"event": "call_established", "call_id": "138e74032983445888627k30956rmwp"}

// 중복 INVITE 도착
{"event": "invite_retransmission_detected", "call_id": "138e74032983445888627k30956rmwp", "state": "inviting"}  ✅
// 100 Trying 재전송
// 더 이상 처리 안 함 (에러 없음)
```

---

## 🎯 핵심 개선사항

1. ✅ **중복 INVITE 감지**: `call_id in self._active_calls` 체크
2. ✅ **멱등성 보장**: 동일한 요청에 동일한 응답 (100 Trying 재전송)
3. ✅ **에러 방지**: "Media session already exists" 에러 발생 방지
4. ✅ **로그 가시성**: `invite_retransmission_detected` 이벤트로 추적 가능
5. ✅ **RFC 3261 준수**: SIP 표준에 따른 재전송 처리

---

## 📝 SIP 재전송 메커니즘 (참고)

### RFC 3261 Timer A (INVITE 재전송)
```
T1 = 500ms (기본값)

재전송 간격:
- 0.5초 후 첫 재전송
- 1초 후 두 번째 재전송
- 2초 후 세 번째 재전송
- 4초 후 네 번째 재전송
- ...
- 최대 64*T1 (32초) 까지
```

### 서버의 올바른 처리:
1. **첫 번째 INVITE**: 정상 처리 → 100 Trying 전송
2. **재전송 INVITE**: 중복 감지 → 100 Trying 재전송 또는 무시
3. **에러 없음**: 동일한 Media Session을 재생성하지 않음

---

## 🚀 테스트 방법

### 1. 서버 재시작
```bash
cd C:\work\workspace_sippbx\sip-pbx
python src/main.py
```

### 2. 통화 진행
- SIP 전화기로 통화 (예: 1002 → 1001)
- 네트워크 지연이나 재전송 발생 시

### 3. 로그 확인
```bash
# 중복 INVITE 감지 확인
cat logs/app.log | findstr "invite_retransmission_detected"

# 예상 출력:
# {"event": "invite_retransmission_detected", "call_id": "xxx", "state": "inviting"}

# 에러 없음 확인
cat logs/app.log | findstr "Media session already exists"
# (출력 없어야 정상)
```

---

## 📌 관련 RFC 참조

- **RFC 3261**: SIP - Session Initiation Protocol
  - Section 17.1.1.2: INVITE Client Transaction (Timer A)
  - Section 17.2.1: INVITE Server Transaction
- **RFC 6026**: Correct Transaction Handling for 2xx Responses

---

## 🎯 수정 파일

- ✅ `sip-pbx/src/sip_core/sip_endpoint.py`
  - `_handle_invite_b2bua()` 함수에 중복 INVITE 체크 로직 추가
  - 재전송 시 100 Trying 재전송 및 early return

