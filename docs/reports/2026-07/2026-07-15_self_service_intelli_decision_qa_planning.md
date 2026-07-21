# 셀프서비스 AI 도우미 — QA 보강(IntelliDecision + 전체 카탈로그 액션형) 계획 수립

**작성일**: 2026-07-15
**상태**: 문서·스크립트 준비 완료 — **실제 실행은 미착수**(서버 재시작 필요, 사용자 요청에 따라 보류)
**관련 문서**:
- [self-service-ai-assistant-intelli-decision-qa-plan.md](../../qa/self-service-ai-assistant-intelli-decision-qa-plan.md) (신규)
- [self-service-ai-assistant-bmad-qa-test-plan.md](../../qa/self-service-ai-assistant-bmad-qa-test-plan.md) (Story 1.10 섹션 추가)
- [1.10.intelli-decision-intent-tier.story.md](../../stories/1.10.intelli-decision-intent-tier.story.md) (QA Results 갱신)
- [2026-07-15_self_service_story_1.10_intelli_decision.md](2026-07-15_self_service_story_1.10_intelli_decision.md) (구현 리포트)

---

## 1. 요청 배경

기존 QA 항목서(Story 1.1~1.9)는 자동설정(Story 1.8) 검증을 chat-relay 1개 필드로만 다뤄
"설정 관련한 API 전체"를 커버하지 못했고, 신규 IntelliDecision(Story 1.10)도 QA 항목서에
반영되지 않은 상태였다. 사용자는 다음 두 시나리오를 구분한 QA 보강을 요청했다.

1. **잘 아는 경우(실행성)**: 각 기능에 대해 고객이 요청하면 필요한 파라미터를 체크하고 기능을
   브리핑하면서 필요한 정보를 답변받고, 부족한 내용은 단계적으로 질문하며 설정이 실제로
   되는지 확인 — **설정 관련 API 전체** 대상.
2. **잘 모르는 경우(탐색성)**: 고객이 물어보는 내용에 매뉴얼 기반으로 답변하면서 IntelliDecision을
   통해 무엇이 필요한지 유추·제안.

단, 실제 기능 테스트(서버 재시작 필요)는 이번 세션에서 수행하지 않고 추후 별도 작업으로
진행하기로 사용자가 명시했다.

---

## 2. 수행 내용

### 2-1. 신규 QA 계획 문서
[self-service-ai-assistant-intelli-decision-qa-plan.md](../../qa/self-service-ai-assistant-intelli-decision-qa-plan.md) 작성:

- **Case 1(실행성)**: 설정 카탈로그 7개 도메인 전체 매트릭스
  - 쓰기 가능 3개(persona/ai-escalation/chat-relay): 완전한 정보 요청(즉시 확인 발화→실행) +
    불완전한 정보 요청(AI가 되물어야 함) 각 케이스
  - 쓰기 불가 4개(call-control/contacts/general/integrations): 정중한 거부 확인 케이스
  - 카탈로그 밖(booking): 알려진 설계상 한계 확인(결함 아님)
- **Case 2(탐색성)**: 매뉴얼 각 섹션 기반 Q&A 5건(+ 대조군 1건 — 순수 정보 질의는 애초에
  Tool 호출 대상이 아님을 재확인하는 용도)
- 판정 절차: `response` 패턴 + `tool_trace` 이벤트 유무 + 원시 로그 교차검증 + 힌트 값은
  참고만 하고 판정 기준에서 제외(Story 1.10 AC3 원칙 재확인)
- 신규 QA 전용 owner `9003` 채택(기존 `9001`은 Story 1.1~1.9 실행으로 이미 상태 변경됨)

### 2-2. 기존 QA 항목서 보강
[self-service-ai-assistant-bmad-qa-test-plan.md](../../qa/self-service-ai-assistant-bmad-qa-test-plan.md)에
"Story 1.10 — IntelliDecision" 섹션 추가(요약 2케이스 + 신규 문서로 크로스링크), §5 다음 단계에
실행 안내 추가.

### 2-3. QA 실행 스크립트 준비
`scripts/self_service_qa_step5_intelli_decision.ps1` 신규 작성 — 기존
`self_service_qa_step3.ps1`과 동일한 `Invoke-Converse`/`Show-Result`/`Test-RawLogCrossCheck`
헬퍼 패턴 재사용. PowerShell 파싱 검증만 수행(`PSParser::Tokenize`)했고 **실제 서버 호출은
수행하지 않았다**.

### 2-4. BMAD 프로세스 문서 갱신
- [1.10.intelli-decision-intent-tier.story.md](../../stories/1.10.intelli-decision-intent-tier.story.md)
  QA Results 섹션을 "계획 수립 완료, 실행 대기" 상태로 갱신
- [docs/INDEX.md](../../INDEX.md): Dev Stories 표에 Story 1.10 행 추가, QA 섹션에 신규 문서 링크 추가,
  PRD 설명 문구를 "Story 1.1~1.10"로 갱신

---

## 3. 실행 여부

**이번 세션에서 실제 API 호출은 수행하지 않았다.** PowerShell 스크립트 문법 검증만 진행했다
(`[System.Management.Automation.PSParser]::Tokenize` → `PARSE OK`). 서버 재시작이 필요한
실제 통합 테스트는 사용자 요청에 따라 다음 별도 세션에서 진행한다.

### 향후 실행 절차 (요약, 상세는 QA 계획 문서 §6 참고)

1. 서버 재시작(`.\stop-all.ps1` → `.\start-all.ps1`, `SELF_SERVICE_QA_TEST_MODE=1` 확인)
2. `GET /api/self-service/test/status`로 준비 상태 확인
3. `pwsh -File scripts/self_service_qa_step5_intelli_decision.ps1` 실행
4. 결과를 `docs/reports/2026-07/`에 리포트로 정리
5. `docs/stories/1.10.intelli-decision-intent-tier.story.md`의 QA Results 섹션을 실제 결과로 갱신

---

## 4. 변경 파일 목록

| 파일                                                            | 상태                               |
| --------------------------------------------------------------- | ---------------------------------- |
| `docs/qa/self-service-ai-assistant-intelli-decision-qa-plan.md` | 신규                               |
| `docs/qa/self-service-ai-assistant-bmad-qa-test-plan.md`        | 수정(Story 1.10 섹션 추가)         |
| `scripts/self_service_qa_step5_intelli_decision.ps1`            | 신규(문법 검증만, 미실행)          |
| `docs/stories/1.10.intelli-decision-intent-tier.story.md`       | 수정(QA Results 갱신)              |
| `docs/INDEX.md`                                                 | 수정(Story 1.10 행 + QA 문서 링크) |

*최종 업데이트: 2026-07-15*
