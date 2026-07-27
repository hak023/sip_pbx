# 능력 레지스트리(제안 2) 축소 설계 구현 — 완료 리포트

**작성일**: 2026-07-23
**작업 유형**: 신규 기능 구현(리서치 제안 2, 축소 권장안 채택) — 셀프서비스 AI 도우미 Story 1.17
**관련 문서**: [1.17.capability-registry-rag-plan.story.md](../../stories/1.17.capability-registry-rag-plan.story.md),
[2026-07-23_capability_registry_decision_options.md](2026-07-23_capability_registry_decision_options.md)(권장안 근거),
[self-service-ai-assistant-prd.md](../../product/self-service-ai-assistant-prd.md)(FR27)

---

## 1. 배경

직전 세션의 [결정 지원 리포트](2026-07-23_capability_registry_decision_options.md)에서, 원래
계획한 "완전 신규 능력 레지스트리 모듈+API+5번째 프론트엔드 탭"이 이미 존재하는
`/catalog`·`/screen-graph` API와 상당 부분 중복됨을 확인하고 축소된 설계를 권장했다. 사용자가
"응 진행해줘"로 승인함에 따라 이 축소 설계를 그대로 구현했다.

## 2. 반영 내용

### 2.1 백엔드: 능력 섹션 동적 생성

- `self_service_agent.py`에 신규 함수 `_format_capability_section()` 추가:
  - `settings_catalog.list_domains()`/`domain_writable_fields()`로 조회/쓰기 가능 도메인을
    실시간 조회(도메인명 → 한국어 라벨 매핑은 `_DOMAIN_LABELS`, 프론트엔드 `DOMAIN_LABEL`과
    동일 값 사용).
  - Tool 기반 능력(통계/통화이력/온보딩/실행취소)은 정적 매핑(`_TOOL_CAPABILITY_EXAMPLES`)으로
    관리.
  - 원시 데이터를 그대로 프롬프트에 넣지 않고, 기존 `_format_rag_context()` 등과 동일한
    스타일의 한국어 텍스트 블록으로 조립.
  - 예외/빈 도메인 시 Story 1.15의 정적 문구(`_STATIC_CAPABILITY_FALLBACK`)로 즉시 폴백.
- 신규 캐시 계층은 두지 않았다(결정 지원 리포트 권장 — 이미 Epic 2 캐시 위의 순수 인메모리
  연산이라 추가 캐시가 무효화 버그 리스크만 늘림).
- `_SELF_SERVICE_SYSTEM_PROMPT_TEMPLATE`에 `[현재 이용 가능한 능력 목록]` 섹션과
  `{capability_section}` 변수를 추가하고, 유형 C(항목 7) 규칙이 하드코딩 목록 대신 이 섹션을
  참조하도록 수정. `.format()` 호출부에 `capability_section=_format_capability_section()` 추가.

### 2.2 매뉴얼 §9 축소

`docs/product/self-service-manual-content.md` §9의 "무엇을 물어볼 수 있나요" Q&A를 목록
나열에서 "직접 물어보라"는 유도 문구로 축소(버전 1.2 → 1.3). 능력 열거의 단일 진실 소스를
프롬프트 동적 생성(§2.1)으로 완전히 이전해, 이번처럼 매뉴얼이 다시 stale해질 여지를 구조적으로
제거했다.

### 2.3 프론트엔드: 정적 안내 카드 추가

`frontend/app/settings/ai-assistant/docs/page.tsx`의 기존 `qa` 탭 상단에 "전화·문자로 이렇게도
도와드릴 수 있어요" 정적 안내 카드를 추가했다(Tool 기반 능력 4종 예시). **신규 API·신규 탭을
만들지 않고** 기존 페이지 구조만 확장했다(결정 지원 리포트 권장안 — 도메인 기반 능력은 이미
`catalog`/`screen` 탭에 노출되어 있어 중복 회피).

### 2.4 문서 반영

- **PRD**: FR27(능력 레지스트리 기반 유형 C 동적화) 신설, 버전 0.7 → 0.8, Post-MVP 섹션을
  "제안 1·2 모두 반영 완료" 상태로 갱신.
- **Architecture**: "능력 레지스트리 기반 유형 C 동적화 (Story 1.17)" 섹션 신설, 버전 0.6 → 0.7.
- **Story**: `docs/stories/1.17.capability-registry-rag-plan.story.md` Status를 Draft → Done으로
  전환, 실제 구현 기준 AC/Tasks/QA Results 추가.

### 2.5 문서 오탈자 수정 (부수 발견)

이전 세션 편집분에서 일부 한글 텍스트 깨짐(mojibake: "섮여"→"섞여", "묬어서"→"묶어서",
"몰뜿그려"→"뭉뚱그려", "즐시"→"즉시", "캠시"→"캐시", "그칙"→"규칙")과 영문 오탈자("raund"→"round")를
PRD·architecture 문서에서 발견해 함께 수정했다.

## 3. 검증 결과

### 3.1 단위 테스트

```
python -m pytest tests_new/unit/test_ai_voicebot/ -k self_service -q --no-cov
```

self_service 관련 전체 단위 테스트(242건, 신규 `test_self_service_capability_section.py` 5건
포함) **전부 통과**. 신규 테스트는 다음을 검증한다:
- 조회 가능 도메인 전체와 쓰기 가능 도메인만 별도 라인에 정확히 반영됨(라벨 매핑 포함).
- Tool 기반 능력(통계/통화이력/실행취소 등) 문구가 항상 포함됨.
- 도메인이 0개이거나 `settings_catalog.list_domains()`가 예외를 던지면 정적 폴백 문자열로
  정확히 되돌아감.
- 미등록(라벨 없는) 도메인은 존재하지 않는 라벨을 지어내지 않고 원본 식별자를 그대로 노출.

### 3.2 실서버 검증 (미실시 — 다음 세션 예정)

결정 지원 리포트 §3에서 필수로 지정한 "하드코딩 버전 대비 동적 버전 유형 C 응답 품질 A/B
비교"는 서버 재시작이 필요해 이번 세션에서 진행하지 못했다. 프론트엔드 신규 카드의 시각적
확인도 함께 다음 세션에서 진행할 것을 권장한다.

## 4. 결론

리서치 제안 2를 원래 계획보다 축소된 설계(신규 레지스트리 모듈/API/탭 없이 기존 인프라
재사용)로 구현 완료했다. 이로써 리서치 리포트에서 제안한 제안 1(Story 1.16)·제안 2(Story
1.17)가 모두 반영되었다. 단위 회귀는 전부 통과했으며, 실서버 A/B 검증만 다음 세션으로
이월한다.

---
*최종 업데이트: 2026-07-23*
