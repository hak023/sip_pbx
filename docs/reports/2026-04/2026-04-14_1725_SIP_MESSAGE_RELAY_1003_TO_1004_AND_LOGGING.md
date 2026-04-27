## 메타

- 작성일: 2026-04-14
- 상태: 구현 완료
- 관련: SIP MESSAGE 1003→1004 미도착, 전송·수신 로그

## 개요

소프트폰이 PBX로 보낸 **인바운드 SIP MESSAGE**는 기존에 200 OK·DB·WebSocket까지만 처리하고 **Request-URI(또는 To) 상대 내선으로의 UDP 릴레이가 없어** 1004 단말에 도착하지 않을 수 있었다. **양쪽 내선이 REGISTER 맵에 있을 때** `send_chat_sip_message`로 상대 Contact에 전달하는 릴레이를 추가했고, 수신·릴레이·UDP 송신·MESSAGE 최종 응답 매칭을 **structlog INFO**로 남기도록 보강했다.

## 변경 이력 (파일별)

| 파일 경로 | 변경 유형 | 요약 | 비고 |
|-----------|-----------|------|------|
| `sip-pbx/src/sip_core/sip_endpoint.py` | 수정 | `_handle_sip_message_method`: `sip_message_received`에 `to_user`·`ruri_user`·`body_preview`; DB 저장 INFO; **릴레이** `asyncio.create_task` + `asyncio.to_thread(send_chat_sip_message)`; 스킵 시 `sip_message_relay_skipped` | 설계대로 |
| `sip-pbx/src/sip_core/sip_endpoint.py` | 수정 | `send_sip_message` / `send_chat_sip_message`: `sip_message_sent`·`sip_message_udp_sent`에 `body_preview`·`kind` | 설계대로 |
| `sip-pbx/src/sip_core/sip_endpoint.py` | 수정 | MESSAGE 응답 트랜잭션 매칭 로그 `sip_message_response_matched` (INFO) | 설계대로 |

## 주요 결정 사항

- 릴레이 조건: `from_uri != to_user` 이고 **발신·수신 user 모두** `_registered_users`에 있을 때만 (무분별 오픈 릴레이 방지).
- `send_chat_sip_message` 내부 `threading.Event.wait`는 **이벤트 루프 블로킹을 피하기 위해** `asyncio.to_thread`로 실행.

## 잔여 과제

- 한쪽만 등록된 경우는 `sip_message_relay_skipped`로만 남음 — 1004 미등록·NAT·Contact 불일치 시 운영자가 로그로 확인.
