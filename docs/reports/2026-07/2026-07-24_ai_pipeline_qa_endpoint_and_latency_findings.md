# AI 파이프라인 QA 테스트 엔드포인트로 지연 실측 — 실서버 통화 없이 검증

**작성일**: 2026-07-24
**작업 유형**: 신규 QA 테스트 하네스 구축 + 실측 검증(코드 변경 있음, `src/api/routers/ai_pipeline_test.py` 신규)
**관련 문서**:
- [voice-latency-turn-taking-prd.md](../../product/voice-latency-turn-taking-prd.md)
- [voice-latency-turn-taking-architecture.md](../../architecture/voice-latency-turn-taking-architecture.md)
- [2026-07-24_voice_latency_epic3_story_3.1_3.2_3.4_implementation.md](2026-07-24_voice_latency_epic3_story_3.1_3.2_3.4_implementation.md)
- [2026-07-24_voice_latency_epic4_5_story_4.1_5.1_design_decisions.md](2026-07-24_voice_latency_epic4_5_story_4.1_5.1_design_decisions.md)

## 배경

사용자가 "테스트는 별도 코드 구현으로 수행 가능하다"며 셀프서비스 AI QA 하네스
(`src/api/routers/self_service_test.py` — STT 직후~TTS 직전을 텍스트로 재현하는
`/api/self-service/test/converse`)와 동일한 패턴을 voice-latency 작업에도 적용할 것을 제안했다.

## 구현

- **신규**: `src/api/routers/ai_pipeline_test.py` — `/api/ai-pipeline/test/converse`
  - `self_service_test.py`와 동일하게 `ConversationAgent.process_utterance()`를 그대로 재사용하되,
    `caller_number`를 `owner`와 다르게(`{owner}-qa-caller`) 고정해 **일반(비셀프서비스) 경로**를
    재현한다 — `classify_intent → route_utterance → generate_response → hitl_alert`.
  - 응답에 `response_chunk_count`, `intent`, `confidence`, `needs_human`, `needs_follow_up`,
    `agent_elapsed_sec`, `llm_first_sentence_elapsed_sec` 등 지연 분석에 필요한 필드를 노출한다.
  - `AI_PIPELINE_QA_TEST_MODE` 환경변수(기본 비활성화)로 게이팅 — `self_service_test.py`와 동일한
    안전 원칙.
- 단위 테스트 18건 신규 작성(`tests_new/unit/test_ai_voicebot/test_ai_pipeline_test_endpoint.py`),
  전체 통과.
- `main.py`에 라우터 등록, `env.example`에 사용법 안내 추가.

## 실측 결과 (실서버, `AI_PIPELINE_QA_TEST_MODE=1`, owner=9001)

| 발화                                                     | intent   | confidence | needs_human | response_chunk_count | agent_elapsed_sec |
| -------------------------------------------------------- | -------- | ---------- | ----------- | -------------------- | ----------------- |
| "안녕하세요"                                             | greeting | 1.0        | False       | 0                    | **0.021초**       |
| "오늘 날씨가 참 좋네요. 기분이 좋아지는 하루예요."       | chitchat | 0.9        | False       | 3                    | **9.66초**        |
| "영업시간이 어떻게 되나요?" (RAG 미매치 → chitchat 폴백) | chitchat | 0.9        | False       | 2                    | **9.752초**       |

### 핵심 발견

1. **greeting은 generate_response_node를 아예 타지 않는다**: `response_chunk_count=0`,
   `agent_elapsed_sec=0.021초`로 사실상 즉시 응답 — 템플릿/캐시 경로(`template_response_node`
   또는 `greeting_farewell_kb_node`)로 처리되는 것으로 보인다. **Story 4.1에서 "안전 서브셋"으로
   분류했던 `greeting`은 애초에 TTFT 개선이 필요 없는 경로**임을 실측으로 확인했다 — Story 4.2
   범위에서 제외하고 `chitchat`/`out_of_scope`에 집중해야 한다(문서 갱신 필요, 아래 참고).
2. **chitchat 응답이 실측 9.6~9.75초로 재현됨**: 서로 다른 두 발화에서 거의 동일한 지연이
   재현되어 우연이 아님을 확인했다. 이는 2026-03-30 리포트의 "평균 8.69초" 실측치와 정합하며,
   `needs_human=False`가 확정된 **"안전한" 경로에서도 지연 문제가 그대로 존재**함을 보여준다 —
   즉 Story 4.2(TTFT 안전 서브셋)의 효과 검증 대상이 정확히 이 케이스임을 재확인했다.
3. **`llm_first_sentence_elapsed_sec`가 API 응답에 비어 있음**: `response_chunk_count>0`(스트리밍은
   발생)임에도 이 필드가 `None`으로 반환된다 — `agent.process_utterance()`가 반환하는 최종 dict에
   해당 키가 유지되지 않거나 `update_state_node`에서 필터링될 가능성이 있다. **다음 조사 필요
   (경미, Story 4.2 착수 시 확인)**.

## 다음 단계 반영

- Story 4.1/PRD Epic 4의 "안전 서브셋" 정의를 `{chitchat, out_of_scope}`로 좁힌다(`greeting`은
  TTFT 대상에서 제외 — 이미 충분히 빠름).
- `llm_first_sentence_elapsed_sec` 누락 원인 확인이 Story 4.2 착수 전 선행 작업으로 추가됨.
- 이 QA 하네스로 real-call 없이도 Story 4.2 구현 전/후 `agent_elapsed_sec` 비교가 가능해졌다 —
  실서버 통화 의존도를 낮춘 것이 본 세션의 핵심 성과.

*최종 업데이트: 2026-07-24*
