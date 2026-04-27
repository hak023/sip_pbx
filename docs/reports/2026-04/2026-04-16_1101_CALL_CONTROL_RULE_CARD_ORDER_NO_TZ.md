## 개요

착신 규칙 목록 카드에서 **착신 동작 배지를 «적용 중» 배지보다 앞**에 두고, 시간 조건 상세에서 **타임존 줄을 제거**했다.

## 변경 이력 (파일별)

| 파일 경로 | 변경 유형 | 요약 | 비고 |
|-----------|-----------|------|------|
| `sip-pbx/frontend/app/settings/call-control/page.tsx` | 수정 | `SortableRuleCard` 내 배지 순서: 동작 → 적용 중 | 설계대로 |
| `sip-pbx/frontend/lib/call-control-display.ts` | 수정 | `formatScheduleDetailLines`에서 타임존 행 제거 | 스케줄 탭·규칙 카드 공통 |

## 주요 결정 사항

- 타임존은 UI에서 숨기고, 서버/스키마의 `timezone` 필드는 그대로 둔다(평가 로직 불변).

---

- 작성일: 2026-04-16 (로컬)
