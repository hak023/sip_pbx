# RTP Connection Lost 근본 원인 분석 및 해결 방안

**작성일**: 2026-03-11  
**분석 대상**: AI 응대 시 `rtp_relay_connection_lost` 즉시 발생 (사용자 종료 아님)

---

## 📋 문제 요약

AI 응대 시작 직후 **29ms 만에** `callee_audio_transport` 연결이 끊어지고, 수백 개의 `'NoneType' object has no attribute 'append'` 에러가 발생합니다.

### 로그 타임라인

```json
18:07:54.420 - call_established (Caller ↔ AI)
18:07:54.422 - TTS started (AI 인사말)
18:07:56.295 - TTS first chunk yielding (1875ms 후)
18:07:56.324 - rtp_relay_connection_lost (callee_audio_rtp) ❌
18:07:56.324 - callee_audio_transport_cleared
18:07:56.337 - rtp_relay_connection_lost (caller_audio_rtp)
18:07:56.349+ - ai_audio_send_error (반복 수백 개)
```

**29ms 안에 사용자가 끊었을 리 없음** → 로직 에러 확정

---

## 🔍 근본 원인

### 1. AI Takeover 시나리오

```
정상 호 흐름:
1. Caller (1003) → INVITE → B2BUA
2. B2BUA → INVITE → Callee (1004)
3. Callee (1004) 무응답 (timeout)
4. B2BUA → CANCEL → Callee (1004) ✅
5. B2BUA → 200 OK → Caller (AI가 응대) ✅

RTP 구조 (AI Takeover 후):
- Caller Audio RTP: Caller의 음성 → B2BUA → AI Pipeline (STT)
- Callee Audio RTP: AI (TTS) → B2BUA → Caller ❌ 문제!
```

### 2. 문제 지점: `RTPRelayWorker` Transport 설정

#### `rtp_relay.py:762-767` (TTS → RTP 전송 루프)

```python
_transport = self.callee_audio_transport or self.caller_audio_transport
if not _transport or not self.caller_endpoint:
    continue

caller_ip = str(self.caller_endpoint.ip)
caller_port = int(self.caller_endpoint.port)
```

**문제**:
- `callee_audio_transport`는 **원래 Callee (1004)의 endpoint를 가리킴**
- AI Takeover 후에도 **Callee endpoint가 업데이트되지 않음**
- Callee는 이미 CANCEL되어 응답하지 않으므로 **transport가 invalid 상태**

#### `rtp_relay.py:221-248` (Callee Audio RTP 소켓 생성)

```python
# Callee Audio RTP 소켓
if callee_audio_rtp_port:
    try:
        protocol = RTPRelayProtocol(
            self,
            "callee_audio_rtp",
            self.caller_endpoint,  # ❌ 이게 문제!
            self.caller_endpoint.port
        )
```

**발견**: `callee_audio_rtp` 프로토콜의 `remote_endpoint`가 `self.caller_endpoint`로 설정되어 있음!

이것은 **Bypass 모드**(Caller ↔ Callee 일반 통화)를 위한 설정입니다.
- Bypass 모드: Callee 소켓이 받은 패킷 → Caller로 전송 ✅
- **AI 모드: Callee 소켓이 TTS를 Caller로 전송해야 함** ✅

하지만 **AI Takeover 시 Callee endpoint가 `0.0.0.0:0`이거나 무효한 상태**이고, Windows에서는 이런 invalid endpoint로 `sendto`를 시도하면 **즉시 `connection_lost` 발생**합니다.

### 3. Windows UDP Transport 동작

Windows의 `ProactorEventLoop` (또는 `SelectorEventLoop`)에서:
- Invalid endpoint (`0.0.0.0:0`)로 UDP `sendto` 시도
- ICMP Destination Unreachable 수신
- **Transport가 즉시 `connection_lost` 콜백 호출** → Transport 객체가 `None`으로 설정됨
- 이후 TTS 전송 시 `_transport.sendto()` 호출 → `'NoneType' object has no attribute 'append'`

---

## ✅ 해결 방안

### P0: AI Takeover 시 Callee Transport Endpoint 명시적 재설정

#### 수정 위치 1: `sip_endpoint.py` (AI Takeover 로직)

`sip_endpoint.py:3075-3110` 부근에서 RTP Worker의 AI 모드 활성화 시:

```python
# 🔄 Step 3: RTP를 AI 모드로 전환
rtp_worker = self._rtp_workers.get(call_id)
if rtp_worker:
    logger.info("🔄 [AI Takeover] Enabling AI mode on RTP Worker",
               call_id=call_id)
    
    # ✅ P0 FIX: AI 모드에서는 Callee Transport의 remote_endpoint를 Caller로 명시적 재설정
    # AI TTS 출력이 Caller에게 가도록 보장
    if "callee_audio_rtp" in rtp_worker.protocols:
        callee_protocol = rtp_worker.protocols["callee_audio_rtp"]
        callee_protocol.remote_endpoint = rtp_worker.caller_endpoint
        callee_protocol.remote_port = rtp_worker.caller_endpoint.port
        logger.info("✅ [AI Takeover] Callee Transport redirected to Caller",
                   call_id=call_id,
                   caller_endpoint=f"{rtp_worker.caller_endpoint.ip}:{rtp_worker.caller_endpoint.port}")
    
    # RTP Worker에 AI 모드 연결
    if self.call_manager and self.call_manager.ai_orchestrator:
        # ... (기존 로직)
```

#### 수정 위치 2: `rtp_relay.py` (Pipecat TTS Sender 안전장치)

`rtp_relay.py:762` 부근에서 Transport 선택 로직 강화:

```python
# AI 모드: Caller Transport 우선 (Callee Transport는 invalid일 수 있음)
if self.ai_mode:
    _transport = self.caller_audio_transport or self.callee_audio_transport
else:
    _transport = self.callee_audio_transport or self.caller_audio_transport

if not _transport or not self.caller_endpoint:
    logger.error("rtp_tts_no_valid_transport",
                call_id=self.media_session.call_id,
                ai_mode=self.ai_mode,
                has_caller_transport=self.caller_audio_transport is not None,
                has_callee_transport=self.callee_audio_transport is not None)
    continue
```

### P1: 추가 안전장치

#### Transport None 체크 강화

`rtp_relay.py:882-895` (sendto 블록):

```python
try:
    # ✅ Transport 유효성 재확인 (connection_lost 후 None일 수 있음)
    if not _transport or _transport.is_closing():
        logger.error("rtp_transport_invalid_before_send",
                    call_id=self.media_session.call_id,
                    transport_type=type(_transport).__name__ if _transport else "None")
        break
    
    async with self._sendto_lock:
        _transport.sendto(packet, (caller_ip, caller_port))
    packets_sent += 1
    self.stats["rtp_tts_packets_sent"] += 1
except Exception as send_err:
    # ... (에러 처리)
```

#### Connection Lost 시 Transport 재생성 (선택)

`rtp_relay.py:1617-1635` (connection_lost 콜백):

```python
def connection_lost(self, exc: Optional[Exception]) -> None:
    if exc:
        logger.warning("rtp_relay_connection_lost",
                      call_id=self.relay_worker.media_session.call_id,
                      socket_type=self.socket_type,
                      error=str(exc))

    if self.socket_type == "callee_audio_rtp":
        # AI 모드에서 Callee Transport가 끊긴 경우 Caller Transport로 폴백
        if self.relay_worker.ai_mode:
            logger.info("callee_transport_lost_in_ai_mode_using_caller_fallback",
                       call_id=self.relay_worker.media_session.call_id)
        self.relay_worker.callee_audio_transport = None
        logger.info("callee_audio_transport_cleared",
                   call_id=self.relay_worker.media_session.call_id,
                   reason="connection_lost")
```

---

## 🧪 검증 계획

### 테스트 시나리오

1. **정상 AI 응대 시나리오**
   - Caller (1003) → INVITE → 1004
   - 1004 무응답 (timeout)
   - AI 응대 시작 → TTS 인사말 전송
   - **검증**: `rtp_relay_connection_lost` 없이 TTS 정상 전송

2. **로그 확인**
   ```json
   {
     "event": "✅ [AI Takeover] Callee Transport redirected to Caller",
     "caller_endpoint": "192.168.1.100:5004"
   }
   {
     "event": "rtp_first_packet_sent",
     "dest_ip": "192.168.1.100",
     "dest_port": 5004
   }
   ```

3. **에러 로그 확인**
   - `rtp_relay_connection_lost` 발생하지 않음 ✅
   - `ai_audio_send_error` 발생하지 않음 ✅
   - `callee_audio_transport_cleared` 정상 통화 종료 시에만 발생 ✅

---

## 📊 예상 결과

### Before (현재)
```
TTS 시작 → 29ms 후 → callee_transport connection_lost → 수백 개 에러 → 음성 전송 실패
```

### After (수정 후)
```
TTS 시작 → callee_transport → caller endpoint로 재설정 → RTP 정상 전송 → 음성 정상 수신
```

---

## 🎯 액션 아이템

- [ ] P0: `sip_endpoint.py`에 Callee Transport 재설정 로직 추가
- [ ] P1: `rtp_relay.py`에 AI 모드 Transport 우선순위 로직 추가
- [ ] P1: Transport 유효성 체크 강화
- [ ] 테스트 실행 및 로그 확인
- [ ] 검증 완료 후 이슈 클로즈

---

## 📌 참고

- **관련 이슈**: AI 응대 시 TTS 음성 깨짐/끊김
- **이전 분석**: `RTP_CONNECTION_LOST_ROOT_CAUSE.md`
- **관련 픽스**: `DATAGRAM_TRANSPORT_FATAL_ERROR.md` (Windows UDP 안정성)
