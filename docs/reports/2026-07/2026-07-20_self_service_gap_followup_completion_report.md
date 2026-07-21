# 셀프서비스 AI 도우미 — 갭 점검 후속 조치 완료 보고서 (자동설정 확장 검토·온보딩 KB 체크·통화 이력 NLQ)

**작성일**: 2026-07-20
**관련 문서**:
- [2026-07-20_self_service_auto_config_expansion_feasibility.md](2026-07-20_self_service_auto_config_expansion_feasibility.md) (항목 1 리포트)
- [2026-07-20_self_service_onboarding_kb_check_direction.md](2026-07-20_self_service_onboarding_kb_check_direction.md) (항목 2 리포트)
- [1.13.call-history-nlq.story.md](../../stories/1.13.call-history-nlq.story.md)
- [self-service-ai-assistant-call-history-nlq-qa-plan.md](../../qa/self-service-ai-assistant-call-history-nlq-qa-plan.md)
- [self-service-ai-assistant-brief.md](../../product/self-service-ai-assistant-brief.md) (v0.3)
- [self-service-ai-assistant-prd.md](../../product/self-service-ai-assistant-prd.md) (v0.4)
- [self-service-ai-assistant-architecture.md](../../architecture/self-service-ai-assistant-architecture.md) (v0.3)

---

## 1. 요청 요약

2026-07-20 앞선 점검 리포트에서 발견한 3가지 갭에 대해 사용자가 다음과 같이 지시했다.

1. **자동설정 범위 축소(7개 중 3개만 쓰기 지원)**: 수행 가능한 방향으로 검토·리포트 (코드 변경 없이 분석만)
2. **온보딩 체크리스트 지식베이스 업로드 항목 누락**: 구현 방향 리포트 (코드 변경 없이 분석만)
3. **통계 자연어 질의 고도화(통화 이력 NLQ)**: 이번 반복 범위로 승격 — 문서 선(先) 수정 후 BMAD 전체 프로세스(설계→Story→구현→QA)로 실제 구현

## 2. 항목 1·2 — 분석 리포트 (코드 변경 없음)

| 항목 | 리포트 | 핵심 결론 |
| --- | --- | --- |
| 자동설정 확장 | [feasibility 리포트](2026-07-20_self_service_auto_config_expansion_feasibility.md) | call-control/contacts는 ID 기반 CRUD가 이미 있어 "목록형 도메인" 모델 확장으로 가능(별도 후속 Story 필요). integrations는 "연동 해제"만 즉시 추가 가능. general은 백엔드에 쓰기 자체가 없어 구조적으로 불가능 — PRD에 이유를 명시하는 것을 권장. |
| 온보딩 KB 체크 | [구현 방향 리포트](2026-07-20_self_service_onboarding_kb_check_direction.md) | `chromadb_client.get_vector_db().get(where={"owner":..., "doc_type":"knowledge"})`로 KB 존재 여부를 확인하는 판정 함수를 `onboarding.py`에 추가하는 방향(카탈로그 도메인으로 등록하지 않고 온보딩 전용 예외 처리) — 소규모 후속 Story로 권장. |

두 항목 모두 **이번 세션에서는 코드를 변경하지 않았다** — 사용자 확인 후 별도 착수 필요.

## 3. 항목 3 — 통화 이력 자연어 질의(Call History NLQ) 구현 완료

### 3-1. BMAD 문서 갱신 (구현 전 선행 작업)

| 문서 | 버전 | 변경 내용 |
| --- | --- | --- |
| [self-service-ai-assistant-brief.md](../../product/self-service-ai-assistant-brief.md) | 0.2 → 0.3 | "통계/모니터링 자연어 질의"를 Out of Scope → MVP Core Feature로 승격, 소스 테이블에 #5 행 추가 |
| [self-service-ai-assistant-prd.md](../../product/self-service-ai-assistant-prd.md) | 0.2 → 0.4 | FR15(3가지 질의 유형)·NFR5(RAG 아닌 구조화 검색 설계 결정) 신설, Epic을 12→13개 Story로 갱신, Story 1.13 섹션 추가 |
| [self-service-ai-assistant-architecture.md](../../architecture/self-service-ai-assistant-architecture.md) | 0.2 → 0.3 | `self_service/call_history_query.py` 컴포넌트 신설(Responsibility/Integration Points/Key Interfaces/Dependencies), Source Tree 갱신, 미응답 판정 근거 기록 |
| [1.13.call-history-nlq.story.md](../../stories/1.13.call-history-nlq.story.md) | 신규 | Task 0(미응답 판정 조사) 포함 5개 Task, AC/IV 정의 |

### 3-2. 설계 결정: RAG가 아닌 구조화 검색/집계 채택

사용자는 "AI가 RAG를 통해 통화 이력에 접근"한다고 요청했으나, 코드 조사 결과 통화 이력은 이미
SQLite `call_records`(`src/common/call_record_db.py`)에 요약 텍스트(`call_summary`)까지 구조화되어
저장되어 있었다. Story 1.11(Screen Graph)이 Full GraphRAG 대신 경량 정적 레지스트리를 택한 것과
동일한 원칙("코드베이스 규모에 맞지 않는 과잉 인프라 도입 지양")에 따라, **새 벡터 임베딩
파이프라인을 구축하지 않고** 기존 `call_record_db.get_call_records_page(owner=...)`를 재사용하는
구조화 검색/집계(Tool-calling)로 구현했다. 이 결정은 PRD NFR5와 아키텍처 문서에 명시적으로
기록했다.

### 3-3. 구현 내용

- **`src/ai_voicebot/self_service/call_history_query.py`** (신규): `search_call_history_by_keyword`,
  `get_top_caller`, `get_missed_calls_today` 3개 함수. 미응답(missed) 판정은
  `sip_endpoint.py::_cleanup_call()` 코드 추적 결과 `has_recording=False AND is_ai_handled=False`를
  프록시로 확정(Task 0).
- **`src/ai_voicebot/self_service/tools.py`** (수정): 3개 LangChain Tool 래퍼 추가,
  `SELF_SERVICE_TOOLS` 4개 → 7개로 확장.
- **`src/ai_voicebot/langgraph/nodes/self_service_agent.py`** (수정): 시스템 프롬프트에
  규칙 12(키워드 검색)/13(최다 발신자 집계)/14(오늘자 미응답 조회) 추가.
- **owner 스코프 보안(IV3)**: 기존 `_run_self_service_tool_loop()`의 "owner는 LLM이 무엇을 보내든
  세션 owner로 강제 오버라이드" 패턴이 이미 모든 Tool에 공통 적용되므로, 신규 Tool도 별도
  코드 없이 동일한 테넌트 격리 보호를 받는다.

### 3-4. 테스트 결과

```
tests_new/unit/test_ai_voicebot/test_self_service_call_history_query.py  → 23 passed (신규)
tests_new/unit/test_ai_voicebot + tests_new/unit/test_events            → 252 passed (전체 회귀, 실패 없음)
```

기존 테스트 3건(`test_self_service_auto_config.py`/`test_self_service_settings_tool.py`/
`test_self_service_stats.py`)이 `SELF_SERVICE_TOOLS` 개수를 4로 하드코딩하고 있어 7로 갱신했다
(회귀 아님, 의도된 갱신).

### 3-5. QA 및 실서버 검증 보류 사유

QA 진행 중 API 서버(포트 8000)가 **본 Story 코드 작성 이전(13:39)에 이미 기동 중**임을 확인했다
(`Get-Process python`으로 프로세스 시작 시각 확인). `.github/copilot-instructions.md`의 "포트
충돌 프로세스 자동 실행 금지" 원칙에 따라 서버 재시작 여부를 사용자에게 직접 확인했고,
**사용자가 재시작을 보류**하기로 결정했다. 따라서:

- 단위 테스트 수준 검증은 **완료**(23건 신규 + 252건 전체 회귀 PASS).
- 실서버 tool-calling 통합 검증(실제 대화에서 3개 Tool이 호출되는지)은 **다음 서버 재시작 시**
  수행해야 한다 — 구체적 시나리오는
  [QA 계획서](../../qa/self-service-ai-assistant-call-history-nlq-qa-plan.md) §3-1에 기록해 두었다.

## 4. 문서 인덱스 갱신

- `docs/SYSTEM_OVERVIEW.md` §4.11에 통화 이력 NLQ 처리 흐름·기능 설명 추가, mermaid 다이어그램에
  `history` 노드 반영.
- `docs/INDEX.md`의 Dev Stories 표에 Story 1.13 행 추가, QA 섹션에 신규 QA 계획서 링크 추가.

## 5. 남은 작업(후속 세션 권장)

1. **다음 서버 재시작 시**: [Call History NLQ QA 계획서](../../qa/self-service-ai-assistant-call-history-nlq-qa-plan.md) §3-1 시나리오(CH-CONV-01~04, CH-API-01) 실행 및 QA Results 갱신.
2. **항목 1(자동설정 확장)**: 사용자 승인 시 call-control/contacts "목록형 도메인 자동설정" 후속 Story 착수.
3. **항목 2(온보딩 KB 체크)**: 사용자 승인 시 `onboarding.py`에 지식베이스 체크 함수 추가(소규모 작업).

*최종 업데이트: 2026-07-20*
