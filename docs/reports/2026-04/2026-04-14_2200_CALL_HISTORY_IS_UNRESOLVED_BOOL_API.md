## 메타

- 작성일: 2026-04-14 (로컬)
- 상태: 구현 반영
- 관련: `sip-pbx/src/api/routers/call_history.py`, `sip-pbx/frontend/lib/callHistoryUnresolved.ts`, `2026-04-14_2145_CALL_HISTORY_UNRESOLVED_TOGGLE_FIX.md` 잔여 과제

## 개요

통화 이력 목록 API 응답의 `is_unresolved`를 **항상 JSON boolean**으로 직렬화하도록 정규화했다. SQLite·레거시 JSON에서 `0/1` 또는 문자열 `"true"`/`"false"`가 올 때 `bool("false") === True`(Python) 같은 오해를 막기 위해 서버 측에서 명시적으로 코어션한다.

## 변경 이력 (파일별)

| 파일 경로 | 변경 유형 | 요약 | 비고 |
|-----------|------------|------|------|
| `sip-pbx/src/api/routers/call_history.py` | 수정 | `_coerce_bool_unresolved` 추가, DB/파일 스캔 목록·배치 초기화에서 동일 규칙 적용 | 응답 직전 재할당으로 일관성 보장 |
| `sip-pbx/frontend/lib/callHistoryUnresolved.ts` | 수정 | 주석·분기 정리(API boolean 전제, 레거시 숫자·누락만 보조) | `null` 전용 분기 제거 |
| `sip-pbx/docs/reports/2026-04/2026-04-14_2145_CALL_HISTORY_UNRESOLVED_TOGGLE_FIX.md` | 수정 | 잔여 과제 완료 링크 | |

## 주요 결정 사항

- **문자열 처리**: `"false"` 등은 False로, 알 수 없는 문자열은 보수적으로 False.
- **목록 항목**: DB 경로는 merge 후 `item["is_unresolved"]`를 한 번 더 코어션; 파일 스캔 경로는 `if insights` 블록 밖에서 최종 코어션해 insights 없는 행도 동일하게 처리.

## 잔여 과제 (선택)

- 없음.
