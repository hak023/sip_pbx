# SIP MESSAGE SMS 흐름 점검 및 수정 리포트

- **작성일**: 2026-04-13 19:30
- **상태**: 점검 완료 / 2건 수정
- **분류**: 버그 수정 + 신규 기능
- **관련 로그**: `sip-pbx/logs/sip_traffic_20260403.log`

---

## 개요

케이스별 SIP MESSAGE(SMS) 발송 구현 여부를 점검하고 미비점을 수정했다.

---

## 점검 결과 요약

| 케이스 | 구현 여부 | 비고 |
|--------|-----------|------|
| 예약 확정 알림 → 고객 SMS | ✅ 구현됨 | LangGraph booking_agent → send_booking_sms Tool |
| 통화 종료 후 요약 SMS | ❌ 미구현 → **신규 구현** | ai_orchestrator.end_call() 수정 |
| SIP MESSAGE 발신 주소 | ⚠️ 버그 → **수정** | 서버 경유가 아닌 Linphone 직접 전송으로 변경 |

---

## 케이스 1: 예약 확정 알림 — 기존 구현 현황

### 흐름 (정상)

```
통화 중 예약 요청
  ↓ booking_agent.py (LangGraph 노드)
  ↓ LLM → create_booking_tool() → DB confirmed
  ↓ LLM → send_booking_sms() [SystemPrompt 95번줄 지시]
      ↓ booking_tools.py
      ↓ POST http://127.0.0.1:8000/api/booking/sms/send
          ↓ booking.py API
          ↓ sip_sms_service.send_sip_sms_sync()
          ↓ UDP SIP MESSAGE → Linphone
```

### 관련 코드

- `src/ai_voicebot/langgraph/nodes/booking_agent.py` L42–47: `_SMS_TRIGGER_TOOLS` 집합 (create/cancel/update/reschedule 시 SMS 자동 발송)
- `src/ai_voicebot/langgraph/tools/booking_tools.py` L532–569: `_send_booking_sms()` Tool 구현
- `src/api/routers/booking.py` L318–350: `POST /api/booking/sms/send` 엔드포인트
- `src/services/sip_sms_service.py`: 실제 UDP 전송 구현

---

## 버그: SIP MESSAGE 발신 주소 오류 (수정 완료)

### 문제

`sip_sms_service.py`가 `to_phone`에 해당하는 Linphone의 **실제 IP/포트**가 아니라 **SIP 서버 주소**(`127.0.0.1:5060`)로 패킷을 전송하고 있었다.

로그(`sip_traffic_20260403.log`)에서 확인된 실제 Linphone 주소:
```
1003 → 10.213.100.47:34537   (숙용의 A34)
1004 → 10.213.100.160:53892  (승학의 Galaxy)
```

SIP 서버(`10.213.100.233:5060`)는 MESSAGE 수신 후 Linphone으로 프록시 전달하는 기능이 없으므로, 메시지가 SIP 서버 자신에게 도달하고 Linphone에는 전달되지 않았다.

### 수정 내용 (`sip_sms_service.py`)

```python
# 수정 전
sip_msg = _build_message(to_host=sip_server_ip, to_port=sip_server_port, ...)
sock.sendto(sip_msg.encode("utf-8"), (sip_server_ip, sip_server_port))

# 수정 후
registered = _get_registered_addr(to_user, ...)   # _registered_users 조회
dest_host, dest_port = registered or (sip_server_ip, sip_server_port)
sock.sendto(sip_msg.encode("utf-8"), (dest_host, dest_port))
```

- `_get_registered_addr()` 신규 함수: `src.main._sip_endpoint._registered_users`에서 username으로 실제 IP/port 조회
- 등록 정보가 없으면 기존 방식(SIP 서버 경유)으로 폴백
- 로그: `sip_sms_direct_delivery` (직접) 또는 `sip_sms_proxy_delivery` (폴백)

---

## 케이스 4: 통화 종료 후 요약 SMS — 신규 구현

### 추가된 위치

`src/ai_voicebot/orchestrator/ai_orchestrator.py`

- `end_call()` 마지막에 `asyncio.create_task(self._send_call_summary_sms())` 추가
- `_send_call_summary_sms()` 메서드 신규 추가

### 로직

```python
async def _send_call_summary_sms(self):
    # 1. caller 번호 없으면 건너뜀
    # 2. 대화 turn 0이면 건너뜀 (실질적 대화 없음)
    # 3. 예약 통화는 booking_agent가 이미 SMS 발송 → 중복 방지
    #    (langgraph state.booking_context.messages 존재 여부로 판단)
    # 4. AI 마지막 응답 최대 3개 요약 → "[AI 통화 요약] ..." 형태로 발송
```

### 예약 통화 중복 방지 로직

```
예약 통화:
  create_booking 호출 → booking_agent send_booking_sms (예약 확인 메시지)
  end_call() → _send_call_summary_sms() → booking_context.messages 존재 → 건너뜀

일반 문의 통화:
  end_call() → _send_call_summary_sms() → AI 응답 요약 SMS 발송
```

---

## 변경 이력 (파일별)

| 파일 경로 | 변경 유형 | 요약 |
|-----------|-----------|------|
| `src/services/sip_sms_service.py` | 수정 | `_get_registered_addr()` 추가, `send_sip_sms_sync()` 직접 전송 로직 수정 |
| `src/ai_voicebot/orchestrator/ai_orchestrator.py` | 수정 | `end_call()`에 summary SMS task 추가, `_send_call_summary_sms()` 신규 |

---

## 로그에서 확인한 Linphone 특성 (참고)

- **User-Agent**: `LinphoneAndroid/6.0.23 LinphoneSDK/5.4.84`
- **Allow 헤더**: `INVITE, ACK, CANCEL, OPTIONS, BYE, REFER, NOTIFY, MESSAGE, SUBSCRIBE, INFO, PRACK, UPDATE`
  → MESSAGE 지원 확인 ✅
- **Accept 헤더**: `text/plain, application/sdp, application/vnd.gsma.rcs-ft-http+xml`
  → text/plain 메시지 수신 가능 ✅
- **REGISTER 포트**: 53892(1004), 34537(1003) — 동적 포트, 등록 정보 필수

---

## 잔여 과제

| 항목 | 내용 |
|------|------|
| `_langgraph_state` 접근 | `_send_call_summary_sms`에서 booking 판별 시 LangGraph state 접근 경로 확인 필요 (속성명 의존) |
| SMS 본문 품질 | AI 응답 앞 80자 단순 truncate → LLM 별도 요약 호출로 개선 가능 |
| 예약 통화 종료 SMS | 예약 변경/취소 포함 확인 요망 (reschedule_booking_tool도 _SMS_TRIGGER_TOOLS에 포함됨 ✅) |
