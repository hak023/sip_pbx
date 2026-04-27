## 메타

- **작성일(로컬)**: 2026-04-21 17:07
- **상태**: 구현 완료
- **근거 플랜**: 연락처 메인 노출 및 Call Dock 연동(내부 설계안)

## 개요

발신 연락처를 **상단 메인 내비**(`/contacts`)로 옮기고, 구 경로 `/settings/contacts`는 **`/contacts`로 리다이렉트**한다. Call Dock CID 카드에 **문자** 옆 **연락처** 버튼을 두어, 현재 통화 발신 번호를 `needle` 쿼리로 연락처 페이지에 넘긴다. URL `needle`/`q`는 검색어와 동기화하며, 성공 응답 기준 **단일 매칭이면 자동 선택**, **0건이면 신규 폼 매칭 번호 프리필**한다.

## 변경 이력 (파일별)

| 파일 경로 | 변경 유형 | 요약 | 비고 |
|-----------|-----------|------|------|
| `sip-pbx/frontend/app/contacts/page.tsx` | 추가 | 기존 연락처 UI + `useSearchParams` + Suspense + URL 포커스 로직 | 설계대로 |
| `sip-pbx/frontend/app/settings/contacts/page.tsx` | 수정 | 서버 `redirect('/contacts')`만 유지 | 북마크 호환 |
| `sip-pbx/frontend/components/AppHeader.tsx` | 수정 | `MAIN_NAV`에 발신 연락처, `SETTINGS_NAV`에서 제거 | 설계대로 |
| `sip-pbx/frontend/components/GlobalCallDock.tsx` | 수정 | CID 영역 `연락처` 버튼, `router.push(/contacts?needle=…)`, 로그 | 설계대로 |
| `sip-pbx/frontend/components/contacts/ContactDetailPanel.tsx` | 수정 | `prefillNewPhone` prop | Call Dock 0건 시 |

## 주요 결정 사항

- Dock에서는 **전역 두 번째 Dock** 대신 **전체 페이지 이동**(트리+디테일 유지, 설계안과 동일).
- `contacts_dock_open_skipped` / `contacts_dock_open_navigate`로 peer 없음·이동 추적.

## 잔여 과제

- 통화 유지가 필요하면 새 탭 열기 옵션.

## 문서 정리(후속)

- M1 리포트 [`2026-04-21_1638_CONTACTS_TREE_UI_M1.md`](2026-04-21_1638_CONTACTS_TREE_UI_M1.md), CID 리포트 [`2026-04-21_1340_CID_DUAL_LINE_CONTACTS_STATS_IMPL.md`](2026-04-21_1340_CID_DUAL_LINE_CONTACTS_STATS_IMPL.md)의 `/settings/contacts`·파일 경로 설명을 **`/contacts` 기준**으로 갱신함(본 섹션 기록일 동일 배치).
