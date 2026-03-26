# 호 전환 — 발신 SIP 미갱신 전제에서의 SDP·미디어 릴레이 점검

- **작성일**: 2026-03-23  
- **질의**: 발신 쪽 SIP(재-INVITE 등)는 수행하지 않을 때, **전환 INVITE SDP**와 **착신 200 OK SDP**를 고려해 미디어를 릴레이하는지.

---

## 1. 결론

**예, 현재 구현은 그 전제를 반영한다.**

- **발신자 단말**은 전환 후에도 **기존과 동일한 B2BUA 측 RTP 목적지**로 패킷을 보내는 경로를 유지할 수 있고(발신 측 SIP 갱신 불필요),  
- **전환 레그**는 B2BUA가 **새 `bridge_ports`로 INVITE SDP를 만들어** 착신이 그 포트로 미디어를내도록 하며,  
- **착신 200 OK 본문 SDP**에서 **IP·오디오 RTP 포트**를 파싱해 `RTPRelayWorker.set_bridge_mode`에 넘겨 **Caller ↔ Bridge 소켓 ↔ New Callee** 릴레이를 연다.

즉 “INVITE 쪽 SDP(서버가 제안한 수신 포트) + 200 OK SDP(착신의 RTP 엔드포인트)” 조합으로 릴레이가 구성된다.

---

## 2. 시그널링 흐름 (요약)

| 단계 | 위치 | 내용 |
|------|------|------|
| INVITE (전환) | `SIPEndpoint.send_transfer_invite` | 대상으로 INVITE. SDP는 **B2BUA IP + `bridge_ports`(RTP/RTCP)** — 착신이 **서버의 bridge RTP 포트**로 송신하도록 제안. |
| 200 OK | `SIPEndpoint.handle_transfer_response` | `status_code == 200`이면 **`_extract_sdp_body` → `callee_sdp`**, ACK 후 `TransferManager.on_transfer_answered(..., callee_sdp)`. |
| 브릿지 전환 | `TransferManager.on_transfer_answered` | AI 중단(`_stop_ai_cb`) 후 `_switch_to_bridge_cb` → `SIPEndpoint.switch_to_bridge_mode(call_id, transfer_leg_call_id, callee_sdp)`. |
| SDP 파싱 | `switch_to_bridge_mode` | `SDPParser.parse(callee_sdp)`로 **connection IP**, **audio `m=` port** 추출. 실패 시 `target_addr` IP와 **fallback 포트**(bridge 포트) 사용(비정상 시 오동작 가능). |
| RTP | `RTPRelayWorker.set_bridge_mode` | `bridge_rtp_port`에 **전용 datagram 소켓** 바인딩(`bridge_callee_rtp`). `bridge_callee_endpoint` = 착신 RTP (200 OK에서 읽은 값). |

---

## 3. RTP 릴레이 (발신 SIP 없이)

`RTPRelayProtocol.datagram_received` — `relay_mode == BRIDGE`일 때 (`rtp_relay.py`):

- **`caller_audio_rtp`**: 발신에서 들어온 RTP → **`bridge_callee_transport.sendto(..., bridge_callee_endpoint)`** → 착신이 200 OK에 알린 주소/포트로 전달.  
- **`bridge_callee_rtp`**: bridge 포트로 들어온 RTP(착신→서버) → **`caller_audio_transport.sendto(..., caller_endpoint)`** → 발신 쪽으로 전달.

발신 단말에 대한 **SIP 재협상** 없이, **이미 열려 있는 caller 측 RTP 소켓 경로**를 그대로 쓴다.

---

## 4. 주의·한계 (점검 메모)

1. **코덱 협상**: 전환 INVITE SDP는 PCMU/PCMA/telephone-event 등 고정 형태에 가깝고, 릴레이는 **바이트 그대로 포워딩**에 가깝다. 200 OK에서 **다른 PT만 선택**되면 **트랜스코딩 없으면** 음질/호환 문제 가능.  
2. **SDP 파싱 실패 시 fallback**: `callee_ip` / `callee_rtp_port`를 못 얻으면 `target_addr[0]`과 **`bridge_rtp_port`를 callee 포트처럼** 쓰는 분기가 있어, 그 경우 **착신 RTP 주소가 틀릴 수 있음**.  
3. **RTCP**: 브릿지 경로는 위 인용 위주로 **RTP**를 명시적으로 다룬다. RTCP 대칭 처리는 별도 분기·테스트 필요할 수 있음.  
4. **INVITE SDP vs “발신자 원 SDP”**: 전환 INVITE는 **발신자가 원래 받은 200 OK SDP를 그대로 복사해 착신에 넣지 않는다.** B2BUA가 **새 bridge 포트**를 제안하는 전형적인 **3pcc/B2BUA** 패턴이다. 발신 **미디어 경로**는 “기존 caller↔B2BUA 소켓”이 유지되고, **착신 미디어**만 200 OK로 학습한다는 점에서 질문하신 “발신 SIP 안 하고 릴레이”와 정합한다.

---

## 5. 관련 파일

- `src/sip_core/sip_endpoint.py` — `send_transfer_invite`, `handle_transfer_response`, `switch_to_bridge_mode`  
- `src/sip_core/transfer_manager.py` — `on_transfer_answered`  
- `src/media/rtp_relay.py` — `set_bridge_mode`, `RelayMode.BRIDGE`, `datagram_received` 브릿지 분기  
