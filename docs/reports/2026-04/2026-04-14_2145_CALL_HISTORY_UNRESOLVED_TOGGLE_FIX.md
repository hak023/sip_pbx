## 메타

- 작성일: 2026-04-14 (로컬)
- 상태: 수정 반영
- 관련: `sip-pbx/frontend/lib/callHistoryUnresolved.ts`, `sip-pbx/frontend/components/call-history/CallHistoryPanel.tsx`, `sip-pbx/frontend/app/dashboard/page.tsx`

## 개요

통화 이력에서 미해결/해결 토글이 기대와 다르게 보이거나 동작하지 않는 문제를 점검했다. 원인으로 **`is_unresolved` 가 SQLite·JSON 경로에서 0/1 숫자로 올 때 `??` 만으로는 불리언으로 정규화되지 않음**(React에서 `0 && …` 렌더 이슈 가능)과, 버튼 문구가 **상태가 아니라 다음 동작**을 표시해 사용자 기대와 어긋남을 정리했다.

## 변경 이력 (파일별)

| 파일 경로 | 변경 유형 | 요약 |
|-----------|------------|------|
| `sip-pbx/frontend/lib/callHistoryUnresolved.ts` | 추가 | `computeIsUnresolved(row, nUnhandled)` — boolean/number/null/undefined 일관 처리 |
| `sip-pbx/frontend/components/call-history/CallHistoryPanel.tsx` | 수정 | `FragmentRow` 에서 위 헬퍼 사용, 버튼 문구를 **현재 상태**(미해결 / 해결)로 표시 |
| `sip-pbx/frontend/app/dashboard/page.tsx` | 수정 | 통화 이력 테이블 동일 로직·버튼 문구 정렬 |

## 주요 결정 사항

- **명시적 `false`**: 운영자가 해결로 표시한 경우(`is_unresolved === false`)에는 `ai_unhandled_count` 가 남아 있어도 미해결로 보이지 않는다.
- **버튼 라벨**: 미해결 행 → `미해결`, 해결된 행 → `해결`(토글 시 문구가 교대로 바뀜). 배지 `미해결 N` 은 기존처럼 미처리 건이 있을 때만 표시.

## 잔여 과제 (선택)

- ~~목록 API가 `is_unresolved` 를 항상 boolean 으로 직렬화~~ → 후속 반영: `2026-04-14_2200_CALL_HISTORY_IS_UNRESOLVED_BOOL_API.md`
