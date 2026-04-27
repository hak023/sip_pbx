## 메타

- 작성일: 2026-04-14 (로컬)
- 상태: 구현 완료
- 관련: `sip-pbx/src/sip_core/sip_endpoint.py`, SIP MESSAGE 릴레이·서버 푸시

## 개요

`listen_ip`가 `0.0.0.0`일 때 발신 SIP MESSAGE의 `Via` / `From` / `Call-ID` 호스트에 `0.0.0.0`이 들어가 일부 UA·NAT 환경에서 전달·응답 매칭이 불안정할 수 있다. B2BUA SDP용과 동일한 `_get_b2bua_ip()`(advertised_ip → 비 0 listen_ip → 자동 감지)로 SIP 헤더용 호스트를 통일했다.

## 변경 이력 (파일별)

| 파일 경로 | 변경 유형 | 요약 | 비고 |
|-----|-----|---|---|
| `sip-pbx/src/sip_core/sip_endpoint.py` | 수정 | `send_sip_message`, `send_chat_sip_message`에서 헤더 호스트를 `_get_b2bua_ip()`로 설정 | 설계대로 |
| `sip-pbx/src/sip_core/sip_endpoint.py` | 수정 | `sip_message_sent` / `sip_message_udp_sent` 로그에 `sip_header_host` 추가 | 운영 확인용 |

## 주요 결정 사항

- 새 헬퍼를 만들지 않고 기존 `_get_b2bua_ip()`를 재사용해 INVITE/B2BUA와 동일한 광고 IP 정책을 유지한다.
- UDP 목적지(`dest_addr`)는 등록 Contact 그대로이며, 본 변경은 **SIP 시맨틱용 헤더**만 보정한다.

## 잔여 과제 (선택)

- `isComposing` 릴레이를 특정 클라이언트에서 숨기거나 필터하는 옵션은 미구현(클라이언트 정책에 따라 필요 시).
