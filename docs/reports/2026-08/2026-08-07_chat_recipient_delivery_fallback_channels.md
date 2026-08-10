# 수신자 미등록 시 3가지 도착 경로 중 하나면 성공 처리 — 로직 확장

- 작성일: 2026-08-07
- 상태: 코드 수정 완료(백엔드 재시작 필요, 미검증)
- 관련 문서: [2026-08-06_sms_sender_registration_exception_fix.md](../2026-08/2026-08-06_sms_sender_registration_exception_fix.md)

## 요청 배경

이전 수정(발신자 REGISTER 예외 처리)에서 "수신자가 REGISTER 안 되어 있으면 여전히
`recipient_not_registered`로 실패한다"고 안내했더니, 사용자가 "실패하면 안 된다 — 도착
지점은 (1) REGISTER된 수신 단말 (2) 서버에 로그인된 유저에게 알림 (3) 설정에 따라 서버의
AI가 직접 받아줌, 이 셋 중 하나라도 되면 성공 처리하라"고 요구했다.

## 코드 확인

- (2) "로그인된 사용자에게 알림": 시스템이 실제 SIP MESSAGE 수신 시 이미
  `emit_sip_message_received()`로 대시보드 SMS 도크에 브로드캐스트하는 경로가 있었다
  (`src/websocket/server.py`). 이걸 수신자 미등록 상황에서도 그대로 재사용할 수 있다.
- (3) "설정에 따라 AI가 받아줌": `chat_relay_settings.message_ai_reply_enabled`(채팅 설정
  화면의 "SIP MESSAGE 수신 시 AI 자동응답")이 이미 존재하고, 그 처리 함수
  `schedule_sip_message_ai_reply()`(`src/services/sip_message_ai_reply.py`)는 실제 inbound
  MESSAGE 유무와 무관하게 호출 가능한 순수 함수였다 — 실제 REGISTER된 단말 없이도 그대로
  재사용 가능.

## 수정 내용

`send_chat_sip_message()`(`src/sip_core/sip_endpoint.py`)의 수신자 REGISTER 검사를,
등록 안 됐을 때 곧바로 실패시키지 않고 신규 `_deliver_chat_message_virtual()`을 호출하도록
변경했다.

```python
tk, to_info = self.lookup_registered_user(to_user)
if not tk or not to_info:
    return self._deliver_chat_message_virtual(fk, to_user, body, suppress_ai_loop=suppress_ai_loop)
```

`_deliver_chat_message_virtual()`은:
1. `schedule_socket_emit("sip_message_received", ...)`로 대시보드에 항상 알림 브로드캐스트
   (경로 2, best-effort — 실제 로그인 여부를 서버가 확인할 방법이 없어 항상 시도한다는 점은
   실제 MESSAGE 수신 시 기존 동작과 동일한 수준의 보장이다).
2. `chat_relay_settings.message_ai_reply_enabled`가 켜져 있으면(`suppress_ai_loop`가 아닐 때)
   `schedule_sip_message_ai_reply()`를 새 웹소켓 이벤트 루프 헬퍼(`schedule_coroutine()`,
   `src/websocket/server.py` 신규)로 예약해 셀프서비스 AI가 실제로 응답을 생성·발송하게 한다
   (경로 3). 이 경우 `code="delivered_ai_self_service"`로 성공 반환.
3. AI 자동응답이 꺼져 있으면 `code="delivered_web_notification"`으로 성공 반환(경로 2만
   해당).

실제 SIP UDP 전송은 발생하지 않으므로(등록된 단말이 없으니 보낼 곳도 없음) 이 경로에서는
`sip_timeout` 등 전송 관련 오류가 나지 않는다.

## 회귀 영향

- 수신자가 실제로 REGISTER된 경우(정상 케이스)는 기존 로직(UDP 전송 + 2xx 대기) 그대로
  유지 — 이번 변경은 "등록 안 됨" 분기에서만 동작한다.
- `suppress_ai_loop=True`로 호출되는 경로(AI 자신이 보낸 응답이 다시 이 함수를 타는 경우)는
  AI 재귀 응답을 만들지 않도록 그대로 존중한다.

## 검증 상태

- `ast.parse()`로 구문 오류 없음 확인.
- **백엔드 재시작 필요** — 재시작 후 확인 절차: owner=9001로 자기 자신에게 문자 전송 →
  `chat_send_done` 로그의 `code`가 `delivered_ai_self_service`(AI 자동응답 켜진 경우) 또는
  `delivered_web_notification`(꺼진 경우)로 나오는지, 그리고 AI 자동응답 활성 시
  `self_service_decision_log`/채팅 스레드에 실제 AI 응답이 저장되는지 확인 필요.

*최종 업데이트: 2026-08-07*
