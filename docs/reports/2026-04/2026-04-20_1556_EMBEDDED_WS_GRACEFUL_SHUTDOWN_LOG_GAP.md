# 임베디드 WS 종료 로그 단절 점검 (graceful shutdown 관측)

- **작성일(로컬)**: 2026-04-20 15:56
- **상태**: 원인 정리 + 로그 보강 반영
- **근거 로그**: `app.log` — `embedded_uvicorn_shutdown_wait_done` 직후 `embedded_ws_shutdown_cancel_begin`, 약 16초 뒤 `stopping_server`

## 개요

Ctrl+C 등으로 `run_server`의 `finally`가 실행될 때, **uvicorn 대기는 끝났는데** 그 다음 **`embedded_ws_shutdown_join_done` / `embedded_ws_shutdown_join_timeout`이 안 보이는** 것처럼 느껴질 수 있다. 코드상으로는 **Socket.IO `start_server` 태스크가 `cancel()` 후 `CancelledError`로 종료**하면서 `await asyncio.wait_for(ws_serve_task)`가 **`CancelledError`를 전파**하고, `main.py`에서 이를 **`pass`로만 삼켜 `join_done` 로그를 찍지 않았기 때문**이다. 그 사이 **수 초~수십 초**는 `server.py`의 `start_server` **`finally`에서 `stop_websocket_server()`**(aiohttp `TCPSite`/`AppRunner` 정리, 기본 상한 25초)가 돌고 있을 수 있다.

## 변경 이력 (파일별)

| 파일 경로 | 변경 유형 | 요약 |
|-----------|------------|------|
| `sip-pbx/src/main.py` | 수정 | WS 태스크 `CancelledError` 종료 시에도 `embedded_ws_shutdown_join_done` (`reason=task_cancelled`) 기록 |
| `sip-pbx/src/websocket/server.py` | 수정 | `websocket_runner_cleanup_begin` — runner 정리 진입 시각 추적 |
| 본 문서 | 추가 | 점검 결론 |

## 주요 결정 사항

- **동작은 이미 graceful**에 가깝다: `start_server`가 `CancelledError`를 잡은 뒤 `finally`에서 `stop_websocket_server()`를 호출한다. 관측만 빠져 있었음.
- `join_done`은 **정상 return**과 **cancel 완료** 모두에서 남기도록 통일해, 운영 로그에서 종료 단계가 끊기지 않게 함.

## 잔여 과제 (선택)

- 정리 시간이 길면 `WS_RUNNER_CLEANUP_TIMEOUT_SEC`·`EMBEDDED_WS_SHUTDOWN_WAIT_SEC` 튜닝.
- `stop_websocket_server` 내부 단계별 소요 시간 측정(프로파일)은 필요 시 후속.
