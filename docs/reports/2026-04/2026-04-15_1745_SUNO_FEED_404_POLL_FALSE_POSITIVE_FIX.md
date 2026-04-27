## 메타

- 작성일: 2026-04-15
- 상태: 완료
- 관련: `app.log` 16:43대 Suno 폴링·콜백, `src/services/ringback_service.py` `poll_suno_task`

## 개요

로그에서 `generate` 직후 첫 `GET .../feed/{task_id}` 가 **HTTP 404** 인데도 `poll_suno_task` 가 `status=failed` 를 반환해 `poll_and_notify` 가 **즉시** `ringback_poll_failed`·할당 `failed`·WS 실패 분기로 빠질 수 있었다. 실제로는 이어지는 Suno 콜백(`complete`)으로 정상 완료되어 **폴링 오탐**이었다. feed **404** 는 태스크 등록 지연으로 간주하고 **pending** 으로 두어 폴링을 이어가도록 수정했다.

## 변경 이력 (파일별)

| 파일 경로 | 변경 유형 | 요약 | 비고 |
|-----|-----|---|---|
| `sip-pbx/src/services/ringback_service.py` | 수정 | `poll_suno_task`: 응답 404 시 `pending` + `suno_poll_feed_not_ready` INFO | |
| `sip-pbx/docs/reports/2026-04/2026-04-15_1745_SUNO_FEED_404_POLL_FALSE_POSITIVE_FIX.md` | 추가 | 본 리포트 | |

## 주요 결정 사항

- **진짜 없는 task_id** 가 404를 내더라도 최대 `max_wait` 까지 폴링 후 타임아웃·실패 처리로 수렴하므로, 404 를 pending 으로 두는 쪽이 콜백 우선 운영과 맞음.

## 로그에서 확인된 정상 동작

- `callbackType` `text` / `first` 는 의도적으로 무시(`ringback_suno_callback_ignored_early`).
- `complete` 콜백에서 `ringback_music_items_saved` → 캐시 MP3 → `ringback_suno_generation_finalized` 까지 정상.

## 잔여 과제 (선택)

- `ngrok_local_api_tunnel_resolved` 가 짧은 간격에 두 번 찍히는 것은 `ensure_suno_generation_prerequisites` 와 `generate` 경로 각각에서 `_suno_callback_url()` 이 호출되기 때문(기능 무해). 필요 시 캐시·로그 레벨 조정 가능.
