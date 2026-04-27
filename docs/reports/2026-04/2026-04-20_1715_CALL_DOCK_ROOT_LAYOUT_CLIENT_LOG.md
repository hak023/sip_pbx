# Call Dock 루트 레이아웃 연결 및 `call-dock` 클라이언트 로그

- **작성일**: 2026-04-20 (로컬)
- **상태**: 구현 완료

## 개요

리포트 `2026-04-20_1600_CID_DOCK_AND_VOICE_RESERVATION_GAP.md` 잔여 과제 1·2에 따라, **인입 Dock**을 앱 루트에서 항상 마운트하고, **`call_started` / `call_ended` 수신·스토어 반영**을 `POST /api/client-log`로 **`source=call-dock`** 에 남겨 `app.log`에서 필터 가능하게 했다.

## 변경 이력 (파일별)

| 파일 경로 | 변경 유형 | 요약 | 비고 |
|-----------|-----------|------|------|
| `sip-pbx/frontend/app/layout.tsx` | 수정 | `ActiveCallDockProvider` + `GlobalCallDock`를 루트에서 `AppShell`과 함께 감쌈 | 로그인 제외 페이지도 동일 트리(로그인은 `AppShell`이 children만 렌더) |
| `sip-pbx/frontend/components/AppShell.tsx` | 수정 | Provider·Dock 제거(중복 방지) | Shell은 헤더+메인만 |
| `sip-pbx/frontend/components/ActiveCallDockProvider.tsx` | 수정 | `call-dock` 소스로 `call_started_received`, `call_started_dock_store_applied`, `call_dock_ws_handlers_attached`, `call_ended_*`, caller-context 계열 로그 | `app.log`에서 `frontend_client_log source=call-dock` 검색 |

## 주요 결정 사항

- Dock을 **`AppShell` 밖(형제)** 에 두면 `AppShell`이 로그인에서 children만 넘길 때도 **고정 Dock**이 동작한다. 다만 **로그인 페이지에서도 Dock 트리는 마운트**되며, WS는 토큰 없으면 연결되지 않아 `phase`는 `idle`로 Dock 카드는 숨는다.
- 서버 로그 필터: JSON **`"event":"frontend_client_log"`** + 필드 **`source`** (`call-dock`) — `client_log` 라우터는 **structlog**로 `app.log`에 기록한다(이전 표준 `logging`만 쓰면 파일에 안 남을 수 있음 → `2026-04-20_1653_CLIENT_LOG_APPLOG_STRUCTLOG.md`).

## `app.log`에 나타나는 이벤트 이름 (payload 요약)

| event | 의미 |
|-------|------|
| `call_dock_ws_handlers_attached` | WS 연결 후 `call_started` 등 리스너 등록됨 |
| `call_started_received` | 소켓 페이로드 요약(`sip_phase`, caller/callee preview, `owner_present`, keys) |
| `call_started_dock_store_applied` | `setFromCallStarted` 직후 `phase` / `activeCallId` / `dockExpanded` |
| `call_started_ignored_empty_call_id` | `call_id` 누락 페이로드 방어 |
| `call_ended_received` / `call_ended_dock_store_applied` | 종료 이벤트 동일 패턴 |
| `caller_context_*` | 기존과 동일 흐름, 소스만 `call-dock`으로 통일 |
