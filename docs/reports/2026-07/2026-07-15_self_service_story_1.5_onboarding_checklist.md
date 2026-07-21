# Story 1.5 (온보딩 체크리스트 안내) 구현 완료 보고서

**작성일**: 2026-07-15
**관련 문서**: [1.5.onboarding-checklist.story.md](../../stories/1.5.onboarding-checklist.story.md), [1.4.settings-catalog-readonly.story.md](../../stories/1.4.settings-catalog-readonly.story.md)
**상태**: 완료 (Story Status → Review)

## 1. 문제 요약

셀프서비스 세션 시작 시, 아직 초기 설정을 마치지 않은 테넌트 관리자에게 AI가 먼저 안내해야 한다(매뉴얼 §2 "초기 설정 체크리스트"). Story 1.4의 설정 카탈로그를 소비하는 첫 번째 기능이며, 완료 여부를 별도 저장소 없이 매번 실시간 조회로 판정해야 한다(IV1).

## 2. 구현 내용

### 2.1 필수 온보딩 항목 범위 확정 (Task 1)

매뉴얼(§2)의 5개 초기 설정 항목 중 **필수 3개**만 체크리스트 대상으로 삼았다:

| 항목            | 판정 기준                                                     |
| --------------- | ------------------------------------------------------------- |
| `persona`       | `exists=False` 또는 `name`/`description` 모두 빈 값           |
| `ai-escalation` | persona 자체가 없으면(`persona_exists=False`) 미결정으로 간주 |
| `call-control`  | `rules` 목록이 비어 있음                                      |

예약 도메인/슬롯(카탈로그에 `booking` 도메인 없음)과 채팅 자동응답·Google 캘린더 연동(매뉴얼에 "필요하다면"/"받는다면"으로 명시된 선택 항목)은 의도적으로 제외했다.

**부수 발견**: `ai-escalation` 판정은 `escalation_mode` 필드만으로는 "코드 기본값 hitl"과 "관리자가 의식적으로 선택한 hitl"을 구분할 수 없었다. Story 1.4의 `settings_catalog._get_ai_escalation()`에 `persona_exists` 플래그를 추가해(최소 수정) 해결했다 — 기존 Story 1.4 테스트는 회귀 없이 통과.

### 2.2 `src/ai_voicebot/self_service/onboarding.py` (신규)

- `get_onboarding_checklist(owner)`: `_CHECKS` 리스트(도메인, 판정 함수, 안내 문구)를 순회하며 `settings_catalog.get_domain_value()`만 호출(카탈로그는 순수 조회, 판정은 별도 관심사 — Story 1.4 IV1과 충돌 방지)
- 7개 도메인 전체가 아닌 필수 3개만 조회해 지연 최소화(IV2)
- 개별 판정 함수 예외는 흡수(로그만 남기고 해당 항목을 미완료로 오판하지 않음)

### 2.3 `src/ai_voicebot/self_service/tools.py` (신규)

- `booking_tools.py::_make_tool` 패턴을 그대로 재현(모듈 간 private 심볼 직접 import 대신 동일 패턴 복제)
- `get_onboarding_checklist_tool`: JSON 문자열 반환(`{"incomplete_count": N, "items": [...]}`), 향후 Story 1.6/1.8의 실제 tool-calling 루프에서 재사용 가능하도록 등록

### 2.4 `self_service_agent_node` 통합 (Task 3)

- `is_first_turn = not state.get("messages")`로 세션 첫 턴만 판별해 체크리스트 조회(반복 호출로 인한 지연 증가 방지, IV2)
- 시스템 프롬프트에 `[온보딩 체크리스트]` 섹션 추가 — 미완료 항목이 있으면 안내 문구 나열, 없으면 "모두 완료됨, 언급 금지" 플레이스홀더, 첫 턴이 아니면 "재안내 금지" 플레이스홀더
- 실제 tool-calling 루프는 아직 없으므로(Story 1.6~1.8에서 구현 예정) 하드코딩 라우팅 없이 LLM 프롬프트 지시로 "안내 후 자동설정 도움 제안" 처리
- 체크리스트 조회 예외는 흡수해 노드 전체 응답 실패로 이어지지 않도록 방어

## 3. 검증 결과

```
python -m pytest tests_new/unit/test_ai_voicebot/test_self_service_onboarding.py -v --no-cov
→ 18 passed

python -m pytest tests_new/unit/test_ai_voicebot tests_new/unit/test_events -q --no-cov
→ 92 passed (Story 1.1~1.5 누적 74 + 신규 18), 회귀 없음
```

## 4. 변경 파일

- `src/ai_voicebot/self_service/onboarding.py` (신규)
- `src/ai_voicebot/self_service/tools.py` (신규)
- `src/ai_voicebot/self_service/settings_catalog.py` (수정 — `_get_ai_escalation()`에 `persona_exists` 필드 추가)
- `src/ai_voicebot/langgraph/nodes/self_service_agent.py` (수정 — 온보딩 체크리스트 통합)
- `tests_new/unit/test_ai_voicebot/test_self_service_onboarding.py` (신규, 18 tests)
- `docs/stories/1.5.onboarding-checklist.story.md` (Task 1~3 체크, Dev Agent Record/Change Log 갱신, Status → Review)

## 5. 후속 작업

- Story 1.6(설정 조회 Tool)에서 `get_onboarding_checklist_tool`과 유사한 패턴으로 개별 도메인 조회 Tool을 추가하고, 실제 LLM tool-calling(bind_tools) 루프를 self_service_agent_node에 처음 도입할 예정.

---
*최종 업데이트: 2026-07-15*
