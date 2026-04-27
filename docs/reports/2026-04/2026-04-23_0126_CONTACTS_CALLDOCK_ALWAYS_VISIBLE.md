## 메타

- **작성일(로컬)**: 2026-04-23 01:26
- **상태**: 구현 완료

## 개요

연락처 좌하단 도크를 **CID 버튼으로만 열리던(idle) 방식에서 제거**하고, 기본 **최소화(핀) 상태로 항상 표시**한다. 목록은 `/contacts`와 동일하게 **`GET /api/caller-contacts?owner&limit=200&offset=0`** 에 선택적 **`q`(검색)** 를 붙여 테넌트 관리 연락처를 불러온다. CID에서 「연락처」를 누르면 기존처럼 패널을 펼치고 발신 번호로 **검색어를 채워** 해당 연락처를 찾기 쉽게 한다.

## 변경 이력 (파일별)

| 파일 경로 | 변경 유형 | 요약 | 비고 |
|-----------|-----------|------|------|
| `sip-pbx/frontend/store/useActiveContactsDockStore.ts` | 수정 | `phase`/`idle` 제거, 기본 `userMinimized: true`, `listQuery`·`setListQuery` 추가, `dismiss`는 최소화+상태 초기화 | 항상 도크 사용 가능 |
| `sip-pbx/frontend/components/GlobalContactsDock.tsx` | 수정 | 항상 렌더, contacts API와 동일 fetch, 검색 입력, 헤더 문구·핀 라벨 조정 | `aria-label` 닫기→최소화 |

## 주요 결정 사항

- **전역 표시**: `phase === "idle"` 시 `null` 반환 제거 — 앱 로드 시 곧바로 최소화 핀 노출.
- **데이터 범위**: `needle`(CID)은 링크·헤더 컨텍스트용으로 두고, 목록 쿼리는 **`listQuery` → API `q`** 로 `/contacts`의 `q`와 동일 역할.
- **CID 연동**: `openFromCall` 시 `listQuery`를 발신 `needle`으로 설정해 필터된 목록 표시; 사용자가 검색창을 비우면 전체(최대 200건) 조회.

## 잔여 과제 (선택)

- 연락처 200건 초과 시 도크 내 페이지네이션 또는 “전체 화면에서 더 보기” 안내 강화.
