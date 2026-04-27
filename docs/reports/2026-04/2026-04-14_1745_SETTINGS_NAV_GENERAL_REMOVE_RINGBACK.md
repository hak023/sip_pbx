## 메타

- 작성일: 2026-04-14
- 상태: 완료
- 관련: 설정 메뉴 재구성, 링백 UI 제거, Google OAuth 경로

## 개요

프론트 **설정**에서 링백 전용 페이지를 제거하고, **일반 설정** 하위에 Google Calendar **OAuth·연동** UI를 두었다. 헤더 **설정** 드롭다운은 섹션(일반 설정 / 통화·착신 / 조직·채팅)으로 재구성했다. OAuth 콜백 리다이렉트는 `/settings/general`로 맞췄고, `/settings/integrations`는 호환용 리다이렉트만 남긴다.

## 변경 이력 (파일별)

| 파일 경로 | 변경 유형 | 요약 | 비고 |
|-----------|-----------|------|------|
| `sip-pbx/frontend/app/settings/ringback/page.tsx` | 삭제 | 링백 전용 설정 UI 제거 | 착신 제어 안내멘트(Suno)로 통합 |
| `sip-pbx/frontend/app/settings/general/page.tsx` | 추가 | 일반 설정 — Google OAuth·Calendar 연동 | 기존 integrations 본문(링백 카드 제외) |
| `sip-pbx/frontend/app/settings/integrations/page.tsx` | 수정 | `/settings/general` 로 리다이렉트(Suspense+search) | 북마크 호환 |
| `sip-pbx/frontend/components/AppHeader.tsx` | 수정 | 설정 드롭다운 섹션·링크 목록 | 링백 제거 |
| `sip-pbx/frontend/app/booking/page.tsx` | 수정 | 연동 안내 링크 → `/settings/general` | |
| `sip-pbx/src/api/routers/google_calendar.py` | 수정 | OAuth 콜백 리다이렉트 URL `.../settings/general` | |

## 주요 결정 사항

- Google Cloud Console **승인 리다이렉트 URI**는 API 콜백(`.../api/google/oauth/callback`)이므로 변경 없음. **성공 후 브라우저 착지 URL**만 `general`로 변경.

## 잔여 과제

- 문서·스크린샷에 `/settings/integrations`가 남아 있으면 `general`로 정리.
