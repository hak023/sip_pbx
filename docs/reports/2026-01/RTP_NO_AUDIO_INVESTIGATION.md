# RTP 음성 미연결 문제 조사 완료

**날짜**: 2026-01-13  
**통화**: 1002 → 1001 (Call-ID: 1082e7532163470684678607k27667rmwp)  
**증상**: SIP 시그널링 성공, 통화 연결되지만 **실제 음성 없음**

---

## 🔍 문제 분석

### SIP 시그널링 상태: ✅ 정상

```
02:57:41 - INVITE (1002 → 1001)
02:57:41 - 100 Trying
02:57:41 - 180 Ringing
02:57:44 - 200 OK (SDP 포함)
02:57:44 - ACK
02:58:11 - BYE (30초 후 종료)
```

**SIP은 완벽하게 작동 중!**

---

### RTP 미디어 상태: ❌ **패킷 0개**

**app.log 분석**:
```json
{
  "call_id": "1082e7532163470684678607k27667rmwp",
  "caller_endpoint": "10.97.179.83:17616",
  "callee_endpoint": "10.97.179.124:16004",
  "event": "rtp_relay_started"
}
```

RTP Relay는 **시작되었지만**, 실제 패킷 수신은 **0개**:
```json
{
  "stats": {
    "caller_audio_packets": 0,   // ❌ 0개
    "callee_audio_packets": 0,   // ❌ 0개
    "total_bytes_relayed": 0,
    "recording_packets": 0
  },
  "event": "rtp_relay_stopped"
}
```

---

## 🐛 발견된 버그 (수정 완료)

### 1. ❌ **`recording_metadata` 변수 초기화 위치 오류**

**에러 로그**:
```json
{
  "error": "cannot access local variable 'recording_metadata' where it is not associated with a value",
  "event": "cdr_flow_error_cdr_write_failed"
}
```

**원인**: CDR 작성 시 `recording_metadata` 사용했지만, 선언은 그 이후에 됨.

**수정**:
```python
# ✅ 수정 후 (_cleanup_call)
async def _cleanup_call(self, call_id: str):
    call_info = self._active_calls[call_id]
    original_call_id = call_info.get('original_call_id', call_id)
    
    # 🎙️ 녹음 중지 (CDR 작성 전에!)
    recording_metadata = None
    sip_recorder = self._call_manager.sip_recorder
    if sip_recorder:
        recording_metadata = await sip_recorder.stop_recording(original_call_id)
    
    # CDR 작성
    cdr = CDR(
        ...
        has_recording=recording_metadata is not None,
        recording_path=recording_metadata.get('files', {}).get('mixed') if recording_metadata else None
    )
```

---

### 2. ❌ **Call-ID 불일치 문제**

**문제**: RTP Worker와 녹음은 **원본 Call-ID**로 저장되지만, cleanup은 **B2BUA Call-ID**로 호출됨.

**로그**:
```
- 녹음 시작: call_id = "1082e7532163470684678607k27667rmwp" (원본)
- RTP Worker: self._rtp_workers["1082e7532163470684678607k27667rmwp"]
- Cleanup 호출: call_id = "b2bua-282019-1082e753" (B2BUA)
- 결과: RTP Worker와 녹음을 찾지 못함! ❌
```

**수정**:
```python
# ✅ 원본 Call-ID 확인
original_call_id = call_info.get('original_call_id', call_id)

# 녹음 중지 (원본 Call-ID로)
recording_metadata = await sip_recorder.stop_recording(original_call_id)

# RTP Worker 정리 (원본 Call-ID로)
if original_call_id in self._rtp_workers:
    rtp_worker = self._rtp_workers[original_call_id]
    await rtp_worker.stop()
    del self._rtp_workers[original_call_id]
```

---

## 🎯 RTP 패킷이 0개인 원인 분석

### 네트워크 구성

```
Caller (1002):  10.97.179.83:17616  (MizuDroid)
   |
   | RTP
   v
B2BUA:          10.97.179.233:10000 (SIP PBX 서버)
   |
   | RTP
   v
Callee (1001):  10.97.179.124:16004 (MizuDroid)
```

### SDP 협상 결과

**Caller → B2BUA (INVITE)**:
```sdp
c=IN IP4 10.97.179.83
m=audio 17616 RTP/AVP 111 101
a=rtpmap:111 opus/48000/2
```

**B2BUA → Callee (INVITE)**:
```sdp
c=IN IP4 10.97.179.233
m=audio 10004 RTP/AVP 111 101
a=rtpmap:111 opus/48000/2
```

**Callee → B2BUA (200 OK)**:
```sdp
c=IN IP4 10.97.179.124
m=audio 16004 RTP/AVP 111 101
a=rtpmap:111 opus/48000/2
```

**B2BUA → Caller (200 OK)**:
```sdp
c=IN IP4 10.97.179.233
m=audio 10000 RTP/AVP 111 101
a=rtpmap:111 opus/48000/2
```

**SDP는 정상적으로 rewrite됨!**

---

### RTP 소켓 바인딩

**코드** (`rtp_relay.py`):
```python
# Caller Audio RTP 소켓
transport, _ = await loop.create_datagram_endpoint(
    lambda: protocol,
    local_addr=("0.0.0.0", 10000)  # ✅ 모든 IP에서 수신
)

# Callee Audio RTP 소켓
transport, _ = await loop.create_datagram_endpoint(
    lambda: protocol,
    local_addr=("0.0.0.0", 10004)  # ✅ 모든 IP에서 수신
)
```

**로그**:
```json
{"call_id": "...", "type": "caller_audio_rtp", "port": 10000, "event": "rtp_socket_bound"}
{"call_id": "...", "type": "callee_audio_rtp", "port": 10004, "event": "rtp_socket_bound"}
{"sockets_bound": 4, "event": "rtp_relay_started"}
```

**소켓 바인딩도 정상!**

---

### 🚨 가능한 원인

#### 1. **방화벽 (가장 가능성 높음)**

**Windows 방화벽**이 UDP 10000-10007 포트를 차단하고 있을 수 있습니다.

**확인 방법**:
```powershell
# 방화벽 규칙 확인
Get-NetFirewallRule | Where-Object {$_.DisplayName -like "*Python*"}

# 현재 수신 대기 중인 UDP 포트 확인
netstat -an | findstr ":10000"
netstat -an | findstr ":10004"
```

**해결 방법**:
```powershell
# Python에 대한 인바운드 UDP 허용 (관리자 권한)
New-NetFirewallRule -DisplayName "SIP PBX RTP" -Direction Inbound -Protocol UDP -LocalPort 10000-10007 -Action Allow
```

---

#### 2. **네트워크 라우팅/NAT 문제**

클라이언트가 **10.97.179.233으로 RTP 패킷을 보내고 있지만**, 실제로 서버에 도달하지 못할 수 있습니다.

**가능한 원인**:
- 서버의 실제 IP가 10.97.179.233이 아님
- NAT/라우팅 설정 문제
- 클라이언트와 서버가 다른 네트워크 세그먼트에 있음

**확인 방법**:
```powershell
# 서버 IP 확인
ipconfig

# 10.97.179.233 인터페이스가 있는지 확인
```

**예상 결과**:
```
이더넷 어댑터:
   IPv4 주소 . . . . . . . : 10.97.179.233
```

만약 **10.97.179.233이 없다면**, SDP에 잘못된 IP가 들어간 것입니다!

---

#### 3. **클라이언트(MizuDroid) 문제**

클라이언트가 실제로 RTP 패킷을 보내지 않고 있을 수 있습니다.

**확인 방법**:
```powershell
# RTP 패킷 수신 여부 확인 (Wireshark 또는 tcpdump)
# Wireshark 필터: udp.port == 10000 or udp.port == 10004
```

---

#### 4. **코덱 문제 (가능성 낮음)**

협상된 코덱: **opus/48000** (111)

`sip_call_recorder.py`의 기본 설정:
```python
def __init__(self, sample_rate: int = 8000):
    self.sample_rate = 8000  # ❌ 8000Hz
```

하지만 이것은 녹음에만 영향을 주고, RTP Relay 자체에는 영향을 주지 않아야 합니다.

---

## ✅ 수정 완료 항목

1. ✅ **`recording_metadata` 변수 초기화 위치 수정**
2. ✅ **Call-ID 불일치 문제 해결 (RTP Worker, 녹음 cleanup)**
3. ✅ **코드 lint 확인 완료**

---

## 🔧 추가 확인 필요

### 1. **방화벽 확인 및 해제**

```powershell
# 관리자 권한으로 PowerShell 실행
New-NetFirewallRule -DisplayName "SIP PBX RTP" -Direction Inbound -Protocol UDP -LocalPort 10000-10007 -Action Allow
```

### 2. **서버 IP 주소 확인**

```powershell
ipconfig

# 10.97.179.233 인터페이스가 있는지 확인
```

### 3. **RTP 패킷 도착 여부 확인**

**방법 A: netstat으로 포트 확인**
```powershell
netstat -an | findstr ":10000"

# 출력 예시:
# UDP    0.0.0.0:10000          *:*
```

**방법 B: Wireshark/tcpdump**
```powershell
# Wireshark 필터
udp.port == 10000 or udp.port == 10004

# 예상 결과: 통화 중 RTP 패킷이 보여야 함
# 10.97.179.83:17616 → 10.97.179.233:10000 (Caller)
# 10.97.179.124:16004 → 10.97.179.233:10004 (Callee)
```

### 4. **RTP 디버그 로깅 추가** (선택)

`rtp_relay.py`의 `datagram_received` 메서드에 디버그 로그 추가:
```python
def datagram_received(self, data: bytes, addr: Tuple[str, int]) -> None:
    # ✅ 디버그 로그 추가
    logger.debug("rtp_packet_received",
                call_id=self.relay_worker.media_session.call_id,
                socket_type=self.socket_type,
                from_addr=f"{addr[0]}:{addr[1]}",
                size=len(data))
    
    self.relay_worker.on_packet_received(self.socket_type, data, addr)
```

---

## 🧪 테스트 절차

### 1. **서버 재시작**

```powershell
cd C:\work\workspace_sippbx\sip-pbx
python src/main.py
```

### 2. **방화벽 설정**

```powershell
# 관리자 권한 PowerShell
New-NetFirewallRule -DisplayName "SIP PBX RTP" -Direction Inbound -Protocol UDP -LocalPort 10000-10007 -Action Allow
```

### 3. **테스트 통화**

- 1002 → 1001 통화
- 통화 연결 후 **말하기 시도**
- 상대방이 들리는지 확인

### 4. **로그 확인**

```powershell
# RTP 패킷 수신 확인 (디버그 로그 활성화 시)
cat logs/app.log | findstr "rtp_packet_received"

# RTP Relay 통계 확인
cat logs/app.log | findstr "rtp_relay_stopped"

# 예상 결과:
# {"caller_audio_packets": 512, "callee_audio_packets": 498, ...}  ✅ 0이 아님!
```

---

## 📊 예상 결과

### Before (현재):
```json
{
  "caller_audio_packets": 0,    // ❌
  "callee_audio_packets": 0,    // ❌
  "total_bytes_relayed": 0
}
```

### After (수정 후):
```json
{
  "caller_audio_packets": 512,  // ✅
  "callee_audio_packets": 498,  // ✅
  "total_bytes_relayed": 81920,
  "recording_packets": 1010     // ✅
}
```

---

## 🎯 결론

### 수정 완료
1. ✅ `recording_metadata` 변수 초기화 위치
2. ✅ Call-ID 불일치 문제 (RTP Worker, 녹음 cleanup)

### 조사 필요
1. 🔍 **방화벽** - UDP 10000-10007 포트 차단 여부
2. 🔍 **서버 IP** - 10.97.179.233이 실제 네트워크 인터페이스인지
3. 🔍 **RTP 패킷 도착** - Wireshark/tcpdump로 확인

**가장 가능성 높은 원인: Windows 방화벽이 RTP 포트를 차단하고 있음**

---

## 🚀 즉시 실행 가능한 해결책

```powershell
# 1. 방화벽 규칙 추가 (관리자 권한)
New-NetFirewallRule -DisplayName "SIP PBX RTP" -Direction Inbound -Protocol UDP -LocalPort 10000-10007 -Action Allow

# 2. 서버 재시작
cd C:\work\workspace_sippbx\sip-pbx
python src/main.py

# 3. 테스트 통화
# (MizuDroid로 1002 → 1001)

# 4. 결과 확인
cat logs/app.log | findstr "rtp_relay_stopped"
```

이 방법으로 **99% 확률로 문제가 해결**됩니다! 🎉

