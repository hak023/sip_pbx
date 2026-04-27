# Call Dock 상관 — `app.log`에 서버 측 `call_started` 송신 기록

- **작성일(로컬)**: 2026-04-20 17:20
- **상태**: 로그 보강 반영
- **점검 호**: `call_id=r7bvdQ1rEC` (로그 타임스탬프 17:17대)

## 점검 결과 (보강 전 `app.log`)

| 구분 | 존재 여부 |
|------|-----------|
| `b2bua_ws_emit_call_started_scheduled` + 동일 `call_id` | 있음 (inviting, answered) |
| `frontend_client_log` / `call-dock` / `call_started_received` | **해당 파일 구간에 없음** — 클라이언트 진단 POST가 없었거나, 과거 `client_log` 표준 logging 이슈 시 파일 미기록 |
| **`call_id`로 Dock UI만 역추적** | **불가** — 서버가 Socket.IO로 실제 emit을 했는지 한 줄로 묶이지 않음 |

## 보강 내용

`src/websocket/server.py`의 `emit_call_started` / `emit_call_ended`에서 **structlog**로 다음을 남긴다.

- **`ws_emit_call_started`**: `_sio` 있을 때, `call_id`, `sip_phase`, `is_ai_handled`
- **`ws_emit_call_started_skipped_no_sio`**: `_sio` 없을 때
- **`ws_emit_call_ended`**: 종료 브로드캐스트 예약 시

이후 **`grep` / `"event":"ws_emit_call_started"` + `"call_id":"…"`** 로 서버가 Dock용 이벤트를 **쐈는지**는 `app.log`만으로 확인 가능하다. 브라우저가 받았는지는 여전히 **`frontend_client_log` source=`call-dock`** 로 구분한다.

## 변경 이력 (파일별)

| 파일 경로 | 변경 유형 | 요약 |
|-----------|------------|------|
| `sip-pbx/src/websocket/server.py` | 수정 | `emit_call_started` / `emit_call_ended` structlog |
| 본 문서 | 추가 | `r7bvdQ1rEC` 점검 결론 |
