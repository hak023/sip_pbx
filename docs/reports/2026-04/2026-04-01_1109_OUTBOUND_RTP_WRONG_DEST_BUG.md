# Outbound AI Bot RTP 목적지 버그 분석 리포트

| 항목 | 내용 |
|------|------|
| 작성일 | 2026-04-01 11:09 |
| 상태 | **버그 확인됨 (미수정)** |
| 증상 | Outbound AI 통화 시작부터 수신자에게 아무 소리도 들리지 않음 |
| 관련 call_id | `outbound-ob-627eba51-60219613`, `outbound-ob-9ae67cdb-51372347` |
| 관련 파일 | `src/sip_core/sip_endpoint.py:4333`, `src/media/rtp_relay.py:1589` |

---

## 1. 증상 요약

Outbound AI 봇 통화에서 TTS는 정상 동작(로그 확인)하고 RTP 패킷도 전송(TSV dump 확인)되지만 **수신자(착신 전화기)에게 음성이 전혀 들리지 않는다.**

---

## 2. 핵심 버그: RTP 목적지 주소 오설정

### 2.1 증거 — TSV dump 분석

| 항목 | 실제 값 | 올바른 값 |
|------|---------|----------|
| TSV `dest` (RTP 실제 송신지) | `10.254.125.243:10000` | `10.254.125.243:60049` (callee_rtp_port) |
| 두 번째 call_id TSV dest | `10.254.125.243:10000` | `10.254.125.243:36351` (callee_rtp_port) |

```
# rtp_tx_outbound-ob-9ae67cdb-51372347.tsv 전체 438패킷
dest = '10.254.125.243:10000'  ← B2BUA 자신의 로컬 포트
# 착신자 실제 RTP 포트: 60049 (SDP에서 협상됨)

# rtp_tx_outbound-ob-627eba51-60219613.tsv 전체 1084패킷
dest = '10.254.125.243:10000'  ← B2BUA 자신의 로컬 포트
# 착신자 실제 RTP 포트: 36351 (SDP에서 협상됨)
```

**모든 패킷이 착신자(수신 전화기)가 아닌 B2BUA 자신의 RTP 소켓 포트(10000)로 전송되고 있다.**

---

## 3. 버그 근본 원인

### 3.1 코드 위치: `sip_endpoint.py` L4333

```python
# src/sip_core/sip_endpoint.py:4333-4337
caller_endpoint = RTPEndpoint(ip=callee_ip, port=local_rtp_port)   # ← 버그 지점
callee_endpoint = RTPEndpoint(
    ip=callee_ip,
    port=callee_rtp_port if callee_rtp_port else local_rtp_port,
)
```

**Outbound 콜에서 `caller_endpoint`에 `local_rtp_port`(B2BUA 자신이 bind한 포트 = 10000)를 할당하고 있다.**

Outbound 구조에서는:
- `local_rtp_port` = B2BUA가 INVITE SDP에 넣은 포트 (자신의 수신용) = **10000**
- `callee_rtp_port` = 착신자 200 OK SDP에서 파싱한 포트 (착신자의 수신용) = **60049/36351**

### 3.2 코드 위치: `rtp_relay.py` L1589-1590 (PCM 송신 스레드)

```python
# src/media/rtp_relay.py:1589-1590
caller_ip = str(self.caller_endpoint.ip)
caller_port = int(self.caller_endpoint.port)   # ← 10000 사용
```

PCM 송신 스레드가 TTS→RTP 변환 후 UDP 큐에 `(packet, (caller_ip, caller_port))` 튜플을 넣는다.  
`caller_endpoint.port`가 10000이므로 **모든 TTS 패킷이 착신자가 아닌 B2BUA 자신에게 전송된다.**

### 3.3 Outbound 콜 RTP 역할 정의

```
정상 인바운드 콜:
  Caller(전화기) ←→ B2BUA:10000 ←→ Callee(착신)
  TTS 음성 → caller 방향으로 전송 = caller_endpoint가 전화기 포트 ✅

Outbound AI 봇 콜:
  B2BUA:10000 ──(INVITE)──▶ Callee(착신 전화기):60049
  TTS 음성 → callee 방향으로 전송해야 함
  ∴ caller_endpoint.port = 10000 (B2BUA 자신) ← 전송 목적지로 사용하면 ❌
```

**Outbound 콜에서 AI TTS 오디오는 `callee_endpoint`(착신자)로 전송해야 하지만,  
`caller_endpoint`(B2BUA 자신)로 전송되고 있다.**

---

## 4. 로그 보조 증거

```json
// pipecat_mode_enabled 이벤트
{
  "event": "pipecat_mode_enabled",
  "caller_endpoint": "10.254.125.243:10000",  // B2BUA 자신의 bind 포트
  "has_transport": true
}

// outbound_rtp_worker_started 이벤트
{
  "event": "outbound_rtp_worker_started",
  "bind_ip": "0.0.0.0",
  "callee_ip": "10.254.125.243",
  "callee_rtp_port": 60049,   // 착신자 실제 수신 포트
  "local_rtp_port": 10000     // B2BUA 자신의 포트
}

// rtp_first_packet_sent 이벤트
{
  "event": "rtp_first_packet_sent",
  "dest_ip": "10.254.125.243",
  "dest_port": 10000,   // ← 착신자 포트(60049)가 아님!
}
```

---

## 5. 왜 에러 로그가 없는가?

`rtp_tts_send_errors = 0`, `bypass_relay_send_failed = 0` — UDP sendto 자체는 성공한다.  
B2BUA의 10000 포트가 `0.0.0.0:10000`으로 bind되어 있으므로 루프백 패킷을 수신하지만, 그것을 처리할 코드가 없어 조용히 버려진다. 에러가 발생하지 않아 탐지가 어려웠다.

---

## 6. 수정 방안

### 방안 A: `caller_endpoint` 할당 수정 (권장)

`sip_endpoint.py:4333`에서 outbound 콜의 `caller_endpoint`를 올바른 값으로 설정한다.

```python
# 수정 전 (버그)
caller_endpoint = RTPEndpoint(ip=callee_ip, port=local_rtp_port)

# 수정 후 — outbound는 TTS를 callee에게 보내야 하므로
# caller_endpoint를 실제 착신자 RTP 포트로 설정
caller_endpoint = RTPEndpoint(ip=callee_ip, port=callee_rtp_port if callee_rtp_port else local_rtp_port)
callee_endpoint = RTPEndpoint(ip=callee_ip, port=local_rtp_port)
```

> **주의**: `caller_endpoint` / `callee_endpoint` 의미가 인바운드와 다르므로 명칭 혼란을 야기한다. 아래 방안 B 병행 권장.

### 방안 B: `enable_pipecat_mode` 에서 outbound용 전송 목적지 별도 처리

`_pcm_sender_thread_main` 내부에서 `caller_endpoint` 대신 `callee_endpoint`를 사용하는 outbound 전용 경로를 추가한다.

```python
# rtp_relay.py:1589 수정
if self.ai_mode and getattr(self, '_is_outbound_call', False):
    dest_ip = str(self.callee_endpoint.ip)
    dest_port = int(self.callee_endpoint.port)
else:
    dest_ip = str(self.caller_endpoint.ip)
    dest_port = int(self.caller_endpoint.port)
```

`sip_endpoint.py`에서 outbound RTP 워커 생성 후:
```python
rtp_worker._is_outbound_call = True
```

### 방안 C: outbound 전용 RTP 전송 목적지 필드 추가 (근본적 해결)

`RTPRelayWorker`에 `tts_dest_endpoint` 필드를 명시적으로 추가하여 인바운드/아웃바운드 혼용 혼란을 제거한다.

```python
# rtp_relay.py __init__ 또는 enable_pipecat_mode
self.tts_dest_endpoint: Optional[RTPEndpoint] = None  # TTS RTP를 보낼 실제 목적지

# _pcm_sender_thread_main에서
dest_ep = self.tts_dest_endpoint or self.caller_endpoint
caller_ip = str(dest_ep.ip)
caller_port = int(dest_ep.port)
```

---

## 7. 영향 범위

| 항목 | 영향 |
|------|------|
| Inbound AI 콜 | **영향 없음** — caller_endpoint가 실제 전화기 포트로 설정됨 |
| Outbound AI 봇 콜 | **전수 영향** — TTS 오디오 전혀 전달 안됨 |
| 통화 연결 자체 | **영향 없음** — SIP 시그널링 정상, 착신자가 전화 받을 수 있음 |
| 착신자 → B2BUA 음성 | **영향 없음** — STT/수신 경로는 별도 |

---

## 8. 결론

Outbound AI 봇 통화에서 TTS 음성이 들리지 않는 근본 원인은 **RTP 패킷의 UDP 목적지 주소가 착신자 포트가 아닌 B2BUA 자신의 로컬 바인드 포트(10000)로 잘못 설정**된 것이다.

- `sip_endpoint.py:4333`에서 `caller_endpoint = RTPEndpoint(ip=callee_ip, port=local_rtp_port)` 가 버그의 출발점
- 438개(9ae67cdb) 및 1084개(627eba51) 패킷 전량이 착신자가 아닌 B2BUA 자신에게 전송됨
- sendto 자체는 성공하므로 에러 로그가 없어 탐지가 어려웠음

**즉시 수정 필요 (방안 A 또는 C 권장)**
