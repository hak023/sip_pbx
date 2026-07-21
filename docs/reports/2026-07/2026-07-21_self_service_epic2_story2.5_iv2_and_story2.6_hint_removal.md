# 셀프서비스 AI 도우미 Epic 2 — Story 2.5 IV2 실서버 검증 + Story 2.6 착수(힌트 제거) 리포트

- 작성일: 2026-07-21
- 버전: 1.0
- 상태: Story 2.5 Done(IV2 포함), Story 2.6 In Progress(코드 제거 완료, 재검증은 사용자 재시작 후)
- 관련 문서:
  - [Story 2.5](../../stories/2.5.frontend-catalog-import.story.md)
  - [Story 2.6](../../stories/2.6.intelli-decision-hint-removal.story.md)
  - [이전 구현 리포트(Story 2.1~2.5 코드)](2026-07-21_self_service_epic2_story_2.1_to_2.5_implementation.md)
  - [IntelliDecision 베이스라인 원시 출력](2026-07-21_qa_step5_intelli_decision_baseline_pre_hint_removal_raw_output.txt)

## 1. 요약

사용자가 서버를 재시작한 뒤 "남은 것 진행해줘"라고 요청해, 직전 세션에서 보류했던 두 가지 실서버
검증 작업을 이어서 진행했다.

1. **Story 2.5 IV2(설정 업로드→즉시 반영) 실서버 검증** — PASS.
2. **Story 2.6(IntelliDecision 키워드 힌트 제거)** — 착수: 베이스라인 확보 → 코드 제거 →
   단위 회귀 확인까지 완료. 제거 후 재검증(Task 4/5)은 **사용자가 직접 서버를 재시작한 뒤
   이어서 진행하기로 함**(추가 재시작 승인 질문에 사용자가 "나중에 직접 하겠다"고 응답).

## 2. Story 2.5 IV2 실서버 검증 상세

**시나리오**: 설정 업로드 → 확정 적용이 서버 재시작 없이 즉시 대화에 반영되는지 실증.

1. `GET /catalog-config/export`로 현재 활성 설정(catalog v2, screen_graph v2) 백업.
2. `screen_graph.chat-relay.nav_hint`를 고유 마커 문구로 수정.
3. `POST /catalog-config/import`로 업로드 → 검증 통과, v3(비활성)로 저장 확인.
4. `POST /catalog-config/activate`로 catalog·screen_graph 각각 v3 활성화
   (`activated_at`/`activated_by` 기록 확인).
5. **서버를 재시작하지 않고 곧바로** `POST /api/self-service/test/converse`로
   "채팅 자동응답 설정 좀 보여줘" 질의 → 응답 문구가 새 nav_hint(중점 `·` 제거된 버전)를
   즉시 반영함을 확인 — 코드 재배포·재시작 없이 실제로 반영되었음을 실증(FR20).
6. 검증 후 `POST /catalog-config/activate`로 양쪽 모두 v2로 롤백해 개발 DB 원상복구,
   롤백 응답 `ok:true` 확인.

**결과**: PASS. Story 2.5 Status → Done.

## 3. Story 2.6 착수 — 중요 발견 및 처리

### 3.1 베이스라인 확보 중 발견된 이슈와 재확인

베이스라인 첫 실행(13:19~13:20) 시점에 "확인 발화 → 긍정 응답 → 실행" 2턴 플로우 3건
(ID-P01, ID-E01, ID-C01)이 **모두** 재시도 로직(최대 2회 추가 재시도)까지 소진한 뒤에도
Gemini가 빈 candidate를 반환해 실패했다. 표본만 보면 "100% 재현"으로 보여, Epic 2 리팩터링이
새로운 회귀를 유발했는지 의심할 만한 상황이었다.

**재확인 절차**: 동일 확인→긍정 2턴 시나리오(ID-E01과 동일 발화)를 별도로 4회 독립 재현했다.
결과: **4/4 모두 정상 성공**(`self_service_auto_config_applied`까지 확인). 몇 분 사이에
재현율이 0%(4/4 성공)로 바뀐 것은, 이 문제가 여전히 **간헐적인 외부 Gemini API 신뢰성 문제**이며
(2026-07-20 세션에서 이미 결론 내린 사항과 일치), 처음 관측된 100% 실패는 특정 시간대에 실패가
우연히 몰린 클러스터링이었다는 뜻이다. Epic 2의 어떤 리팩터링도 이 현상의 원인이 아님을 확인했다.

이후 안정된 시점에 베이스라인을 다시 확보해 16건 전부 기대 패턴과 일치함을 확인했다(첨부 원시
출력 참고).

### 3.2 코드 제거 작업

- `self_service_agent.py`의 시스템 프롬프트 템플릿에서 `[발화 유형 참고 신호]` 섹션과
  `{intent_tier_hint_label}` 자리표시자 제거.
- 규칙 11번의 "[발화 유형 참고 신호]는 참고만 하고..." 문구 제거(유형 A/B 판단 지시 자체는 유지).
- `classify_intent_tier_hint`/`hint_to_prompt_label` import 및 호출 제거.
- 관련 로깅(`self_service_agent_intent_tier_hint`, `self_service_intent_tier_hint`) 완전 제거
  — 대체 로깅을 추가하지 않기로 결정(힌트 값 자체가 사라지므로 로깅 대상이 없고, "LLM 최종 판단"을
  사후 분류하는 별도 로직을 추가하면 NFR1 지연 예산을 해칠 수 있어 PRD Non-Goals 원칙에 따름).
- `intent_tier.py` 모듈 자체와 그 단위 테스트(`test_self_service_intent_tier.py`)는 아직
  삭제하지 않음 — Task 5(제거 후 재검증 결과가 동등 이상이어야 삭제 확정)가 남아 있기 때문.

### 3.3 단위 회귀

`pytest tests_new/unit/test_ai_voicebot tests_new/unit/test_events -q --no-cov` → **327개 전체
통과**(회귀 0건). `test_self_service_intent_tier.py`는 `intent_tier.py` 모듈을 직접 테스트하므로
영향 없음.

## 4. 남은 작업

사용자가 서버를 재시작하면:
1. Story 2.6 Task 4 — 힌트 제거 후 동일 IntelliDecision QA 16건을 재실행하고, 이번 리포트에
   첨부된 베이스라인과 비교(확인 발화 vs 설명+제안 패턴이 유지되는지가 핵심).
2. Story 2.6 Task 5 — 결과가 동등 이상이면 `intent_tier.py` 삭제(또는 deprecated 처리) 확정,
   저하되면 이번 코드 변경을 롤백하고 대안(경량 분류 등) 재검토.
3. Story 2.7 — 통합 QA(`master-qa.md` Branch L)로 Epic 2 전체 마무리.

*최종 업데이트: 2026-07-21*
