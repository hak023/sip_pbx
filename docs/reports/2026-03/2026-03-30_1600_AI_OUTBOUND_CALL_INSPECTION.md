# AI 발신 기능 점검 리포트

**작성일**: 2026-03-30 16:00
**상태**: 버그 수정 완료 (일부 구조적 한계 사항 남음)
**범위**: Frontend → API → SIP → OutboundManager → AI 응대 전 흐름

---

## 1. 전체 흐름 개요

```
Frontend (outbound/page.tsx 또는 new/page.tsx)
  │
  │ POST /api/outbound/create
  ▼
FastAPI (src/api/routers/outbound.py)
  │ _get_outbound_manager() — ws서버에 주입된 CallManager → SIPEndpoint._outbound_manager
  ▼
OutboundCallManager.create_call()  (src/sip_core/outbound_manager.py)
  │ max_concurrent 체크 → 즉시 dial 또는 queue
  ▼
OutboundCallManager._dial()
  │ _send_invite_cb(to_number, from_number, ...)
  ▼
SIPEndpoint.send_outbound_invite()  (src/sip_core/sip_endpoint.py)
  │ 포트 할당 + SDP + INVITE 전송
  │ ring_timeout 타이머
  ▼
  (callee 응답)
SIPEndpoint.handle_outbound_response()  ← 200 OK
  │ ACK 전송
  │ on_answered(call_id, callee_sdp)
  ▼
OutboundCallManager.on_answered()
  │ _start_ai_cb(call_id, outbound_context)
  ▼
CallManager._start_outbound_ai()  (set_ai_orchestrator 시 등록된 콜백)
  │ ai_orchestrator.handle_outbound_call(call_id, outbound_context)
  ▼
AIOrchestrator.handle_outbound_call()  (src/ai_voicebot/orchestrator.py)
  │ 인사말 TTS → STT 루프 → LLM 대화 → 태스크 완료 판단
  ▼
OutboundCallManager.on_task_completed()  ← AI 완료 콜백
  │ BYE 전송 → _complete() → 이력 저장
  ▼
통화 종료
```

---

## 2. 발견된 버그

### Bug 1 (Critical): `get_call_manager` 미정의 — 모든 API 엔드포인트 500 에러
**파일**: `src/api/routers/outbound.py`
**원인**: 모든 핸들러에서 `from src.sip_core.call_manager import get_call_manager` 임포트 후 호출했으나, `call_manager.py`에 `get_call_manager` 함수가 존재하지 않음. 실제 CallManager 인스턴스는 `src/main.py`에서 `ws_server.set_call_manager(sip_endpoint.call_manager)`로 주입됨.
**영향**: 발신 생성/취소/재시도/목록/통계 모든 API 요청 시 `ImportError` → 500 에러
**수정**: `_get_outbound_manager()` 헬퍼 함수 추가하여 `get_injected_call_manager()`(웹소켓 서버 주입) 경유 + `SIPEndpoint._outbound_manager` 탐색으로 변경. 모든 핸들러에 적용.

### Bug 2 (Critical): `outbound/new/page.tsx` 잘못된 엔드포인트
**파일**: `frontend/app/outbound/new/page.tsx`
**원인**: `POST /api/outbound/` (trailing slash)로 요청. 라우터에 해당 경로 없음 (`/api/outbound/create`만 존재).
**영향**: 새 발신 페이지에서 발신 요청 시 404 에러
**수정**: `/api/outbound/` → `/api/outbound/create`로 수정.

---

## 3. 프론트엔드 구조

### 3.1 발신 관리 메인 페이지 (`app/outbound/page.tsx`)
- **기능**: 활성 통화 목록, 이력, 통계 표시 + 인라인 발신 생성 폼
- **API 호출**: `/api/outbound/active`, `/api/outbound/history`, `/api/outbound/stats`
- **발신 생성**: `/api/outbound/create` (정상)
- **취소**: `/api/outbound/cancel` (정상)
- **재시도**: `/api/outbound/retry` (정상)
- **상태**: 버그 없음 (Bug 1 수정 후 정상 동작 예상)

### 3.2 새 발신 페이지 (`app/outbound/new/page.tsx`)
- **기능**: 독립형 발신 생성 폼, 로그인 테넌트 자동 반영
- **발신번호**: localStorage `tenant.owner`에서 자동 설정 (readOnly)
- **발신자 표시명**: localStorage `tenant.name`에서 자동 설정
- **Bug 2 수정 완료**: `/api/outbound/` → `/api/outbound/create`

### 3.3 결과 상세 페이지 (`app/outbound/[outbound_id]/page.tsx`)
- **문제**: `GET /api/outbound/{outbound_id}/result` 호출 — 해당 라우터 없음
- **영향**: 결과 상세 페이지 404 (실사용 경로 여부 확인 필요)
- **조치**: 사용하지 않는 페이지이면 무시. 필요 시 라우터에 추가해야 함.

---

## 4. API 라우터 (`src/api/routers/outbound.py`)

### 4.1 정의된 엔드포인트

| 메서드 | 경로 | 기능 |
|---|---|---|
| POST | `/api/outbound/create` | 발신 생성 |
| POST | `/api/outbound/cancel` | 발신 취소 |
| POST | `/api/outbound/retry` | 수동 재시도 |
| GET | `/api/outbound/active` | 활성 통화 목록 |
| GET | `/api/outbound/history` | 통화 이력 |
| GET | `/api/outbound/stats` | 통계 |

### 4.2 수정 후 CallManager 탐색 로직

```python
def _get_outbound_manager():
    # 1. websocket.server.get_injected_call_manager() → CallManager
    # 2. cm._outbound_manager 확인 (직속)
    # 3. cm._sip_endpoint._outbound_manager 확인 (SIPEndpoint 경유)
    return cm, obm
```

---

## 5. OutboundCallManager 동작 분석 (`src/sip_core/outbound_manager.py`)

### 5.1 상태 기계

```
queued → dialing → ringing → connected → completed
                           ↘ no_answer (→ retry)
                           ↘ busy      (→ retry)
                           ↘ rejected
              ↘ failed
cancelled (any state)
```

### 5.2 동시 통화 제한
- `max_concurrent_calls` (config 기본값 확인 필요)
- 초과 시 `call_queue`에 넣고 대기, 완료 시 자동 다음 처리

### 5.3 링 타임아웃 / 재시도
- `ring_timeout`초 후 CANCEL → `no_answer`
- `retry_enabled` + `retry_on_no_answer` → `retry_interval`초 후 자동 재시도
- 최대 `max_retries`회

---

## 6. SIP 발신 흐름 (`sip_endpoint.py`)

### 6.1 send_outbound_invite
- 대상 번호 → `_resolve_outbound_target` (등록된 내선 or default_gateway)
- RTP 포트 할당 → SDP 생성 (PCMU/PCMA + telephone-event)
- INVITE 전송, `X-Outbound-Call-ID` 헤더 추가
- `_active_calls[call_id] = {..., is_outbound: True, outbound_id: ...}`

### 6.2 200 OK 처리
- ACK 전송
- `outbound_manager.on_answered(call_id, callee_sdp)` 호출
- **주의**: 일반 B2BUA 인바운드 흐름과 달리 `MediaSessionManager.update_callee_sdp()`를 명시적으로 호출하지 않음

---

## 7. AI 응대 연동 분석

### 7.1 실제 사용 경로: Legacy Orchestrator (AIOrchestrator)
- `CallManager.set_ai_orchestrator()` 시 `_start_outbound_ai` 콜백 등록
- 200 OK → `ai_orchestrator.handle_outbound_call(call_id, outbound_context)`
- **Pipecat 파이프라인 사용 안 함** — 레거시 `ai_orchestrator.py` 경로

### 7.2 outbound_context 구조
```python
{
    "outbound_id": record.outbound_id,
    "purpose": record.purpose,          # 통화 목적
    "questions": record.questions,       # 확인 사항 목록
    "caller_display_name": ...,          # 발신자 표시명
    "callee_number": record.callee_number,
}
```

### 7.3 Pipecat 파이프라인 미사용 이슈 (구조적 한계)
- 현재 인바운드 AI는 Pipecat 파이프라인 사용 (`pipeline_engine: "pipecat"`)
- 아웃바운드는 `handle_outbound_call()` 레거시 경로 → 기능 차이 가능성:
  - Barge-in (VAD 기반 끼어들기) 지원 여부 불명확
  - HITL 연동 여부 불명확
  - 대시보드 실시간 STT/TTS 표시 여부 불명확
- 이 부분은 별도 개선 작업 필요 시 아웃바운드도 Pipecat 파이프라인으로 통합 권장

### 7.4 RTP 콜백 설정 경로
- 아웃바운드 200 OK 시 `rtp_send_callback` 명시적 설정 없음
- 레거시 오케스트레이터가 `speak()` 시 사용하는 콜백이 인바운드 통화와 공유 가능성
- **싱글 AIOrchestrator 인스턴스 기반 설계 리스크**: 동시 2건 이상 아웃바운드는 충돌 위험

---

## 8. 수정 요약

| 항목 | 파일 | 수정 내용 |
|---|---|---|
| Bug 1 수정 | `src/api/routers/outbound.py` | `get_call_manager` 미정의 → `_get_outbound_manager()` 헬퍼 함수 도입, 모든 핸들러 적용 |
| Bug 2 수정 | `frontend/app/outbound/new/page.tsx` | 엔드포인트 `/api/outbound/` → `/api/outbound/create` |

---

## 9. 추가 검토 필요 사항 (구조적 한계)

| 항목 | 우선순위 | 설명 |
|---|---|---|
| 아웃바운드 → Pipecat 통합 | 중간 | 레거시 오케스트레이터 대신 Pipecat 파이프라인 사용으로 HITL/Barge-in/대시보드 통합 |
| 동시 아웃바운드 AI 충돌 | 높음 | 싱글 AIOrchestrator 인스턴스 → 동시 2건 이상 아웃바운드 AI 응대 불가 |
| `outbound/[id]/result` 페이지 | 낮음 | 라우터에 해당 엔드포인트 없어 404 (사용 여부 검토) |
| WebSocket 아웃바운드 이벤트 | 중간 | 아웃바운드 시작/종료 시 `call_started`/`call_ended` 이벤트 대시보드 전달 여부 확인 |
