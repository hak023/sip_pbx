# CID Call Dock 미표시 재점검 — `call_id=xUfFVrFw8R`

- **작성일(로컬)**: 2026-04-20 16:39
- **상태**: 로그 기반 분석
- **근거**: `sip-pbx/logs/app.log`, `sip-pbx/logs/call_data_record_20260420.log`

## 개요

해당 통화에 대해 **백엔드는 Socket.IO `call_started` 발행까지 성공한 것으로 기록**되어 있다. 동일 기간 **`app.log` 전체에서 `frontend_client_log`(call-dock 진단) 문자열이 한 건도 없다** → 브라우저가 **`POST /api/client-log`를 치지 않았거나** 도달하지 못한 상태로 추정된다. Dock UI는 **`call_started` 수신 + WebSocket 연결**에 의존하므로, **미로그인·WS URL 불일치·대시보드 탭 미오픈** 등 클라이언트 측 원인을 우선 확인하는 것이 맞다.

## 타임라인 (`app.log`)

| 시각(로컬) | 이벤트 | 의미 |
|------------|--------|------|
| 16:00:33.314 | `b2bua_ws_emit_call_started_scheduled` (`sip_phase=inviting`) | INVITE 직후 `emit_call_started`를 `asyncio.create_task`로 예약 |
| 16:00:43.308 | `ai_call_started_event_emitted` | `call_manager.handle_no_answer_timeout` 안에서 **`await ws_manager.emit_call_started` 성공** (`call_manager.py` L807–808) |
| (동일 시각대) | Pipecat·STT 등 | 음성 파이프라인 기동 — `call_data_record`에도 이어짐 |

`ai_call_started_event_failed` 로그는 **없음** → 두 번째( AI 전환 후 ) `emit_call_started`는 예외 없이 완료된 것으로 본다.

## `call_data_record` (보조)

- `16:00:43.581` `call_connected` — 통화 연결 이벤트 기록.
- 이후 `stt_final`, `tts`, LangGraph 등 **동일 `call_id`로 정상 누적** → 서버·파이프라인은 살아 있었음.

## 결론 (원인 분리)

| 구분 | 판단 |
|------|------|
| 서버가 `call_started`를 안 쐈다 | **해당 없음** — `ai_call_started_event_emitted`로 발행 완료가 로그에 남음 |
| 브라우저가 이벤트를 못 받았다 | **가능성 높음** — Socket.IO 미연결·다른 호스트·탭 없음 |
| Dock 전용 진단 로그 부재 | **`frontend_client_log`가 `app.log`에 0건** — 최신 프론트 미배포, API 미도달, 또는 로그인 없이 WS 게이트만 막힌 상태와 부합 (`2026-04-20_1541_CALL_DOCK_CID_NO_LOGS_ANALYSIS.md` 참고) |

## 권장 확인 순서

1. 통화 시각에 **대시보드(Next) 탭이 열려 있었는지**, **`access_token`/`token`으로 Socket.IO가 붙었는지** (브라우저 개발자 도구 Network·WS).
2. **`NEXT_PUBLIC_WS_URL`** 이 브라우저가 접속한 호스트에서 **8001**(또는 실제 WS 포트)에 도달하는지 — 기본 `localhost:8001`은 원격 PC에서 실패하기 쉬움.
3. 배포 후 **`call_dock_ws_subscribe_gate`** / **`call_dock_ws_handlers_attached`** / **`call_started_received`** 가 `frontend_client_log`로 `app.log`에 찍히는지 재검증.

## 변경 이력 (파일별)

| 파일 경로 | 변경 유형 | 요약 |
|-----------|------------|------|
| 본 문서 | 추가 | `xUfFVrFw8R` 통화 로그 기반 재점검 |
