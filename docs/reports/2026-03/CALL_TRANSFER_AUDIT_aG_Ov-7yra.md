# 호전환 점검: call_id `aG~Ov-7yra`

- **작성일**: 2026-03-25 (로컬)
- **상태**: 분석 완료 + 코드 조치(From 헤더)
- **관련 로그**: `sip-pbx/logs/app.log` (타임스탬프 KST)

## 요약

해당 통화에서 **호전환은 SIP 단에서 실패**했습니다. 서버 로그에 `transfer_rejected`, **400 Bad Request**가 기록되어 있으며, 착신 단말(`172.21.26.109:54065`)이 전환 INVITE를 거절한 것으로 해석됩니다.  
실패 후에도 **원 호 `aG~Ov-7yra`의 AI 파이프라인은 계속 동작**하므로, 운영자 입장에서는 “전환이 안 됐는데 통화는 AI로 유지”로 느껴질 수 있습니다.

## 로그 타임라인 (01:58:31 근처)

| 시각 | 이벤트 |
|------|--------|
| 01:58:31.167 | `media_pair_allocated` (전환 레그 `xfer-leg-c3946cb8-aG~Ov-7y`) |
| 01:58:31.167 | `transfer_invite_sent` → 대상 `1004@172.21.26.109:54065` |
| 01:58:31.184 | `manual_transfer_from_operator` (operator 1004) |
| 01:58:31.184–185 | `transfer_initiated`, `ai_call_transfer_record_created`, 재 `transfer_invite_sent` |
| 01:58:31.199 | `sip_recv` — **400**, `from_addr` 단말 |
| 01:58:31.199 | `transfer_ack_sent`, `ports_released` |
| 01:58:31.200 | **`transfer_rejected`**, `status_code`: 400, `reason`: Bad |

## 원인 분석

1. **400 Bad Request**  
   전환 INVITE의 **`From` 헤더에 `sip:user@host`의 user 부분이 비어 있는 형태**가 되기 쉬웠습니다.  
   `call_transfer.manager.initiate_call_transfer` → `TransferManager.initiate_transfer` 경로에서 `caller_display=""`, `caller_uri=""`로 넘어가고, `send_transfer_invite`가 이를 그대로 쓰면 다음과 유사한 잘못된 메시지가 됩니다.  
   `From: "" <sip:@<b2bua_ip>>`  
   RFC 3261 관점에서 유효하지 않은 URI로, 단말/게이트웨이가 **400**을 반환하는 전형적인 케이스입니다.

2. **“실패가 안 된 것 같다”**  
   전환 실패 시 `_handle_transfer_failure`가 안내 멘트·AI 복귀 등을 시도하고, **원 통화 Call-ID는 유지**됩니다. 로그상 전환 직후에도 STT/TTS 파이프라인 로그가 이어지므로, **전환 실패가 끊김으로 이어지지 않는 것이 정상 동작**에 가깝습니다.  
   다만 대시보드/알림에서 `transfer_failed` 수신 여부는 별도 확인이 필요합니다.

3. **로그 순서**  
   `transfer_invite_sent`가 `manual_transfer_from_operator`보다 앞에 찍힌 것은, 비동기 로깅 큐·또는 **동일 초 내 다른 전환 시도(예: 안내 후 INVITE)** 와 겹칠 때 발생할 수 있습니다. 재현 시 `transfer_invite_caller_id_resolved` 등으로 From 보강 여부를 확인하면 됩니다.

## 코드 조치

- `sip_core/sip_endpoint.py` `send_transfer_invite`:  
  `caller_display`가 비어 있으면 `_active_calls[call_id].caller_username`으로 보강, 그래도 없으면 `"caller"`로 최소 유효 user 사용.  
  `Contact`에도 동일 user를 넣어 단말 호환성 개선.  
  보강 시 `transfer_invite_caller_id_resolved` 로그 추가.

## 권장 확인 사항

- 전환 재시도 후 **200/180** 등 정상 응답 여부.  
- 단말이 **특정 From/PAI 형식**을 요구하면 추가 헤더 검토.  
- 동일 시각 **이중 INVITE**가 의심되면 전환 버튼 중복 클릭·AI 자동 전환과의 경합을 로그로 대조.
