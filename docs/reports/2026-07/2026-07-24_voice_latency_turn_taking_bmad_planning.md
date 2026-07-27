# 음성 AI 응답 지연 개선 및 스마트 턴테이킹 — 리서치 및 BMAD 계획 수립

**작성일**: 2026-07-24
**작업 유형**: 설계/계획(코드 변경 없음)
**관련 문서**:
- [voice-latency-turn-taking-brief.md](../../product/voice-latency-turn-taking-brief.md)
- [voice-latency-turn-taking-prd.md](../../product/voice-latency-turn-taking-prd.md)
- [voice-latency-turn-taking-architecture.md](../../architecture/voice-latency-turn-taking-architecture.md)
- [docs/stories/3.1~3.4, 4.1, 5.1](../../stories/)

## 요청 배경

사용자가 다음을 요청함:
1. AI 응대가 너무 늦음 — 발화 후 5초 이내 응답 보장, 초과 시 원인 판단 로직 필요.
2. TTFT(Time To First Token) 도입 검토 — 현재 LLM 응답을 모두 기다린 후 TTS로 보내는 것으로 추정됨.
3. 스마트 턴테이킹 재검토 — 잡음/짧은 발화 무시, LLM 사고 중 추가 발화 합산 재판단, "유의미한 발화"
   판정 기준 리서치.
4. 위 내용을 BMAD 초기 단계(Brief→PRD→Architecture→Story)부터 계획.

## 조사 방법

코드 직접 grep/read(추측 금지 원칙)로 다음을 확인:
- `pipecat/pipeline_builder.py` 파이프라인 조립 순서·VAD/barge-in 설정값
- `pipecat/processors/smart_turn_processor.py` 턴 완료 판단 로직
- `pipecat/processors/streaming_tts_processor.py`, `barge_in_strategy.py`, `orchestrator/barge_in_controller.py`
- `ai_pipeline/llm_client.py`(`generate_response_streaming`), `ai_pipeline/tts_client.py`(`synthesize_stream`)
- `langgraph/nodes/generate_response.py`(`_collect_streaming`)
- `pipecat/processors/rag_processor.py`(LLM→TTS 연결부, L1650~2100)
- `docs/architecture/voice-ai-conversation-engine.md`, `docs/design/TTS_RTP_STRUCTURE_REVIEW.md`,
  `docs/analysis/ai-response-time-analysis.md`, `docs/reports/2026-03/*RESPONSE_TIME*`

## 핵심 발견

### 1) 설계상 추정치와 실측치의 큰 괴리
- `voice-ai-conversation-engine.md`: 평균 응답 지연 **1.3초 추정**.
- 실측 리포트(`2026-03-30_1440_AI_RESPONSE_TIME_ANALYSIS_AND_OPTIMIZATION_DESIGN.md`): **평균 8.69초**,
  최악 16초 이상. 병목 Top3: `generate_response`(LLM+RAG) 4.6초, `step_back`(80% 불필요 실행) 2.19초,
  `check_cache`(콜드스타트) 1.62초.

### 2) TTFT 미구현 확인 (사용자 추정이 사실로 확인됨)
- `generate_response_node`의 `_collect_streaming()`이 LLM 스트리밍 제너레이터를 **전량 소진해 리스트로
  수집한 후에만** 함수가 반환됨.
- `rag_processor.py`는 이 리스트가 도착한 **이후에야** 문장 단위로 `push_frame`을 호출 — 코드 내부
  변수명 `_tts_mode_planned = "chunked_after_llm_complete"`가 이를 스스로 증언.
- 즉 현재 "스트리밍 TTS"는 텍스트를 문장으로 나누어 전송할 뿐, **전송 시작 시점(TTFT)은 LLM 전체
  완료 시각과 동일**함을 코드로 확정.
- `streaming_tts_processor.py`(진짜 TTFT 게이트웨이로 보이는 프로세서)는 `pipeline_builder.py`의 실제
  조립 코드에 연결되어 있지 않음(죽은 코드 가능성 — Story 3.4에서 최종 확정 필요, 본 세션에서는
  단정하지 않음).

### 3) 턴테이킹 로직은 상당 부분 이미 구현되어 있음
- Smart Turn(`max_hold_secs=2.0`, grammar/tone/pace 분석), VAD(`stop_secs=0.2`), barge-in 3단계
  필터(키워드 즉시 판단→3단어 게이트→LLM 판단), `accumulated_text` 발화 누적 로직이 이미 존재.
- 사용자가 요청한 "LLM 사고 중 추가 발화 합산 재판단"과 유사한 구조가 이미 있을 가능성이 높으나,
  **실서버 검증 데이터가 없어 요구사항과 정확히 일치하는지는 미확인** — 이번 세션은 계획 단계라
  실서버 검증은 하지 않았고, Story 5.3으로 계획에 반영.

## 산출물

| 유형          | 경로                                                                                                               |
| ------------- | ------------------------------------------------------------------------------------------------------------------ |
| Project Brief | `docs/product/voice-latency-turn-taking-brief.md`                                                                  |
| PRD           | `docs/product/voice-latency-turn-taking-prd.md` (Epic 3·4·5, FR1-FR12, NFR1-NFR6, CR1-CR3)                         |
| Architecture  | `docs/architecture/voice-latency-turn-taking-architecture.md` (현재 구조 mermaid 다이어그램, TTFT 설계 대안 A/B/C) |
| Story(Draft)  | `docs/stories/3.1~3.4.*.story.md`, `4.1.ttft-design-decision.story.md`, `5.1.turn-taking-threshold-audit.story.md` |
| 인덱스 갱신   | `docs/INDEX.md`에 신규 문서·Story 항목 추가                                                                        |

## Epic 구조 요약

- **Epic 3 — 응답 지연 계측 및 5초 SLA 가드레일**: TTFT 개선 이전에 정확한 실측 계측(T0~T5 구간)과
  5초 초과 원인 자동 태깅을 먼저 확보(선행 조건).
- **Epic 4 — 진짜 TTFT 파이프라인 전환**: LLM 첫 문장 완성 즉시 TTS 전달. 설계 대안 3가지(A: 노드
  조기 반환, B: rag_processor가 직접 스트림 구독(권장 후보), C: 기존 streaming_tts_processor 재사용)를
  Story 4.1에서 프로토타입 검증 후 확정.
- **Epic 5 — 스마트 턴테이킹 재정비**: 새로 만들기보다 기존 로직(Smart Turn/barge-in)의 실동작 검증과
  임계값 근거 정리, "유의미한 발화" 판정 기준 리서치가 핵심.

## 다음 단계(미착수, 사용자 확인 필요)

1. PRD의 Open Questions 3건(5초 초과 정책, streaming_tts_processor.py 실사용 여부, 턴테이킹 임계값
   실통화 A/B 테스트 승인) 확인.
2. Story 3.1(계측)부터 순서대로 착수 — 계측 없이 Epic 4/5를 먼저 구현하지 않는다(정확한 실측 없이
   최적화하지 않는다는 원칙, copilot-instructions.md "재시도·완화책으로 증상만 가리기 금지"와
   동일 취지).
3. 본 세션은 **코드 변경 없이 계획 문서만 작성**했으며, 실서버 검증·구현은 착수하지 않았다.

*최종 업데이트: 2026-07-24*
