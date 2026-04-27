## 메타

- 작성일: 2026-04-15
- 상태: 완료
- 관련: `src/sip_core/sip_endpoint.py`, `src/websocket/server.py`, `frontend/app/chat/page.tsx`

## 개요

SIP MESSAGE 수신 시 `utf-8` + `surrogateescape` 로 디코딩된 본문에 단일 서로게이트가 포함되면 structlog·SIP 트래픽 파일 로그·`print` 가 `UnicodeEncodeError` 로 실패해 `_handle_sip_message_method` 전체가 예외 처리되었다. 표시·저장·WS용으로 치환 문자열을 분리하고, 릴레이 UDP 전송은 원본 `body` 를 유지한다. 웹 채팅 화면은 `sip_message_received` 를 구독하지 않아 DB 저장 후에도 UI가 갱신되지 않았으므로 `useWebSocket` + 스레드 매칭 시 `loadThreads` / `loadMessages` 를 호출하고, WS 페이로드에 `to_user` 를 추가했다.

## 변경 이력 (파일별)

| 파일 경로 | 변경 유형 | 요약 | 비고 |
|-----|-----|---|---|
| `sip-pbx/src/sip_core/sip_endpoint.py` | 수정 | `_sanitize_sip_text_for_utf8_io`, 파일 로그·sip_recv_raw·MESSAGE 로그/DB/WS 표시용 | 릴레이 `body_` 는 원본 |
| `sip-pbx/src/websocket/server.py` | 수정 | `emit_sip_message_received(..., to_user=)` | |
| `sip-pbx/frontend/app/chat/page.tsx` | 수정 | `useWebSocket`, `sip_message_received` 구독, `normPeer` | |
| `sip-pbx/docs/reports/2026-04/2026-04-15_1830_SIP_MESSAGE_SURROGATE_AND_CHAT_WS.md` | 추가 | 본 리포트 | |

## 주요 결정 사항

- 채팅 DB·운영자 WS는 **UTF-8 안전 문자열**만 쓰고, **상대 UA로 나가는 SIP MESSAGE** 는 기존 바이트 보존 `body` 유지.

## 잔여 과제 (선택)

- 대시보드 등 다른 화면에서도 SIP 문자 알림이 필요하면 동일 이벤트 구독 패턴 적용.
