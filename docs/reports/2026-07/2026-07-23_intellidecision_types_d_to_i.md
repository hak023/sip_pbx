# IntelliDecision 유형 D~I(대화 수리·복구 패턴) 구현 — 완료 리포트

**작성일**: 2026-07-23
**작업 유형**: 신규 기능 구현(리서치 제안 1 채택) — 셀프서비스 AI 도우미 Story 1.16
**관련 문서**: [1.16.intellidecision-types-d-to-i.story.md](../../stories/1.16.intellidecision-types-d-to-i.story.md),
[2026-07-23_intellidecision_enhancement_research.md](2026-07-23_intellidecision_enhancement_research.md)(제안 1 근거),
[self-service-ai-assistant-prd.md](../../product/self-service-ai-assistant-prd.md)(FR26)

---

## 1. 배경

직전 세션 리서치([2026-07-23_intellidecision_enhancement_research.md](2026-07-23_intellidecision_enhancement_research.md))에서
셀프서비스 IntelliDecision(유형 A/B/C)이 대화 정정·되돌리기·모호성 해소·일괄 처리·범위 외
설명·반복 요청 6가지 상황을 명시적으로 다루지 않는 공백을 발견했다. 사용자가 "제안 1은
구현하는 게 좋겠다"고 승인함에 따라 BMAD 순서(PRD → architecture → story → 구현 → 테스트 →
리포트)로 진행했다.

## 2. 반영 내용

### 2.1 IntelliDecision 신규 유형 6종

| 유형              | 구현 방식                                      | 위치                                                       |
| ----------------- | ---------------------------------------------- | ---------------------------------------------------------- |
| D(정정)           | 유형 B 확인 발화 중 정정 시 새 대상으로 재확인 | `_TOOL_USAGE_INSTRUCTION` 항목 14-b                        |
| E(실행 취소/Undo) | 신규 Tool 2개(조회+되돌리기)                   | `self_service/tools.py`, `_TOOL_USAGE_INSTRUCTION` 항목 18 |
| F(모호성 해소)    | 대상 불명확 시 되묻기                          | 기본 프롬프트 항목 8                                       |
| G(일괄 처리)      | 여러 설정을 묶어서 확인                        | `_TOOL_USAGE_INSTRUCTION` 항목 14-c                        |
| H(범위 외 설명)   | Tool의 `error` 필드 사유를 그대로 인용         | `_TOOL_USAGE_INSTRUCTION` 항목 14-d                        |
| I(반복 요청)      | 직전 AI 발화 요약 재안내                       | 기본 프롬프트 항목 9                                       |

D/F/G/H/I는 Tool 호출 추가 없이 프롬프트 규칙만으로 구현했고(NFR1 지연 예산 보호, 별도 분류
LLM 호출 없음 — Story 1.15/2.6과 동일 원칙), E(실행 취소)만 신규 Tool이 필요했다.

### 2.2 신규 Tool (유형 E)

- `get_last_self_service_change_tool`: `self_service_config_change_db.list_config_changes()`
  (Story 1.9 기존 이력 테이블)로 가장 최근 변경 1건을 조회하는 읽기 전용 Tool. 되돌리기 전
  확인 발화용 preview로 사용된다.
- `undo_last_self_service_change_tool`: 최근 변경의 `old_value`를 `_coerce_value()`로 타입
  복원 후 기존 `apply_self_service_setting()`(Story 1.8)에 그대로 위임해 재적용 — **신규
  DB 스키마·신규 제외 목록 로직 없이 기존 쓰기 경로를 100% 재사용**한다(제외 목록 검사·이중
  감사 기록이 되돌리기에도 자동으로 동일하게 적용됨).
- `SELF_SERVICE_TOOLS` 목록이 7개 → 9개로 증가.

### 2.3 프롬프트 구조 변경

- 기본 프롬프트(`_SELF_SERVICE_SYSTEM_PROMPT_TEMPLATE`)에 항목 8(유형 F)·9(유형 I) 추가,
  간결성 규칙을 항목 10으로 이동.
- `_TOOL_USAGE_INSTRUCTION`의 이어지는 번호를 9~15 → 11~18로 재조정(두 문자열이
  `system_prompt + _TOOL_USAGE_INSTRUCTION`으로 단순 연결되므로 번호 겹침 방지 — Story
  1.15에서도 동일하게 처리한 패턴).

### 2.4 문서 반영

- **PRD**: FR26(유형 D~I) 신설, 버전 0.6 → 0.7, Post-MVP 섹션을 "제안 1 반영 완료/제안 2
  계획 수립" 상태로 갱신.
- **Architecture**: "IntelliDecision 유형 D~I 추가 (Story 1.16)" 섹션 신설, 버전 0.5 → 0.6.
- **Story**: `docs/stories/1.16.intellidecision-types-d-to-i.story.md` 신규(Status: Done).
- **INDEX.md**: Story 1.16 행 추가.

## 3. 검증 결과

### 3.1 단위 테스트

```
python -m pytest tests_new/unit/test_ai_voicebot/ -k self_service -q --no-cov
```

전체 self_service 관련 단위 테스트(237건, 신규 `test_self_service_undo.py` 9건 포함) **전부
통과**. 신규 테스트는 다음을 검증한다:
- 변경 이력이 없을 때 `has_history: false`/`ok: false` 정상 반환.
- boolean 필드(`message_ai_reply_enabled`)의 문자열 `old_value`("False")가 실제 `False` 값으로
  올바르게 coerce되어 `apply_self_service_setting()`에 전달됨.
- Tool 예외가 흡수되어 `{"error": ...}` 형태로 반환됨(다른 Tool들과 동일한 방어 패턴).
- 제외 목록 등으로 되돌리기가 실패하면 `excluded`/`error` 필드가 그대로 전파됨.

기존 도구 개수를 하드코딩한 테스트 3개 파일(`test_self_service_settings_tool.py`,
`test_self_service_auto_config.py`, `test_self_service_stats.py`)의 기대값을 7 → 9로 갱신했다
(repo 메모에 이미 기록된 관례를 따름).

### 3.2 실서버 검증 (미실시 — 다음 세션 예정)

유형 D(정정)·F(모호성 해소)·E(Undo) 실제 대화 흐름은 실행 중인 서버가 필요해 이번 세션에서는
검증하지 못했다. `.github/copilot-instructions.md`의 포트/서버 재시작 사용자 승인 규칙에 따라
다음 세션에서 진행할 것을 권장한다(Story 1.16 Task 8, IV3).

## 4. 결론

리서치에서 제안한 6가지 IntelliDecision 신규 유형을 전부 반영했다. 5종(D/F/G/H/I)은 프롬프트
규칙 추가만으로, 1종(E)은 기존 데이터/쓰기 경로를 재사용하는 신규 Tool 2개로 구현해 회귀 리스크를
최소화했다. 단위 회귀는 전부 통과했으며, 실서버 검증만 다음 세션으로 이월한다.

---
*최종 업데이트: 2026-07-23*
