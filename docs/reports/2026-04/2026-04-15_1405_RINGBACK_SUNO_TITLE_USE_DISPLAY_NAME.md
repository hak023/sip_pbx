## 메타

- **작성일(로컬)**: 2026-04-15
- **상태**: 완료
- **관련 경로**: `sip-pbx/frontend/app/settings/call-control/page.tsx`

## 개요

통화 연결음 모달에서 Suno 모드일 때 «표시 이름»과 «곡 제목»을 각각 입력하던 UX를 정리했다. 곡 제목 입력란을 제거하고, 저장 시 `suno_title`은 항상 최종 표시 이름(`name`)과 동일하게 보낸다.

## 변경 이력 (파일별)

| 파일 경로 | 변경 유형 | 요약 | 비고 |
|-----------|-----------|------|------|
| `sip-pbx/frontend/app/settings/call-control/page.tsx` | 수정 | `sunoTitle` 상태·곡 제목 필드 제거; `suno_title` = 표시 이름; Suno 모드 안내 문구 | 백엔드 스키마 유지 |

## 주요 결정 사항

- 서버·DB의 `suno_title` 컬럼은 그대로 두고, 프론트만 단일 입력으로 통일한다. `ringback_service`의 `(suno_title or name)` 폴백과도 일치한다.

## 잔여 과제

- 없음.
