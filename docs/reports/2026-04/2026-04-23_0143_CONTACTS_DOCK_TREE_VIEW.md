## 메타

- **작성일(로컬)**: 2026-04-23 01:43
- **상태**: 구현 완료

## 개요

연락처 Call Dock 목록을 **전체 연락처 화면과 동일한 1단계 그룹 트리**(`buildContactTree` + `ContactGroupTree`)로 표시한다. **출처(source) / 표시명 접두** 그룹 모드·그룹 펼침·검색 시 전체 그룹 펼침 동작을 `/contacts` 페이지와 맞춘다. 항목 클릭 시 **`/contacts?needle=`** 로 이동해 상세 편집으로 이어지게 한다.

## 변경 이력 (파일별)

| 파일 경로 | 변경 유형 | 요약 | 비고 |
|-----------|-----------|------|------|
| `sip-pbx/frontend/components/GlobalContactsDock.tsx` | 수정 | `ContactGroupTree` 통합, `groupMode`·`expandedGroupIds`·`selectedId`, 행 선택 시 `router.push` | 기존 평면 `Link` 리스트 제거 |

## 주요 결정 사항

- **컴포넌트 재사용**: `ContactGroupTree`를 그대로 써서 접근성·UI를 `/contacts`와 통일.
- **행 클릭**: 도크 너비에서는 상세 패널 대신 **전체 화면으로 이동**(기존 링크와 동등한 목적).

## 잔여 과제 (선택)

- 도크 안에서 `ContactDetailPanel` 인라인 편집(너비·스크롤 제약).
