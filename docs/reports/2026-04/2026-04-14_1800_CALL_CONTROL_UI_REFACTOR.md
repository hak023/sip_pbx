## 개요

착신 제어(Call Control) 설정 UI를 사용자 요청에 따라 리팩터링.
'직접 연결' 동작 제거, 규칙 순서 드래그 정렬 도입, 착신 그룹 탭 제거,
발신자 필터 입력을 모달 형식으로 개선(차단/직접응대/AI응대 옵션 추가).

## 변경 이력 (파일별)

| 파일 경로 | 변경 유형 | 요약 | 비고 |
|---|---|---|---|
| `frontend/app/settings/call-control/page.tsx` | 수정 | 4가지 UI 개선 전체 반영 | 전면 재작성 |
| `src/call_control/models.py` | 수정 | `RoutingAction.BLOCK` 추가 | 발신자 필터 차단 지원 |
| `frontend/package.json` | 수정 | `@dnd-kit/core`, `@dnd-kit/sortable`, `@dnd-kit/utilities` 추가 | 드래그 정렬 라이브러리 |

## 상세 변경 내용

### 1. '직접 연결' 동작 옵션 제거
- `RoutingAction` 타입에서 `'direct'` 제거 (프론트 전용)
- `RuleFormModal`의 동작 선택 버튼 목록에서 제외
- 규칙이 없는 경우 안내 문구: "규칙이 없으면 기본 직접 연결(A→B)이 적용됩니다."로 명시

### 2. 규칙 목록 드래그 정렬 + 우선순위 자동 지정
- `@dnd-kit` 라이브러리 도입: `DndContext`, `SortableContext`, `useSortable` 사용
- `SortableRuleCard` 컴포넌트로 분리, 드래그 핸들(≡) + 순서 번호 표시
- 드래그 종료 시 `PATCH /api/call-control/rules/{id}/priority` 호출로 서버 동기화 (500ms debounce)
- 모달에서 우선순위 숫자 입력 필드 제거, 새 규칙은 목록 끝 priority 자동 할당

### 3. 착신 그룹 탭 제거
- `TabId`에서 `'ring-groups'` 제거
- 탭 목록 및 콘텐츠 영역에서 착신 그룹 섹션 전체 삭제
- `loadAll`에서 ring-groups API 호출 제거
- 오버플로우 정책 섹션도 착신 그룹과 함께 제거

### 4. 발신자 필터 UI 개선
- 기존 `prompt()` 방식 → `CallerFilterFormModal` 컴포넌트로 전환
- 입력 항목: 발신번호 패턴, 필터 이름(선택), 연결 옵션, 활성화 여부
- 연결 옵션: **차단** / **직접 응대** / **AI 응대** (라디오 버튼 형식)
- 백엔드 `RoutingAction` 열거형에 `BLOCK = "block"` 추가
- API 저장 시 `ai` → `immediate_ai` 매핑, `block` → `block` 직접 전달
- 필터 목록 카드에 배지(차단/직접 응대/AI 응대)와 수정 버튼 추가

## 주요 결정 사항

- **`block` 백엔드 지원**: 단순 UI 레이블로만 처리하지 않고 `RoutingAction.BLOCK`을 모델에 추가하여 라우팅 엔진이 SIP 603 Decline 처리를 향후 구현할 수 있도록 준비.
- **드래그 debounce**: 드래그 중 매 이벤트마다 API 요청하지 않고 정렬 완료 500ms 후 일괄 PATCH.
- **`direct` 제거 범위**: 프론트 착신 규칙 모달에서만 제거. `CallerFilter`의 `direct` 옵션(직접 응대)은 필터 전용으로 유지.

## 잔여 과제

- 라우팅 엔진(`routing_engine.py`)에서 `block` 액션 실제 처리 구현 (현재 enum만 추가된 상태).
- 드래그 정렬 순서가 백엔드 재조회 시 반영되려면 `priority` 필드 기반 정렬이 API에서 보장되어야 함 (현재 서버측 order by priority 확인 필요).
