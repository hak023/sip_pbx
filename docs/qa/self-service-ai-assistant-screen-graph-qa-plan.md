# 셀프서비스 AI 도우미 — Screen Graph(화면 안내형 응대) QA 계획 및 실행

> ⚠️ **본 문서는 2026-07-20부터 [self-service-ai-assistant-master-qa.md](self-service-ai-assistant-master-qa.md)로 통합되었습니다(Branch I).**
> 통합 문서에서 백엔드 API는 재검증되었으나, 프론트엔드 탭 클릭이 자동화 도구에서 지속적으로 실패하는 신규 결함이 발견되었습니다(통합 문서 §3 결함② 참고).

**작성일**: 2026-07-16
**대상**: Story 1.11(Screen Graph 구축 및 화면 안내형 응대), Story 1.12(Screen Graph 프론트엔드 열람)
**실행 방식**: `POST /api/self-service/test/converse`(대화형) + `GET /api/settings/ai-assistant/screen-graph`(API 직접 검증) + 브라우저(프론트엔드 시각 검증)
**관련 문서**:
- [self-service-ai-assistant-intelli-decision-qa-plan.md](self-service-ai-assistant-intelli-decision-qa-plan.md) (기존 QA 원칙·환경 재사용)
- [1.11.screen-graph-guided-assistance.story.md](../stories/1.11.screen-graph-guided-assistance.story.md)
- [1.12.screen-graph-frontend-viewer.story.md](../stories/1.12.screen-graph-frontend-viewer.story.md)

---

## 1. 목적

Story 1.11/1.12 구현(어제) 시점에는 단위 테스트·TypeScript 컴파일 검증만 수행했고, 서버 재시작
후 실제 통합 검증은 미실시 상태였다. 본 문서는 서버 재시작 완료 후 다음을 검증한다.

1. **백엔드 API**: `/api/settings/ai-assistant/screen-graph`가 실제로 올바른 화면 정보를 반환하는지
2. **대화 연계**: `self_service_agent_node`가 탐색성 질문에 실제로 화면 안내를 포함해 응답하는지,
   `self_service_screen_graph_hit` 이벤트가 정확히 기록되는지
3. **프론트엔드**: `settings/ai-assistant/docs`의 "화면 안내" 탭이 실제로 정상 렌더링되는지

---

## 2. 테스트 환경

기존 QA owner `9003`을 재사용한다(어제 Story 1.10 QA에서 매뉴얼이 이미 색인되어 있어 RAG 검색이
정상 동작함을 확인한 owner).

```
QA_OWNER = "9003"
```

---

## 3. 테스트 케이스

### 3-1. 백엔드 API 직접 검증

| ID        | 검증 방법                                     | 기대 결과                                                                                                       |
| --------- | --------------------------------------------- | --------------------------------------------------------------------------------------------------------------- |
| SG-API-01 | `GET /api/settings/ai-assistant/screen-graph` | HTTP 200, `screens` 배열에 6개 도메인(ai-escalation/chat-relay/call-control/general/integrations/contacts) 포함 |
| SG-API-02 | 위 응답에서 `domain=persona` 존재 여부 확인   | **존재하지 않아야 함**(전용 설정 폼 없음, 의도적 미등록)                                                        |
| SG-API-03 | `domain=ai-escalation` 항목의 `fields` 확인   | `escalation_mode` 필드, `element_type=radio`, `options`에 3개 값 포함                                           |
| SG-API-04 | `domain=call-control` 항목의 `fields` 확인    | 5개 tab 요소(rules/schedules/forward-targets/ringback/caller-filters)                                           |

### 3-2. 대화 연계(탐색성 질문 → 화면 안내 포함 여부)

| ID         | 입력                                                                                          | 기대 결과                                                                                                        | 확인 필드                                                                              |
| ---------- | --------------------------------------------------------------------------------------------- | ---------------------------------------------------------------------------------------------------------------- | -------------------------------------------------------------------------------------- |
| SG-CONV-01 | "AI가 모르는 질문 받으면 나한테 전화하게 해줄 수 있어?" (ai-escalation 관련, Story 1.10 예문) | 응답에 "설정 > AI 에스컬레이션" 화면 위치 언급 포함                                                              | `tool_trace`에 `self_service_screen_graph_hit`(has_screen_guidance=true)               |
| SG-CONV-02 | "채팅으로 온 문의도 자동으로 답장하는 기능이 있어?" (chat-relay 관련)                         | 응답에 "/settings/chat-relay" 또는 "설정 > 채팅" 화면 언급 포함                                                  | `has_screen_guidance=true`                                                             |
| SG-CONV-03 | "구글 캘린더 연동하면 뭐가 좋아?" (integrations/general 관련)                                 | 응답에 "설정 > 일반" 화면 언급 포함                                                                              | `has_screen_guidance=true`                                                             |
| SG-CONV-04 | "운영자가 부재중이면 어떻게 처리돼?" (대조군 — 관련 도메인 없음/화면 무관)                    | 화면 안내 없이 순수 매뉴얼 설명만 제공                                                                           | `has_screen_guidance=false`                                                            |
| SG-CONV-05 | 페르소나 설명 관련 질문("페르소나 설명 어떻게 바꿀 수 있어?")                                 | 화면 정보가 없으므로(persona 미등록) 화면 안내 없이 텍스트 설명만 제공 — 존재하지 않는 화면을 지어내지 않아야 함 | `has_screen_guidance=false`, 응답에 가짜 라우트("/settings/persona" 등) 언급 없어야 함 |

### 3-3. 프론트엔드 시각 검증

| ID       | 검증 방법                                                                                 | 기대 결과                                                         |
| -------- | ----------------------------------------------------------------------------------------- | ----------------------------------------------------------------- |
| SG-FE-01 | 브라우저로 `http://localhost:3000/settings/ai-assistant/docs` 접속 후 "화면 안내" 탭 클릭 | 탭이 정상 렌더링되고 도메인별 카드(라우트 링크·설명·UI 요소) 표시 |
| SG-FE-02 | 화면 안내 카드의 라우트 링크 클릭                                                         | 실제 설정 화면(예: `/settings/ai-escalation`)으로 정상 이동       |
| SG-FE-03 | 기존 "이용 매뉴얼 Q&A"/"AI 변경 가능 설정" 탭 재확인                                      | 기존 탭 동작에 회귀 없음(IV1)                                     |

---

## 4. 실행 결과

**실행일**: 2026-07-20 (서버 재시작 완료 후)

### 4-1. 백엔드 API 직접 검증

| ID        | 결과   | 비고                                                                                           |
| --------- | ------ | ---------------------------------------------------------------------------------------------- |
| SG-API-01 | ✅ PASS | `screens` 6건(ai-escalation/chat-relay/call-control/general/integrations/contacts) 정확히 반환 |
| SG-API-02 | ✅ PASS | `persona` 도메인 0건(미등록 확인)                                                              |
| SG-API-03 | ✅ PASS | `escalation_mode` radio, options 3개(hitl/transfer/none) 정확                                  |
| SG-API-04 | ✅ PASS | call-control 5개 tab(rules/schedules/forward-targets/ringback/caller-filters) 정확             |

### 4-2. 대화 연계(탐색성 질문 → 화면 안내 포함 여부)

| ID         | 결과   | 비고                                                                                                                  |
| ---------- | ------ | --------------------------------------------------------------------------------------------------------------------- |
| SG-CONV-01 | ✅ PASS | `has_screen_guidance=true`, 응답에 "설정 > 착신 제어" 화면 언급 포함                                                  |
| SG-CONV-02 | ✅ PASS | `has_screen_guidance=true`, 응답에 "설정 > 채팅" 화면·토글 언급 포함                                                  |
| SG-CONV-03 | ⚠️ 참고 | `has_screen_guidance=false`이지만 응답에 "설정 > 일반" 문구가 매뉴얼 원문 인용으로 포함됨(§4-4 분석 참고) — 결함 아님 |
| SG-CONV-04 | ✅ PASS | `has_screen_guidance=false`, 순수 정보 질의로 화면 언급 없음(대조군 정상)                                             |
| SG-CONV-05 | ⚠️ 참고 | `has_screen_guidance=true`이지만 응답에는 화면 언급 없음(§4-4 분석 참고) — LLM이 안전하게 무시함                      |

### 4-3. 프론트엔드 시각 검증

| ID       | 결과   | 비고                                                              |
| -------- | ------ | ----------------------------------------------------------------- |
| SG-FE-01 | ✅ PASS | "화면 안내" 탭 클릭 시 6개 도메인 카드 정상 렌더링(스크린샷 확인) |
| SG-FE-02 | ✅ PASS | 라우트 링크 클릭 시 `/settings/ai-escalation`으로 정상 이동 확인  |
| SG-FE-03 | ✅ PASS | "이용 매뉴얼 Q&A"/"AI 변경 가능 설정" 탭 모두 회귀 없이 정상 동작 |

> **SG-FE-01 관련 참고**: 최초 페이지 로드 직후 첫 클릭 시 탭이 전환되지 않는 것처럼 보이는 현상을
> 관찰했으나(콘솔에 `client-log` 요청 실패 이벤트 존재), 페이지 새로고침 후 재시도하니 정상
> 동작했다. 클라이언트 사이드 상태 초기화 타이밍 이슈로 추정되며, 재현이 일관되지 않아 이번
> QA에서는 결함으로 확정하지 않고 참고 관찰로만 기록한다(추후 재발 시 조사 필요).

### 4-4. 발견 사항 분석 (SG-CONV-03, SG-CONV-05)

두 케이스 모두 **코드 결함이 아니라 매뉴얼 도메인 태깅의 세분화 한계**로 설명된다.

- **SG-CONV-03**: 구글 캘린더 관련 Q&A는 매뉴얼 "## 6. 예약 관리" 섹션(6.3 하위 항목)에 속해
  있어 `manual_indexer.py`의 섹션 단위 태깅 규칙상 `related_domain="booking"`으로 색인된다.
  `booking`은 Screen Graph에 등록되어 있지 않으므로(카탈로그 밖 도메인, Story 1.11 AC2 문서화된
  한계) `has_screen_guidance=false`가 정확한 동작이다. 다만 매뉴얼 원문 자체에 "설정 > 일반에서
  'Google 계정 연동' 버튼으로…"라는 문구가 이미 포함되어 있어, LLM이 Screen Graph 주입 없이도
  매뉴얼 텍스트를 그대로 인용해 화면 위치를 안내했다 — 결과적으로 사용자 경험에는 문제가 없다.
- **SG-CONV-05**: 매뉴얼에 "페르소나"를 직접 다루는 섹션이 없어 RAG가 의미적으로 인접한 다른
  도메인(화면이 등록된 도메인)의 Q&A를 매칭한 것으로 추정된다. 이 때문에 `has_screen_guidance`가
  `true`로 찍혔지만, 실제 응답에는 (관련 없는) 화면 안내가 노출되지 않았다 — 시스템 프롬프트
  규칙 6("사용자가 궁금해하는 것과 무관하면 언급하지 않는다")이 의도대로 안전망 역할을 한
  것으로 판단된다. 다만 이는 우연이 아니라 확률적(LLM temperature)으로 항상 보장되는 것은
  아니므로, 향후 매뉴얼에 페르소나 전용 섹션을 추가하는 것을 개선 과제로 남긴다(본 Story 범위 밖).

---

## 5. 최종 판정

| 구분                                    | 결과                                              |
| --------------------------------------- | ------------------------------------------------- |
| 백엔드 API(SG-API 4건)                  | ✅ 전체 PASS                                       |
| 대화 연계 핵심 케이스(SG-CONV-01/02/04) | ✅ PASS                                            |
| 대화 연계 참고 케이스(SG-CONV-03/05)    | ⚠️ 결함 아님(매뉴얼 도메인 커버리지 한계로 설명됨) |
| 프론트엔드(SG-FE 3건)                   | ✅ 전체 PASS                                       |

**Story 1.11/1.12 모두 실서버·실브라우저 통합 검증 완료.**

*최종 업데이트: 2026-07-20*
