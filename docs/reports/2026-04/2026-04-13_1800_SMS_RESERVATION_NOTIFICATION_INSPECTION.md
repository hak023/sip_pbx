# SMS / SIP MESSAGE / 예약 알림 구현 현황 점검 리포트

- **작성일**: 2026-04-13
- **최종 수정**: 2026-04-13 (SIP MESSAGE 재점검 추가)
- **상태**: 점검 완료 (2차 재점검)
- **분류**: 현황 분석
- **점검 범위**: SMS 발송, SIP MESSAGE 메서드, 예약 알림, 예약 관련 코드 전체

---

## 개요

1차 점검에서 "외부 SMS 발송 기능 없음"으로 결론 내렸으나, **SIP 프로토콜 자체의 MESSAGE 메서드(RFC 3428)**를 통한 문자 전송 구현 여부를 추가로 재점검한 결과를 정리한다.

---

## 2차 점검 결과 요약

> **결론: SIP MESSAGE 메서드도 현재 처리 핸들러가 구현되어 있지 않다.**
> `sip_endpoint.py`에서 MESSAGE는 `else` 분기로 처리되어 **501 Not Implemented** 응답을 반환한다.

| 점검 항목 | 결과 | 비고 |
|-----------|------|------|
| 외부 SMS SDK (solapi, coolsms, twilio 등) | ❌ **없음** | 1차 점검과 동일 |
| SIP MESSAGE 메서드 핸들러 (`_handle_message` 등) | ❌ **없음** | `else`→501 처리 |
| SIP MESSAGE 수신 분기 처리 | ❌ **미처리** | `sip_method_not_implemented` 로그 후 501 반환 |
| SIP MESSAGE 발신 기능 (아웃바운드) | ❌ **없음** | 구현 코드 없음 |
| SIP SIMPLE (Presence/IM) 프레임워크 | ❌ **없음** | |
| MSRP (세션 기반 메시지) | ❌ **없음** | |
| 예약 관련 파일 (`reservation`, `booking`, `appointment`) | ❌ **없음** | 1차 점검과 동일 |

---

## 상세 점검 내역

### 0. SIP MESSAGE 메서드 (RFC 3428) 처리 현황 ← 2차 재점검 신규

SIP는 음성통화(INVITE) 외에 **MESSAGE** 메서드를 이용해 인스턴트 메시지(SMS 유사)를 전송할 수 있다(RFC 3428, SIP SIMPLE). 이 경로를 통한 문자 전송 구현 여부를 점검했다.

#### `src/sip_core/sip_endpoint.py` 분기 처리 분석

```python
# MockB2BUASIPEndpoint._handle_sip_message() — 현재 구현
if method == 'OPTIONS':
    response = self._create_options_response(message, addr)
elif method == 'REGISTER':
    response = self._handle_register(message, addr)
elif method == 'INVITE':
    asyncio.create_task(self._handle_invite_b2bua(message, addr))
elif method == 'ACK':
    self._handle_ack(message, addr)
elif method == 'BYE':
    asyncio.create_task(self._handle_bye(message, addr))
elif method == 'CANCEL':
    asyncio.create_task(self._handle_cancel(message, addr))
else:
    # SIP 응답 메시지 (180, 200 OK 등)
    if message.startswith('SIP/2.0'):
        asyncio.create_task(self._handle_sip_response(message, addr))
    else:
        logger.warning("sip_method_not_implemented", method=method)
        response = self._create_not_implemented_response(message, addr)
        # → 501 Not Implemented 반환
```

**MESSAGE 메서드는 `else` 분기로 떨어져 501 Not Implemented를 반환한다.**

#### 현재 `sip_core/` 내 파일 구성

| 파일 | 역할 |
|------|------|
| `sip_endpoint.py` | 메인 SIP 서버 (INVITE/REGISTER/BYE/ACK/CANCEL/OPTIONS 처리) |
| `call_manager.py` | 통화 세션 관리 |
| `register_handler.py` | REGISTER 전용 핸들러 |
| `cancel_handler.py` | CANCEL 전용 핸들러 |
| `prack_handler.py` | PRACK 전용 핸들러 |
| `update_handler.py` | UPDATE 전용 핸들러 |
| `message_handler.py` 등 | **존재하지 않음** |

→ INFO/SUBSCRIBE/NOTIFY/MESSAGE 등 **IM 계열 메서드 핸들러가 전혀 없다.**

#### `test_sip_client.py` 확인

테스트 클라이언트(`test_sip_client.py`)도 **REGISTER, OPTIONS 두 가지만 구현**되어 있고 MESSAGE 발송 테스트 코드가 없다.

---

### 1. 패키지 의존성 (`requirements.txt`, `requirements-ai.txt`)

SMS 발송에 필요한 패키지가 **전혀 없음**.

```
# SMS 관련 패키지 중 아래 항목 모두 미포함
- solapi          ← 솔라피 (국내 SMS)
- coolsms         ← 쿨SMS
- twilio          ← Twilio
- boto3 (SNS)     ← AWS SNS
- vonage          ← Vonage
- infobip-api     ← Infobip
```

현재 포함된 외부 통신 관련 패키지:
- `aiohttp` — HTTP 비동기 클라이언트 (Webhook 발송용)
- `redis` — Redis 클라이언트 (HITL 큐)
- `python-socketio` — WebSocket 서버

---

### 2. 알림 구현 현황

현재 구현된 알림 채널은 **WebSocket + Webhook** 뿐이다.

| 알림 채널 | 구현 여부 | 위치 |
|-----------|-----------|------|
| WebSocket (운영자 대시보드) | ✅ 구현됨 | `src/websocket/server.py` |
| Webhook (HTTP POST) | ✅ 구현됨 | `src/events/webhook.py` |
| SMS 문자 발송 | ❌ 미구현 | — |
| 카카오 알림톡 | ❌ 미구현 | — |
| 이메일 | ❌ 미구현 | — |
| 푸시 알림 | ❌ 미구현 | — |

**Webhook 발송 대상** (`config/config.yaml`):
```yaml
events:
  webhook_urls:
    - "http://localhost:5000/webhook"
  webhook_timeout: 10
  webhook_retries: 3
```
→ 현재 localhost 로컬 엔드포인트만 설정되어 있음 (테스트용).

---

### 3. 설정 파일 (`config/config.yaml`)

SMS 관련 설정 섹션이 **전혀 없음**.
예약(reservation) 관련 설정도 **전혀 없음**.

현재 설정에 존재하는 알림 관련 항목:
```yaml
events:
  webhook_urls: [...]     # HTTP Webhook만 있음
  thresholds:             # 이벤트 발생 임계값
    profanity: 0.8
    anger: 0.7
```

---

### 4. 예약(Reservation) 도메인 코드

전체 파일 트리에서 `reservation`, `booking`, `appointment`, `schedule` 키워드로 검색한 결과 **관련 파일 없음**.

| 레이어 | 예약 관련 구현 |
|--------|---------------|
| 백엔드 API 라우터 (`src/api/routers/`) | ❌ 없음 (`calls`, `hitl`, `knowledge`, `metrics`, `operator`, `auth` 만 존재) |
| 서비스 레이어 (`src/services/`) | ❌ 없음 (`hitl.py` 만 존재) |
| DB 마이그레이션 (`migrations/`) | ❌ 없음 (`001_create_unresolved_hitl_requests.sql` 만 존재) |
| 프론트엔드 페이지 | ❌ 없음 (`dashboard`, `call-history`, `login`, `settings/persona`, `knowledge/upload` 만 존재) |
| 프론트엔드 타입 (`frontend/types/index.ts`) | ❌ 없음 |

---

### 5. PRD 문서에서 발견된 SMS 언급

`bmad/docs/prd-detailed-phase1-4.md`에서 `send_confirmation_sms()` 라는 **Tool 명세**가 등장하지만,
이는 **기획 단계의 Agent Tool 시나리오**일 뿐, 실제 구현 코드가 없다.

```
[Tool 4] send_confirmation_sms(customer_phone, "배송지 변경 완료")
  → Result: {sent: true}
```

> 이 Tool은 PRD에서 배송지 변경 시나리오의 MCP/Agent 툴로 **설계만** 된 상태이며,
> 어떤 SMS 제공업체를 쓸지, 실제 구현 방법도 정해지지 않았다.

---

## 현재 HITL 흐름과의 관계

현재 HITL(Human-in-the-Loop) 흐름에서 운영자 알림은 **WebSocket으로만** 전달된다.

```
[AI 신뢰도 낮음]
     ↓
[HITLService.request_human_help()]
     ↓
[WebSocket → 운영자 대시보드 팝업]  ← 현재 구현
     ↓
[운영자 답변 → AI 재개]
```

운영자가 **부재중(AWAY)** 상태일 때의 흐름:
```python
# src/services/hitl.py
if operator_status in [OperatorStatus.AWAY, OperatorStatus.OFFLINE]:
    # → 미처리 HITL 요청 DB 저장
    # → 고객에게 폴백 메시지 재생
    # SMS 발송 없음 ← 현재 미구현
```

---

## 결론 및 권장 사항

### 현재 상태 한 줄 요약

> 외부 SMS 발송 기능도, SIP MESSAGE 메서드를 통한 문자 전송 기능도 모두 구현되어 있지 않다.
> PRD에 시나리오로만 존재하며, 코드·설정·패키지 어디에도 구현된 것이 없다.

### 문자 메시지 전송 방식 비교

| 방식 | 프로토콜 | 구현 여부 | 특징 |
|------|---------|-----------|------|
| 외부 SMS 제공업체 (솔라피 등) | HTTP REST | ❌ 미구현 | 일반 휴대폰 SMS 발송, 알림톡 포함 |
| SIP MESSAGE (RFC 3428) | SIP UDP/TCP | ❌ 미구현 | SIP 단말 간 IM, 통화 없이 문자 |
| SIP SIMPLE / MSRP | SIP | ❌ 미구현 | 세션 기반 IM, 고급 기능 |

**SIP MESSAGE 방식의 제약:**
- SIP 단말(IP 폰, 소프트폰)끼리만 주고받을 수 있음
- 일반 스마트폰 기본 문자 앱으로 수신 불가
- 예약 확인 SMS를 고객에게 보내는 용도에는 **부적합**
- 사내 내선 메시지, B2BUA 제어 용도에는 활용 가능

### 구현이 필요한 경우 권장 스택

| 용도 | 권장 솔루션 | 비고 |
|------|-------------|------|
| 국내 SMS | **솔라피(Solapi)** 또는 CoolSMS | 알림톡 동시 지원 가능 |
| 카카오 알림톡 | 솔라피 or 카카오 비즈메시지 직접 연동 | 예약 확인 알림에 최적 |
| 글로벌 SMS | Twilio | 국제 서비스 대비 |

### 구현 위치 제안

```
src/
└── services/
    ├── hitl.py              ← 현재 운영자 알림
    └── notification.py      ← 신규: SMS/알림톡 발송 서비스
        ├── send_sms()
        ├── send_alimtalk()
        └── send_reservation_confirmation()
```

### 예약 알림 시나리오 (미구현 → 구현 필요)

1. **예약 확정 알림** → 고객에게 SMS/알림톡 발송
2. **예약 리마인드** → 이용일 전날 자동 발송
3. **운영자 부재중** → 미처리 HITL 요청을 운영자 휴대폰 SMS로 알림
4. **통화 종료 후** → AI가 처리한 내용 요약 SMS 발송 (PRD `send_confirmation_sms` 시나리오)

---

## 잔여 과제

### 외부 SMS (고객 발송용 — 우선순위 높음)

1. **SMS 제공업체 선정** — 솔라피 vs CoolSMS vs Twilio 비교 후 결정
2. **`src/services/notification.py` 신규 작성** — SMS/알림톡 발송 서비스
3. **`requirements.txt`에 SMS SDK 추가**
4. **`config/config.yaml`에 SMS 설정 섹션 추가** (API Key, 발신번호 등)
5. **`env.example`에 SMS API Key 환경 변수 추가**
6. **HITL 부재중 처리 시 SMS 알림 연동** (`src/services/hitl.py` 수정)
7. **예약 도메인 기반 구현** — 예약 확정/리마인드 SMS 트리거 연결 (예약 모듈 구현 후)
8. **MCP 툴 연동** — `send_confirmation_sms` PRD 시나리오 → MCP 서버로 구현 (`2026-04-13_1730_MCP_INTEGRATION_FEATURE_PLAN.md` 참조)

### SIP MESSAGE 핸들러 (내선 IM 용도 — 선택적 구현)

9. **`src/sip_core/message_handler.py` 신규 작성** — SIP MESSAGE 메서드 수신 처리
10. **`sip_endpoint.py` 분기 추가** — `elif method == 'MESSAGE':` 핸들러 연결
11. **메시지 아웃바운드 API** — `src/api/routers/` 에 내선 문자 전송 엔드포인트 추가 (필요 시)
