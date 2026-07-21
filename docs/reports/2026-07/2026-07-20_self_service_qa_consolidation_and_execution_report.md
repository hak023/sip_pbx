# 셀프서비스 AI 도우미 — QA 문서 통합 및 통합 실행 완료 보고서

**작성일**: 2026-07-20
**관련 문서**:
- [self-service-ai-assistant-master-qa.md](../../qa/self-service-ai-assistant-master-qa.md) (신규 통합 QA 문서, 본 세션 핵심 산출물)
- [self-service-ai-assistant-call-history-nlq-qa-plan.md](../../qa/self-service-ai-assistant-call-history-nlq-qa-plan.md) (실서버 검증 완료로 갱신)
- [1.13.call-history-nlq.story.md](../../stories/1.13.call-history-nlq.story.md) (Status → Done 확정)

---

## 1. 요청 요약

1. 이전 세션에서 사용자가 보류했던 Story 1.13(통화 이력 NLQ) 실서버 QA를 서버 재시작 후 수행.
2. 셀프서비스 관련 QA 문서 4개(BMAD 전체 항목서, IntelliDecision, Screen Graph, Call History NLQ)를
   하나로 통합. STT 이후~TTS 이전 구간을 실제로 재실행하며, 기능 분기별 케이스(사전조건·입력문구·
   기대문구·출력문구)와 다중 턴 연계 시나리오를 포함한 QA 문서로 정리.

## 2. 수행 내용

### 2-1. Story 1.13 실서버 QA (보류분 재개)

- 서버 재시작(15:55) 확인 후, QA owner `9003`에 결정론적 통화 데이터 4건을 시드
  (`scripts/self_service_qa_seed_call_history.py`, 신규 재사용 가능 스크립트).
- CH-CONV-01~04 전체 실서버 실행 → **전체 PASS**(키워드 검색 2건 정확 매칭, Top 발신자 집계 정확,
  오늘자 미응답 통화 정확 조회, 미지원 기간 폴백 정상).
- 원시 로그(`call_data_record`) 교차검증으로 API 응답 조작 가능성 배제.
- Story 1.13 Status를 최종 **Done**으로 확정.

### 2-2. QA 문서 통합

- 신규 [self-service-ai-assistant-master-qa.md](../../qa/self-service-ai-assistant-master-qa.md) 작성 —
  Story 1.1~1.13 전체를 **Branch A~K**(기능 분기)로 재구성.
- 기존 4개 QA 문서는 삭제하지 않고 각 파일 상단에 "본 문서는 master-qa.md로 통합됨" 배너만 추가해
  이력 자료로 보존.
- 총 **34개 케이스**를 서버 재시작 후 실제로 재실행(신규 작성이 아니라 실제 API 호출로 검증):
  - Branch A(감지)·B(RAG)·C(카탈로그 조회)·D(온보딩)·E(통계)·F(자동설정)·H(IntelliDecision 대표
    케이스)·I(Screen Graph)·J(통화이력 NLQ)·K(다중 Tool 연계, 7턴)
  - **Branch K는 이번에 신규로 설계한 "단순 질의응답을 넘어서는 다중 턴 연계 시나리오"** — 인사
    →설정조회→자동설정 확인/실행→통계→통화이력 검색→미응답 조회까지 7턴이 한 세션에서 끊김
    없이 이어지는지 검증(전체 PASS, 4개 서로 다른 Tool 그룹이 정상 연동됨을 확인).

### 2-3. 통합 실행 중 신규 발견 결함 2건

| 결함                                | 내용                                                                                                                                                                                              | 상태                                                                  |
| ----------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | --------------------------------------------------------------------- |
| ① 자동설정 boolean "켜기" 방향 실패 | chat-relay 등 boolean 필드를 true로 바꾸는 2턴 확인→실행 흐름에서 LLM이 빈 응답을 반환해 안전망 문구로 대체되고 실제 변경은 안 됨. "끄기(false)" 방향은 항상 정상. 3/3 재현(owner·세션·문구 무관) | 🔴 미해결, 근본 원인 미확정 — 다음 세션에서 서버 stdout 로그 확인 필요 |
| ② 도움말 페이지 탭 클릭 자동화 실패 | `/settings/ai-assistant/docs`의 탭 버튼 클릭이 Playwright에서 지속적으로 "stable 대기 타임아웃". WebSocket 재연결 실패 반복이 원인으로 추정                                                       | 🔴 미해결, 실사용자 영향 범위 불명확 — 수동 확인 권장                  |

두 결함 모두 **이번 세션에서는 수정하지 않고 발견·재현·근거 기록까지만 수행**했다(사용자가 QA
수행과 문서화를 요청했을 뿐 수정은 요청하지 않았으므로, 임의로 코드를 변경하지 않고 명확히
보고하는 쪽을 선택했다).

## 3. 종합 결과

34개 케이스 중 32개 PASS(94%), 2개 FAIL(신규 발견 결함, 위 §2-3). 핵심 기능(감지, RAG, 설정
조회, 온보딩, 통계, 통화이력 NLQ, 다중 턴 연계)은 모두 정상 동작을 재확인했다.

## 4. 문서/메모리 갱신

- `docs/INDEX.md`: Story 1.13 상태를 `Done`으로 정리, QA 섹션에 master-qa.md를 최상단 항목으로 추가.
- `docs/SYSTEM_OVERVIEW.md` §4.11: 통합 QA 문서 링크 추가.
- `docs/stories/1.13.call-history-nlq.story.md`: QA Results를 실서버 검증 완료로 갱신.
- 리포지토리 메모리(`/memories/repo/sip_pbx_notes.md`): QA 통합 사실 + 2건의 신규 결함 + PowerShell
  일괄 QA 실행 기법(및 `$Input` 파라미터명 함정) 기록.

## 5. 후속 권장 사항

1. **결함① 근본 원인 조사**: 다음 서버 세션에서 `logger.warning`/`error` 레벨 애플리케이션 로그를
   직접 확인하며 Gemini FC 응답이 비어있는 원인을 특정해야 한다.
2. **결함② 조사**: WebSocket 재연결 로직의 백오프 정책 점검 및 실사용자 수동 클릭 테스트로 실제
   영향 여부 확인.
3. 향후 신규 Story의 QA는 신규 문서를 만들지 않고 `self-service-ai-assistant-master-qa.md`에
   Branch를 추가하는 방식으로 진행한다.

*최종 업데이트: 2026-07-20*
