## 메타

- **작성일(로컬)**: 2026-04-23 06:09
- **상태**: 구현 완료
- **근거 플랜**: 연락처 사용자 폴더 트리 + DnD + UI 개선

## 개요

출처·표시명 접두 **파생 그룹**을 제거하고, 테넌트별 **사용자 정의 폴더(`contact_folders`)** 와 `caller_contacts.folder_id`로 디렉터리형 트리를 구성한다. `@dnd-kit`으로 연락처·폴더 이동을 지원하고, 출처는 **행 배지**로만 표시한다.

## 변경 이력 (파일별)

| 파일 경로 | 변경 유형 | 요약 | 비고 |
|-----------|-----------|------|------|
| `sip-pbx/src/booking/database.py` | 수정 | `contact_folders` DDL, `caller_contacts.folder_id`, 마이그레이션 ALTER | 폴더 테이블이 contacts보다 앞서 생성 |
| `sip-pbx/src/common/contact_folder_db.py` | 추가 | 목록/생성/수정/삭제(하위 승격·연락처 재배치), 순환 검사 | |
| `sip-pbx/src/api/routers/contact_folders.py` | 추가 | `/api/contact-folders` CRUD | |
| `sip-pbx/src/api/main.py` | 수정 | 라우터 등록 | |
| `sip-pbx/src/common/caller_contact_db.py` | 수정 | `folder_id` 조회·삽입·갱신, 폴더 이동만 시 source 유지 | |
| `sip-pbx/src/api/routers/caller_contacts.py` | 수정 | POST/PATCH `folder_id` | |
| `sip-pbx/frontend/lib/contactFolders.ts` | 추가 | 타입·`groupFoldersByParent`·순환 헬퍼·`UNFILED_DROP_ID` | |
| `sip-pbx/frontend/lib/contactTree.ts` | 수정 | `ContactRow.folder_id`, 출처 배지 헬퍼만 유지 | `buildContactTree` 등 제거 |
| `sip-pbx/frontend/components/contacts/ContactFolderTree.tsx` | 추가 | DnD 트리·미분류·세련 UI | |
| `sip-pbx/frontend/components/contacts/ContactGroupTree.tsx` | 삭제 | 파생 그룹 전용 | |
| `sip-pbx/frontend/app/contacts/page.tsx` | 수정 | 폴더 CRUD 툴바·병렬 로드·`ContactFolderTree` | |
| `sip-pbx/frontend/components/GlobalContactsDock.tsx` | 수정 | 동일 트리·compact | |
| `sip-pbx/frontend/components/contacts/ContactDetailPanel.tsx` | 수정 | 폴더 `<select>`, 신규 시 `defaultFolderId` | |

## 주요 결정 사항

- **폴더 삭제**: 하위 폴더는 삭제 노드의 `parent_id`로 승격, 해당 폴더 연락처도 동일 타깃으로 이동 후 삭제.
- **이름·메모·번호만** 수정 시 `source='manual'` 처리; **폴더만 이동** 시에는 source 유지.
- **미분류**: `folder_id` NULL, 드롭 id `contact-drop-unfiled`.

## 잔여 과제 (선택)

- 같은 부모 내 폴더 `sort_order` 드래그 정렬 UI.
- 검색 시 빈 폴더 숨김 등 UX 미세 조정.
