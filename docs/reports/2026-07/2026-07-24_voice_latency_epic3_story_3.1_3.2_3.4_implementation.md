# 음성 지연 개선 Epic 3 — Story 3.1/3.2/3.4 구현

**작성일**: 2026-07-24
**작업 유형**: 코드 구현 + 조사(Brownfield, 회귀 없음)
**관련 문서**:
- [voice-latency-turn-taking-prd.md](../../product/voice-latency-turn-taking-prd.md)
- [voice-latency-turn-taking-architecture.md](../../architecture/voice-latency-turn-taking-architecture.md)
- [docs/stories/3.1.latency-instrumentation.story.md](../../stories/3.1.latency-instrumentation.story.md)
- [docs/stories/3.2.latency-sla-cause-tagging.story.md](../../stories/3.2.latency-sla-cause-tagging.story.md)
- [docs/stories/3.4.streaming-tts-processor-audit.story.md](../../stories/3.4.streaming-tts-processor-audit.story.md)

## 문제 요약

이전 세션(BMAD 계획 수립)에서 Epic 3(계측)이 "미착수"로 분류되어 있었으나, 실제로 착수해보니
**핵심 계측 인프라(`src/common/ai_response_latency_compare.py`)가 이미 실전에 배선되어 있었음**을
확인했다. 이전 조사(리서치 subagent)가 `src/common/`을 전수 검색하지 않아 발생한 조사 누락이었다.

## 근본 원인/발견 사항

1. **Story 3.1(계측)**: `ai_response_latency_compare.py`가 STT 최종 확정→LLM 시작→LLM 첫 문장→
   LLM 전체 완료→TTS 텍스트 전달→첫 RTP 오디오까지의 전 구간을 이미 `rag_processor.py`/
   `rtp_transport.py`에서 호출되어 계측하고 있었다. AC1~AC3(총 지연 단일 지표, 구간별 분해, 기존
   계측 재사용)은 이미 만족.
2. **Story 3.4(streaming_tts_processor.py 감사)**: `sip-pbx/src/**` 전수 grep 결과
   `StreamingTTSGateway`는 자기 자신의 정의부와 주석 1건 외에 어디에도 import되지 않는 **죽은
   코드**로 확정. Epic 4의 대안 C(재사용)는 채택하지 않기로 결정.

## 수정/추가 내용 (Story 3.2, 실제 신규 구현)

- `src/common/ai_response_latency_compare.py`에 순수 함수 3개 추가:
  - `compute_sla_stage_breakdown_ms(t)` — 턴 타이밍에서 5개 구간(캐시/RAG 사전 처리, LLM 첫 문장
    생성, LLM 나머지 생성, LLM 완료 후 처리, TTS 합성+RTP)별 소요시간(ms) 계산.
  - `suspected_sla_stage(breakdown)` — 가장 소요시간이 큰 구간을 원인으로 태깅(단순 최댓값 비교,
    과설계 지양).
  - `check_and_tag_sla_exceeded(t, total_ms=..., call_id=..., threshold_ms=5000.0)` — 5초(기본값)
    초과 시에만 태깅 payload 반환, 이하이면 `None`(정상 케이스 로그 노이즈 없음).
- `mark_first_audio_and_compare()` 말미에서 위 함수를 호출해 초과 시 `response_latency_sla_exceeded`
  이벤트를 `logger.warning` + `call_data_record`에 기록.
- 기존 함수(`begin_turn`, `mark_stt_final`, `mark_llm_start`, `apply_llm_first_sentence_timing`,
  `mark_llm_complete`, `mark_tts_text_pushed`, `mark_first_audio_and_compare`)의 **호출 시그니처는
  변경하지 않음** — `rag_processor.py`/`rtp_transport.py` 등 기존 호출부 무변경(CR1, NFR2 준수).

## 검증 결과

- 신규 단위 테스트: `tests_new/unit/test_common/test_ai_response_latency_compare.py` (10건)
  - `compute_sla_stage_breakdown_ms`: 전체 구간 존재/부분 구간(llm_complete 누락 시 첫 문장으로
    대체)/빈 타이밍 케이스.
  - `suspected_sla_stage`: 최댓값 선택, 빈 breakdown → `unknown`.
  - `check_and_tag_sla_exceeded`: 임계값 이하(None)/정확히 임계값(None, 경계값)/초과 시 태깅/
    타이밍 전무 시에도 `unknown`으로 태깅(예외 없음)/커스텀 임계값.
  - 결과: **10 passed**.
- 회귀 테스트: `pytest tests_new/unit`(사전에 존재하던 의존성 문제로 수집 실패하는
  `test_ai_pipeline/test_rag_engine.py`·`test_text_embedder.py`, 그리고 본 변경과 무관한 기존 실패
  `test_sip_core/test_call_session.py` 10건 제외) — **전체 통과** (`rag_processor.py` import 정상
  동작도 별도 확인).
- 실서버 통합 검증(실제 통화에서 `response_latency_sla_exceeded` 로그 cross-check)은 서버 재시작이
  필요하므로 **사용자 승인 후 다음 세션에서 진행** — copilot-instructions.md 포트 충돌 규칙 준수.

## 문서 동기화

- `docs/architecture/voice-latency-turn-taking-architecture.md`: §1.3(지연 계측 인프라, 신규),
  §2.1(계측 포인트 갱신 — 실제 배선 반영), §2.2(대안 C 미채택 결정 기록).
- `docs/stories/3.1.*.story.md`, `3.2.*.story.md`, `3.4.*.story.md`: Status → Done, Dev Agent Record
  갱신.
- `docs/INDEX.md`: Epic 3~5 Story 상태 표 갱신.

## 다음 단계

1. Story 3.3(5초 초과 시 대응 정책) — 운영 데이터 축적 필요, 착수 보류.
2. Story 4.1(TTFT 설계 대안 확정) — 대안 B(rag_processor.py가 LLM 스트림 직접 구독)를 우선 검토
   대상으로 프로토타입 검증 착수 가능.
3. Story 5.1(턴테이킹 임계값 전수 조사) — 코드 조사 전용, 회귀 위험 없이 바로 착수 가능.
4. `response_latency_sla_exceeded` 이벤트의 실서버 cross-check(사용자 승인 후).

*최종 업데이트: 2026-07-24*
