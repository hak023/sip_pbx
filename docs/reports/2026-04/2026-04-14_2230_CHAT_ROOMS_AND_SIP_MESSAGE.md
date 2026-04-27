## 메타

- 작성일: 2026-04-14 (로컬)
- 상태: 구현 반영
- 관련: `sip-pbx/frontend/app/chat/page.tsx`, `sip-pbx/src/api/routers/chat.py`, `sip-pbx/src/services/chat_service.py`, `sip-pbx/src/services/chat_sip_delivery.py`, `sip-pbx/src/sip_core/sip_endpoint.py`, `sip-pbx/src/booking/database.py`

## 개요

「채팅 관리」에서 대화방 생성(상대 착신번호 입력)·메시지 전송 시 **REGISTER 맵**을 사용한 SIP MESSAGE 발신, 성공/실패 표시, 실패 건 **재전송**을 구현했다. API는 실패 시에도 HTTP 200 + `success: false` 로 내려 DB에 실패 행을 남기고 UI에서 재시도할 수 있게 했다.

## 변경 이력 (파일별)

| 파일 경로 | 변경 유형 | 요약 |
|-----------|------------|------|
| `sip-pbx/frontend/app/chat/page.tsx` | 추가 | 대화방 만들기 모달, 스레드/메시지 목록, 전송·실패·재전송 UI |
| `sip-pbx/src/api/routers/chat.py` | 수정 | `deliver_chat_sip_message` 연동, `ChatSendResponse` 확장, `POST /api/chat/retry/{id}` |
| `sip-pbx/src/services/chat_sip_delivery.py` | 추가 | `src.main._sip_endpoint.send_chat_sip_message` 호출 래퍼 |
| `sip-pbx/src/sip_core/sip_endpoint.py` | 수정 | `send_chat_sip_message`, `lookup_registered_user`, From=발신 내선 |
| `sip-pbx/src/services/chat_service.py` | 수정 | `error_code` 저장, `get_message_by_id`, `update_message_after_retry` |
| `sip-pbx/src/booking/database.py` | 수정 | `chat_messages.error_code` 컬럼 + 마이그레이션 |
| `sip-pbx/frontend/components/call-history/CallHistoryPanel.tsx` | 수정 | 채팅 전송 응답 `detail` 표시 보강 |

## 주요 결정 사항

- **동일 프로세스**: `deliver_chat_sip_message`는 `src.main`의 `_sip_endpoint`가 있을 때만 REGISTER 기반 전송이 가능하다. API만 단독 기동 시 `sip_unavailable` 로 실패·DB 기록.
- **발신 From**: PBX 고정값이 아니라 `<sip:{발신owner}@{listen_ip}>` 형태로 등록 내선과 일치시킨다.
- **재전송**: 동일 `chat_messages` 행의 `status`/`error_code`만 갱신한다.

## 잔여 과제 (선택)

- SIP 200 OK 대기 기반의 확정 “전달 완료” 판별.
- 수신 MESSAGE의 `thread_id`/`owner`를 To 헤더 기준으로 정교화.
