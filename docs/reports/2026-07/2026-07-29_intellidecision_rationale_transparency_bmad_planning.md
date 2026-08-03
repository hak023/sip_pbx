# IntelliDecision 판단 근거 투명성 — BMAD 절차 계획 수립 (Story 1.20~1.22)

**작성일**: 2026-07-29
**작업 유형**: BMAD 절차(PRD→architecture→story) 계획 수립(코드 구현은 아직 착수하지 않음)

## 배경

사용자가 이전 리서치([SELF_SERVICE_CORE_FEATURES_EXTERNAL_RESEARCH.md](../../design/SELF_SERVICE_CORE_FEATURES_EXTERNAL_RESEARCH.md)
§8)에서 제안한 "IntelliDecision 판단 근거 로깅" 개선을 승인하고, 추가로 "투명성에 근거한
기능이므로 프론트엔드까지 반영해 유저가 확인할 수 있어야 한다"는 요구사항을 확정했다. 이에
따라 BMAD 절차(요청→PRD→architecture→story)로 구현·QA 계획을 수립했다.

## 산출물

### 1. PRD 갱신
- [self-service-ai-assistant-prd.md](../../product/self-service-ai-assistant-prd.md) 버전
  1.0→1.1: **FR30**(IntelliDecision 판단 근거 투명성 — 캡처·저장·프론트엔드 열람 요구사항,
  지연 영향 금지·개인정보 최소 노출 명시) + **NFR6**(지연·신뢰성 예산) 신설, Change Log 갱신.

### 2. Architecture 갱신
- [self-service-ai-assistant-architecture.md](../../architecture/self-service-ai-assistant-architecture.md)
  버전 0.9→0.10: "IntelliDecision 판단 근거 투명성 설계" 섹션 신설 — 3개 캡처 방식 후보
  (구조화 출력 병행 / 센티널 태그 후행 파싱 / 경량 별도 분류 호출)와 각각의 장단점·리스크,
  저장소·API·프론트엔드 컴포넌트 개요, Non-Goal(원본 발화 전문 미저장) 명시. 실제 방식 선택은
  Story 1.20의 스파이크 결과로 확정하도록 설계만 남기고 구현은 보류.

### 3. Story 3건 신규 작성 (모두 Status=Draft, 순차 의존)
| Story                                                                         | 제목                                    | 핵심 내용                                                                                      |
| ----------------------------------------------------------------------------- | --------------------------------------- | ---------------------------------------------------------------------------------------------- |
| [1.20](../../stories/1.20.intellidecision-rationale-capture-spike.story.md)   | 판단 근거 캡처 방식 설계 결정(스파이크) | 3개 후보 방식을 실제 API로 검증 후 1개 선택(Story 4.1 "설계 결정 우선" 패턴 재사용)            |
| [1.21](../../stories/1.21.intellidecision-rationale-logging-and-api.story.md) | 캡처·로깅·조회 API 구현                 | 백엔드 캡처 로직(실패해도 응답 흐름 무영향)·신규 테이블·`GET /api/self-service/decision-log`   |
| [1.22](../../stories/1.22.intellidecision-rationale-frontend-viewer.story.md) | 프론트엔드 투명성 UI                    | `settings/ai-assistant/docs` "AI 의사결정 로직" 탭 확장, 신규 npm 의존성 없이 기존 패턴 재사용 |

### 4. QA 계획
- [self-service-ai-assistant-master-qa.md](../../qa/self-service-ai-assistant-master-qa.md)
  버전 1.4→1.5: **Branch Q**(계획 단계, 미실행) 신설 — 검증 목표 5개(캡처가 응답 흐름을
  지연/차단하지 않는가, 유형 코드 일치, 캡처 실패 강제 재현 시 정상 응답, owner 격리,
  프론트엔드 렌더링·개인정보 미노출) 및 Story별 실행 계획.

### 5. INDEX.md 반영
- Dev Stories 표에 1.20~1.22 행 추가, PRD 요약 라인의 Story 범위를 1.1~1.22로 갱신.

## 설계상 핵심 결정 사항

1. **판단 로직 자체는 건드리지 않는다**: 기존 검증된 프롬프트 산문(`_SELF_SERVICE_SYSTEM_
   PROMPT_TEMPLATE`)은 그대로 유지 — 순수 "관측·로깅 추가"만 한다(Story 7.1 Smart Turn 관측
   로깅과 동일 원칙).
2. **캡처 실패가 사용자 응답에 영향을 주면 안 된다**(FR30 명시) — 예외 흡수 필수.
3. **캡처 방식은 추측하지 않고 스파이크로 실측 결정**한다(Story 1.14의 "재시도로 증상만
   가리지 말고 실제 페이로드를 직접 검증하라" 원칙 재적용) — 특히 센티널 태그 방식은 2026-07-29
   근본 수정한 "conversation_history 오염발 메타 JSON 유출" 결함과 동일 클래스 리스크가 있어
   신중한 검증이 필요함을 architecture 문서에 명시.
4. **개인정보 최소 노출**: 원본 발화 전문은 저장·표시하지 않고 근거 요약만 다룬다.

## 다음 단계

Story 1.20(스파이크) 착수 승인이 필요하다. 착수 시 실제 Gemini API 호출로 스파이크 스크립트를
실행하며, 이는 코드 변경(스크립트 신규 파일)이 발생하므로 별도 승인 절차를 거친다.

*최종 업데이트: 2026-07-29*
