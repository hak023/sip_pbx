# 셀프서비스 AI 도우미 — IntelliDecision 정책 레지스트리 + Screen Graph 다중 홉 지식 그래프 구현 (Story 1.18)

**작성일**: 2026-07-28
**작업 유형**: 신규 기능 구현(코드)
**관련 문서**:
- [SELF_SERVICE_INTELLIDECISION_KNOWLEDGE_STRUCTURING_RESEARCH.md](../../design/SELF_SERVICE_INTELLIDECISION_KNOWLEDGE_STRUCTURING_RESEARCH.md) — 본 구현이 따르는 축 A/B 리서치
- [self-service-ai-assistant-prd.md](../../product/self-service-ai-assistant-prd.md) FR28
- [1.18.intellidecision-policy-registry-and-knowledge-graph.story.md](../../stories/1.18.intellidecision-policy-registry-and-knowledge-graph.story.md)

## 1. 요약

사용자가 2026-07-27 리서치 문서 §6 제안 우선순위를 승인("세운 계획인 괜찮은것같아. 제안대로
진행해줘")하면서, 축 B(Screen Graph 다중 홉 확장) 구현 시 "AI 응답 생성 시 연결된 홉으로
확장되어 IntelliDecision이 스마트하게 판단되도록" 반영해 달라고 추가 요청했다. 이에 따라
축 A(정책을 데이터로)와 축 B(다중 홉 그래프)를 함께 구현했다.

## 2. 구현 내용

### 축 A — `intellidecision_policy.py`(신규)

- `settings_catalog.py`와 동일한 정적 레지스트리 패턴으로 IntelliDecision 유형 A~I(9종)을
  `IntentTypeSpec`(code/name/summary/trigger_examples/requires_tool/requires_writable_domain/
  related_types) 데이터로 등록.
- `list_intent_types()`/`get_intent_type(code)`/`applicable_types_for_domain(domain, writable=)`
  3개 공개 함수 제공. 마지막 함수가 이번 구현의 핵심 — `requires_writable_domain=True`인
  유형(B/D/E/G)을 실제로 쓰기 가능한 도메인에서만 반환한다.
- **의도적 범위 축소**: 기존 `_SELF_SERVICE_SYSTEM_PROMPT_TEMPLATE`/`_TOOL_USAGE_INSTRUCTION`
  프롬프트 산문 자체는 그대로 유지했다(이미 여러 Story를 거쳐 실서버로 검증된 응대 품질이므로,
  레지스트리 도입과 동시에 프롬프트 렌더링 방식까지 바꾸면 회귀 위험이 커짐 — CR 원칙). 이번
  레지스트리는 축 B의 데이터 소스 및 향후 축 C(시각화)의 조회 소스로 우선 확립했다.

### 축 B — `knowledge_graph.py`(신규) + 사용자 지시 반영(스마트 판단 연동)

- `traverse(domain, max_hops=2)`: 1-hop(`screen_graph.get_screen_for_domain`, 기존 재사용)에
  이어 2-hop(`settings_catalog.domain_writable_fields()` → `intellidecision_policy.
  applicable_types_for_domain()`)까지 확장.
- `format_decision_hint(domain)`: 2-hop 결과를 "(참고: 이 설정은 조회·변경·되돌리기가 모두
  가능합니다)" / "(참고: 이 설정은 조회만 가능하며 변경·되돌리기는 지원되지 않습니다)" 한국어
  한 줄 힌트로 조립.
- **`self_service_agent.py::_format_screen_guidance()` 연동(사용자 요청의 핵심)**: 기존
  1-hop 화면 안내 문구(`describe_screen_for_conversation`) 뒤에 `format_decision_hint()`
  결과를 추가로 붙여 `{screen_guidance_section}` 프롬프트 변수에 주입. 이로써 RAG 히트가
  가져온 도메인에 대해 "화면이 어디 있는지"뿐 아니라 "이 도메인에서 실제로 변경·되돌리기가
  가능한지"까지 LLM에게 명시적으로 드러나, 쓰기 불가능한 도메인(`contacts`/`general`)에서
  유형 B(실행)·E(되돌리기)를 잘못 안내하는 환각을 프롬프트 차원에서 구조적으로 줄인다
  (Anthropic "Building Effective Agents"의 투명성 원칙 — 판단 근거를 데이터로 드러냄).

## 3. Non-Goals(명시적 배제, 리서치 §5와 동일)

- Full GraphRAG 패키지·그래프 DB·LLM 자동 엔터티 추출 — 이번에도 채택하지 않음.
- IntelliDecision을 결정 트리로 강제 전환 — 최종 판단은 여전히 LLM의 자연어 맥락 이해에 맡김,
  레지스트리는 "판단 기준 데이터"이지 "판단 로직 대체"가 아님.
- 기존 프롬프트 산문의 완전한 데이터 기반 자동 렌더링 — 후속 Story로 이연.

## 3-1. (같은 세션, 추가 진행) 축 C-1 — 정적 표 시각화 탭

사용자의 "진행해줘" 지시로 리서치 §4 축 C-1(저비용 정적 표 시각화)까지 이어서 구현했다.

- **백엔드**: `GET /api/settings/ai-assistant/intellidecision-policy` 신규 엔드포인트
  (`src/api/routers/settings_ai_assistant.py`) — `intellidecision_policy.list_intent_types()`를
  그대로 직렬화해 반환하는 읽기 전용 조회(응답을 바꿔도 실제 응대 로직에는 영향 없음).
- **프론트엔드**: `frontend/app/settings/ai-assistant/docs/page.tsx`에 기존 4개 탭
  (이용 매뉴얼 Q&A/AI 변경 가능 설정/화면 안내/설정 관리) 옆에 **"AI 의사결정 로직"** 탭을
  추가(Story 1.12의 Screen Graph 열람 탭과 동일한 카드 UI 패턴 재사용). 각 유형 카드에 코드/이름/
  요약/트리거 예시/"Tool 필요"·"변경·되돌리기 필요(쓰기 가능 도메인만)" 배지·관련 유형을 표시한다.
- 신규 단위 테스트(`test_settings_ai_assistant_intellidecision_policy.py`, 3건) 포함 전체
  self_service/settings_ai_assistant 관련 테스트 재실행 결과 0 FAILED.
- **정적 검증 추가 실시**: `npx tsc --noEmit`(frontend) 통과, `npx eslint app/settings/
  ai-assistant/docs/page.tsx` 통과. 백엔드는 `settings_ai_assistant.router.routes`를 직접
  임포트해 `/api/settings/ai-assistant/intellidecision-policy`가 라우트 목록에 정상 등록됨을
  확인(서버 기동 없이 라우터 레벨 검증). 브라우저 수동 클릭 확인은 미실시(개발 서버 필요).

## 4. 검증 결과

- 신규 단위 테스트 2개 파일 작성:
  - `tests_new/unit/test_ai_voicebot/test_self_service_intellidecision_policy.py`(5건)
  - `tests_new/unit/test_ai_voicebot/test_self_service_knowledge_graph.py`(6건)
  - 최초 1건(`test_format_decision_hint_unknown_domain_returns_empty`) 실패 발견 → 원인:
    `format_decision_hint()`가 "화면 미등록 + 적용 가능 유형 없음"을 조건으로 빈 문자열을
    반환했는데, `applicable_types_for_domain()`은 미등록 도메인에서도 writable 불필요 유형
    (A/C/F/I)을 항상 반환하므로 조건이 항상 거짓이었음 → "화면이 등록되어 있는가"만으로
    조건을 단순화해 수정, 재검증 통과.
- `tests_new/unit -k "self_service"`(사전 결함 있는 rag_engine/text_embedder 2개 모듈 제외)
  전체 32건(신규 11건 포함) 0 FAILED.
- 전체 `tests_new/unit` 회귀(위 2개 모듈 제외) 실행 결과, `test_sip_core/test_call_session.py`
  12건이 실패했으나 `CallSession.__init__() missing 1 required positional argument: 'state'`
  로 본 작업과 무관한 SIP Core 테스트/구현 시그니처 불일치(git status로 본 세션에서 관련 파일을
  전혀 수정하지 않았음을 확인) — 사전 존재 결함으로 판정, 이번 범위 밖.
- 실서버 통합 검증(coding-standards.md §6)은 미실시 — 프롬프트에 새 텍스트 라인만 추가하는
  변경이라 리스크는 낮으나, 다음 서버 재시작 시 RAG 히트가 있는 실제 대화로 `screen_guidance_section`에
  결정 힌트가 정상 노출되는지 확인 권장.

## 4-1. (같은 세션, 사용자가 서버 재시작 후) 실서버 검증 완료

- **프로세스 최신 코드 반영 확인**: `Get-Process python`으로 서버 시작 시각(09:34)이 변경 파일
  최종 수정 시각(09:26~09:32)보다 늦음을 확인(coding-standards.md §6 방법론).
- **신규 API 실서버 호출**: `GET /api/settings/ai-assistant/intellidecision-policy`를 포트 8000에
  직접 호출해 유형 A~I 9종이 정확한 필드로 반환됨을 확인.
- **프론트엔드 브라우저 확인**: `/settings/ai-assistant/docs` 접속 → "AI 의사결정 로직" 탭 클릭 →
  9개 유형 카드가 코드/이름/요약/트리거 예시/Tool 필요·변경·되돌리기 필요 배지·관련 유형과 함께
  정상 렌더링됨을 스크린샷으로 확인.
- **실제 대화 통합 검증**: `POST /api/self-service/test/converse`(owner=9001)로 2개 시나리오 실행 —
  ① 쓰기 가능 도메인(chat-relay) 조회 → `self_service_screen_graph_hit`(has_screen_guidance=true)
  이벤트 발생 + `_get_self_service_settings` Tool 정상 호출 + 실제 값 기반 정확한 응답 확인.
  ② 읽기 전용 성격 도메인(contacts) 질의 → 오류 없이 정상 처리(과도한 추측 응답 없음).
  두 경우 모두 예외 없이 정상 종료, `logs/app.log`에 `knowledge_graph`/`screen_guidance_failed`
  관련 경고 로그가 전혀 없음을 확인(신규 코드 경로가 예외 없이 동작).

## 5. 문서 갱신

- `docs/product/self-service-ai-assistant-prd.md`: FR28 추가, 버전 0.8→0.9, changelog 행 추가.
- `docs/stories/1.18.intellidecision-policy-registry-and-knowledge-graph.story.md` 신규 작성(Done).
- `docs/INDEX.md`: Story 1.18 행 추가.

## 6. 다음 단계 제안

1. 축 A의 "프롬프트 산문 완전 데이터 기반 렌더링"(번호 재조정 함정의 근본 해결)은 이번 범위에서
   의도적으로 보류 — 별도 Story로 착수 여부를 사용자와 논의. **→ (같은 날 이어서) Story 1.19로
   완료됨**: `docs/reports/2026-07/2026-07-28_intellidecision_prompt_auto_rendering.md` 참고.
2. 축 C-2(그래프 시각화)는 신규 의존성 없이 순수 SVG 고정 원형 배치로 저비용 구현 완료
   (§7 참고) — react-force-graph 등 신규 패키지 도입은 결국 필요 없었다(노드 9개뿐이라
   force-directed 레이아웃이 과설계로 판단됨).

## 7. (같은 세션, 사용자 승인 후 이어서 진행) 축 C-2 — 그래프 시각화

- **신규 의존성 없이 구현**: `frontend/app/settings/ai-assistant/docs/page.tsx`에
  `IntentTypeGraph`(신규 순수 SVG 컴포넌트) 추가. 노드가 9개뿐이라 `react-force-graph` 등
  라이브러리 도입 없이 삼각함수로 원형 배치(고정 좌표)하고, `related_types` 관계를 중복 없는
  선(edge)으로 연결했다.
- "AI 의사결정 로직" 탭에 **"표 보기"/"그래프로 보기"** 토글을 추가해 기존 카드 목록(축 C-1)과
  새 그래프 뷰를 전환할 수 있게 했다. 노드 색상으로 `requires_writable_domain` 여부(안내
  전용=인디고 / 변경·되돌리기 필요=호박색)를 구분해 한눈에 구분 가능하게 했다.
- **정적 검증**: `npx tsc --noEmit`, `npx eslint app/settings/ai-assistant/docs/page.tsx` 모두
  통과. 백엔드 변경 없음(기존 `/intellidecision-policy` 응답을 그대로 재사용)이라 백엔드
  회귀 테스트도 재실행해 224건 그대로 통과 확인.
- **브라우저 자동 클릭 검증은 실패**: Playwright `click_element`가 "AI 의사결정 로직" 탭 버튼에서
  반복적으로 타임아웃됨(ref/selector 방식 모두 동일). 이는 신규 코드의 결함이 아니라 이미
  2026-07-20 세션에서 발견·기록된 **앱 전역 WebSocket(포트 8001) 재연결 루프로 인한 자동화
  클릭 불안정 이슈**(`/dashboard` 새로고침 버튼 등 무관한 다른 페이지에서도 100% 재현되는
  전역 이슈, self_service 범위 밖)와 동일 증상 — 실사용자 클릭에는 영향 없을 가능성이 높다고
  과거에도 판정된 바 있다. 따라서 이번에는 정적 타입/린트 검증으로 대체하고 범위를 마무리했다.

*최종 업데이트: 2026-07-28*
