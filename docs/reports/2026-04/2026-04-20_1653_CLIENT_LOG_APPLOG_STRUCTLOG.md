# `POST /api/client-log` 가 `app.log`에 안 보이던 원인 및 수정

- **작성일(로컬)**: 2026-04-20 16:53
- **상태**: 수정 반영
- **관련**: `2026-04-20_1715_CALL_DOCK_ROOT_LAYOUT_CLIENT_LOG.md`, 점검 호 `call_id=lWGGivqXf-`

## 개요

Call Dock 진단은 브라우저가 **`POST /api/client-log`** 로 남기고, 문서상 **`app.log`에서 `frontend_client_log` / `source=call-dock`** 로 찾도록 되어 있다. 그런데 **`src/api/routers/client_log.py`가 표준 라이브러리 `logging.getLogger`만 사용**하고 있었고, PBX 프로세스의 **`setup_logging()`은 structlog만 동일 `app.log` 스트림에 연결**한다. 그 결과 **요청이 성공(204)해도 한 줄도 `app.log`에 없을 수 있는** 상태였다(표준 로거는 기본 핸들러가 없으면 상위로 전달되며, 파일에는 structlog만 기록).

## 변경 이력 (파일별)

| 파일 경로 | 변경 유형 | 요약 |
|-----------|------------|------|
| `sip-pbx/src/api/routers/client_log.py` | 수정 | `structlog.get_logger` + `logger.info("frontend_client_log", source=..., client_log_event=..., payload=...)` |
| 본 문서 | 추가 | 원인·검증 방법 |

## `app.log` 검색 예시 (수정 후)

- `grep` / 로그 뷰어: **`frontend_client_log`** 또는 **`call-dock`** (`source` 필드).
- JSON 한 줄 예: `"event": "frontend_client_log", "source": "call-dock", "client_log_event": "call_dock_ws_subscribe_gate", ...`

## 잔여 과제

- 브라우저가 **아예 요청을 보내지 않는** 경우(토큰 없음·CORS·Next rewrites)는 별도 — `call_dock_ws_subscribe_gate` 등이 여전히 없으면 네트워크 탭으로 `POST /api/client-log` 도달 여부 확인.
