# Direct Media Mode 구현 완료 보고서

**작성일:** 2026-01-16  
**작성자:** AI Assistant  
**관련 이슈:** RTP 패킷 수신 테스트를 위한 Direct Media 모드 구현

---

## 📋 **개요**

클라이언트가 실제로 RTP 패킷을 전송하는지 테스트하기 위해, SDP를 수정하지 않고 양 단말간 직접 RTP를 주고받을 수 있는 **Direct Media 모드**를 구현했습니다.

---

## 🎯 **목적**

- **테스트 목적**: 클라이언트가 RTP 패킷을 실제로 전송하는지 확인
- **문제 상황**: B2BUA 모드에서 RTP 패킷이 수신되지 않는 문제 발생
- **해결 방안**: SDP를 수정하지 않고 단말간 직접 통신하도록 설정하여, B2BUA의 영향을 배제하고 테스트

---

## 🔧 **구현 내용**

### 1. **MediaMode Enum 확장**

**파일:** `sip-pbx/src/media/media_session.py`

```python
class MediaMode(str, Enum):
    """미디어 처리 모드"""
    DIRECT = "direct"          # 단말간 직접 통신 (SDP 수정 없음, 테스트용)
    BYPASS = "bypass"          # B2BUA가 RTP 중계 (녹음/분석 가능)
    REFLECTING = "reflecting"  # 반사 (AI 분석용)
```

**변경 사항:**
- `DIRECT` 모드 추가
- 각 모드별 설명 주석 추가

---

### 2. **Config.yaml 업데이트**

**파일:** `sip-pbx/config/config.yaml`

```yaml
media:
  mode: "direct"  # direct | bypass | reflecting
                  # - direct: SDP 수정하지 않음, 단말간 직접 RTP 통신 (테스트용)
                  # - bypass: B2BUA가 RTP 중계 (녹음/분석 가능)
                  # - reflecting: B2BUA가 RTP 중계 + AI 분석
```

**변경 사항:**
- `mode: "direct"` 설정
- 각 모드별 상세 설명 추가

---

### 3. **SIPEndpoint MediaMode 변환 로직 수정**

**파일:** `sip-pbx/src/sip_core/sip_endpoint.py`

**변경 전:**
```python
media_mode = MediaMode.BYPASS if config.media.mode.value == "bypass" else MediaMode.REFLECTING
```

**변경 후:**
```python
mode_value = config.media.mode.value.lower()
if mode_value == "direct":
    media_mode = MediaMode.DIRECT
elif mode_value == "bypass":
    media_mode = MediaMode.BYPASS
else:
    media_mode = MediaMode.REFLECTING
```

**변경 사항:**
- `direct` 모드 처리 추가
- 대소문자 구분 없이 처리 (`.lower()`)

---

### 4. **CallManager - Outgoing INVITE SDP 처리**

**파일:** `sip-pbx/src/sip_core/call_manager.py`  
**함수:** `create_outgoing_invite()`

**변경 사항:**
```python
if media_session.mode != MediaMode.DIRECT:
    # B2BUA IP로 Connection 변경
    modified_sdp = SDPManipulator.replace_connection_ip(modified_sdp, self.b2bua_ip)
    
    # Callee leg의 할당된 포트로 변경
    audio_port = media_session.callee_leg.get_audio_rtp_port()
    video_port = media_session.callee_leg.get_video_rtp_port()
    
    modified_sdp = SDPManipulator.replace_multiple_ports(
        modified_sdp,
        audio_port=audio_port,
        video_port=video_port,
    )
    
    logger.info("sdp_modified_for_outgoing_invite", ...)
else:
    logger.info("sdp_not_modified_direct_mode", mode="direct")
```

**동작:**
- **Direct 모드**: SDP를 수정하지 않고 그대로 전달
- **Bypass/Reflecting 모드**: B2BUA IP/포트로 SDP 수정

---

### 5. **SIPEndpoint - 200 OK 응답 SDP 처리**

**파일:** `sip-pbx/src/sip_core/sip_endpoint.py`  
**함수:** `_relay_response_to_caller()`

**변경 사항:**
```python
if media_session.mode == MediaMode.DIRECT:
    # Direct 모드: SDP 수정하지 않고 그대로 전달
    rewritten_sdp = callee_sdp
    print(f"🔀 Direct Media Mode: SDP not modified (end-to-end RTP)")
    logger.info("direct_media_mode_enabled", ...)
else:
    # Bypass/Reflecting 모드: B2BUA가 중계
    # 1. 벤더 특정 속성 제거
    rewritten_sdp = SDPManipulator.remove_vendor_attributes(callee_sdp)
    # 2. Connection IP를 B2BUA IP로 교체
    rewritten_sdp = SDPManipulator.replace_connection_ip(rewritten_sdp, b2bua_ip)
    # 3. Audio 포트를 Caller Leg 할당 포트로 교체
    ...
    # 4. RTCP 속성도 B2BUA 포트로 교체
    ...
    # 5. RTP Relay 시작
    rtp_success = await self._start_rtp_relay(original_call_id)
```

**동작:**
- **Direct 모드**: 
  - SDP를 수정하지 않음
  - RTP Relay를 시작하지 않음
  - 단말간 직접 RTP 통신
- **Bypass/Reflecting 모드**: 
  - SDP를 B2BUA IP/포트로 수정
  - RTP Relay 시작

---

## 📊 **모드별 비교**

| 항목 | Direct | Bypass | Reflecting |
|------|--------|--------|------------|
| **SDP 수정** | ❌ 없음 | ✅ B2BUA IP/포트 | ✅ B2BUA IP/포트 |
| **RTP 중계** | ❌ 없음 | ✅ 중계 | ✅ 중계 |
| **녹음** | ❌ 불가 | ✅ 가능 | ✅ 가능 |
| **AI 분석** | ❌ 불가 | ❌ 불가 | ✅ 가능 |
| **용도** | 테스트 | 녹음/기본 | AI 분석 |

---

## 🧪 **테스트 방법**

### 1. **Direct 모드 활성화**

`config.yaml` 수정:
```yaml
media:
  mode: "direct"
```

### 2. **서버 재시작**

```powershell
.\start-server.ps1
```

### 3. **테스트 통화**

1. 클라이언트 A에서 클라이언트 B로 전화 걸기
2. Wireshark로 RTP 패킷 캡처:
   ```
   udp and (ip.src == CLIENT_A_IP or ip.src == CLIENT_B_IP)
   ```

### 4. **예상 결과**

**Direct 모드:**
- ✅ SIP 시그널링: B2BUA 경유
- ✅ RTP 패킷: **클라이언트 A ↔ 클라이언트 B 직접 통신**
- ✅ Wireshark에서 클라이언트 간 RTP 패킷 관찰 가능

**Bypass 모드 (비교):**
- ✅ SIP 시그널링: B2BUA 경유
- ✅ RTP 패킷: **클라이언트 A ↔ B2BUA ↔ 클라이언트 B**
- ✅ B2BUA 포트 (10000-20000)로 패킷 수신

---

## 📝 **로그 확인**

### Direct 모드 활성화 시 로그:

```json
{
  "event": "sdp_not_modified_direct_mode",
  "call_id": "...",
  "mode": "direct"
}

{
  "event": "direct_media_mode_enabled",
  "call_id": "...",
  "message": "SDP not modified, direct RTP between endpoints"
}
```

### 출력 메시지:

```
🔀 Direct Media Mode: SDP not modified (end-to-end RTP)
```

---

## ⚠️ **주의 사항**

1. **Direct 모드는 테스트 전용**
   - 녹음 불가
   - AI 분석 불가
   - CDR에 `caller_audio_packets: 0` 기록됨

2. **운영 환경에서는 Bypass 또는 Reflecting 사용**
   ```yaml
   media:
     mode: "bypass"  # 녹음/분석 필요 시
   ```

3. **NAT 환경에서 주의**
   - Direct 모드는 클라이언트가 같은 네트워크에 있어야 함
   - NAT 뒤의 클라이언트는 연결 실패 가능

---

## ✅ **검증 항목**

- [x] `MediaMode.DIRECT` enum 추가
- [x] config.yaml에 `mode: "direct"` 설정
- [x] SIPEndpoint MediaMode 변환 로직 수정
- [x] CallManager - INVITE SDP 처리 (Direct 모드 시 수정 안 함)
- [x] SIPEndpoint - 200 OK SDP 처리 (Direct 모드 시 수정 안 함)
- [x] Direct 모드 시 RTP Relay 시작하지 않음
- [x] Linter 에러 없음
- [ ] 실제 통화 테스트 (사용자 수행 필요)
- [ ] Wireshark 패킷 캡처 확인 (사용자 수행 필요)

---

## 🎯 **다음 단계**

1. **테스트 통화 수행**
   - Direct 모드에서 통화 테스트
   - Wireshark로 RTP 패킷 흐름 확인

2. **결과 분석**
   - 클라이언트가 RTP를 전송하는지 확인
   - 패킷이 상대방에게 도달하는지 확인

3. **문제 해결**
   - **RTP 패킷이 보인다면**: 클라이언트는 정상, B2BUA 중계 문제
   - **RTP 패킷이 없다면**: 클라이언트 문제 (설정, 권한, 버그 등)

---

## 📚 **참고 자료**

- RFC 3261 (SIP): Section 13.2.1 (Media Handling)
- RFC 4566 (SDP): Session Description Protocol
- B2BUA vs Direct Media: [VoIP Architecture Comparison]

---

**구현 완료!** ✅
