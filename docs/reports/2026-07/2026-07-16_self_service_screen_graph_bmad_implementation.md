# 셀프서비스 AI 도우미 — 화면 안내형 응대(Screen Graph) BMAD 전체 사이클 구현

**작성일**: 2026-07-16
**상태**: 문서 산출 + 구현 완료 (단위 테스트/TypeScript 검증 완료, 실서버 통합 검증은 다음 서버 재시작 시 수행 권장)
**관련 문서**:
- [SELF_SERVICE_SCREEN_GUIDED_GRAPHRAG_RESEARCH.md](../../design/SELF_SERVICE_SCREEN_GUIDED_GRAPHRAG_RESEARCH.md) (전일 리서치)
- [self-service-ai-assistant-prd.md](../../product/self-service-ai-assistant-prd.md) FR13/FR14, Story 1.11/1.12
- [self-service-ai-assistant-architecture.md](../../architecture/self-service-ai-assistant-architecture.md)
- [1.11.screen-graph-guided-assistance.story.md](../../stories/1.11.screen-graph-guided-assistance.story.md)
- [1.12.screen-graph-frontend-viewer.story.md](../../stories/1.12.screen-graph-frontend-viewer.story.md)

---

## 1. 요청 요약

전일 리서치(GraphRAG Brownfield 검토)에서 도출한 "경량 Screen Graph" 방향을 **요구사항 검토 →
문서 산출(PRD/아키텍처/Story) → 구현**까지 BMAD 전체 프로세스로 진행했다. 추가로 사용자가
"frontend에서도 지식정보를 볼 수 있도록" 요구사항을 넣어달라고 요청해, Screen Graph 데이터를
프론트엔드에서 읽기 전용으로 열람하는 기능(Story 1.12)도 함께 반영했다.

---

## 2. BMAD 문서 산출물

| 단계     | 문서                                                                                                       | 변경 내용                                                                                                                          |
| -------- | ---------------------------------------------------------------------------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------- |
| PRD      | [self-service-ai-assistant-prd.md](../../product/self-service-ai-assistant-prd.md)                         | FR13(화면 안내형 응대), FR14(Screen Graph 프론트엔드 열람) 추가, Epic Story 목록에 1.11/1.12 추가, Epic 개수 10→12 갱신            |
| 아키텍처 | [self-service-ai-assistant-architecture.md](../../architecture/self-service-ai-assistant-architecture.md)  | 신규 컴포넌트 `self_service/screen_graph.py` 추가(Responsibility/Integration Points/Key Interfaces/Dependencies), Source Tree 갱신 |
| Story    | [1.11.screen-graph-guided-assistance.story.md](../../stories/1.11.screen-graph-guided-assistance.story.md) | 백엔드 Screen Graph 구축 + self_service_agent 연계                                                                                 |
| Story    | [1.12.screen-graph-frontend-viewer.story.md](../../stories/1.12.screen-graph-frontend-viewer.story.md)     | 프론트엔드 열람(화면 안내 탭)                                                                                                      |
| 인덱스   | `docs/INDEX.md`                                                                                            | Story 1.11/1.12 행 추가, Story 1.10 상태를 Done으로 정정                                                                           |

---

## 3. 구현 내용

### 3-1. `src/ai_voicebot/self_service/screen_graph.py` (신규)

- `ScreenEntry`/`UiFieldSpec` 데이터클래스 + `_register_screen()` 정적 레지스트리(`settings_catalog.py`와 동일 패턴)
- 실제 프론트엔드 코드(`frontend/app/settings/*`)를 직접 조사해 등록:
  - `ai-escalation`: 라디오 3종(hitl/transfer/none)
  - `chat-relay`: 토글 + 텍스트
  - `call-control`: 내부 탭 5개(rules/schedules/forward-targets/ringback/caller-filters)
  - `general`/`integrations`: 둘 다 `/settings/general`로 수렴(실제 리다이렉트 확인)
  - `contacts`: `/contacts`(메인 내비, `/settings/contacts`는 리다이렉트)
  - **`persona`는 의도적으로 미등록**(전용 설정 폼이 없음 — 실제 조사로 확인, 존재하지 않는 화면을 안내하는 환각 방지)
- `get_screen_for_domain()`, `describe_screen_for_conversation()`(best-effort, 예외 없음), `list_all_screens()`

### 3-2. `src/ai_voicebot/langgraph/nodes/self_service_agent.py` (수정)

- `_format_screen_guidance()` 신규 — RAG 검색 결과 문서의 `related_domain` 메타데이터로 Screen Graph 조회(GraphRAG의 "Local Search" 패턴 재현: 매뉴얼 RAG → 도메인 → 화면 1-hop 확장)
- 시스템 프롬프트에 `[화면 안내 정보]` 섹션 추가, 응답 규칙 6번 신설("화면 정보 있으면 탐색성 응답에 포함, 없으면 언급 금지")
- `_TOOL_USAGE_INSTRUCTION`의 규칙 번호를 7→8로 재조정(신설 규칙과 번호 충돌 방지)
- `call_data_record`에 `self_service_screen_graph_hit` 이벤트 로깅

### 3-3. `src/api/routers/settings_ai_assistant.py` (수정)

- `GET /api/settings/ai-assistant/screen-graph` 신규 — `screen_graph.list_all_screens()`를 JSON으로 반환

### 3-4. `frontend/app/settings/ai-assistant/docs/page.tsx` (수정)

- 기존 탭(`qa`/`catalog`)에 **"화면 안내"(`screen`) 탭 신규 추가**
- 도메인별 카드: 라우트 링크(클릭 시 실제 설정 화면 이동) + 설명 + UI 요소 목록
- 화면 정보가 없는 도메인 안내 문구 포함

---

## 4. 검증 결과

| 항목                                            | 결과                                                             |
| ----------------------------------------------- | ---------------------------------------------------------------- |
| `test_self_service_screen_graph.py` (신규 13건) | ✅ PASS                                                           |
| 전체 `tests_new/unit/test_ai_voicebot` 회귀     | ✅ PASS (실패 없음)                                               |
| 시스템 프롬프트 템플릿 포맷팅                   | ✅ 정상(길이 2683자, 신규 플레이스홀더 모두 치환됨)               |
| 앱 임포트 (`src.api.main`)                      | ✅ 정상                                                           |
| 신규 API 라우트 등록 확인                       | ✅ `/api/settings/ai-assistant/screen-graph` 포함 4개 라우트 확인 |
| 프론트엔드 TypeScript 오류                      | ✅ 없음                                                           |

---

## 5. 향후 권장 사항

- **실서버 재검증 미실시**: `self_service_agent.py` 변경은 서버 프로세스 재시작 후에만 반영된다.
  다음 서버 재시작 시 아래를 확인 권장:
  - 탐색성 발화(예: "AI가 모르는 질문 받으면 전화하게 해줄 수 있어?")에 화면 안내 문구가
    자연스럽게 포함되는지(`call_data_record`의 `self_service_screen_graph_hit` 이벤트로 확인)
  - 프론트엔드 `/settings/ai-assistant/docs` "화면 안내" 탭이 정상 렌더링되는지
- **매뉴얼-화면 연결 확장**: 현재 매뉴얼 `related_domain`은 섹션 단위(도메인 단위)로만 연결되어
  있어, 향후 필드 단위(예: "escalation_mode" 질문 → 해당 라디오 버튼만 강조)로 세분화하면 안내
  정확도를 더 높일 수 있다(향후 Story 후보, 본 범위 밖).

*최종 업데이트: 2026-07-16*
