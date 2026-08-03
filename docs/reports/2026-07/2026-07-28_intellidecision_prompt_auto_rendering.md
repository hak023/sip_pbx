# IntelliDecision 프롬프트 산문 자동 렌더링 구현 (Story 1.19, 축 A 완전판)

**작성일**: 2026-07-28
**작업 유형**: 리팩터링(회귀 방지 목적, 응대 로직 의미 불변)
**관련 문서**:
- [SELF_SERVICE_INTELLIDECISION_KNOWLEDGE_STRUCTURING_RESEARCH.md](../../design/SELF_SERVICE_INTELLIDECISION_KNOWLEDGE_STRUCTURING_RESEARCH.md)
- [1.18.intellidecision-policy-registry-and-knowledge-graph.story.md](../../stories/1.18.intellidecision-policy-registry-and-knowledge-graph.story.md)
- [1.19.intellidecision-prompt-auto-rendering.story.md](../../stories/1.19.intellidecision-prompt-auto-rendering.story.md)

## 1. 요약

Story 1.18에서 의도적으로 보류했던 축 A의 나머지 목표 — "프롬프트 번호 재조정 함정"의
근본 해결 — 을 이번 세션에서 완료했다. `self_service_agent.py`의 `_SELF_SERVICE_SYSTEM_PROMPT_TEMPLATE`/
`_TOOL_USAGE_INSTRUCTION`에 하드코딩되어 있던 18개 번호 규칙을 `prompt_rules.py`(신규)의
데이터 리스트로 이관하고, 번호와 교차 참조("유형 C(7번)")를 렌더링 시점에 자동 계산하도록
전환했다.

## 2. 구현 내용

- **`prompt_rules.py`(신규)**: `_BASE_RULES`/`_TOOL_RULES` 두 정적 리스트에 기존 18개 규칙을
  등록 순서 그대로 이관(내용은 원문과 동일). `render_base_prompt_rules()`/
  `render_tool_prompt_rules()`가 리스트 인덱스로 번호를 자동 계산해 텍스트를 조립한다.
- **센티널 토큰 방식 교차 참조**: 규칙 10("유형 C(<<REF:type_c>>번) 응답을 제외하고는...")의
  `<<REF:type_c>>`는 렌더링 시점에 실제 번호(7)로 자동 치환된다. `str.format()`을 이 모듈에서
  전혀 사용하지 않아(`str.replace()`만 사용) 규칙 텍스트 안의 `{fallback_message}` 같은 외부
  placeholder가 손상되지 않고 보존된다(호출측이 나중에 `.format()`으로 채움).
- **`self_service_agent.py` 연동**: `_SELF_SERVICE_SYSTEM_PROMPT_TEMPLATE`은 정적 문자열 뒤에
  `.replace("{response_rules_section}", prompt_rules.render_base_prompt_rules())`를 붙여 조립하고,
  `_TOOL_USAGE_INSTRUCTION`은 `prompt_rules.render_tool_prompt_rules()` 호출 결과를 그대로 사용한다.

## 3. 검증 결과

- 렌더링 결과를 실제로 콘솔에 출력해 원본 프롬프트(1~18번)와 의미가 완전히 동일함을 육안 대조:
  번호 순서, 각 규칙 본문, "유형 C(7번)" 교차 참조 모두 정확히 재현됨을 확인.
- 사전에 `grep`으로 테스트 코드 어디에도 프롬프트 문자열을 정확히 assert하는 케이스가 없음을
  확인(회귀 리스크가 낮다고 판단한 근거).
- `tests_new/unit -k "self_service or settings_ai_assistant"`(사전 결함 있는 2개 모듈 제외)
  224건 전체 0 FAILED — 리팩터링 이전과 동일한 통과 건수.
- 신규 `test_self_service_prompt_rules.py`(7건) 작성 및 통과 — 번호 연속성, 센티널 토큰 잔존
  여부, 외부 placeholder 보존 여부, 핵심 Tool 이름 존재 여부를 검증.

## 4. 의도적 트레이드오프

- **서식(공백/들여쓰기) 완벽 재현은 하지 않음**: 번호 자릿수가 바뀌어도(예: 7→70) 연속줄
  들여쓰기를 자동으로 재정렬하지 않는다. 이 프롬프트는 LLM 입력이지 사람이 읽는 문서가
  아니므로 코드 유지보수성을 우선했다.
- `intellidecision_policy.py`(Story 1.18, 유형 메타데이터)와 `prompt_rules.py`(이번 Story,
  실제 프롬프트 산문)는 완전히 통합하지 않고 별도 모듈로 유지했다 — 과설계 방지 원칙
  ("능력 레지스트리 결정 지원 리포트"의 축소 원칙과 동일 정신).

## 5. 다음 단계

- Story 1.18의 축 C-2(그래프 시각화)는 여전히 사용자 승인 대기 상태.

## 6. (같은 날 사용자가 서버 재시작 후) 실서버 검증 결과

- `Get-Process python` 시작 시각(14:25)이 변경 파일 수정 시각(14:12)보다 늦음을 확인 —
  최신 코드(prompt_rules.py 반영 버전)로 재시작됨.
- `POST /api/self-service/test/converse`(owner=9001)로 IntelliDecision 유형 A/C/F 3가지
  시나리오 실행, 모두 설계대로 정확히 동작:
  - **유형 A(탐색성)**: "AI가 모르는 질문 받으면 상담원한테 연결해줄 수 있어?" → Tool 호출
    없이 기능·사전 준비사항만 설명하고 "설정이 필요하시면 말씀해 주세요"로 마무리(정확).
  - **유형 C(포괄적 도움 요청)**: "뭘 할 수 있어?" → 3개 카테고리(설정 조회/변경/통계)를
    예시 발화와 함께 요약하고 "궁금하신 부분을 편하게 말씀해 주세요"로 마무리(정확히 규칙
    7번 지시대로).
  - **유형 F(모호성 해소)**: "그거 설정 좀 바꿔줘" → 도메인을 특정해 되묻는 응답(정확).
  - 세 경우 모두 `logs/app.log`에 오류 없음 확인.
- **결론**: 프롬프트 문자열 조립 로직을 하드코딩에서 자동 렌더링으로 바꿨음에도 실제 응대
  품질(내용·형식)에 변화가 없음을 실증했다 — 리팩터링 목표(회귀 없는 근본 구조 개선) 달성.

*최종 업데이트: 2026-07-28*
