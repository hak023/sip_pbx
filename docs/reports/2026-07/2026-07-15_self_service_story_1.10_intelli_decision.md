# 셀프서비스 AI 도우미 — IntelliDecision (탐색성/실행성 발화 구분 응대) 구현

**작성일**: 2026-07-15
**버전**: 1.0
**상태**: 완료 (단위 테스트 검증 완료, 실서버 통합 검증은 향후 권장)
**관련 문서**:
- [self-service-ai-assistant-prd.md](../../product/self-service-ai-assistant-prd.md) FR12, Story 1.10
- [self-service-ai-assistant-architecture.md](../../architecture/self-service-ai-assistant-architecture.md) §Component Architecture
- [1.10.intelli-decision-intent-tier.story.md](../../stories/1.10.intelli-decision-intent-tier.story.md)

---

## 1. 문제 요약

기존 셀프서비스 AI 도우미는 설정 변경 관련 발화를 모두 동일하게 "확인 발화 → 긍정 → 실행"
흐름으로만 처리했다. 그러나 실제로는 두 가지 유형이 섞여 있다:

- **탐색성**: "AI가 모르는 질문 받으면 나한테 전화하게 해줄 수 있어?" — 아직 기능을 잘 모르고
  궁금해서 물어보는 경우. 변경 대상(도메인/필드/값)이 확정되지 않음.
- **실행성**: "AI가 에스컬레이션 안 하도록 설정해줘." — 이미 원하는 바가 명확한 경우.

기존 로직은 두 경우 모두 동일한 "즉시 확인 발화" 패턴만 지시해, 탐색성 질문에도 마치
설정을 바꿀 것처럼 응답할 위험이 있었다.

---

## 2. 근본 원인

`self_service_agent.py`의 `_TOOL_USAGE_INSTRUCTION` 규칙 10이 발화 유형 구분 없이
"확인 발화 후 실행" 단일 분기만 지시하고 있었다.

---

## 3. 수정 내용 (BMAD 흐름 전체 반영)

### 3-1. PRD 보강
- [self-service-ai-assistant-prd.md](../../product/self-service-ai-assistant-prd.md)에 **FR12(IntelliDecision)** 추가
- Epic 1에 **Story 1.10** 섹션 추가, Epic Structure Decision을 "10개 순차 Story"로 갱신

### 3-2. 아키텍처 보강
- [self-service-ai-assistant-architecture.md](../../architecture/self-service-ai-assistant-architecture.md)에 신규 컴포넌트 `self_service/intent_tier.py` 추가
- Source Tree에 파일 위치 반영

### 3-3. Story 문서
- [1.10.intelli-decision-intent-tier.story.md](../../stories/1.10.intelli-decision-intent-tier.story.md) 신규 작성 (AC, Tasks, Dev Notes 포함)

### 3-4. 구현

| 파일                                                               | 변경 내용                                                                                                                                                                                                 |
| ------------------------------------------------------------------ | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `src/ai_voicebot/self_service/intent_tier.py`                      | 신규 — `classify_intent_tier_hint()`(종결 어미 패턴 매칭, best-effort), `hint_to_prompt_label()`                                                                                                          |
| `src/ai_voicebot/langgraph/nodes/self_service_agent.py`            | 시스템 프롬프트에 `[발화 유형 참고 신호]` 섹션 추가, 규칙 10을 유형 A(탐색성)/유형 B(실행성)로 재작성(사용자 제시 2개 예문을 few-shot으로 그대로 포함), `self_service_agent_node`에서 힌트 계산·로깅 배선 |
| `tests_new/unit/test_ai_voicebot/test_self_service_intent_tier.py` | 신규 — 16개 단위 테스트                                                                                                                                                                                   |

### 3-5. 핵심 설계 원칙

- **힌트는 강제 게이트가 아니다.** 최종 판단은 LLM이 내리며, `intent_tier.py`의 결과는
  시스템 프롬프트에 "참고 신호"로만 삽입된다(`.github/copilot-instructions.md`의
  "의도 분류는 키워드 매칭보다 LLM 판단을 우선한다" 원칙 준수).
- **기존 확인 발화 흐름(Story 1.8)과 100% 호환.** 유형 B의 하위 규칙(a, b)은 기존 규칙 10의
  b, c를 그대로 승계해 회귀 없음.
- **순수 함수, 지연 시간 영향 없음.** LLM 호출 없이 정규식 매칭만 수행(NFR1 준수).
- **best-effort.** 예외 발생 시 항상 `"unclear"`로 폴백해 전체 응대 흐름을 끊지 않음(IV2).

---

## 4. 검증 결과

### 4-1. 힌트 분류 정확도 (Story 원문 예문 기준)

| 입력                                                    | 기대 힌트          | 실제 결과            |
| ------------------------------------------------------- | ------------------ | -------------------- |
| "AI가 모르는 질문 받으면 나한테 전화하게 해줄 수 있어?" | informational_hint | ✅ informational_hint |
| "AI가 에스컬레이션 안 하도록 설정해줘."                 | actionable_hint    | ✅ actionable_hint    |

### 4-2. 단위 테스트

```
tests_new/unit/test_ai_voicebot/test_self_service_intent_tier.py — 16 passed
```

### 4-3. 회귀 테스트 (기존 self_service 스위트 전체)

```
test_self_service_auto_config.py, test_self_service_settings_tool.py,
test_self_service_manual_rag.py, test_self_service_detection.py,
test_self_service_onboarding.py, test_self_service_stats.py
— 133 passed, 1 warning (기존 Pydantic 경고, 본 변경과 무관)
```

### 4-4. 앱 임포트 검증

```
python -c "from src.api.main import app" → 정상 (라우팅/의존성 주입 오류 없음)
```

---

## 5. 향후 권장 사항

- 실서버 재기동 후 두 예문을 실제 셀프서비스 세션(자기 번호 통화/문자)으로 재현해,
  LLM이 실제로 유형 A/B에 맞는 응답을 생성하는지 통합 검증 필요(`call_data_record`의
  `self_service_intent_tier_hint` 이벤트로 힌트 값 확인 가능).
- 힌트 정규식 패턴은 실제 사용 데이터가 쌓이면 오분류 사례를 기반으로 보강 가능(다만
  힌트가 틀려도 LLM 최종 판단에는 영향 없음 — 안전).

*최종 업데이트: 2026-07-15*
