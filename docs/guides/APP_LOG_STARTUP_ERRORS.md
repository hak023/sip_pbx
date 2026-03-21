# app.log 기동 시 에러/경고 점검 (2026-03-06 기준)

서버 기동 및 통화 시 자주 나오는 로그 이벤트와 조치 요약입니다.

---

## 1. `call_manager_inject_failed` (warning)

- **로그**: `module 'src.api.routers.calls' has no attribute 'set_call_manager'`
- **원인**: `main.py`가 `api.routers.calls`에 CallManager를 주입하는데, 해당 모듈에 `set_call_manager`가 없었음.
- **조치**: **적용 완료.** `src/api/routers/calls.py`를 추가하고 `set_call_manager(cm)` / `get_call_manager()`를 정의했습니다. 재시작 시 해당 경고는 사라져야 합니다.

---

## 2. `hitl_timeout_register_failed` (warning)

- **로그**: `'HITLService' object has no attribute 'register_on_hitl_timeout'`
- **원인**: `main.py`가 HITL 서비스에 타임아웃 콜백을 등록하는데, `src.services.hitl` 또는 해당 클래스에 `register_on_hitl_timeout`가 없었음.
- **조치**: **적용 완료.** `src/services/hitl.py`를 추가하고 `HITLService.register_on_hitl_timeout()`, `set_config()`, `get_hitl_service()`를 정의했습니다. 재시작 시 해당 경고는 사라져야 합니다.

---

## 3. `pipecat_import_error` (error)

- **로그**: `cannot import name 'VoiceAIPipelineBuilder' from 'src.ai_voicebot.pipecat.pipeline_builder'`
- **원인**: Pipecat 파이프라인 사용 시 `VoiceAIPipelineBuilder`를 기대하는데, 패키지 미설치 또는 해당 모듈에 클래스가 없음.
- **조치**: 현재는 **legacy** 파이프라인으로 정상 기동됩니다. Pipecat을 쓰려면 `pip install pipecat-ai[google,silero]` 후 `pipeline_builder`에 `VoiceAIPipelineBuilder`를 구현하면 됩니다. 필수는 아닙니다.

---

## 4. `b2bua_call_started_ws_failed` / `b2bua_call_ended_ws_failed` (warning)

- **로그**: `cannot import name 'emit_call_started' from 'src.websocket.server'`
- **원인**: `src.websocket.manager`가 `server`에서 `emit_call_started`, `emit_call_ended` 등 emit/broadcast 함수를 import하는데, `server.py`에 정의가 없었음.
- **조치**: **적용 완료.** `src/websocket/server.py`에 아래 함수들을 추가했습니다.
  - `emit_call_started`, `emit_call_ended`, `emit_stt_transcript`, `emit_tts_started`, `emit_tts_completed`, `emit_ai_greeting`, `emit_hitl_requested`, `emit_hitl_fallback_available`, `emit_knowledge_updated`
  - `broadcast_to_call`, `broadcast_to_operators`, `broadcast_global`
  - 서버 기동 시 `_sio`에 Socket.IO 인스턴스를 넣어 위 emit들이 동작하도록 했습니다. 재시작 후 통화 시작/종료 시 해당 경고는 사라져야 합니다.

---

## Import 에러 점검 요약

| 로그 이벤트 | 원인 | 조치 |
|------------|------|------|
| call_manager_inject_failed | `api.routers.calls`에 `set_call_manager` 없음 | `src/api/routers/calls.py` 추가 |
| hitl_timeout_register_failed | `HITLService`에 `register_on_hitl_timeout` 없음 | `src/services/hitl.py` 추가 |
| pipecat_import_error | `VoiceAIPipelineBuilder` 없음 | legacy 사용 시 무시, Pipecat 사용 시 패키지/구현 추가 |
| b2bua_call_started_ws_failed / b2bua_call_ended_ws_failed | `server`에 `emit_call_started` 등 없음 | `src/websocket/server.py`에 emit/broadcast 함수 추가 |

이후에도 동일한 이벤트가 나오면 해당 모듈이 실제로 로드되는지(경로/패키지 구조)와 위 함수/클래스가 존재하는지 확인하면 됩니다.
