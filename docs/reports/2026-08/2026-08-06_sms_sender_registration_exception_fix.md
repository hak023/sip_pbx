# 웹사이트/AI 자체응답 발신 시 발신자 SIP REGISTER 요구 완화 — 로직 수정

- 작성일: 2026-08-06
- 상태: 코드 수정 완료(백엔드 재시작 필요, 미검증) — 발신 측만 해결, 수신 측 잔여 이슈 있음
- 관련 문서: [2026-08-06_self_service_sms_sender_not_registered_analysis.md](2026-08-06_self_service_sms_sender_not_registered_analysis.md)

## 사용자 지적

"전화나 문자를 실제 단말로 주고받는 경우는 REGISTER 확인이 맞지만, 웹사이트 자체에서
문자를 보내는 정식 기능(운영 콘솔·셀프서비스 GlobalSmsDock)이나 AI 자체응답처럼 **물리
단말이 아닌 발신자**도 있는데, 이 경우까지 REGISTER를 요구하는 건 예외 처리가 필요하다."

## 코드 확인 — 지적이 맞음

`send_chat_sip_message()`(`src/sip_core/sip_endpoint.py`)에서 발신자(`from_user`) 등록 조회
결과(`from_info`의 `ip`/`port`)는 **실제로 아무 곳에도 쓰이지 않는다** — SIP 패킷의 실제
전송 목적지(`dest_addr`)는 오직 수신자(`to_user`)의 REGISTER 정보로만 결정되고, From 헤더에는
사용자명 문자열(`fk`)만 들어간다. 즉 **발신자 REGISTER 검사는 순수 검증(gate) 목적**이지
전송 로직에 구조적으로 필요한 게 아니었다 — 사용자 지적대로 예외 처리가 안전하게 가능하다.

## 수정 내용

`send_chat_sip_message()`에 `sender_registration_required: bool = True` 파라미터를 추가하고,
`False`이면 발신자 REGISTER 조회를 건너뛰고 `from_user` 문자열을 그대로 From 사용자명으로
쓰도록 했다. 이 값을 `chat_sip_delivery.deliver_chat_sip_message()` → (`_deliver_in_process`/
`_deliver_via_internal_http`) → `sip_internal_http.py`(별도 프로세스 릴레이 경로)까지 전부
관통시켰다.

호출부에서 `sender_registration_required=False`로 지정한 곳(물리 단말이 아닌 발신):

| 파일                                   | 호출부                              | 발신 주체                                                |
| -------------------------------------- | ----------------------------------- | -------------------------------------------------------- |
| `src/api/routers/chat.py`              | `POST /api/chat/send`               | 웹사이트(운영 콘솔·셀프서비스 GlobalSmsDock) 사용자 조작 |
| `src/api/routers/chat.py`              | `POST /api/chat/retry/{message_id}` | 위와 동일(재전송)                                        |
| `src/services/sip_message_ai_reply.py` | AI 자동응답 전송                    | AI가 서버 내부에서 생성한 응답                           |
| `src/services/booking_notify.py`       | 예약 알림(chat_api 채널)            | booking 서비스가 생성한 시스템 알림                      |

기존 동작을 유지해야 하는 다른 호출부(현재는 위 4곳이 전부)는 기본값 `True`라 영향 없음.

## 잔여 이슈 — 수신 측(recipient) 검사는 그대로 남음

**중요**: 이번 수정은 발신 측만 해결한다. `to_user`(수신자) REGISTER 검사는 실제 UDP 전송
목적지(`dest_addr = to_info["ip"], to_info["port"]`)를 결정하는 데 **구조적으로 필수**라 그대로
유지했다. 따라서 원래 보고하신 "owner 9001이 자기 자신에게 문자"(from_user == to_user == 9001,
양쪽 다 실제 단말 없음) 케이스는:

- 이번 수정 전: `sender_not_registered`
- 이번 수정 후: 발신 측 통과 → **`recipient_not_registered`로 오류만 바뀌고 여전히 실패**
  (본인도 실제 단말로 REGISTER되어 있어야 메시지가 실제로 도착할 곳이 정해짐).

이건 셀프서비스 "자기 자신에게 문자 보내기" 시나리오에서 **본인이 실제 SIP 소프트폰으로
REGISTER되어 있지 않으면** 여전히 근본적으로 필요한 제약이다(실제 SIP MESSAGE는 도착 지점이
있어야 하므로). 이걸 완전히 없애려면 "자기 자신에게 보내는 셀프서비스 문의는 실제 SIP 왕복
없이 서버 내부에서 바로 AI 처리 후 결과를 웹 화면에 표시"하는 별도 경로가 필요한데, 이는
이번 수정보다 큰 설계 변경이라 이번 범위에는 포함하지 않았다 — 필요하시면 별도로 계획하겠다.

## 검증 상태

- `ast.parse()`로 수정한 6개 파일 구문 오류 없음 확인.
- **백엔드 재시작 필요**(Python 프로세스는 코드 변경을 자동 반영하지 않음) — 재시작 여부는
  포트 충돌 우려로 사용자 승인 후 진행 예정, 이번 세션에서는 실행 검증 미완료.
- 재시작 후 확인 절차 제안: (1) 실제 고객 번호로 웹 콘솔에서 문자 발송 → 발신자(owner) 쪽
  REGISTER 없이도 성공하는지 확인(recipient만 등록돼 있으면 됨), (2) 자기 자신에게 문자 →
  이제 `recipient_not_registered`로 바뀌는지 확인(발신자 검사 통과 실증).

*최종 업데이트: 2026-08-06*
