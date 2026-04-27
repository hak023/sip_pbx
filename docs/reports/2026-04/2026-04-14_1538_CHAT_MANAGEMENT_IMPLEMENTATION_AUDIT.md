## 메타

- 작성일: 2026-04-14 (로컬)
- 상태: 코드 점검 (런타임 미검증)
- 범위: 채팅 관리 UI, `/api/chat/*`, `chat_sip_delivery`, `SIPEndpoint.send_chat_sip_message`, 수신 `MESSAGE` 처리

## 개요

요구사항은 **REGISTER 된 착신(UA)으로 SIP MESSAGE 전달**, **상대 UA의 200 OK 수신 여부로 전송 성공/실패 표시 및 재전송**이다. 코드 기준으로 **전달 경로의 뼈대는 있으나, 발신 측은 200 OK를 전혀 보지 않아 “UDP로만 쏘고 곧바로 성공”에 가깝고**, **프로세스/owner 정합성 문제**로 목업처럼 느껴질 수 있다.

## 구현된 것

| 영역 | 내용 |
|------|------|
| REST API | `GET /api/chat/threads`, `GET /api/chat/messages`, `POST /api/chat/send`, `POST /api/chat/retry/{message_id}` (`sip-pbx/src/api/routers/chat.py`) |
| DB | `chat_messages` 저장·조회·재시도 시 `status`/`error_code` 갱신 (`sip-pbx/src/services/chat_service.py`) |
| SIP 발신 | `deliver_chat_sip_message` → `src.main._sip_endpoint.send_chat_sip_message` (`sip-pbx/src/services/chat_sip_delivery.py`) |
| REGISTER 맵 | 수신자·발신자 모두 `_registered_users`에서 `lookup_registered_user`로 조회 후 Contact `ip:port`로 UDP MESSAGE 전송 (`sip-pbx/src/sip_core/sip_endpoint.py` `send_chat_sip_message`) |
| 실패 코드 | 미기동/미연결: `sip_unavailable`; 발신 미등록: `sender_not_registered`; 수신 미등록: `recipient_not_registered`; 등 |
| 프론트 | `sip-pbx/frontend/app/chat/page.tsx` — 대화방 생성, 스레드/메시지 로드, 발신 후 DB 기준 `sent`/`failed` 배지, 실패 시 재전송 버튼 |
| 수신 MESSAGE | `_handle_sip_message_method`에서 **즉시 200 OK** 응답 후 WS 알림 + `chat_messages` inbound 저장 |

## 요구 대비 갭 (핵심)

### 1. 200 OK 기준 전송 성공/실패 — **미구현**

`send_chat_sip_message`는 `socket.sendto` 직후 `success: True`를 반환한다. **원격 UA가 보내는 SIP 응답(200/4xx/5xx)을 수신·매칭·대기하는 트랜잭션 로직이 없다.**

```3344:3356:c:\work\workspace_sippbx\sip-pbx\src\sip_core\sip_endpoint.py
            if not self._socket:
                return {"success": False, "code": "sip_socket_down", "message": "SIP 소켓이 없습니다."}

            self._socket.sendto(message.encode("utf-8"), dest_addr)

            logger.info(
                "chat_sip_message_sent",
                from_user=fk,
                to_user=tk,
                dest_addr=f"{dest_addr[0]}:{dest_addr[1]}",
                body_len=len(body),
            )
            return {"success": True, "code": "", "message": ""}
```

- 프론트의 「전송됨」은 API의 `success` → **실질적으로 “소켓으로 나감”** 수준이다.
- **재전송**도 동일하게 “다시 sendto”만 수행한다.

### 2. “REGISTER 된 착신” — **조건부로만 충족**

- 수신 측 내선이 `_registered_users`에 없으면 `recipient_not_registered`로 실패 처리된다. **의도와 일치.**
- 다만 **발신 측도** `from_user`(API의 `owner`)가 REGISTER 키와 맞아야 한다. 대시보드 `getTenantOwner()`와 SIP 등록 username(예: `1001` vs `+8210…`)이 다르면 **`sender_not_registered`**로 실패하거나, 운영 환경에 따라 혼란이 난다.

### 3. API 프로세스와 SIP 프로세스 분리 시 — **항상 `sip_unavailable`**

`_sip_endpoint`는 `src.main` 기동 시 모듈에 붙인다 (`sip-pbx/src/main.py`). **HTTP API만 별도 워커로 띄우고 SIP가 없는 구성**이면 `deliver_chat_sip_message`가 엔드포인트를 못 찾아 목업처럼 동작한다.

### 4. 수신 저장 `owner` vs 채팅 UI `owner` — **스레드 불일치 가능**

수신 시 `save_chat_message`의 `owner`는 SIP 엔드포인트에서 뽑은 `_owner_id`(설정 기반, 기본 `pbx` 등)이다.

```3187:3195:c:\work\workspace_sippbx\sip-pbx\src\sip_core\sip_endpoint.py
                _owner_id = (
                    getattr(self, '_owner', None)
                    or getattr(getattr(self, 'config', None), 'owner', None)
                    or getattr(getattr(getattr(self, 'config', None), 'sip', None), 'listen_ip', None)
                    or "pbx"
                )
                save_chat_message(
                    thread_id=from_uri,
                    owner=_owner_id,
```

- UI는 `GET ...?owner=<테넌트 로그인>`으로 조회한다.
- **같은 tenant 문자열이 아니면** 소프트폰이 보낸 수신 메시지가 **채팅 관리 목록에 안 보일** 수 있다.

## 요약 표

| 요구 | 현재 |
|------|------|
| REGISTER 착신으로 MESSAGE | 등록 맵 기준 UDP 전송 — **구현됨** (단, 발신자도 등록 필요) |
| 200 OK 후 전송됨/실패 | **미구현** (sendto 즉시 성공) |
| 재전송 | **구현됨** (DB `failed` + API 재시도) — 의미상은 위와 동일 한계 |
| 목업 느낌 원인 | **응답 미대기** + **owner/프로세스 분리** + **수신 owner 키 불일치** |

## 잔여 과제 (구현 방향 제안)

1. ~~MESSAGE 클라이언트 트랜잭션~~ → `2026-04-14_1547_CHAT_SIP_MESSAGE_RELAY_AND_TENANT_DB.md` 에 반영.
2. ~~수신 DB의 `owner`~~ → `chat_relay_settings` + To/R-URI 매핑으로 반영 (동일 리포트).
3. **배포 모델**: API 전용 프로세스라면 SIP 엔드포인트 참조를 IPC/내부 HTTP로 통일 (미변경).
