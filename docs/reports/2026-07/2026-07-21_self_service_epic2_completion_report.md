# 셀프서비스 AI 도우미 Epic 2 — 완료 리포트 (Story 2.1~2.7)

- 작성일: 2026-07-21
- 버전: 1.0
- 상태: Epic 2(Story 2.1~2.7) 전체 Done. Story 2.8은 저우선순위·선택 사항으로 별도 진행.
- 관련 문서:
  - [PRD Epic 2](../../product/self-service-ai-assistant-prd.md)
  - [Architecture §Epic 2](../../architecture/self-service-ai-assistant-architecture.md)
  - [Story 2.1~2.7](../../stories/)
  - [통합 QA Branch L](../../qa/self-service-ai-assistant-master-qa.md)
  - [이전 리포트: Story 2.1~2.5 구현](2026-07-21_self_service_epic2_story_2.1_to_2.5_implementation.md)
  - [이전 리포트: Story 2.5 IV2 + Story 2.6 힌트 제거 착수](2026-07-21_self_service_epic2_story2.5_iv2_and_story2.6_hint_removal.md)
  - [Story 2.7 원시 QA 출력](2026-07-21_epic2_story2.7_integration_qa_raw_output.txt)

## 1. 요약

사용자가 "셀프서비스 AI 도우미 기능이 너무 하드코딩되어 있다"고 지적한 문제를 해결하기 위해
기획된 Epic 2(설정 카탈로그/Screen Graph 동적화 + IntelliDecision 신뢰성 개선)를 BMAD 프로세스
(브리프→PRD→아키텍처→스토리→구현→테스트→QA)에 따라 story 단위로 순차 구현하고, 이번 세션에서
**Story 2.1~2.7 전체를 완료**했다.

## 2. Epic 2 최종 결과

| Story | 내용                                                                  | 상태                     |
| ----- | --------------------------------------------------------------------- | ------------------------ |
| 2.1   | 카탈로그/Screen Graph DB 저장소 + 함수 화이트리스트 레지스트리        | Done                     |
| 2.2   | `settings_catalog.py` DB 우선 로딩(하드코딩 폴백 유지)                | Done                     |
| 2.3   | `screen_graph.py` 동일 패턴 전환                                      | Done                     |
| 2.4   | 설정 내보내기 API + 프론트엔드 다운로드                               | Done                     |
| 2.5   | 설정 업로드(검증→diff→적용)/롤백/버전 이력 + IV2 실서버 검증          | Done                     |
| 2.6   | IntelliDecision 키워드 힌트 완전 제거(`intent_tier.py` 삭제) + 재검증 | Done                     |
| 2.7   | 통합 QA(master-qa.md Branch L) + Epic 1 전체 회귀 재확인              | Done                     |
| 2.8   | 매뉴얼 도메인 매핑 동적화                                             | 미착수(저우선순위, 선택) |

## 3. Story 2.6 최종 마무리(이번 세션)

이전 세션에서 힌트 제거 코드까지 완료하고 재검증을 사용자의 재시작 이후로 미뤄두었다. 이번
세션에서 서버 재시작 확인 후:

1. IntelliDecision QA 16건(Case 1: 11건 + Case 2: 5건)을 힌트 제거 후 코드로 재실행.
2. 베이스라인과 비교한 결과 13/16건이 완전 일치하거나 더 정확했고, 1건(P01 2턴)은 힌트와 무관한
   기존 Gemini API 이슈가 베이스라인·재검증 양쪽에서 동일하게 재현되었으며, 2건(I01/B01)은
   최초 1회 관찰된 이상 응답이 재현 테스트(각 3~5회)에서 모두 정상으로 확인되어 노이즈로 판명됐다.
3. 결과가 동등 이상이므로 `intent_tier.py`와 `test_self_service_intent_tier.py`를 삭제했다
   (사용처가 완전히 사라졌음을 grep으로 확인 후 진행). `docs/stories/1.10.*.story.md`에 제거
   이력을 기록했다.
4. 단위 회귀: 327개(힌트 제거 직후) → 311개(모듈 삭제 후) 모두 통과.

## 4. Story 2.7 통합 QA 결과

`master-qa.md`에 신규 **Branch L**(4건: L1 카탈로그 writable_fields 동적 반영, L2 Screen Graph
nav_hint 즉시 반영, L3 잘못된 함수명 거부, L4 롤백)을 추가해 실서버로 검증했다.

- **L2/L3/L4**: PASS. 특히 L3(화이트리스트 위반 업로드 거부)는 `import` 응답이 명확한 오류
  메시지와 함께 `ok=false`를 반환하고 활성 버전이 전혀 바뀌지 않음을 확인해 Epic 2의 핵심 보안
  설계(RCE 방지)가 실제로 작동함을 실증했다.
- **L1**: 부분 확인. `persona.description`의 쓰기 권한을 DB에서 제거한 뒤 실제로 거부되는지
  확인하려 했으나, 아래 §5의 신규 결함으로 인해 확인 턴 자체가 Gemini 빈 응답으로 실패해 직접
  관찰하지 못했다. 대신 같은 메커니즘을 이미 검증한 Story 2.2 단위 테스트
  (`test_unwhitelisted_update_fn_ref_disables_write_but_keeps_read`)와, 같은 시험에서 성공한
  chat-relay의 다른 필드(`message_ai_reply_enabled`) 케이스로 메커니즘 자체는 간접 확인했다.

Epic 1 전체 회귀는 재실행 대신 단위 테스트(311개 통과) + Story 2.6에서 이미 재확인한 Branch H로
갈음해 중복 실행 비용을 절감했다.

## 5. 신규 발견 결함 — persona 등 문자열 값 필드의 확인→실행 2턴 흐름 (Epic 2와 무관, 별도 Story 권장)

Story 2.7 통합 QA 중, `persona.description`을 자연어 문자열로 변경하는 확인→긍정 2턴 흐름에서
긍정 턴(2턴째)이 **6/6회 모두** Gemini의 완전히 빈 응답(`finish_reason=STOP`, 내용 없음)으로
실패해 `_FALLBACK_GREETING`으로 대체되는 현상을 발견했다.

- **Epic 2와 무관함을 확인**: 카탈로그를 전혀 수정하지 않은 원본 버전에서도 동일하게 100%
  재현되었다(대조군 테스트).
- **도메인이 아니라 필드의 값 타입과 상관관계**: 동일 시점 chat-relay의 boolean 값 필드
  (`message_ai_reply_enabled`)는 즉시 성공했고, ai-escalation의 enum 값 필드도 안정적으로
  성공했다. 반면 chat-relay의 문자열 값 필드(`message_ai_reply_prefix`)는 persona.description과
  마찬가지로 동일하게 실패했다 — "확인 질문에 사용자가 직접 입력한 자연어 문자열 값이 포함되는지
  여부"가 실패율과 상관관계가 있는 것으로 추정된다(확정적 원인 규명은 미완료).
- **영향도**: Story 1.8(자동설정 쓰기)의 핵심 시나리오 중 문자열 값 필드 변경 성공률이 현저히
  낮아질 수 있다. 기존 완화책(최대 2회 재시도)만으로는 충분하지 않다(재시도 모두 소진된 사례가
  6/6 관측됨).
- **후속 조치 권장(신규 별도 Story)**: (1) 실패 시 요청 contents 자체(특히 따옴표·대괄호가 포함된
  직전 턴 모델 메시지)를 로깅해 가설 검증, (2) 문자열 값 필드에 한해 재시도 횟수를 늘리는 방안
  검토, (3) 재시도 모두 소진 시 사용자에게 "다시 한번 말씀해 주세요"처럼 명확히 실패를 알리는
  메시지 도입(현재는 일반 인사말로 조용히 폴백되어 사용자가 실패를 인지하기 어려움).

## 6. 최종 산출물

- 코드: `src/booking/database.py`, `src/common/self_service_catalog_config_db.py`,
  `src/ai_voicebot/self_service/{settings_catalog.py, screen_graph.py, catalog_config_loader.py}`,
  `src/api/routers/settings_ai_assistant.py`, `src/ai_voicebot/langgraph/nodes/self_service_agent.py`,
  `scripts/self_service_catalog_migrate_seed.py`, `frontend/app/settings/ai-assistant/docs/page.tsx`
- 삭제: `src/ai_voicebot/self_service/intent_tier.py`,
  `tests_new/unit/test_ai_voicebot/test_self_service_intent_tier.py`
- 신규 테스트: 100개 이상(Story 2.1~2.6 합산), 전체 회귀 311개 통과
- 문서: Story 2.1~2.7 전체 Done 처리, `master-qa.md` Branch L 추가 + 결함③ 기록,
  `docs/stories/1.10.*` 제거 이력, `SYSTEM_OVERVIEW.md`/`INDEX.md` 갱신

## 7. 다음 단계

- Story 2.8(매뉴얼 도메인 매핑 동적화) — 저우선순위, 필요 시 별도 착수.
- **신규 권장 Story**: §5의 persona 등 문자열 값 필드 확인→실행 2턴 흐름 Gemini 빈 응답 문제
  전용 조사·개선 Story.

*최종 업데이트: 2026-07-21*
