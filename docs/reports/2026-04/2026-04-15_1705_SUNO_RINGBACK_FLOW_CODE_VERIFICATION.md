## 메타

- 작성일: 2026-04-15
- 상태: 코드·설계 기준 정적 검증 (실제 Suno API·ngrok E2E 미실행)
- 관련: `frontend/app/settings/call-control/page.tsx`, `src/api/routers/call_control_api.py`, `src/api/routers/ringback.py`, `src/services/ringback_service.py`, `src/websocket/server.py`

## 개요

착신 제어 통화 연결음(Suno) 흐름을 프론트 저장 → 서버 Suno `generate` → `callBackUrl` 콜백 또는 서버 폴링 → DB·WS까지 추적했다. 전 구간이 한 줄로 연결되며, 이중 완료 처리에 대한 가드가 있다.

## 검증 결과 (흐름)

| 단계 | 위치 | 판정 |
|------|------|------|
| 1. UI 입력·저장 | `call-control/page.tsx` — Suno 모드 시 가사·스타일 필수, 저장 시 `POST/PUT /api/call-control/ringback-assignments` | 정상 |
| 2. 사전 조건 | `call_control_api.create/update_ringback_assignment` — `_will_run_suno_after_save` 시 `ensure_suno_generation_prerequisites()` (API 키·`callBackUrl`) | 정상; 실패 시 400 |
| 3. DB·백그라운드 기동 | 생성 시 `suno_generation_status=pending`, 행 저장 후 `BackgroundTasks.add_task(kickoff_suno_after_assignment_saved, id)` | 정상 |
| 4. Suno 요청 | `kickoff_suno_after_assignment_saved` → `generate_suno_music` — 본문에 `callBackUrl`=`_suno_callback_url()` | 정상 |
| 5. task_id·폴링 | 생성 성공 시 할당 행에 `suno_task_id` 갱신, `asyncio.create_task(poll_and_notify(..., ringback_assignment_id=...))` | 정상 |
| 6a. 콜백 | `POST /api/ringback/suno-callback` — 즉시 `{"status":"received"}`, `BackgroundTasks`로 `process_suno_music_callback_payload` | 정상 |
| 6b. 콜백 파싱 | `code==200`, `callbackType`이 `first`/`text`/`error`가 아닌 완료 분기, `task_id`로 `get_ringback_schedule_assignment_by_suno_task_id` | 정상; 이미 `complete`면 스킵 |
| 7. 완료 공통 | `_finalize_suno_generation_success` — `save_music_items`, 할당이면 MP3 다운로드·`suno_generation_status=complete` | 정상 |
| 8. 폴링 보조 | `poll_and_notify` — 할당이 이미 `complete`면 조기 종료; 완료 시 동일 `_finalize_*` | 정상 (콜백·폴링 중복 방지) |
| 9. 프론트 갱신 | `ringback_music_ready` / `ringback_music_failed` 수신 시 `loadAll(owner)` | 정상 |

## 프론트가 직접 쓰지 않는 API

- `POST /api/ringback/generate-music` + `ringback_assignment_id`: 착신 제어 통화 연결음 경로에서는 **사용하지 않음**(할당 저장 → `kickoff_*`만 사용). 다른 클라이언트·테스트용으로는 유효.

## 운영 시 확인 포인트 (코드 외)

- 공개 `callBackUrl`(ngrok·고정 URL)·`SUNO_API_KEY`·WebSocket(8001) 연결.
- Suno 콜백 본문에서 `callbackType`·`data.data` 곡 배열이 문서와 다르면 `ringback_suno_callback_no_audio_items` 등으로 남고, 폴링이 완료를 담당할 수 있음.

## 잔여 과제

- 실제 `api.sunoapi.org` 응답·콜백 스키마는 계정/버전에 따라 달라질 수 있어, 스테이징에서 한 번 E2E 로그 확인 권장.
