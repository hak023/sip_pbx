## 메타

- **작성일(로컬)**: 2026-04-21 16:38
- **상태**: M1 구현 완료
- **관련 경로**: `sip-pbx/frontend/app/contacts/page.tsx`, `sip-pbx/frontend/lib/contactTree.ts`, `sip-pbx/frontend/components/contacts/*` (구현 당시 페이지는 `app/settings/contacts/page.tsx`였으며, 후속 [`2026-04-21_1707_CONTACTS_MAIN_NAV_CALL_DOCK.md`](2026-04-21_1707_CONTACTS_MAIN_NAV_CALL_DOCK.md)에서 `/contacts`로 이전·구 URL은 리다이렉트)

## 개요

발신 연락처 화면(현재 **`/contacts`**, M1 작성 시점 URL은 `/settings/contacts`)을 **파생 그룹 트리 + 좌우 마스터/디테일**로 바꾸었다. 백엔드·스키마는 변경하지 않고(M1), `source` 및 `display_name`의 `_` 앞 접두로 1단계 그룹을 만들며, 검색 시 API `q`로 필터된 결과에 맞춰 그룹을 **전부 펼친 상태**로 보여 준다. M2(저장형 그룹·`group_id`·DnD)는 이번 범위에서 제외했다.

## 변경 이력 (파일별)

| 파일 경로 | 변경 유형 | 요약 | 비고 |
|-----------|-----------|------|------|
| `sip-pbx/frontend/lib/contactTree.ts` | 추가 | `buildContactTree`, source/접두 그룹 키·라벨, 클라이언트 검색 헬퍼 | 설계대로 |
| `sip-pbx/frontend/components/contacts/ContactGroupTree.tsx` | 추가 | 그룹 펼침·건수 배지·연락처 선택, ARIA tree/treeitem | 설계대로 |
| `sip-pbx/frontend/components/contacts/ContactDetailPanel.tsx` | 추가 | 신규 POST·선택 시 PATCH/DELETE·요약 | 기존 페이지 로직 이전 |
| `sip-pbx/frontend/components/contacts/ContactsLayout.tsx` | 추가 | 상단 툴바 + 좌 트리/우 디테일 그리드, 데스크톱 목록 접기 | 설계대로 |
| `sip-pbx/frontend/app/contacts/page.tsx` | 수정·이전 | 트리·그룹 모드·선택·펼침 상태·로드 연동(M1 시 `settings/contacts`에 두었다가 `/contacts`로 이전) | 설계대로 |
| `sip-pbx/frontend/types/index.ts` | 수정 | `HITLRequest`, `HITLResponseData`, `ConversationMessage` 보강 | 빌드 타입 정합 |
| `sip-pbx/frontend/lib/incomingCallAttention.ts` | 수정 | `setInterval` 핸들 타입(DOM/Node 충돌) 정리 | 빌드 |
| `sip-pbx/frontend/app/booking/slots/page.tsx` | 수정 | POST `body`를 `apiJson` 제네릭에 맞게 단언 | 빌드 |
| `sip-pbx/frontend/app/outbound/page.tsx` | 수정 | 재시도 실패 분기에서 `res.message` 타입 내로잉 | 빌드 |
| `sip-pbx/frontend/app/settings/call-control/page.tsx` | 수정 | `useSearchParams`용 `<Suspense>` 래퍼 export | Next prerender |

## 주요 결정 사항

- **그룹 모드**: 기본 `source`(알려진 값 + `기타`), 옵션 `displayPrefix`(`이름_접미` → `이름_*` 키, 라벨은 접두 문자열).
- **검색**: 기존과 같이 서버 `q`로 조회한 `items`만 트리에 반영; 검색 중에는 모든 그룹을 펼쳐 매칭 리프가 보이도록 함.
- **모바일**: 별도 전체 화면 전환 없이 **세로 스택**(트리 위·디테일 아래)으로 단순화(플랜의 고급 반응형은 후속 가능).
- **M2/M2-DnD**: DDL·REST·DnD는 계획서 2단계로 남김(이번 미구현).

## 잔여 과제

- 트리 키보드 네비게이션(WAI-ARIA TreeView) 고도화.
- 모바일에서 트리↔디테일 전환·뒤로가기 패턴.
- M2: `caller_contact_groups`, `group_id`/`sort_order`, DnD 및 배치 PATCH.
