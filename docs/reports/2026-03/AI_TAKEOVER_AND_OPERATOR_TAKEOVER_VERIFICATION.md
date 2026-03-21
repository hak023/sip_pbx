# AI 모드 vs 상담원 Takeover 검증

**작성일**: 2026-03-11  
**목적**: AI 모드에서의 RTP/callee 리다이렉트 수정이 상담원 takeover(호 전환)와 충돌하지 않음을 확인

---

## 1. 흐름 요약

| 구간 | 동작 |
|------|------|
| **AI 모드** | Caller ↔ 서버(AI). callee 측 소켓(callee_audio_rtp/rtcp)의 `remote_endpoint`를 Caller로 설정해 TTS가 Caller로 전달되도록 함. |
| **상담원 Takeover** | TransferManager가 INVITE → 200 OK 수신 후 `switch_to_bridge_mode` 호출 → RTP Worker의 `set_bridge_mode()` 실행. |
| **Bridge 모드** | Caller ↔ 서버 ↔ New Callee(상담원). **새로 만든 bridge 소켓**만 사용. 기존 callee_audio_rtp/rtcp는 relay 경로에 사용되지 않음. |

---

## 2. RTP Relay 처리 순서 (datagram_received)

1. **BRIDGE 모드**  
   - `relay_mode == RelayMode.BRIDGE`이면  
     - `caller_audio_rtp` → `bridge_callee_transport`(상담원)  
     - `bridge_callee_rtp` → `caller_audio_transport`(발신자)  
   - 여기서 사용하는 것은 **bridge_callee_transport / bridge_callee_rtp**만 해당.

2. **AI 모드**  
   - `ai_mode == True`이면  
     - `caller_audio_rtp`만 `on_packet_received`(AI 파이프라인)  
     - 나머지 소켓 타입은 relay 없이 return.  
   - **callee_audio_rtp/rtcp의 remote_endpoint는 이 구간에서 relay에 쓰이지 않음** (AI 모드에서는 callee로 보내지 않음).

3. **invalid_remote 검사**  
   - BRIDGE일 때는 1번에서 이미 return.  
   - AI 모드일 때는 2번에서 return.  
   - 따라서 **상담원 takeover 후 Bridge 모드**에서는 callee_audio 쪽 remote 검사로 넘어가지 않음.

---

## 3. set_bridge_mode() 동작

- `ai_mode = False`, `relay_mode = RelayMode.BRIDGE` 설정.
- **새 소켓** `bridge_callee_rtp` 생성 (New Callee ↔ 서버).
- Caller → New Callee: `caller_audio_rtp` 수신 → `bridge_callee_transport.sendto(..., bridge_callee_endpoint)`.
- New Callee → Caller: `bridge_callee_rtp` 수신 → `caller_audio_transport.sendto(..., caller_endpoint)`.

즉, **상담원(New Callee)과의 미디어는 전부 bridge 소켓으로만** 처리됨.  
기존 **callee_audio_rtp/rtcp는 Bridge 모드 relay 경로에 관여하지 않음**.

---

## 4. 결론

- **AI 모드에서 callee_audio_rtp/rtcp의 remote_endpoint를 Caller로 바꾸는 수정**은  
  - AI 구간에서만 의미 있음 (TTS → Caller, invalid_remote 방지).  
  - **상담원 takeover 후에는 relay가 Bridge 전용**이므로 이 설정과 **충돌 없음**.
- 상담원 takeover는 **동일한 `switch_to_bridge_mode` → `set_bridge_mode`** 경로를 타며,  
  **Bridge 모드에서만** bridge 소켓을 사용하므로, 기존 callee 소켓 설정과 무관하게 동작함.

**정리**: AI 모드용 callee 리다이렉트는 **상담원 takeover 로직까지 고려된 상태**이며, takeover 시 별도 조치 없이 Bridge 모드로 정상 전환됨.
