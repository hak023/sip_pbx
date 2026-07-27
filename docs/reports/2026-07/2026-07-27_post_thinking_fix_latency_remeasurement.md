# thinking 비활성화(Epic 6) 이후 지연 재측정 리포트 — 실구현(Epic 4)은 보류, 측정·비교만 수행

**작성일**: 2026-07-27
**목적**: Epic 6(Gemini SDK 마이그레이션, thinking 실제 비활성화) 완료 후 실서버 chitchat 응답
지연을 재측정해 2026-07-24 베이스라인과 비교한다. **TTFT 구조 개선(Epic 4) 실제 구현은
이번에 하지 않고, 데이터 확보와 재판단 근거 마련만 수행한다**(사용자 지시).
**관련 문서**: [2026-07-24_ai_pipeline_qa_endpoint_and_latency_findings.md](2026-07-24_ai_pipeline_qa_endpoint_and_latency_findings.md)
(베이스라인), [6.4.full-integration-verification-and-cleanup.story.md](../../stories/6.4.full-integration-verification-and-cleanup.story.md),
[voice-latency-turn-taking-prd.md](../../product/voice-latency-turn-taking-prd.md) Story 4.1

---

## 1. 측정 방법

사용자가 재시작한 실서버(`AI_PIPELINE_QA_TEST_MODE` 게이트 활성)의
`/api/ai-pipeline/test/converse`(QA 하네스, 실서버 통화 없이 STT 직후~TTS 직전 갭을 텍스트로
재현)로 동일 유형 발화를 반복 호출하고 `agent_elapsed_sec`(API 응답) +
`call_data_record_20260727.log`의 `agent_graph_total`/`classify_intent`/
`llm_generate_response` 이벤트(원본 로그)를 cross-check했다.

## 2. 결과 — 베이스라인(2026-07-24, thinking 켜짐) vs 재측정(2026-07-27, thinking 꺼짐)

| 발화 유형                              | 베이스라인(2026-07-24)        | 재측정(2026-07-27, n=4)                | 개선폭         |
| -------------------------------------- | ----------------------------- | -------------------------------------- | -------------- |
| chitchat("오늘 날씨가 참 좋네요" 계열) | 9.6~9.75초                    | **1.05~3.02초**(평균 약 2.0초)         | 약 70~89% 감소 |
| greeting                               | 0.02초(원래도 즉시 응답 경로) | (재측정 안 함 — 원래도 문제 없던 경로) | —              |

### 재측정 개별 표본 (chitchat 계열, `reset_session=true`로 매 회 신규 세션)

| 회차                                       | agent_elapsed_sec | 비고                                                                                    |
| ------------------------------------------ | ----------------- | --------------------------------------------------------------------------------------- |
| 1                                          | 3.020             | 최초 호출(콜드스타트 가능성) — 노드별: classify_intent 1.986s, generate_response 1.005s |
| 2                                          | 2.345             |                                                                                         |
| 3                                          | 2.070             |                                                                                         |
| 4                                          | 1.712             |                                                                                         |
| 5("커피숍" 발화, intent=chitchat으로 분류) | 1.196             |                                                                                         |
| 6                                          | 1.114             |                                                                                         |
| 7                                          | 1.050             |                                                                                         |

### 노드별 breakdown(1회차, 원본 로그 cross-check)

```
classify_intent:     1.986s  (LLM 3차 분류 호출 — 여전히 thinking 아닌 orchestration 자체 비용)
generate_response:   1.005s  (메인 chitchat 응답 생성)
update_state/route_utterance/hitl_alert/update_cache: 각 0.01초 미만 (무시 가능)
────────────────────────────
graph_elapsed_sec:   3.01s   (거의 전부 classify_intent + generate_response 두 LLM 호출의 합)
```

## 3. 해석

1. **thinking 비활성화만으로 이미 목표(5초 SLA)를 충분히 만족한다.** 재측정 전 구간 모두
   5초 미만이며, 최악 표본(3.02초)도 베이스라인 최선 표본보다 낮다.
2. **잔여 지연의 원인이 바뀌었다**: 베이스라인 리포트(2026-03-30)는 "LLM 호출 자체(thinking
   포함)가 병목"이라고 봤으나, thinking 제거 후에는 **`classify_intent`(3차 LLM 분류)가
   `generate_response`와 거의 동급의 비중(약 2배)** 을 차지한다. 이는 아직 thinking과 무관한
   "LLM 호출 2회를 순차 실행"하는 orchestration 구조 자체의 비용이다.
3. **Epic 4(진짜 TTFT 전환)의 전제가 바뀌었다.** Story 4.1은 thinking이 켜진 채(6~9초대) 내려진
   결정이라 "안전 서브셋 {chitchat, out_of_scope}만 우선 TTFT 적용"으로 범위를 좁혔다. 지금은
   전체 응답이 이미 3초 이내라, **TTFT 구조 전환의 한계효용이 베이스라인 대비 훨씬 작아졌다.**
   다만 여전히 "1~3초"는 사람 대화 기준으로는 체감되는 지연이므로, Epic 4를 완전히 폐기할
   근거는 아니다.

## 4. 권고 (실구현 없음, 의사결정 자료로만 제공)

- **Epic 4는 즉시 실구현(Story 4.2)로 넘어가지 말고, 다음 중 하나를 사용자가 선택해야 한다**:
  (a) 현재 수준(1~3초)을 충분하다고 보고 Epic 4를 보류/폐기, (b) `classify_intent`(3차 분류)
  자체를 줄이거나 병렬화하는 **다른 종류의 개선**(TTFT 구조 전환이 아니라 orchestration 단순화)
  으로 범위를 재정의, (c) 원안(Story 4.1의 TTFT 전환)을 그대로 진행하되 기대 효과가
  베이스라인 대비 작아졌음을 감안.
- 표본이 아직 적다(chitchat 계열 7건, 다른 인텐트 미측정) — 실제 착수 시에는
  question/booking/help 등 다른 intent도 포함한 표본을 늘려야 한다(2026-07-20/21 self_service
  트랙의 "표본을 늘리기 전까지 결론 내리지 않는다" 교훈 적용).

## 5. 다음 단계

- 이번 리포트는 **측정·비교만** 수행했고 Epic 4 실구현은 진행하지 않는다(사용자 지시).
- 다음 착수 시점에 사용자가 위 §4의 (a)/(b)/(c) 중 방향을 정하면 그에 따라 Story 4.1을
  갱신하거나 신규 Story로 대체한다.

*최종 업데이트: 2026-07-27*
