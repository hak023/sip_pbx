# 음성 지연 개선 Epic 4/5 — Story 4.1(TTFT 설계 결정)/5.1(턴테이킹 실사용 감사) 완료

**작성일**: 2026-07-24
**작업 유형**: 조사·설계 결정(코드 변경 없음)
**관련 문서**:
- [voice-latency-turn-taking-prd.md](../../product/voice-latency-turn-taking-prd.md)
- [voice-latency-turn-taking-architecture.md](../../architecture/voice-latency-turn-taking-architecture.md)
- [docs/stories/4.1.ttft-design-decision.story.md](../../stories/4.1.ttft-design-decision.story.md)
- [docs/stories/5.1.turn-taking-threshold-audit.story.md](../../stories/5.1.turn-taking-threshold-audit.story.md)

## 배경

Story 3.1/3.2/3.4 완료 후 사용자가 실서버를 기동했으나, 실제 테스트 통화는 다음 세션으로 미루고
Epic 4(TTFT)·Epic 5(턴테이킹) 설계 작업을 계속 진행해달라고 요청했다. 코드 조사만으로 진행 가능한
Story 4.1(대안 결정)과 5.1(실사용 로직 감사)을 완료했다.

## 핵심 발견 — Story 5.1: 턴테이킹 로직 대부분이 죽은 코드였음

`pipeline_builder.py`의 실제 `Pipeline([...])` 조립 리스트를 직접 확인한 결과:

| 이전에 "이미 구현됨"으로 서술했던 것                                                | 실제 상태                                                                                                                                     |
| ----------------------------------------------------------------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------- |
| `SmartTurnProcessor`(grammar/tone/pace 기반 턴 완료 판단)                           | **죽은 코드** — 파이프라인에 전혀 연결되지 않음                                                                                               |
| `SmartBargeInStrategy`/`SmartBargeInProcessor`(3단계 키워드/단어수/LLM 판단 바지인) | **죽은 코드** — 어디에도 import되지 않음                                                                                                      |
| 실제 턴 완료 판단                                                                   | Google STT 자체 스트리밍 엔드포인팅에 전적으로 의존                                                                                           |
| 실제 바지인                                                                         | legacy WebRTC `VADDetector`(`trigger_threshold=0.5`) + `MinWordsUserTurnStartStrategy(min_words=3)` + Pipecat 내장 `allow_interruptions=True` |
| FR7(LLM 사고 중 발화 합산)                                                          | **다른 메커니즘으로 이미 충족됨** — `rag_processor.py`의 Supersede/Coalesce(STT 텍스트 레벨 병합, `barge_in_strategy.py`와 무관)              |

이는 Story 3.4에서 `streaming_tts_processor.py`를 죽은 코드로 확정한 것과 **동일한 패턴의 조사
실수**(파일이 존재하고 잘 작성되어 있다고 실제 파이프라인에 연결됐다는 뜻은 아님)가 두 번째로
발견된 것이다. 향후 "기존 로직 확인"이 필요한 작업에서는 파일 내용만 읽지 말고 실제 조립 코드
(`Pipeline([...])`, `import` 전수 검색)까지 반드시 확인해야 한다는 교훈을 얻었다.

이로 인해 PRD의 Epic 5 전제("이미 있는 정교한 로직을 검증만 하면 된다")가 틀렸음을 확인하고 PRD를
갱신했다 — Story 5.2~5.4는 "죽은 코드를 되살릴지, 현재의 단순 필터로 충분한지 결정"하는 문제로
범위가 바뀌었다.

## 핵심 결정 — Story 4.1: TTFT 연결부 대안 확정

- **최종 선택: 대안 B**(`rag_processor.py`가 LLM 스트림을 직접 구독, LangGraph 그래프 자체는 현행
  유지).
- 실제 코드 확인으로 조기 문장 전송과 충돌하는 시나리오 3건 확정:
  1. HITL 오버라이드(`hitl_alert_node`가 응답 생성 **이후** 실행, 응답 전체를 덮어쓸 수 있음)
  2. 아웃바운드 JSON 파싱(원시 스트리밍 청크가 파싱 전 JSON 파편이라 TTS 불가)
  3. 오류/미상 응답 폴백(전체 응답이 안내 문구로 교체될 수 있음)
- **구현 전략(Story 4.2 범위 축소)**: 위 3가지가 전혀 해당하지 않는 안전한 경로(비아웃바운드 +
  `needs_human=False`가 사전 확정된 경우)에서만 첫 문장 조기 전송을 적용하고, 그 외에는 현행 배치
  방식을 그대로 유지 — 회귀 위험을 구조적으로 차단하는 점진적 롤아웃 전략.

## 문서 동기화

- `docs/architecture/voice-latency-turn-taking-architecture.md`: §1.1(파이프라인 다이어그램 정정),
  §1.4(턴테이킹 실제 로직 표로 전면 교체), §2.2.1(TTFT 충돌 시나리오 신설), §2.3(턴테이킹 정리
  방향 갱신).
- `docs/product/voice-latency-turn-taking-prd.md`: Epic 5 섹션에 범위 재조정 안내 추가.
- `docs/stories/4.1.*.story.md`, `5.1.*.story.md`: Status → Done, Dev Agent Record 기록.
- `docs/INDEX.md`: Story 4.1/5.1 상태 갱신.

## 검증

본 세션은 프로덕션 코드를 변경하지 않았다(문서·설계 결정만) — 별도 회귀 테스트 불필요. 이전
세션(Story 3.1/3.2/3.4)의 코드 변경분은 이미 검증 완료 상태(`docs/reports/2026-07/2026-07-24_voice_latency_epic3_story_3.1_3.2_3.4_implementation.md` 참고).

## 다음 단계 (사용자 확인 필요)

1. **실서버 테스트 통화**(보류 중): Story 3.2의 `response_latency_sla_exceeded` 로그 cross-check —
   사용자가 준비되면 진행.
2. **Story 4.2**(TTFT 안전 서브셋 구현): `hitl_escalation_policy.py`를 재확인해 `needs_human`을
   `generate_response_node` 이전에 사전 확정할 수 있는지부터 검증 후 구현 착수.
3. **Story 5.2 재작성**(PRD Epic 5 범위 재조정 반영): "유의미한 발화" 기준을 죽은 코드 부활 여부
   결정 문제로 재구성.
4. **Story 5.3**(FR7 실서버 검증): 이미 코드로 충족된 Supersede 메커니즘의 실제 로그(`stt_turn_superseded`)
   cross-check.

*최종 업데이트: 2026-07-24*
