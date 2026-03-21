# 유저 간 통화 — 대시보드 실시간 표시·STT 점검

**작성일**: 2026-03

---

## 결론 요약

| 항목 | 설계/기대 | 실제 |
|------|-----------|------|
| **실시간 통화 카드** | WebSocket `call_started` + (선택) REST 폴링 | `call_started`는 **Python `src.websocket.server`** 가 `_sio`로 송신. **Node `ws-server/server.js`만 켜 두면 이벤트 없음**. |
| **REST 활성 목록** | `GET /api/calls/active` | `CallManager` 주입 시 **`get_active_sessions()` 미호출 버그**로 목록이 비었을 수 있음 → **수정함** (`calls.py`). |
| **표시 필드명** | 프론트가 `caller_number` 기대 | 백엔드는 **`caller` / `callee` (SIP URI)** 로 송신 → 카드에 "알 수 없음"만 보일 수 있음 → **프론트에서 `caller`/`callee` 폴백 추가**. |
| **실시간 STT/TTS** | 유저 간: RTP→STT→`stt_transcript` / AI: Pipecat→emit | **2026-03 후속 구현**: `rtp_relay`의 `bypass_realtime_stt`가 WS 콜백 미등록이었음 → **`start_server`에서 등록**. SIP/Pipecat **메인 루프**와 **Socket.IO 전용 스레드** 불일치로 emit이 먹히지 않을 수 있음 → **`_emit_on_ws_loop`로 WS 루프에 위임**. 대시보드에 **실시간 로그 패널** + `stt_transcript` / `tts_started` / `ai_greeting` 구독. |

---

## 1. `call_started` 발생 경로

1. **`CallManager.handle_ack`** (incoming leg ACK, 통화 성립 후)  
   - `emit_call_started(call_id, { caller: get_caller_uri(), callee: get_callee_uri(), ... })`

2. **`SIPEndpoint._handle_sip_response`** (B2BUA, 200 OK 등)  
   - `emit_call_started(original_call_id, { caller: sip:..., callee: sip:... })`

유저 간 통화도 위 중 하나를 타면 이벤트는 나가야 함.  
단, **수신 측 Socket.IO 서버가 Python 서버여야** 함 (`_sio`가 설정된 프로세스).

---

## 2. WebSocket 서버 이중 구조 (중요)

- **`python -m src.main`**: 스레드로 **Python Socket.IO** (`src.websocket.server.start_server`) 기동 → `emit_*` 와 **동일 프로세스**.
- **`ws-server` (npm)**: **연결/connection_established만 제공하는 스텁** → **`call_started` / `call_ended` / STT 미송신**.

**대시보드가 안 뜨는 흔한 원인**: 포트 8001에 **Node ws-server만** 떠 있고, SIP는 **별도 Python**에서 도는 경우.

**권장**: 유저 간 통화 실시간 연동 시 **`src.main` 한 프로세스**로 SIP + API + Python WS 사용, 또는 Node를 쓰지 않음.  
프론트 `NEXT_PUBLIC_WS_URL`이 **실제로 이벤트를 쏘는 서버**와 일치하는지 확인.

---

## 3. REST `GET /api/calls/active`

- `python -m src.main`은 `set_call_manager`로 API 스레드와 동일 모듈의 `_call_manager`를 설정함.
- 기존 `_get_active_calls_from_manager()`는 `get_active_calls` / `get_calls` / `.calls` 만 시도하고, **`CallManager.get_active_sessions()`는 호출하지 않음** → 저장소에 있는 유저 간 세션이 REST에 안 나올 수 있었음.  
- **조치**: `get_active_sessions()` 우선으로 `CallSession` → dict 매핑 추가.

---

## 4. 실시간 STT / TTS (구현 요약)

- **유저 간(Bypass)**: `src/media/rtp_relay.py`가 `not ai_mode`일 때 `bypass_realtime_stt.feed_audio` 호출 → Google **스트리밍 STT** → `set_broadcast_callback`으로 `stt_transcript` 송신.  
  - **전제**: `GOOGLE_APPLICATION_CREDENTIALS`(또는 녹음기 초기화와 동일한 GCP 설정) + `google-cloud-speech`.
- **AI(Pipecat)**: `rag_processor`가 `emit_stt_transcript`(발신자/사용자), `emit_tts_started` / `emit_tts_completed`, `emit_ai_greeting`(인사 단계) 호출.
- **Socket.IO 스레드**: `emit_*`는 `_ws_loop`에서 실행되도록 `_emit_on_ws_loop` / `schedule_socket_emit` 적용 (SIP·Pipecat과 **루프 분리** 대응).
- **종료 시**: `CallManager.cleanup_terminated_call`에서 `get_bypass_realtime_stt().end_call(call_id)` 로 스트림 스레드 정리.

---

## 5. 변경 이력 (파일별)

| 파일 | 변경 유형 | 요약 |
|------|-----------|------|
| `src/websocket/server.py` | 수정 | `_ws_loop`, `_emit_on_ws_loop`, `schedule_socket_emit`; Bypass STT→`stt_transcript` 콜백 등록 |
| `src/sip_core/call_manager.py` | 수정 | `cleanup_terminated_call`에서 bypass 실시간 STT `end_call` |
| `src/ai_voicebot/pipecat/processors/rag_processor.py` | 수정 | STT/TTS emit에 `speaker`/`role`/`source` 메타 |
| `frontend/app/dashboard/page.tsx` | 수정 | 실시간 로그 패널, `stt_transcript`·`tts_started`·`ai_greeting` 구독, `is_ai_handled` 뱃지 |
| `frontend/lib/normalizeActiveCall.ts` | 수정 | REST `is_ai_handled` 반영 |
| `src/api/routers/calls.py` | 수정 | (이전) `get_active_sessions()` 기반 활성 통화 목록 |

---

## 6. 운영 체크리스트

1. [ ] SIP/API/WS를 **`src.main` 단일 기동**으로 맞췄는지 (또는 WS가 Python과 동일 이벤트 스트림을 받는지).
2. [ ] `NEXT_PUBLIC_WS_URL` = Python WS (기본 `http://localhost:8001`이 **Node와 포트 충돌 없는지**).
3. [ ] 통화 중 `GET /api/calls/active`에 `call_id`가 보이는지 (폴링/초기 로드).
4. [ ] 로그에 `call_started_event_failed` / `emit_call_started_failed` 없는지.
