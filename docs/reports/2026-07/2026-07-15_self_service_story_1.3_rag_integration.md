# Story 1.3 (셀프서비스 매뉴얼 RAG 연동) Task 2~5 구현 완료 보고서

**작성일**: 2026-07-15
**관련 문서**: [1.3.self-service-manual-rag.story.md](../../stories/1.3.self-service-manual-rag.story.md), [self-service-manual-content.md](../../product/self-service-manual-content.md), [self-service-ai-assistant-architecture.md](../../architecture/self-service-ai-assistant-architecture.md)
**상태**: 완료 (Story Status → Review)

## 1. 문제 요약

Story 1.3의 Task 1(매뉴얼 콘텐츠 작성)은 기존에 완료되었으나, 실제 RAG 색인·검색·에이전트 통합·테스트(Task 2~5)는 구현되지 않은 상태였다. 목표는 셀프서비스 세션(관리자 본인 통화)에서 매뉴얼 Q&A를 RAG로 검색해 정확한 안내를 제공하되, 테넌트 고객용 `knowledge` doc_type과 완전히 격리하는 것이다.

## 2. 근본 제약 사항 (Story 사전 조사에서 확인)

`RAGEngine.__init__()`의 `doc_type_allowlist`는 생성자 시점에만 고정되고 `.search()` 호출마다 바꿀 수 없다(`src/ai_voicebot/ai_pipeline/rag_engine.py`). 메인 파이프라인의 RAG 엔진 인스턴스는 테넌트 질의 전체에 공용으로 쓰이므로, 셀프서비스 전용 격리를 위해서는 **별도의 RAGEngine 인스턴스**가 반드시 필요했다.

## 3. 구현 내용

### 3.1 Task 2 — ChromaDB 색인 파이프라인 (`src/ai_voicebot/self_service/manual_indexer.py`, 신규)

- `parse_manual_qa_pairs()`: `docs/product/self-service-manual-content.md`의 `**Q: ...**\nA: ...` 형식을 정규식으로 파싱(멀티라인 답변·목록 포함, 다음 질문/`---` 구분선 전까지 캡처). 실제 파일에서 52개 Q&A 쌍 추출 확인.
- `index_self_service_manual(owner, vector_db, embedder, force=False)`: 기존 `knowledge_service.add_knowledge()`를 재사용해 `doc_type="self_service_manual"`, `category="question"`, `source="seed"` 메타데이터로 색인.
  - **Q+A 결합 저장**: `add_knowledge()`는 `text` 파라미터만 임베딩/저장하고 `answer`는 별도 저장하지 않는다는 점을 코드 확인 후, 기존 `manual_to_faq_extractor.py`의 `"Q: ...\nA: ..."` 결합 패턴을 그대로 재사용하여 검색 결과(`Document.text`)에 질문+답변이 모두 포함되도록 함.
  - **owner 단위 색인**: `RAGEngine.search()`가 항상 `owner_filter`를 적용하므로(AC2), 매뉴얼 콘텐츠는 테넌트 공통이지만 테넌트별로 색인해야 검색된다. `list_knowledge(doc_type=...)`로 기존 색인 여부를 확인해 멱등성을 보장(중복 색인 방지, `force=True`로 재색인 가능).

### 3.2 Task 3 — 전용 RAGEngine 싱글턴 (`src/ai_voicebot/self_service/rag.py`, 신규)

- `get_self_service_rag_engine()`: `call_context.get_embedder()`/`get_vector_db()`로 메인 파이프라인과 embedder/vector_db를 공유하되, `doc_type_allowlist=["self_service_manual"]`로 고정된 별도 `RAGEngine` 인스턴스를 생성.
- 프로세스 전역 모듈 레벨 캐시(지연 초기화 싱글턴) 적용 — 매 통화·매 턴마다 재생성하지 않음. `id(embedder)`/`id(vector_db)` 비교로 캐시 무효화 조건을 판단해 인스턴스 교체(재시작 등) 시에도 안전.

### 3.3 Task 4 — 폴백 처리 (`src/ai_voicebot/langgraph/nodes/self_service_agent.py`, 수정)

- `self_service_agent_node`에 RAG 검색 단계 추가: 전용 RAGEngine으로 `owner_filter` + `intent="question"` 검색 후 결과를 시스템 프롬프트의 `[매뉴얼 참고 정보]` 섹션에 주입.
- 폴백 문구는 `generate_response.py`의 `RESPONSE_UNKNOWN_NEEDS_FOLLOWUP` 상수를 그대로 재사용(신규 문구 생성 안 함).
- **설계 판단**: `self_service_agent_node`는 `classify_intent`를 거치지 않고 self_service 세션에서 바로 진입하므로(Story 1.2 설계), 메인 파이프라인처럼 `intent=="question" and rag_results==[]` 조건으로 LLM 호출 자체를 생략하는 하드 게이트는 사용할 수 없었다. 대신 RAG 컨텍스트를 프롬프트에 주입하고, "참고 정보가 없고 구체적 질문이면 고정 문구, 단순 인사·잡담이면 자연스럽게 대화"하도록 LLM에 지시했다 — 이는 `RESPONSE_SYSTEM_PROMPT`가 이미 사용 중인 방식과 동일한 메커니즘이며, Story 1.2에서 확립된 인사말 자연스러운 응대를 회귀시키지 않기 위한 필수 조정이다.
- HITL은 트리거하지 않음(`needs_follow_up` 등 HITL 관련 필드를 세팅하지 않음) — 셀프서비스는 관리자 세션이므로 고객 응대 개입 큐에 넣지 않는다는 AC3 요구사항 반영.

### 3.4 Task 5 — 테스트 (`tests_new/unit/test_ai_voicebot/test_self_service_manual_rag.py`, 신규)

17개 테스트 신규 작성(파서 4, 색인 파이프라인 6, RAGEngine 싱글턴 4, 에이전트 통합 4 — 일부 중복 그룹):

- 매뉴얼 Q&A 파싱(멀티라인 답변, 섹션 경계 처리, 빈 입력)
- 색인 owner/doc_type 격리, 멱등성(재색인 스킵/강제 재색인), 테넌트 간 격리
- RAGEngine 싱글턴: embedder/vector_db 부재 시 None 반환, `doc_type_allowlist` 고정 확인, 인스턴스 캐싱, 인스턴스 교체 시 재생성
- 에이전트 노드: RAG 히트 시 컨텍스트 주입 확인, RAG 미스 시 폴백 문구 지시 확인(HITL 필드 미설정 확인), RAG 검색 예외 시 안전한 폴백, RAG 엔진 부재 시 회귀 없음(Story 1.2 동작 유지)

## 4. 검증 결과

```
python -m pytest tests_new/unit/test_ai_voicebot -q --no-cov
→ 50 passed (기존 33 + 신규 17)

python -m pytest tests_new/unit/test_ai_voicebot tests_new/unit/test_events -q --no-cov
→ 전체 통과, 회귀 없음
```

테스트 작성 중 `lambda: object()`를 캐싱 테스트에 그대로 사용하면 매 호출마다 새 객체가 생성되어 캐시가 항상 무효화되는 버그를 발견 — 고정 객체 참조로 수정 후 통과 확인(구현 코드 결함 아님, 테스트 코드 결함).

## 5. 변경 파일

- `src/ai_voicebot/self_service/manual_indexer.py` (신규)
- `src/ai_voicebot/self_service/rag.py` (신규)
- `src/ai_voicebot/langgraph/nodes/self_service_agent.py` (수정 — RAG 검색 통합)
- `tests_new/unit/test_ai_voicebot/test_self_service_manual_rag.py` (신규, 17 tests)
- `docs/stories/1.3.self-service-manual-rag.story.md` (Task 2~5 체크, Dev Agent Record/Change Log 갱신, Status → Review)

## 6. 후속 작업

- Story 1.3은 색인 파이프라인만 제공하며, 실제 테넌트별 색인 실행(운영 스크립트/API 트리거)은 범위 밖 — 필요 시 별도 운영 태스크로 `index_self_service_manual()` 호출 지점을 마련해야 한다.
- Story 1.4(설정 카탈로그) 착수 예정.

---
*최종 업데이트: 2026-07-15*
