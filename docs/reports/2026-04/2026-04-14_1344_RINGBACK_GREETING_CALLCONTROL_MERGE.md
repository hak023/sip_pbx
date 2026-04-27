## 개요

`/settings/ringback`의 "인사말(TTS)" 기능과 `/settings/call-control`의 안내멘트 기능이 중복되어 있어, 인사말 관리를 call-control 안내멘트로 일원화했다. ringback 페이지의 Suno 음원 생성/관리 기능은 그대로 유지한다.

## 변경 이력 (파일별)

| 파일 경로 | 변경 유형 | 요약 | 비고 |
|---|---|---|---|
| `src/call_control/models.py` | 수정 | `AnnouncementProfile`, `AnnouncementCreate`, `AnnouncementUpdate`에 `use_as_ringback_greeting` 필드 추가 | |
| `src/call_control/db.py` | 수정 | DDL 컬럼 추가, `_migrate_announcement_profiles()` 추가, CRUD 반영, `get_ringback_greeting_announcement()` 신규 | 기존 DB ALTER TABLE migration 처리 |
| `src/api/routers/call_control_api.py` | 수정 | `GET /api/call-control/announcements/ringback-greeting` 엔드포인트 추가 | `{announcement_id}` 경로보다 먼저 등록 |
| `src/api/routers/ringback.py` | 수정 | `GET /api/ringback/settings` — call-control ringback-greeting 우선 조회 폴백 추가 | |
| `frontend/app/settings/call-control/page.tsx` | 수정 | `AnnouncementProfile` 타입 확장, 폼 모달에 링백 인사말 체크박스 + 경고 추가, 목록 카드에 배지 추가, URL `?tab=` 쿼리 파라미터 지원 | |
| `frontend/app/settings/ringback/page.tsx` | 수정 | 인사말(TTS) 섹션 제거 → call-control 안내멘트 링크 카드로 대체, 관련 state/API 제거 | greeting_text, enabled_greeting, fetchKbGreeting, handleToggleGreeting 제거 |

## 주요 결정 사항

1. **단방향 통합**: 인사말 텍스트 관리는 call-control 안내멘트로 완전 이전. ringback_settings.greeting_text는 폴백으로만 사용(하위 호환).
2. **단일 링백 인사말 보장**: `create_announcement`, `update_announcement`에서 `use_as_ringback_greeting=True`로 설정 시 다른 행의 플래그를 자동 해제.
3. **인덱스 migration 순서**: `executescript` DDL에서 새 컬럼을 포함한 인덱스 생성이 불가하여, 인덱스를 `_migrate_announcement_profiles()` 내에서 `ALTER TABLE` 이후 생성하도록 분리.
4. **URL 탭 파라미터**: ringback 페이지의 "안내멘트 설정으로 이동" 링크가 `/settings/call-control?tab=announcements`로 이동하도록 `useSearchParams` 적용.

## 잔여 과제

- ringback_player.py에서 인사말 텍스트를 직접 call-control DB에서 읽도록 추가 연동 가능 (현재는 ringback.py GET settings를 통해 간접 참조).
- `ringback_settings.greeting_text`, `enabled_greeting` 컬럼은 하위 호환을 위해 DB에 유지. 추후 cleanup 가능.
