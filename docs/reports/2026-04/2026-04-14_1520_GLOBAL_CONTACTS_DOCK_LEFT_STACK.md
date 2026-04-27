## 메타

- 작성일(로컬): 2026-04-14
- 상태: 구현 반영
- 관련: `frontend/app/layout.tsx`, `GlobalLeftDockStack`, `GlobalContactsDock`, `GlobalSmsDock`, `GlobalCallDock`, `useActiveContactsDockStore`

## 개요

연락처는 기존에 전역 도크가 아니라 Call Dock의 버튼이 `/contacts`로만 이동해, 사용자가 기대한 “세 번째 Call Dock(좌하단 문자 도크와 같은 영역)”이 없었다. 좌하단에 **연락처 전역 도크**를 추가하고, 문자 도크와 **세로 스택**으로 겹치지 않게 배치했다. Call Dock의 「연락처」는 이제 해당 패널을 연다.

## 변경 이력 (파일별)

| 파일 경로 | 변경 유형 | 요약 | 비고 |
|-----------|------------|------|------|
| `sip-pbx/frontend/store/useActiveContactsDockStore.ts` | 추가 | 연락처 도크 phase·needle·peerLabel·최소화 상태 | Zustand 단순 스토어 |
| `sip-pbx/frontend/components/GlobalContactsDock.tsx` | 추가 | CID 기준 검색 API 호출·목록·전체 화면 링크 | `/api/caller-contacts` 재사용 |
| `sip-pbx/frontend/components/GlobalLeftDockStack.tsx` | 추가 | `fixed bottom-4 left-4` 래퍼, 연락처 위·문자 아래 | pointer-events 패턴 |
| `sip-pbx/frontend/components/GlobalSmsDock.tsx` | 수정 | 자체 `fixed` 제거, 스택 너비 `w-full`에 맞춤 | 위치는 스택이 담당 |
| `sip-pbx/frontend/app/layout.tsx` | 수정 | `GlobalSmsDock` → `GlobalLeftDockStack` | |
| `sip-pbx/frontend/components/GlobalCallDock.tsx` | 수정 | 연락처 버튼이 `openFromCall`로 도크 오픈 | `router.push` 제거, 로그 키 변경 |

## 주요 결정 사항

- **전체 트리 UI를 도크에 이식하지 않음**: 유지보수·높이 제약상 API 검색 결과 목록 + 「연락처 전체 화면」 링크로 구성.
- **좌하단 단일 고정 컨테이너**에 연락처(위)·문자(아래)를 두어 두 도크가 같은 `bottom-4 left-4`에서 겹치지 않게 함.

## 잔여 과제 (선택)

- 헤더 메인 내비에서도 연락처 도크만 열기(페이지 이동 없이) 등 동일 UX 확장 여부는 제품 정책에 따름.
