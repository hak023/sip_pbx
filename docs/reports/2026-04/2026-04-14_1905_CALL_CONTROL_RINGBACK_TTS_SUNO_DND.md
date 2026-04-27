## 개요

착신 제어 > 통화 연결음에서 **캐시된 음원만 선택**하던 방식을 제거하고, 기존 링백과 동일하게 **텍스트 TTS** 또는 **Suno AI 생성·적용** 흐름을 쓰도록 바꿨다. **우선순위 숫자 입력**은 없애고, **착신 규칙과 같은 드래그 앤 드롭 목록 순서**가 곧 평가 순서가 되도록 `position` 기반으로 정리했다.

## 변경 이력 (파일별)

| 파일 경로 | 변경 유형 | 요약 | 비고 |
|-----------|------------|------|------|
| `sip-pbx/src/call_control/db.py` | 수정 | `ringback_schedule_assignments` 스키마를 `position`·`generation_mode`·TTS/Suno 컬럼으로 변경, 마이그레이션·CRUD·`reorder_ringback_schedule_assignments` 추가 | 기존 `music_item_id`/`priority` 테이블은 마이그레이션 시 재생성 |
| `sip-pbx/src/call_control/models.py` | 수정 | 할당 Pydantic 모델 교체, `RingbackAssignmentsReorderBody` 추가 | 설계대로 |
| `sip-pbx/src/api/routers/call_control_api.py` | 수정 | enrich 단순화, `PATCH .../ringback-assignments/reorder` 추가 | 설계대로 |
| `sip-pbx/src/services/ringback_service.py` | 수정 | `resolve_ringback_segment` 추가, `poll_and_notify`에 할당 전용 분기 | 전역 `ringback_settings` 오염 방지 |
| `sip-pbx/src/api/routers/ringback.py` | 수정 | `generate-music` / `apply-music`에 `ringback_assignment_id` 옵션 | 설계대로 |
| `sip-pbx/src/sip_core/ringback_player.py` | 수정 | 세그먼트가 `tts`면 `_play_tts`, `mp3`면 루프 | 설계대로 |
| `sip-pbx/frontend/app/settings/call-control/page.tsx` | 수정 | 모달 TTS+Suno UI, 목록 DnD·토글·재정렬 API, `RuleFormModal` 중복 키 제거 | TS1117 수정 포함 |

## 주요 결정 사항

- **DB**: `priority`·`music_item_id` 대신 **`position` + `generation_mode` + TTS/Suno 필드**로 통합. 기존 행은 마이그레이션 시 `music_item_id`로 예약 DB에서 경로를 조회해 `suno_audio_path`에 넣고 `generation_mode=suno`로 둔다.
- **Suno API**: `ringback_assignment_id`가 있으면 `suno_task_id`·적용 경로는 **call_control 할당 행만** 갱신하고, `ringback_settings`는 건드리지 않는다(폴링 완료 시에도 동일).
- **재생**: `resolve_ringback_segment`가 목록 순서대로 스케줄 매칭 후 `tts`면 문구 합성, `suno`면 로컬 MP3, 없으면 기존처럼 `ringback_settings` MP3 폴백.
- **프론트**: Suno **적용**은 `music-status` 완료 응답의 `items[].audio_url`로 후보를 만들어 `apply-music`에 넘긴다(`music-list`에는 URL이 없을 수 있음).

## 잔여 과제

- 동일 `owner`로 Suno 캐시 파일명이 겹치면 마지막 적용이 덮어쓸 수 있음(기존 `download_and_cache_audio` 규칙과 동일). 할당별 고유 파일명이 필요하면 후속 작업.

## 메타

- 작성일: 2026-04-14
- 관련: `sip-pbx/src/call_control/`, `sip-pbx/src/api/routers/call_control_api.py`, `sip-pbx/src/api/routers/ringback.py`, `sip-pbx/frontend/app/settings/call-control/page.tsx`
