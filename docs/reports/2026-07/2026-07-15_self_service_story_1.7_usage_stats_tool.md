# Story 1.7 (이용 통계 조회 Tool) 구현 완료 보고서

**작성일**: 2026-07-15
**관련 문서**: [1.7.usage-stats-tool.story.md](../../stories/1.7.usage-stats-tool.story.md), [1.6.settings-query-tool.story.md](../../stories/1.6.settings-query-tool.story.md)
**상태**: 완료 (Story Status → Review)

## 1. 문제 요약

테넌트 관리자가 "이번 달 AI가 몇 번 응대했어?"처럼 물으면 대시보드 없이 이용 현황(통화 수, 평균 confidence, HITL 발생 건수)을 답변받아야 한다. PRD는 데이터 소스를 "StatisticsCollector 등 기존 통계 소스 재사용"으로 가정했으나, Story 준비 단계에서 이미 `StatisticsCollector`가 owner 파라미터 없는 전역 프로세스 싱글턴임이 확인되어 `call_record_db` 기반으로 정정된 상태였다. Task 0에서 나머지 미확인 부분(평균 confidence, HITL 발생 건수의 정확한 소스)을 코드로 재검증했다.

## 2. Task 0 — 데이터 소스 재검증 결과

| 항목                   | 확정된 소스                                                                                                                                                                                                                                                                                                  | 비고                                                                                                                                                                                                             |
| ---------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| 통화 수 / AI 응대 건수 | `call_record_db.get_call_records_page(owner=, since=)` → `total`, `is_ai_handled` 카운트                                                                                                                                                                                                                     | 신뢰 가능, PRD 가정과 일치                                                                                                                                                                                       |
| 평균 confidence        | `metrics.py::_get_avg_confidence_today(owner)` 재검증 결과 **실제로 owner 파라미터를 받지만 필터링에 사용하지 않음**(그날 전체 테넌트의 confidence를 섞어 평균)을 코드 확인으로 발견. "오늘"만 지원하는 한계도 발견(이번 주/이번 달 미지원)                                                                  | 기존 함수 수정 없이, 본 Story의 `stats.py`에서 동일 로그 형식(`logs/call_data_record_YYYYMMDD.log`, `llm_response_generated` 이벤트)을 재사용하되 call_id 교집합 필터 + 기간 내 여러 날짜 파일 스캔으로 바로잡음 |
| HITL 발생 건수         | `src/api/routers/hitl.py`의 `HITLService._hitl_request_fifo`는 프로세스 메모리에만 존재하는 일시 구조(통화 종료 시 소멸)로 이력 조회에 부적합함을 확인. 대신 통화 종료 시 `call_insights_buffer.py`가 저장하는 `call_insights.json`의 `ai_unhandled_resolved_by_hitl_count` 필드가 유일한 영속 소스임을 확인 | `metrics.py::_count_unresolved_calls`와 동일한 `recordings_dir` 조회 패턴 재사용                                                                                                                                 |

## 3. 구현 내용

### 3.1 `src/ai_voicebot/self_service/stats.py` (신규)

- `get_self_service_stats(owner, period)`: `period`가 `"week"`/`"month"`가 아니면 AC3 폴백 메시지(+ `supported_periods`) 반환
- 기간 시작 시각(UTC 자정) 계산 후 `call_record_db.get_call_records_page(owner=owner, since=...)` 호출 → `call_count`, `ai_handled_count` 산출
- `_avg_confidence_for_call_ids()`: 기간에 해당하는 모든 날짜의 `call_data_record_*.log`를 스캔해 `llm_response_generated` 이벤트 중 해당 owner의 call_id 집합에 속한 것만 필터링해 평균
- `_hitl_count_for_items()`: 각 통화의 `recordings_dir`에서 `call_insights.json`을 읽어 `ai_unhandled_resolved_by_hitl_count`를 합산(`load_call_insights_for_directory` 재사용, IV1 — 읽기 전용)

### 3.2 `get_self_service_stats_tool` (Task 2, `tools.py`/`self_service_agent.py` 수정)

- `SELF_SERVICE_TOOLS`에 세 번째 도구로 추가(Story 1.6에서 도입한 `bind_tools` 루프를 그대로 재사용 — 노드 구조 변경 없음)
- `_TOOL_USAGE_INSTRUCTION`에 "week"/"month"만 지원함을 명시하고, 그 외 기간(지난달·작년 등)은 Tool을 호출하지 말고 정형 질의만 가능하다고 안내하도록 지시 추가(AC3)

### 3.3 테스트 (`tests_new/unit/test_ai_voicebot/test_self_service_stats.py`, 신규)

15개 테스트:
- 기간 계산(주 시작=월요일, 월 시작=1일), 미지원 기간 폴백
- `get_self_service_stats()`가 `call_record_db.get_call_records_page()`만 호출하는지(IV1), owner 격리, DB 미가용/빈 결과 처리
- `_avg_confidence_for_call_ids()` call_id/이벤트명 필터링 검증
- `_hitl_count_for_items()` call_insights.json 합산/누락 처리
- Tool 래퍼 등록·위임·예외 흡수

기존 Story 1.6 테스트(`test_registers_both_tools`)가 도구 개수 2를 하드코딩하고 있어 3으로 갱신(`test_registers_all_tools`).

## 4. 검증 결과

```
python -m pytest tests_new/unit/test_ai_voicebot/test_self_service_stats.py -v --no-cov
→ 15 passed

python -m pytest tests_new/unit/test_ai_voicebot tests_new/unit/test_events -q --no-cov
→ 123 passed (Story 1.1~1.7 누적 108 + 신규 15), 회귀 없음
```

## 5. 변경 파일

- `src/ai_voicebot/self_service/stats.py` (신규)
- `src/ai_voicebot/self_service/tools.py` (수정 — `get_self_service_stats_tool` 추가)
- `src/ai_voicebot/langgraph/nodes/self_service_agent.py` (수정 — `_TOOL_USAGE_INSTRUCTION`에 통계 조회 규칙 추가)
- `tests_new/unit/test_ai_voicebot/test_self_service_stats.py` (신규, 15 tests)
- `tests_new/unit/test_ai_voicebot/test_self_service_settings_tool.py` (수정 — 도구 개수 검증 2→3)
- `docs/stories/1.7.usage-stats-tool.story.md` (Task 0~3 체크, 데이터 소스 재검증 결과 표, Dev Agent Record/Change Log 갱신, Status → Review)

## 6. 후속 작업

- Story 1.8(자동설정 실행)에서 `SELF_SERVICE_TOOLS`/`bind_tools` 루프를 확장해 쓰기 Tool을 추가할 예정 — `destructive` 플래그(Story 1.4) 집행 로직 필요.
- `metrics.py::_get_avg_confidence_today`의 owner 미필터링 버그는 이번 Story 범위 밖이라 수정하지 않았다. 운영 대시보드에도 영향을 줄 수 있으므로 별도 버그 리포트로 다룰지 검토 필요.

---
*최종 업데이트: 2026-07-15*
