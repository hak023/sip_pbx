## 메타

- 작성일: 2026-04-23 (로컬)
- 상태: 완료
- 관련: 연락처 미분류 실폴더 연동, 상세 패널 출처 표시

## 개요

`ContactFolderTree`가 서버 기본 미분류 폴더 id(`default_unfiled_folder_id`)를 필수로 받도록 바뀐 뒤, 연락처 페이지·글로벌 도크에서 동일 id를 로드·전달하고 DnD PATCH 시 `folder_id`를 일관되게 넣도록 맞췄다. 상세 패널에서는 폴더 셀렉트의 「미분류」를 빈 값이 아닌 실제 기본 폴더 id와 동기화하고, 출처 원문 대신 `sourceDetailLabel`로 표시해 `auto_booking_hint`를 「자동 - 예약 힌트」로 구분한다.

## 변경 이력 (파일별)

| 파일 경로 | 변경 유형 | 요약 | 비고 |
|-----------|------------|------|------|
| `sip-pbx/frontend/app/contacts/page.tsx` | 수정 | API `default_unfiled_folder_id` 수신, `effectiveUnfiledId`, 확장/검색/이동/신규 폴더 부모·삭제 가드 연동 | 설계대로 |
| `sip-pbx/frontend/components/contacts/ContactDetailPanel.tsx` | 수정 | `defaultUnfiledFolderId` prop, 폴더 select 미분류 옵션 값 정규화, 메타 `sourceDetailLabel` | 설계대로 |
| `sip-pbx/frontend/components/GlobalContactsDock.tsx` | 수정 | 페이지와 동일한 미분류 id·확장·이동·새 폴더 부모, `ContactFolderTree` prop 전달 | 설계대로 |

## 주요 결정 사항

- 미분류는 API에서 `null`로 둘 수 있으나 UI에서는 기본 폴더 id를 옵션 값으로 쓰고, 내부 상태는 미분류일 때 `null`로 두어 PATCH/POST와 맞췄다.
- 도크와 전체 페이지가 동일한 폴더 API 응답 스키마를 쓰도록 해 이중 동작을 피했다.

## 잔여 과제 (선택)

- `folder_id`가 여전히 비어 있는 레거시 행은 트리 하단 고아 안내 블록에 남는다. DB 마이그레이션·백엔드 ensure가 모두 적용되면 자연히 사라진다.
