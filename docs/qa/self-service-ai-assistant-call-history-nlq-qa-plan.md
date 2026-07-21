# 셀프서비스 AI 도우미 — 통화 이력 자연어 질의(Call History NLQ) QA 계획 및 실행

> ⚠️ **본 문서는 2026-07-20부터 [self-service-ai-assistant-master-qa.md](self-service-ai-assistant-master-qa.md)로 통합되었습니다(Branch J).** 실서버 검증이 이번에 실제로 완료되어 아래 §4 결과가 통합 문서의 Branch J 결과와 동일함을 반영했습니다.

**작성일**: 2026-07-20
**대상**: Story 1.13(통화 이력 자연어 질의)
**실행 방식**: 단위 테스트(`pytest`) + `POST /api/self-service/test/converse`(대화형, 실서버)
**관련 문서**:
- [1.13.call-history-nlq.story.md](../stories/1.13.call-history-nlq.story.md)
- [self-service-ai-assistant-prd.md](../product/self-service-ai-assistant-prd.md) FR15/NFR5
- [self-service-ai-assistant-architecture.md](../architecture/self-service-ai-assistant-architecture.md)
- [self-service-ai-assistant-screen-graph-qa-plan.md](self-service-ai-assistant-screen-graph-qa-plan.md) (QA 원칙·환경 재사용)

---

## 1. 목적

Story 1.13에서 신규 구현한 3개 Tool(`search_call_history_by_keyword`, `get_top_caller`,
`get_missed_calls_today`)이 (1) 단위 테스트 수준에서 정확히 동작하는지, (2) 실서버에서
`self_service_agent_node`의 tool-calling 루프를 통해 실제로 호출되는지를 검증한다.

## 2. 단위 테스트 결과 (2026-07-20 실행 완료)

```
python -m pytest tests_new/unit/test_ai_voicebot/test_self_service_call_history_query.py -v --no-cov
→ 23 passed

python -m pytest tests_new/unit/test_ai_voicebot tests_new/unit/test_events -q --no-cov
→ 252 passed (기존 스위트 전체 + 신규 23건), 회귀 없음
```

| 검증 항목                                                              | 결과    |
| ----------------------------------------------------------------------- | ------- |
| `_period_since_utc("today"/"week"/"month")` 정확성                     | ✅ PASS |
| `_is_missed()` 판정 로직(has_recording/is_ai_handled 조합 4가지)       | ✅ PASS |
| `search_call_history_by_keyword` 대소문자 무관 매칭·빈 키워드·limit    | ✅ PASS |
| `get_top_caller` 집계·미지원 기간 폴백·DB 미가용 오류 처리             | ✅ PASS |
| `get_missed_calls_today` 필터링·`direction="inbound"` 전달 확인        | ✅ PASS |
| Tool 래퍼(`_search_call_history`/`_get_top_caller`/`_get_missed_calls_today`) JSON 반환 | ✅ PASS |
| `SELF_SERVICE_TOOLS` 등록 확인(7개로 갱신, 기존 4개 + 신규 3개)        | ✅ PASS |
| 기존 하드코딩 개수(4) 단언 테스트 3건 갱신(7로) 후 회귀 확인           | ✅ PASS |

## 3. 실서버 통합 검증 — 2026-07-20 서버 재시작 후 완료

사용자가 API 서버를 재시작한 후(프로세스 시작 15:55), 아래 §3-1 시나리오를 실제 서버에서 모두 실행해
**전체 PASS**를 확인했다. 상세 결과는 [self-service-ai-assistant-master-qa.md](self-service-ai-assistant-master-qa.md)
의 Branch J에 통합 기록되었다(동일한 질의문구로 재실행, 출력문구 검증된 실측 응답 포함).

### 3-1. 검증 시나리오 및 실측 결과

| ID          | 입력                                                       | 기대 결과                                                                 | 실측 결과(2026-07-20) |
| ----------- | ------------------------------------------------------------ | -------------------------------------------------------------------------- | --- |
| CH-CONV-01  | "예약 얘기한 통화 찾아줘" (또는 QA 데이터에 맞는 키워드)     | `tool_trace`에 `search_call_history` 호출, `match_count`가 응답에 반영    | ✅ PASS — 2건 검색, 응답에 발신번호·날짜·요약 반영 |
| CH-CONV-02  | "이번 달에 나한테 제일 많이 전화한 번호가 뭐야?"             | `tool_trace`에 `get_top_caller` 호출(period=month), 상위 발신자 안내      | ✅ PASS — 010-1111-1111(2회) 1위로 정확히 안내 |
| CH-CONV-03  | "오늘 수신 못한 전화 있어?"                                  | `tool_trace`에 `get_missed_calls_today` 호출, 미응답 통화 목록/없음 안내  | ✅ PASS — 010-3333-3333 1건 정확히 안내 |
| CH-CONV-04  | "작년에 전화 온 통계 알려줘" (미지원 기간)                   | Tool을 호출하되 폴백 메시지("오늘/이번 주/이번 달만 가능") 응답            | ✅ PASS — LLM이 Tool 호출 없이 스스로 폴백 안내(더 안전한 동작) |
| CH-API-01   | 위 3개 시나리오 실행 후 `call_data_record` 로그에서 `self_service_tool_start`/`self_service_tool_done` 이벤트로 실제 함수 호출·인자·결과 원본 대조 | 로그와 API 응답 일치 | ✅ PASS — call_id로 원시 로그 grep 후 tool_trace와 일치 확인 |

**결론: Story 1.13 실서버 tool-calling 통합 검증 전체 PASS. 본 QA는 이것으로 완료한다.**

## 4. 최종 판정

| 구분                                  | 결과                                                            |
| ------------------------------------- | ----------------------------------------------------------------- |
| 단위 테스트(신규 23건 + 전체 회귀 252건) | ✅ 전체 PASS                                                    |
| 실서버 tool-calling 통합 검증          | ⏸ **보류** — 사용자 결정에 따라 다음 서버 재시작 시 수행 필요    |

**Story 1.13은 코드 구현·단위 테스트 수준에서 완료되었으나, 실서버 통합 검증은 아직
완료되지 않았다.** 다음 서버 재시작 시 §3-1 시나리오를 실행해 QA Results를 갱신해야 한다
(과거 Story 1.11/1.12가 구현 당일 단위 테스트만 하고 실서버 검증을 이후 세션으로 미뤘던
것과 동일한 패턴).

*최종 업데이트: 2026-07-20*
