## 메타

- **작성일(로컬)**: 2026-04-20
- **상태**: 구현·점검 완료
- **관련 이슈**: 발신 CANCEL 시 착신 미종료, 내선 통화 이력 미표시, 연결음 묵음, CID/GlobalCallDock 미표시

## 개요

1. **CANCEL**: `_handle_cancel`이 발신 CANCEL에 200 OK만 보내고 **B2BUA→착신 INVITE에 대한 CANCEL을 전달하지 않아** 착신 단말이 링 상태로 남을 수 있었다. **착신으로 CANCEL 전달** 후에는 기존 **487 릴레이·cleanup** 경로가 동작하도록 정리 순서를 바꿨다(전달 성공 시 즉시 cleanup 생략).
2. **통화 이력**: CDR 파일만 기록되고 **`call_records` SQLite에 동기화되지 않아** `/api/call-history` DB 우선 경로에서 내선 통화가 누락될 수 있었다. **`_cleanup_call`에서 `upsert_call_record`** 를 추가했다.
3. **연결음 묵음**: 원인 후보(180 SDP, ringback_settings, RTP 목적지) 판별을 위해 **`ringback_early_media_first_pcm_send`** 로그를 RTP 송신 경로에 추가했다(설정·SDP는 기존 리포트 참고).
4. **CID**: 브라우저 **`[cid-dock]`** 콘솔 로그, 백엔드 **`caller_context_*`**, **`emit_call_started`**, **`b2bua_ws_emit_call_started_scheduled`** 로 재시험 시 원인 분리 가능.

## 변경 이력 (파일별)

| 파일 경로 | 변경 유형 | 요약 | 비고 |
|-----------|-----------|------|------|
| `sip-pbx/src/sip_core/sip_endpoint.py` | 수정 | `_forward_cancel_to_callee_leg`, `_handle_cancel`에서 착신 CANCEL·487 후 cleanup | 발신 취소 시 착신 링 해제 |
| `sip-pbx/src/sip_core/sip_endpoint.py` | 수정 | `_cleanup_call` 후 `upsert_call_record` | owner=착신 내선, direction=inbound |
| `sip-pbx/src/sip_core/sip_endpoint.py` | 수정 | no_answer AI 인수 시 CANCEL 전송을 헬퍼로 통합 | 동작 동일 |
| `sip-pbx/src/sip_core/sip_endpoint.py` | 수정 | `emit_call_started` 스케줄 시 `b2bua_ws_emit_call_started_scheduled` 로그 | WS 미수신 추적 |
| `sip-pbx/src/media/rtp_relay.py` | 수정 | `ringback_early_media_first_pcm_send` 1회 로그 | 묵음 시 RTP 송신 여부 |
| `sip-pbx/src/api/routers/call_history.py` | 수정 | `caller-context` 요청·히트/미스 로그 | CID API 추적 |
| `src/websocket/server.py` | 수정 | `emit_call_started` 시 `emit_call_started` structlog | PBX 실행 시 WS 패키지 경로에 따라 사용 |
| `sip-pbx/frontend/components/ActiveCallDockProvider.tsx` | 수정 | `[cid-dock]` 콘솔·fetchCallerContext 실패 로그 | tenant owner 누락 등 가시화 |
| `sip-pbx/docs/reports/2026-04/2026-04-20_1515_CANCEL_CALL_RECORDS_RINGBACK_CID_LOGS.md` | 추가 | 본 리포트 | |

## 주요 결정 사항

- 발신 CANCEL 후 **착신에 CANCEL을 보낸 경우** `_cleanup_call`은 **487 수신 처리**에서 수행한다. **전달 불가**(away·INVITE 미전송)일 때만 즉시 cleanup.
- `call_records.owner`는 **착신 내선**으로 두어 `owner=1003` 필터·CID `inbound` 조회와 맞춘다. 발신 전용 `outbound` 필터와의 정합은 후속 검토 가능.

## 잔여 과제

- 착신 **487 미도착**(패킷 손실) 시 세션이 잠깐 남을 수 있음 → 필요 시 타임아웃 cleanup.
- `ringback_settings` 미구성·`enabled_ringback` off 시 여전히 묵음 — `ringback_start_skipped` 로그로 확인.

---

## 후속 (2026-04-20): CID 진단을 콘솔 → app.log

- 브라우저 `console.info` 대신 **`POST /api/client-log`** 로 서버 `app.log`에 `frontend_client_log` 한 줄로 남김.
- 파일: `src/api/routers/client_log.py`, `src/api/main.py`, `frontend/lib/clientAppLog.ts`, `frontend/components/ActiveCallDockProvider.tsx`.

---

## 후속 (2026-04-20): Graceful shutdown — SIP listen join

- **원인**: `sip_endpoint.stop()`이 listen 태스크를 `cancel()`만 하고 **await 하지 않아** `_listen_loop`의 `finally`(UDP `close`)가 실행되기 전에 `stop_async_logging()` 등으로 넘어가 **포트·백그라운드 SIP 처리 태스크가 잠깐 남는** 구간이 생길 수 있음.
- **조치**: `SIPEndpoint.shutdown_async()` 추가 — cancel 후 `wait_for(listen_task)` → SIP 트래픽 로그 닫기 → `sip_server_stopped`. `main.py` finally·기동 실패 경로는 `stop()` 대신 `await shutdown_async()`.
- **로그**: `sip_listen_task_joined` / `sip_listen_task_join_timeout`, 종료 후 `sip_shutdown_phase_complete`.
- **환경변수**: `SIP_SHUTDOWN_LISTEN_TIMEOUT_SEC` (기본 15, 1~120초).

---

## 후속 (2026-04-20): Graceful 종료 — uvicorn 이후 정체

- **현상**: 콘솔에 uvicorn `Finished server process` 후 프로세스가 잠깐 남거나 멈춘 것처럼 보임. ngrok는 PBX 내 **상시 프로세스**가 아니라 ringback URL 조회용 **HTTP** 위주이나, **임베디드 Socket.IO + aiohttp `runner.cleanup()`** 이 느리면 그 구간에서 대기.
- **조치**:
  - `websocket/server.py` `start_server` `finally`: `stop_websocket_server()` 에 `asyncio.wait_for`(기본 25초, `WS_RUNNER_CLEANUP_TIMEOUT_SEC`) 적용·타임아웃·완료 로그.
  - `main.py` finally: `ws_serve_task` join 에 `EMBEDDED_WS_SHUTDOWN_WAIT_SEC`(기본 35초) `wait_for`, 초과 시 `stop_websocket_server()` 한 번 더 시도.
  - SIP: `shutdown_async` **멱등** 플래그(`_sip_shutdown_done`), finally 에서 `sip_endpoint`만 있으면 호출(`is_running` 조건 제거).

---

## 후속 (2026-04-20): `no_answer_timeout_error` — `listen_port` 미정의

- **원인**: `_handle_no_answer_timeout` AI 인수 200 OK의 `Contact` URI가 지역 변수 `listen_port`를 참조했으나, CANCEL 전송 리팩터 시 해당 줄 위의 `listen_port = self.config.sip.listen_port` 할당이 사라져 `NameError`.
- **영향**: 부재중→AI 인수 시 200 OK 전송 전에 예외로 떨어져 **이후 단계(CallManager·통화 상태)** 가 어긋날 수 있음. 사용자 체감으로는 **CID/연결음**과 함께 이상이 겹쳐 보일 수 있음(링백은 AI 인수 직전 `_stop_ringback_player`에서 이미 중지).
- **조치**: `Contact`에 `self.config.sip.listen_port` 직접 사용으로 수정 (`sip_endpoint.py`).

---

## 후속 (2026-04-20): `ringback_start_skipped` — owner 1003 `no_ringback_settings_row`

- **원인**: `get_settings("1003")` → `ringback_settings` 테이블에 **owner=1003 행이 없음**이면 SIP 측에서 링백을 아예 시작하지 않았음.
- **설계 간극**: `resolve_ringback_segment` 는 **스케줄 할당 MP3**를 행 없이도 고를 수 있는데, `_start_ringback_player` / `RingbackPlayer` 가 **먼저 DB 행**을 요구해 스케줄만 있는 구성이 묵음으로 남을 수 있었음.
- **조치**: `get_effective_ringback_settings_for_player(owner)` 추가 — 행이 없어도 세그먼트가 재생 가능한 로컬 MP3면 `enabled_ringback=1` 합성 설정으로 플레이어 기동. 스킵 사유 로그는 `no_ringback_settings_or_playable_segment` 로 정리 (`ringback_service.py`, `ringback_player.py`, `sip_endpoint.py`).
