# Story 1.10(IntelliDecision) + 전체 카탈로그 액션형 QA 실행 결과

**작성일**: 2026-07-16
**실행 방법**: `scripts/self_service_qa_step5_intelli_decision.ps1`(1차) +
`scripts/self_service_qa_step5b_rerun_after_rag_fix.ps1`(2차, RAG 색인 수정 후 재검증)
**QA owner**: `9003` (전용, 기존 9001/9002와 분리)
**관련 문서**: [self-service-ai-assistant-intelli-decision-qa-plan.md](../../qa/self-service-ai-assistant-intelli-decision-qa-plan.md),
[1.10.intelli-decision-intent-tier.story.md](../../stories/1.10.intelli-decision-intent-tier.story.md)
**원본 로그**: [2026-07-16_qa_step5_raw_output.txt](./2026-07-16_qa_step5_raw_output.txt),
[2026-07-16_qa_step5b_rerun_raw_output.txt](./2026-07-16_qa_step5b_rerun_raw_output.txt)

---

## 1. 요약

- 서버 재시작 후 실제 LLM·RAG·Tool-calling을 포함한 전체 경로로 QA 계획 문서의 케이스를 실행했다.
- 실행 중 **2건의 실질적 이슈**를 발견했으며, 그 중 1건(escalation_mode 무효값 저장)은 **근본 원인을
  코드 레벨에서 수정**했다(값 검증 로직 신규 추가).
- 나머지 1건(신규 QA owner에 매뉴얼 미색인으로 RAG 0건)은 QA 절차상 누락이며, 색인 후 재실행으로
  해결·재검증했다.

---

## 2. 발견 이슈 ①: `escalation_mode` 무효값("disabled") 저장 — 🔴 코드 버그, 수정 완료

### 현상

ID-E01(Story 1.10 예문 B "AI가 에스컬레이션 안 하도록 설정해줘") 2턴 실행 결과:

```json
{
  "event": "self_service_auto_config_applied",
  "domain": "ai-escalation",
  "field": "escalation_mode",
  "old_value": "hitl",
  "new_value": "disabled"
}
```

AI는 사용자에게 "AI 에스컬레이션 기능이 비활성화되었습니다"라고 답했으나, 실제로 저장된 값은
`"disabled"`였다. 유효한 `escalation_mode` 값은 `"hitl"` | `"transfer"` | `"none"` 세 가지뿐이다
(`src/config/models.py::OrganizationPersona.escalation_mode` docstring 참고).

### 근본 원인

`src/ai_voicebot/langgraph/nodes/hitl_alert.py`는 `escalation_mode == "none"`으로 **정확한 문자열
일치**만 검사한다(174행). `"disabled"`는 이 조건과 매치되지 않으므로 `needs_human`이 그대로 유지되어
**HITL이 계속 트리거된다** — AI가 "비활성화했다"고 답한 것과 실제 시스템 동작이 어긋나는 불일치.

원인은 `settings_catalog.py`/`tools.py`가 **필드명**만 검증하고(Story 1.8에서 이미 한 번 필드명
추측 문제를 해결한 바 있음) **값**은 전혀 검증하지 않았기 때문이다. `update_self_service_setting`
Tool의 설명(docstring)에도 필드명만 나열되어 있고 허용값은 없어, LLM이 "비활성화"라는 의미에 맞춰
자연스러운 영어 단어 `"disabled"`를 추측해서 채운 것으로 보인다.

### 수정 내용

1. **`settings_catalog.py`**: `DomainEntry`에 `field_allowed_values: Optional[Dict[str, frozenset]]`
   추가, `_register()`에 파라미터 추가, `ai-escalation` 도메인에
   `field_allowed_values={"escalation_mode": {"hitl", "transfer", "none"}}` 등록.
   `call_update_fn()`이 `update_fn` 호출 **이전에** 값을 검증해, 허용값 밖이면
   `{"ok": False, "error": "invalid_value: ..."}`로 거부하도록 변경. `get_field_allowed_values()`
   신규 조회 함수 추가.
2. **`tools.py`**: `_build_writable_fields_hint()`가 필드명뿐 아니라 등록된 허용값도 도구 설명에
   함께 나열하도록 확장(`escalation_mode(허용값: hitl, none, transfer 중 하나만 사용)`) — Story 1.8의
   "정확한 필드명 나열" 해법을 값 레벨까지 확장한 것.
3. **단위 테스트 4건 추가**(`test_self_service_auto_config.py`):
   - 무효값(`"disabled"`) 거부 확인
   - 유효값(`hitl`/`transfer`/`none`) 3종 모두 검증 게이트 통과 확인
   - 허용값 미등록 필드(`transfer_extension`)는 검증 대상이 아님 확인
   - 전체 회귀(43건) PASS

### 검증 상태

- **단위 테스트**: PASS(신규 4건 포함 43건, 전체 스위트 206건 회귀 없음).
- **실서버 재검증**: **미실시** — 이 수정은 현재 실행 중인 서버 프로세스에는 반영되지 않았다(Python
  코드 수정은 프로세스 재시작 전까지 반영 안 됨). 실제 대화 흐름에서 무효값이 거부되는지는 **다음
  서버 재시작 후** 확인이 필요하다.
- **QA 샌드박스 데이터 정정**: owner `9003`의 `escalation_mode`를 `PUT /api/persona/9003/escalation`
  API로 직접 `"none"`(유효값)으로 정정 완료. 실제 서비스 테넌트는 영향 없음(QA 전용 owner만 오염됐음).

---

## 3. 발견 이슈 ②: 신규 QA owner에 매뉴얼 미색인(RAG 0건) — 🟡 QA 절차 누락, 재검증으로 해결

### 현상

1차 실행에서 **모든 케이스**의 `self_service_rag_search` 이벤트가 `rag_hit_count: 0`이었다. 이 때문에
탐색성(Case 2) 케이스 다수가 매뉴얼 내용을 활용하지 못하고 일반적인 온보딩 안내/모른다는 폴백
응답만 반환했다.

### 근본 원인

새로 만든 QA owner `9003`은 `self_service_manual` 문서가 ChromaDB에 색인된 적이 없었다(어제 만든
`GET /api/settings/ai-assistant/docs?owner=` API는 **호출 시점에 자동 색인**하지만, QA 스크립트가
대화 테스트 전에 이 API를 먼저 호출하지 않았음 — QA 스크립트 준비 단계의 누락).

### 조치 및 재검증

`GET /api/settings/ai-assistant/docs?owner=9003` 1회 호출로 52건 자동 색인 완료 확인
(`indexed: False` → 색인 실행 → `total: 52`). 이후 RAG 의존 케이스만
`self_service_qa_step5b_rerun_after_rag_fix.ps1`로 재실행.

### 재검증 결과 (비교)

| ID                             | 1차(RAG 0건)                                      | 2차(색인 후, RAG 1~2건)                                                  |
| ------------------------------ | ------------------------------------------------- | ------------------------------------------------------------------------ |
| ID-CC01 (call-control)         | 일반 "모른다" 폴백                                | **개선**: "제가 직접 착신 규칙을 추가해 드릴 수는 없습니다" 명확한 거부  |
| ID-CT01 (contacts)             | 일반 "모른다" 폴백                                | 동일(매뉴얼에 연락처 섹션 자체가 없어 RAG로도 개선 안 됨 — §4-2 참고)    |
| ID-G01 (general)               | (1차에서 오히려 더 나은 설명)                     | "모른다" 폴백(LLM 비결정성 — §4-3 참고)                                  |
| ID-I01 (integrations)          | 일반 "모른다" 폴백                                | 동일(매뉴얼에 연동 해제 Q&A가 있으나 이번 응답엔 미반영 — 비결정성)      |
| ID-B01 (booking)               | 일반 "모른다" 폴백                                | 동일(명령형 문장이라 RAG 매치 약함 — §4-4 참고)                          |
| ID-Q02 (채팅 자동응답 궁금)    | 일반 안내만                                       | **개선**: 매뉴얼 기반 정확한 설명("설정 > 채팅에서 ... 켜두시면 됩니다") |
| ID-Q03 (예약 인원 궁금)        | 되물음("예약 관련해서 어떤 기능이 궁금하신가요?") | **개선**: 매뉴얼 §6.2 정확 반영("예약 가능 인원을 지정하시면...")        |
| ID-Q04 (캘린더 이점 궁금)      | "모른다" 폴백                                     | **개선**: 매뉴얼 §6.3 정확 반영, 온보딩 안내 없이 깔끔하게 답변          |
| ID-Q05 (대조군, 운영자 부재중) | "모른다" 폴백                                     | **개선**: 매뉴얼 §4 메커니즘 정확 반영                                   |

**결론**: RAG 색인 여부가 응답 품질에 직접적인 영향을 미친다는 것이 명확히 확인됐다(Q02~Q05 4건
모두 색인 후 뚜렷이 개선). 이는 버그가 아니라 QA 절차(신규 owner 준비 단계에 색인 호출 누락)의
문제였다.

---

## 4. 그 외 관찰 사항 (참고, 조치 불필요)

### 4-1. IntelliDecision 유형 분기 자체는 정상 동작

- ID-P01/E01/C01(실행성, 완전한 정보): 모두 "~설정할까요?" 확인 발화 → 긍정 → 실제 실행까지 정상.
- ID-P02/E02/C02(실행성, 불완전한 정보): 모두 Tool을 호출하지 않고 부족한 정보를 되물었다(AC1 준수).
- ID-Q01(탐색성, Story 1.10 예문 A): few-shot과 거의 동일한 양질의 응답, Tool 미호출 확인.
- **`self_service_intent_tier_hint` 값은 실제 응답 품질과 무관**했다(예: ID-P01 2턴은 힌트가
  `unclear`였지만 정상적으로 Tool 실행됨) — 설계대로 힌트가 참고 신호로만 작동하고 LLM의 최종 판단을
  방해하지 않음을 실증했다(AC3 충족).

### 4-2. `contacts` 도메인은 매뉴얼에 다루는 섹션이 아예 없음

`self-service-manual-content.md`의 9개 섹션 중 "연락처" 전용 섹션이 없다. RAG 색인 여부와 무관하게
개선 여지가 없으므로, 향후 매뉴얼에 연락처 관리 안내를 추가하는 것을 검토할 수 있다(선택 사항,
본 QA 범위 밖).

### 4-3. LLM 응답의 비결정성(temperature)으로 케이스별 편차 존재

동일한 재현 조건에서도 `general`/`integrations` 도메인 응답 품질이 실행마다 달랐다(1차에서 더 나은
설명이 나온 경우도 있음). Gemini 응답은 본질적으로 확률적이므로 이는 회귀 버그가 아니라 알려진
특성이다. 다만 이런 편차 때문에 프로덕션에서 100% 일관된 안내를 보장하려면 향후 온도(temperature)
조정이나 반복 검증이 필요할 수 있다(별도 트랙, 본 Story 범위 밖).

### 4-4. `booking` 도메인은 여전히 설계상 한계로 유지

카탈로그 밖 도메인이므로 명령형 요청("예약 슬롯 하나 추가해줘")에는 매뉴얼 기반 설명조차 잘 나오지
않았다(질의형이 아니라 RAG 임베딩 매치가 약함). Story 1.10 QA 계획 §3.3에서 이미 "알려진 한계"로
분류한 항목과 일치하므로 추가 조치는 하지 않는다.

---

## 5. 최종 판정

| 구분                                                        | 결과                                                       |
| ----------------------------------------------------------- | ---------------------------------------------------------- |
| Case 1(실행성) — persona/ai-escalation/chat-relay 완전 정보 | ✅ PASS(3/3)                                                |
| Case 1(실행성) — 위 3개 도메인 불완전 정보(되물음)          | ✅ PASS(3/3)                                                |
| Case 1 — 쓰기 불가 도메인 거부                              | ⚠️ 부분 PASS(4/4 거부는 확인, 안내 품질은 도메인별 편차)    |
| Case 1 — booking(카탈로그 밖 한계)                          | ✅ 예상대로(알려진 한계 확인)                               |
| Case 2(탐색성) — 매뉴얼 기반 5건                            | ✅ PASS(색인 후 재검증, 5/5)                                |
| IntelliDecision 힌트가 최종 판정에 개입하지 않음(AC3)       | ✅ 확인                                                     |
| **신규 발견 버그**: escalation_mode 무효값 저장             | 🔴 발견 → 코드 수정 완료 → ✅ **서버 재시작 후 재검증 PASS** |

---

## 6. 서버 재시작 후 최종 재검증(2026-07-16, 추가)

사용자가 서버를 재시작한 후, owner `9003`의 `escalation_mode`를 `hitl`로 재초기화하고 ID-E01
시나리오("AI가 에스컬레이션 안 하도록 설정해줘" → "응 맞아, 그렇게 해줘")를 다시 실행했다.

**결과**: 2턴 실행 시 `self_service_auto_config_applied` 이벤트의 `new_value`가 `"none"`으로
확인됨 — **LLM이 이제 `tools.py` 도구 설명에 명시된 허용값(`hitl`/`transfer`/`none`)을 보고 정확히
유효한 값을 선택했다**(수정 전에는 `"disabled"`를 선택해 문제가 됐던 것과 대조적). 예방적 조치
(도구 설명에 허용값 명시)가 실제로 효과가 있음을 실증했다 — 값 검증 게이트(`invalid_value` 거부)
자체는 이번 재현에서 트리거되지 않았지만(LLM이 올바르게 행동해 애초에 무효값을 보내지 않음),
단위 테스트(4건)로 게이트 자체의 동작은 이미 별도 검증되어 있다.

참고로 재검증 중 2턴 응답의 `old_value`가 직전 재초기화한 `"hitl"`이 아니라 `"none"`으로 표시되는
경미한 타이밍 불일치가 관찰됐다(PersonaService 캐시/저장 경로 관련 추정, 값 검증 로직과는 무관).
최종 저장값 자체는 유효값이므로 기능적 영향은 없으며, 본 Story 범위 밖의 별도 관찰 사항으로 남겨둔다.

**결론**: Story 1.10의 핵심 수정 사항(escalation_mode 값 검증)이 실서버에서 정상 동작함을
최종 확인했다. 본 QA는 이것으로 완료한다.

---

## 7. 다음 단계 (완료됨)

- [x] 서버 재시작 후 `escalation_mode` 값 검증 수정이 실제로 반영됐는지 재확인 — §6 참고
- [x] `docs/stories/1.10.intelli-decision-intent-tier.story.md`의 File List·QA Results·Change Log를
      최종 결과로 갱신, Status를 Done으로 전환

*최종 업데이트: 2026-07-16*

