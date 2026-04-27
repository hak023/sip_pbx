# 착신 제어: 안내멘트 UI 제거 및 «통화 연결음» 스케줄 탭

- **작성일**: 2026-04-14 (로컬)
- **상태**: 구현 완료

## 개요

착신 규칙 화면에서 «착신 안내멘트» 선택을 제거하고, 별도 탭 «통화 연결음»에서 **시간 스케줄 + 저장된 Suno 음원(ringback_music_items)** 을 묶어 저장하도록 했다. 런타임은 해당 매칭으로 MP3 경로를 고르고, 없으면 `ringback_settings.suno_audio_path` 로 폴백한다. `GET /api/ringback/settings` 는 call-control 안내멘트를 더 이상 덮어쓰지 않는다.

## 변경 이력 (파일별)

| 파일 경로 | 변경 유형 | 요약 |
|-----------|------------|------|
| `sip-pbx/src/call_control/db.py` | 수정 | `ringback_schedule_assignments` 테이블 및 CRUD |
| `sip-pbx/src/call_control/routing_engine.py` | 수정 | `schedule_active_now()` 공개 |
| `sip-pbx/src/call_control/models.py` | 수정 | RingbackScheduleAssignment* Pydantic 모델 |
| `sip-pbx/src/api/routers/call_control_api.py` | 수정 | `/ringback-assignments` CRUD, 안내멘트 생성 시 링백 플래그 강제 false, ringback-greeting 엔드포인트 비권장 응답 |
| `sip-pbx/src/services/ringback_service.py` | 수정 | `get_music_item_local_path`, `resolve_ringback_mp3_path_for_call` |
| `sip-pbx/src/sip_core/ringback_player.py` | 수정 | 해석된 MP3 경로 사용 및 로그 |
| `sip-pbx/src/api/routers/ringback.py` | 수정 | settings 조회 시 call-control 안내멘트 병합 제거 |
| `sip-pbx/frontend/app/settings/call-control/page.tsx` | 수정 | 안내멘트 탭·모달·규칙 폼 안내멘트 제거, 통화 연결음 탭·모달 |
| `sip-pbx/frontend/app/settings/general/page.tsx` | 수정 | 안내 문구 |

## 주요 결정 사항

- 스케줄 미지정(`schedule_id` NULL) 행은 **항상** 매칭 후보로 취급하며, `priority` 오름차순으로 첫 매칭 음원을 사용한다.
- DB `announcement_profiles.use_as_ringback_greeting` 컬럼은 유지하되, REST 생성 시 항상 0으로 저장하고 ringback-greeting 조회는 빈 값을 반환한다.

## 잔여 과제

- 스케줄 삭제 시 할당 행의 `schedule_id` 정리 UI(또는 서버 CASCADE)는 후속으로 다듬을 수 있다.
