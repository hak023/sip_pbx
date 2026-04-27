# call-dock 로그 부재·CID 미표시 점검

- **작성일(로컬)**: 2026-04-20 15:41
- **상태**: 분석 및 진단 로그 보강 반영
- **참고**: `2026-04-20_1600_CID_DOCK_AND_VOICE_RESERVATION_GAP.md`, `2026-04-20_1715_CALL_DOCK_ROOT_LAYOUT_CLIENT_LOG.md`

## 개요

`app.log`에서 `frontend_client_log source=call-dock`가 전혀 보이지 않는다면, **클라이언트가 `POST /api/client-log`를 호출하지 않았거나** 호출이 실패한 경우다. 코드상 가장 흔한 원인은 **`ActiveCallDockProvider`가 Socket.IO 연결(`isConnected`) 이후에만** `call_dock_ws_handlers_attached`·`call_started_received` 등을 남기도록 되어 있는데, **`useWebSocket`은 유효한 로그인 토큰이 없으면 `connect()`를 아예 호출하지 않아** `isConnected`가 영구적으로 `false`인 경우다.

## 코드 경로 요약

| 단계 | 파일 | 동작 |
|------|------|------|
| 루트 마운트 | `frontend/app/layout.tsx` | `ActiveCallDockProvider` → `AppShell` + `GlobalCallDock` — Provider 자체는 마운트됨 |
| WS 연결 조건 | `frontend/hooks/useWebSocket.ts` | `localStorage`의 `access_token` 또는 `token`이 JWT(3파트) 또는 `tok_*` 형태일 때만 `wsClient.connect` |
| Dock 이벤트 구독 | `frontend/components/ActiveCallDockProvider.tsx` | `useEffect(..., [isConnected, ...])`에서 **`if (!isConnected) return`** → 토큰 없으면 **여기서 끊김** |
| 서버 로그 | `src/api/routers/client_log.py` | `frontend_client_log source=%s event=%s ...` |

즉 **미로그인·만료 토큰·잘못된 토큰 형식**이면 `call-dock` 관련 이벤트가 **설계대로 한 줄도 안 찍힐 수 있다** (이전 구현).

## CID UI와의 관계

- `GlobalCallDock`은 `useActiveCallDockStore`의 `phase !== "idle"`일 때만 카드를 그린다.
- `phase`는 `call_started` 수신 후 `setFromCallStarted`로 바뀐다.
- `call_started`는 Socket.IO로만 온다 → **WS 미연결이면 CID 카드도 안 뜨는 것이 정상**이다.

## `app.log` 검색 가이드

1. **`frontend_client_log source=call-dock`** — Dock·WS 관련 클라이언트 진단.
2. **`event=call_dock_ws_subscribe_gate`** (보강 후) — 토큰 유무·`socket_io_connected`·`ws_url_configured`·`note`로 원인 분기.
3. 백엔드만 확인할 때: **`b2bua_ws_emit_call_started_scheduled`** / **`ai_call_started_event_emitted`** — 서버가 브로드캐스트를 쐈는지 (갭 분석 리포트 §1.1).

## 변경 이력 (파일별)

| 파일 경로 | 변경 유형 | 요약 |
|-----------|------------|------|
| `sip-pbx/frontend/hooks/useWebSocket.ts` | 수정 | `isAcceptableWebSocketToken`·`readAcceptableWebSocketToken` export (이름 정리) |
| `sip-pbx/frontend/components/ActiveCallDockProvider.tsx` | 수정 | `call_dock_ws_subscribe_gate` — WS 연결 전에도 `source=call-dock`로 한 줄 기록 |
| 본 문서 | 추가 | 점검 결론·검증 절차 | 

## 잔여 과제

- 운영 환경에서 **`NEXT_PUBLIC_WS_URL`** 이 브라우저가 실제로 접근 가능한 Socket.IO 엔드포인트와 일치하는지 확인 (기본 `http://localhost:8001`은 다른 PC 브라우저에서는 실패하기 쉬움).
- 로그인 직후 **같은 탭에서 토큰만 갱기고 풀 리로드가 없을 때** `useWebSocket`의 `[]` 의존성으로 WS가 늦게 붙는 경우가 있으면, 로그인 완료 시 `reconnect` 호출 등을 검토.
