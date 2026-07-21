# 셀프서비스 AI 도우미 — IntelliDecision & 전체 카탈로그 액션형 QA 계획

> ⚠️ **본 문서는 2026-07-20부터 [self-service-ai-assistant-master-qa.md](self-service-ai-assistant-master-qa.md)로 통합되었습니다(Branch H).**
> 대표 케이스는 통합 문서에서 재실행해 회귀를 확인했으며, 전체 카탈로그 도메인 매트릭스(11건)는 본 문서의 2026-07-16 실행 결과를 근거 자료로 계속 참조합니다.

**작성일**: 2026-07-15
**상태**: 계획 작성 완료 — **실행 미착수**(서버 재시작 필요, 사용자 요청에 따라 이번 세션에서는 보류)
**대상**: Story 1.10(IntelliDecision) + Story 1.8(자동설정) 전체 카탈로그 도메인 커버리지 보강
**실행 방식**: 기존과 동일 — `POST /api/self-service/test/converse`(`SELF_SERVICE_QA_TEST_MODE=1` 필요)
**관련 문서**:
- [self-service-ai-assistant-bmad-qa-test-plan.md](self-service-ai-assistant-bmad-qa-test-plan.md) — 기존 Story 1.1~1.9 QA 항목서(본 문서는 이를 대체하지 않고 보강)
- [../reports/2026-07/2026-07-15_self_service_bmad_qa_step3_execution_result.md](../reports/2026-07/2026-07-15_self_service_bmad_qa_step3_execution_result.md) — 기존 3단계 실행 결과
- [../stories/1.10.intelli-decision-intent-tier.story.md](../stories/1.10.intelli-decision-intent-tier.story.md) — 본 QA 대상 Story
- [../product/self-service-manual-content.md](../product/self-service-manual-content.md) — Case 2(탐색성) 근거 매뉴얼 원문

---

## 0. 배경 및 목적

기존 QA 항목서(Story 1.1~1.9)는 자동설정(Story 1.8) 검증을 **chat-relay 도메인 1개 필드**로만
수행했고, IntelliDecision(Story 1.10)은 아직 QA 항목서에 반영되지 않았다. 본 문서는 다음 두 가지를
보강한다.

1. **Case 1(실행성 — 잘 아는 경우)**: 사용자가 특정 기능을 이미 알고 명확히 설정 변경을 요청할 때,
   AI가 (a) 필요한 파라미터를 확인하고, (b) 기능을 간단히 브리핑하며, (c) 부족한 정보는 단계적으로
   되물어 수집한 뒤, (d) 확인 발화 → 실제 설정까지 이어지는지를 **설정 카탈로그 7개 도메인 전체**
   기준으로 검증한다(쓰기 가능 3개 + 쓰기 불가 4개 각각의 기대 동작 포함).
2. **Case 2(탐색성 — 잘 모르는 경우)**: 사용자가 기능을 몰라서 궁금해할 때, AI가 매뉴얼 기반으로
   설명하고 IntelliDecision에 따라 "무엇이 필요한지"를 유추·제안하되 **즉시 실행하지 않는지** 검증한다.

---

## 1. 두 유형의 판정 기준 (재확인)

| 구분            | 트리거 예시                                   | 기대 응답 패턴                                                                      | Tool 호출                                           |
| --------------- | --------------------------------------------- | ----------------------------------------------------------------------------------- | --------------------------------------------------- |
| Case 1 (실행성) | "~해줘", "~바꿔줘", "~꺼줘/켜줘", "~설정해줘" | "[항목]을 [값]으로 설정할까요?" 즉시 확인 발화(+ 매뉴얼 부작용 안내) → 긍정 시 실행 | 긍정 응답 턴에서 `update_self_service_setting` 호출 |
| Case 2 (탐색성) | "~할 수 있어?", "~되나요?", "그런 기능 있어?" | 매뉴얼 기반 설명 + 사전 준비사항 + "필요하시면 말씀해 주세요" 제안                  | **호출 안 함**(이 턴에서는)                         |

판정에 사용할 필드: `response`(응답 원문), `tool_trace`의 이벤트 목록, `call_data_record`의
`self_service_intent_tier_hint`(hint 값 — 참고용이며 최종 판정 기준이 아님, LLM 응답 패턴이
판정 기준).

---

## 2. 테스트 환경 준비

기존 QA owner(`9001`)는 Story 1.1~1.9 실행으로 이미 chat-relay 값이 변경된 상태이므로, 본 QA는
**신규 전용 owner**를 사용해 깨끗한 상태에서 검증한다.

```
QA_OWNER_INTELLI = "9003"
```

사전 페르소나 생성(기존 §1.2 절차와 동일, escalation_mode는 기본값 "hitl"로 시작):

```bash
curl -X POST http://localhost:8000/api/persona/ \
  -H "Content-Type: application/json" \
  -d '{
    "owner": "9003",
    "name": "QA 테스트 테넌트(IntelliDecision)",
    "description": "Story 1.10 및 전체 카탈로그 액션형 QA 전용 가상 테넌트입니다.",
    "scope_keywords": ["테스트"],
    "escalation_mode": "hitl"
  }'
```

실행 방법은 기존 문서 §2와 동일(`/api/self-service/test/converse`, 세션 유지로 멀티턴, 원시 로그
교차검증 병행 권장).

---

## 3. Case 1 — 실행성(잘 아는 경우): 전체 카탈로그 도메인 매트릭스

### 3.1 쓰기 가능 도메인 (persona / ai-escalation / chat-relay)

각 도메인마다 **(A) 완전한 정보로 요청**과 **(B) 정보 부족 → AI가 되물어야 함** 두 케이스를 둔다.

| ID     | 도메인        | 입력(멀티턴)                                                                                      | 기대 결과                                                                                                                               | 확인 필드                                                                                       |
| ------ | ------------- | ------------------------------------------------------------------------------------------------- | --------------------------------------------------------------------------------------------------------------------------------------- | ----------------------------------------------------------------------------------------------- |
| ID-P01 | persona       | "페르소나 설명을 '친절한 카페 매니저입니다'로 바꿔줘" (완전)                                      | "설명을 '친절한 카페 매니저입니다'로 설정할까요?" 확인 발화 → "응 맞아" → 실제 변경                                                     | `tool_trace`에 `self_service_auto_config_applied`(domain=persona, field=description)            |
| ID-P02 | persona       | "페르소나 설명 좀 바꿔줘" (불완전 — 새 값 없음)                                                   | Tool 호출 없이 "어떤 내용으로 바꿔드릴까요?" 류로 되물음                                                                                | `tool_trace`에 `self_service_tool_start`(update_self_service_setting) **없어야 함**             |
| ID-E01 | ai-escalation | "AI가 에스컬레이션 안 하도록 설정해줘" (Story 1.10 예문 B, 완전 — escalation_mode=none 유추 가능) | "에스컬레이션하지 않도록 설정할까요? 이 경우 고객이 먼저 '상담원 연결해 주세요'라고 요청하면 그때만 처리됩니다" 확인 발화 → 긍정 → 실행 | `self_service_auto_config_applied`(domain=ai-escalation, field=escalation_mode, new_value=none) |
| ID-E02 | ai-escalation | "에스컬레이션 방식 좀 바꿔줘" (불완전 — hitl/transfer/none 중 무엇인지 불명)                      | Tool 호출 없이 세 가지 방식 중 무엇을 원하는지 되물음                                                                                   | Tool 미호출, `response`에 3가지 방식 언급                                                       |
| ID-C01 | chat-relay    | "채팅 자동응답 꺼줘" (완전, 기존 SS-1.8-01과 동일)                                                | 확인 발화 → 긍정 → 실행                                                                                                                 | `self_service_auto_config_applied`(domain=chat-relay, field=message_ai_reply_enabled)           |
| ID-C02 | chat-relay    | "채팅 자동응답 설정 좀 바꿔줘" (불완전 — on/off 불명)                                             | Tool 호출 없이 켜기/끄기 중 무엇인지 되물음                                                                                             | Tool 미호출                                                                                     |

### 3.2 쓰기 불가 도메인 (call-control / contacts / general / integrations)

카탈로그에 `update_fn`이 없거나 제외 목록(`config/self_service_exclusions.yaml`)에 등록된
도메인. AI가 변경 시도 자체를 하지 않거나, 시도해도 코드 레벨에서 거부되어야 한다(IV2 원칙).

| ID      | 도메인       | 입력                                              | 기대 결과                                                                             | 확인 필드                                                                                |
| ------- | ------------ | ------------------------------------------------- | ------------------------------------------------------------------------------------- | ---------------------------------------------------------------------------------------- |
| ID-CC01 | call-control | "착신 규칙 하나 추가해줘" (기존 SS-1.8-03 재확인) | 정중한 거부 + "설정 > 착신 제어에서 직접 등록해 주세요" 류 안내                       | `self_service_auto_config_rejected`(domain=call-control)                                 |
| ID-CT01 | contacts     | "연락처에 홍길동 010-1234-5678 추가해줘"          | 거부 + 프론트엔드 연락처 화면 안내                                                    | `self_service_auto_config_rejected`(domain=contacts) 또는 애초에 Tool 미호출 + 안내 응답 |
| ID-G01  | general      | "우리 회사 이름을 다른 이름으로 바꿔줘"           | 거부(정적 데이터, 변경 함수 없음) + 안내                                              | `self_service_auto_config_rejected`(domain=general) 또는 안내 응답                       |
| ID-I01  | integrations | "구글 캘린더 연동 끊어줘"                         | 거부(OAuth 액션이라 대화형 불가) + "설정 > 일반에서 연동 해제 버튼을 눌러주세요" 안내 | `self_service_auto_config_rejected`(domain=integrations) 또는 안내 응답                  |

### 3.3 카탈로그 밖 도메인 (booking) — 알려진 한계

`settings_catalog.py`에는 `booking` 도메인이 아예 등록되어 있지 않다(예약은 별도
`booking_agent`/`booking_tools.py`가 처리하며 self_service Tool 범위 밖). 아래 케이스는 **결함이
아니라 설계상 한계를 확인**하는 목적이다.

| ID     | 입력                      | 기대 결과                                                                                               | 비고                                                                                                                                              |
| ------ | ------------------------- | ------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------- |
| ID-B01 | "예약 슬롯 하나 추가해줘" | Tool을 호출하지 않고 매뉴얼(§6 예약 관리) 기반 설명만 제공(예약 관리 화면 안내) — 실제 실행은 되지 않음 | Case 2(탐색성)와 유사하게 처리되는 것이 정상. 실제 예약 슬롯 생성은 booking_agent 채널(고객 응대)의 영역이며 셀프서비스 세션에서는 지원 대상 아님 |

---

## 4. Case 2 — 탐색성(잘 모르는 경우): 매뉴얼 기반 IntelliDecision

각 케이스는 매뉴얼(§)의 특정 Q&A와 연결되며, AI가 **설명 + 사전 준비사항 + 제안**으로 응답하고
이 턴에서 어떤 `update_self_service_setting` 호출도 하지 않아야 한다.

| ID     | 입력                                                                        | 매뉴얼 근거                   | 기대 응답 요지                                                                                                                      | 확인 필드                                     |
| ------ | --------------------------------------------------------------------------- | ----------------------------- | ----------------------------------------------------------------------------------------------------------------------------------- | --------------------------------------------- |
| ID-Q01 | "AI가 모르는 질문 받으면 나한테 전화하게 해줄 수 있어?" (Story 1.10 예문 A) | §3 "상담원 직접 연결(호전환)" | 호전환 방식 설명 + "착신 제어에서 대상 내선 등록 필요" + "설정이 필요하면 말씀해주세요"                                             | `tool_trace`에 update 계열 Tool 호출 **없음** |
| ID-Q02 | "채팅으로 온 문의도 자동으로 답장하는 기능이 있어?"                         | §7 채팅 자동응답              | 기능 설명(자동응답 접두 문구 포함) + 켜고 싶으면 말해달라는 제안                                                                    | Tool 미호출                                   |
| ID-Q03 | "예약 여러 명 한 슬롯에 받을 수 있어?"                                      | §6.2 예약 슬롯                | "예약 가능 인원" 지정 방식 설명(카탈로그 밖이므로 실행 제안이 아니라 예약 관리 화면 안내 위주)                                      | Tool 미호출                                   |
| ID-Q04 | "구글 캘린더 연동하면 뭐가 좋아?"                                           | §6.3 Google 캘린더 연동       | 연동 이점 설명 + "설정 > 일반에서 연동 가능" 안내(OAuth라 대화형 실행 불가함을 은연중에 반영)                                       | Tool 미호출                                   |
| ID-Q05 | "운영자가 부재중이면 어떻게 처리돼?"                                        | §4 운영자 부재중 모드         | 동작 메커니즘 설명(상태 전환 시점 등) — 이 항목은 설정 변경 여지가 없는 순수 정보성 질문이므로 애초에 유형 분기 대상이 아님(대조군) | Tool 미호출, `response`에 매뉴얼 내용 반영    |

> **ID-Q05는 대조군(negative control)**: IntelliDecision 유형 분기와 무관하게 원래도 Tool을
> 호출하면 안 되는 순수 정보 질의다. 힌트 로직이 이런 질문까지 잘못 `actionable_hint`로 오분류해도
> LLM이 올바르게 처리하는지 확인하는 용도로 포함한다.

---

## 5. 실행 후 판정 절차 (기존과 동일 원칙 재확인)

1. `response` 원문이 기대 패턴(확인 발화 vs 설명+제안)과 일치하는지 확인.
2. `tool_trace`에서 `update_self_service_setting` 관련 이벤트(`self_service_tool_start`/`done`,
   `self_service_auto_config_applied`/`rejected`) 유무를 유형별 기대와 대조.
3. 핵심 케이스(ID-P01, ID-E01, ID-C01 각 2턴 완료분)는 원시 로그
   (`logs/call_data_record_YYYYMMDD.log`)를 `call_id`로 직접 grep해 교차검증(기존 문서 §0 원칙).
4. `self_service_intent_tier_hint` 이벤트 값을 기록해 두되, **힌트가 실제 응답 유형과 다르더라도
   실패로 판정하지 않는다**(힌트는 참고 신호일 뿐 — Story 1.10 AC3). 실패 판정은 오직 `response`
   패턴·Tool 호출 여부 기준으로만 내린다.

---

## 6. 실행 상태

**✅ 실행 완료(2026-07-16).** 서버 재시작 후 실제 LLM·RAG·Tool-calling 경로로 전체 케이스를
실행했다. 상세 결과·발견 이슈·조치 내용은
[2026-07-16_self_service_story_1.10_qa_execution_result.md](../reports/2026-07/2026-07-16_self_service_story_1.10_qa_execution_result.md)
참고. 요약:

- Case 1(실행성) 6/6 PASS(완전/불완전 정보 각 3건), 쓰기 불가 4개 도메인 거부 확인, booking 알려진 한계 확인.
- Case 2(탐색성) 5/5 PASS — 1차 실행 시 신규 QA owner에 매뉴얼 미색인으로 RAG 0건이었던 문제를
  색인 후 재검증으로 해결.
- **신규 발견 버그(수정 완료, 실서버 재검증 대기)**: `escalation_mode`에 무효값("disabled")이
  저장되는 버그 발견 → `settings_catalog.py`에 필드별 허용값 검증 계층 추가로 근본 수정.

### 실행 후 체크리스트

- [x] 서버 재시작 확인(`GET /api/self-service/test/status` → `test_mode_enabled: true`)
- [x] QA owner(9003) 페르소나 생성
- [x] `scripts/self_service_qa_step5_intelli_decision.ps1` 실행
- [x] RAG 미색인 이슈 발견 → 색인 후 `scripts/self_service_qa_step5b_rerun_after_rag_fix.ps1`로 재검증
- [x] 결과를 `docs/reports/2026-07/2026-07-16_self_service_story_1.10_qa_execution_result.md`로 정리
- [x] `docs/stories/1.10.intelli-decision-intent-tier.story.md`의 QA Results 섹션 갱신
- [x] escalation_mode 값 검증 수정 반영을 위한 서버 재시작 + 재검증 완료(2026-07-16) — LLM이 이제
      도구 설명에 명시된 허용값을 보고 정확히 유효값("none")을 선택함을 ID-E01 재실행으로 확인.
      상세: [2026-07-16_self_service_story_1.10_qa_execution_result.md](../reports/2026-07/2026-07-16_self_service_story_1.10_qa_execution_result.md) §6

**본 QA는 이것으로 완료됐다. Story 1.10은 Done 상태로 전환됐다.**

---

## 7. 준비된 실행 스크립트

`scripts/self_service_qa_step5_intelli_decision.ps1`(본 QA 계획 문서의 케이스 전체 실행,
2026-07-16 실행 완료) + `scripts/self_service_qa_step5b_rerun_after_rag_fix.ps1`(RAG 색인 수정 후
재검증용, 신규). 둘 다 기존 `self_service_qa_step3.ps1`과 동일한 `Invoke-Converse`/`Show-Result`
헬퍼 패턴을 재사용한다.

```powershell
pwsh -File scripts/self_service_qa_step5_intelli_decision.ps1
pwsh -File scripts/self_service_qa_step5b_rerun_after_rag_fix.ps1
```

*최종 업데이트: 2026-07-16*
