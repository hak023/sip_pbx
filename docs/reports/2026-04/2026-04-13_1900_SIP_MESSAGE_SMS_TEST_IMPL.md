# SIP MESSAGE (RFC 3428) 구현 리포트 — Linphone SMS 테스트 대용

- **작성일**: 2026-04-13 19:00
- **상태**: 구현 완료
- **분류**: 신규 기능 구현
- **관련 리포트**: `2026-04-13_1800_SMS_RESERVATION_NOTIFICATION_INSPECTION.md`

---

## 개요

Linphone 소프트폰의 SIP MESSAGE 기능을 활용해 실제 SMS 없이 예약 알림·확인 문자 시나리오를 테스트할 수 있도록 SIP MESSAGE 수신/발신 기능을 구현했다. 기존에는 MESSAGE 메서드가 `else` 분기로 빠져 501 Not Implemented가 반환되었으나, 이제 완전히 처리된다.

---

## 변경 이력 (파일별)

| 파일 경로 | 변경 유형 | 요약 |
|-----------|-----------|------|
| `sip-pbx/src/sip_core/sip_endpoint.py` | 수정 | MESSAGE 분기 추가, `_handle_sip_message_method()`, `send_sip_message()` 신규 메서드 |
| `sip-pbx/src/websocket/server.py` | 수정 | `emit_sip_message_received()` 함수 추가 |
| `sip-pbx/src/api/routers/messages.py` | **신규** | `POST /api/messages/send`, `GET /api/messages/registered` 엔드포인트 |
| `sip-pbx/src/api/main.py` | 수정 | messages 라우터 등록 |
| `sip-pbx/src/main.py` | 수정 | `_sip_endpoint` 전역 노출 (`messages.py`에서 접근) |

---

## 구현 상세

### 1. SIP MESSAGE 수신 — `_handle_sip_message_method()`

`sip_endpoint.py`의 메서드 분기에 `elif method == 'MESSAGE':` 를 추가했다.

```
Linphone → [SIP MESSAGE UDP] → sip_endpoint._handle_sip_message_method()
                                    ├─ 200 OK 응답 반환 (RFC 3428 §4)
                                    ├─ 로그 출력 (콘솔 + sip_traffic.log)
                                    └─ WebSocket emit_sip_message_received() → 대시보드
```

**RFC 3428 준수 사항:**
- 200 OK에 Via / From / To / Call-ID / CSeq 동일하게 에코
- Content-Type: text/plain (Linphone 기본값) 지원
- Allow 헤더에 MESSAGE 추가

### 2. SIP MESSAGE 발신 — `send_sip_message()`

서버가 먼저 소프트폰에 문자를 보내는 아웃바운드 경로.

```
API POST /api/messages/send
    → messages.py → endpoint.send_sip_message(to_uri, body)
        → _registered_users 에서 IP:port 조회
        → UDP SIP MESSAGE 패킷 전송 → Linphone 팝업
```

**등록 선행 조건:** Linphone이 먼저 REGISTER 해야 IP:port를 알 수 있다.

### 3. WebSocket 이벤트 — `sip_message_received`

운영자 대시보드가 Socket.IO로 구독 중이면 수신 메시지가 실시간으로 전달된다.

```json
{
  "event": "sip_message_received",
  "data": {
    "from_uri": "1001",
    "from_addr": "192.168.1.100:5060",
    "body": "[예약확인] 내일 오후 2시 예약 확정되었습니다.",
    "content_type": "text/plain",
    "call_id": "abc123@192.168.1.100",
    "timestamp": "2026-04-13T10:00:00Z"
  }
}
```

### 4. REST API

| 메서드 | 경로 | 설명 |
|--------|------|------|
| `POST` | `/api/messages/send` | 서버 → Linphone 메시지 발신 |
| `GET` | `/api/messages/registered` | 현재 등록된 SIP 사용자 목록 |

**`POST /api/messages/send` 요청 예시:**
```json
{
  "to": "1001",
  "body": "[예약확인] 내일 오후 2시 예약이 확정되었습니다. 취소: 02-0000-0000"
}
```

---

## 테스트 방법 (Linphone 기준)

### Linphone → 서버 메시지 전송

1. Linphone 실행 → SIP 계정 등록 (서버 IP, 포트 5060)
2. 대화상대 추가: `sip:pbx@{서버IP}`
3. 채팅창 열기 → 메시지 입력 → 전송
4. 서버 콘솔에서 `💬 SIP MESSAGE from 1001` 확인

### 서버 → Linphone 메시지 발신

```bash
# Linphone이 1001로 등록된 상태에서
curl -X POST http://localhost:8000/api/messages/send \
  -H "Content-Type: application/json" \
  -d '{"to": "1001", "body": "[예약확인] 내일 오후 2시 예약이 확정되었습니다."}'
```

Linphone 화면에 채팅 팝업이 표시된다.

### 등록 사용자 확인

```bash
curl http://localhost:8000/api/messages/registered
# → [{"username": "1001", "ip": "192.168.1.100", "port": 5080}]
```

---

## 주요 결정 사항

| 결정 | 이유 |
|------|------|
| SIP MESSAGE → SMS 테스트 대용 채택 | 외부 SMS API 없이 즉시 테스트 가능, 소프트폰 기반이므로 실제 메시지 전달 확인 가능 |
| Body를 WebSocket으로 전달 | 운영자가 수신 메시지를 대시보드에서 실시간 확인 가능 |
| `_registered_users` 기반 발신 | 등록 안 된 단말에 UDP를 blind send 하면 유실되므로 등록 선행 강제 |
| `src.main._sip_endpoint` 전역 노출 | FastAPI 라우터가 싱글턴 endpoint 인스턴스에 접근하는 가장 단순한 방법 |

---

## 한계 및 잔여 과제

| 항목 | 내용 |
|------|------|
| SIP ↔ 일반 휴대폰 | SIP MESSAGE는 SIP 단말끼리만 가능. 고객에게 실제 SMS 발송은 솔라피 등 외부 API 필요 |
| 수신 이력 저장 | 현재 메시지는 로그·WebSocket으로만 흘러감. DB 저장이 필요하면 `messages` 테이블 추가 필요 |
| 인증 | `POST /api/messages/send` 현재 인증 없음. 운영 환경에서는 Bearer 토큰 추가 필요 |
| 대화방 UI | 프론트엔드에서 `sip_message_received` 이벤트 수신 시 채팅 UI 연동 미구현 |
