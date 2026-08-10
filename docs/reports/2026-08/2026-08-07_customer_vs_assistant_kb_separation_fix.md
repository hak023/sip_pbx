# 고객 지식 베이스 ↔ 도우미 지식 베이스 혼재 버그 수정

- 작성일: 2026-08-07
- 버전: v1.0
- 상태: 완료(코드 수정), 실서버 IV 잔여
- 관련 문서: [self-service-ai-assistant-architecture.md](../../architecture/self-service-ai-assistant-architecture.md),
  [self-service-ai-assistant-prd.md](../../product/self-service-ai-assistant-prd.md)

## 1. 문제 요약

사용자가 1001 테넌트의 `/knowledge`(프론트 "고객 지식 베이스" 화면)에서 목록을 조회했을 때,
`/settings/ai-assistant/docs`(도우미 지식 베이스)에 업로드한 매뉴얼/문서 항목이 함께 섞여
보이는 현상을 발견했다. 두 화면은 서로 다른 기능(①통화·문자 응대용 고객 FAQ/페르소나,
②AI 셀프서비스 도우미의 매뉴얼·업로드 문서 RAG)을 다루므로 분리되어야 한다.

## 2. 근본 원인

- 두 기능은 **같은 ChromaDB 컬렉션(`knowledge`, `KNOWLEDGE_COLLECTION`)을 공유**하고, `doc_type`
  메타데이터로만 구분된다.
  - 고객 지식 베이스: `doc_type="knowledge"`(기본값), `"faq"` 등 — `src/ai_voicebot/knowledge/knowledge_service.py::add_knowledge()`
  - 도우미 지식 베이스(매뉴얼 md): `doc_type="self_service_manual"` — `src/ai_voicebot/self_service/manual_indexer.py`
  - 도우미 지식 베이스(Story 1.26 업로드 문서, PDF/OpenAPI): `doc_type="knowledge_document"` —
    `src/ai_voicebot/self_service/knowledge_documents.py`
- `GET /api/knowledge`(`src/api/routers/knowledge_api.py::knowledge_list`)는 `doc_type` 쿼리
  파라미터가 있을 때만 필터링했고, **없으면 전체 doc_type을 그대로 반환**했다.
- 프론트엔드 `/knowledge` 페이지(`frontend/app/knowledge/page.tsx::fetchList`)는 `owner`/`category`/
  `source`만 쿼리에 실어 보내고 `doc_type`은 전혀 지정하지 않는다.
- 결과적으로 셀프서비스 도우미 쪽에서 업로드한 매뉴얼·문서 청크가 "고객 지식 베이스" 목록에
  그대로 섞여 노출됨 — 실제 저장 구조가 공유되는 걸 몰랐다면 재현이 쉬운 설계상 함정이었다.

## 3. 수정 내용

`src/api/routers/knowledge_api.py`:

- `ASSISTANT_KB_DOC_TYPES = frozenset({"self_service_manual", "knowledge_document"})` 상수 신설
  (도우미 전용 doc_type 화이트리스트).
- `knowledge_list()`에서 `doc_type` 쿼리가 **명시적으로 지정되지 않은 경우**, 이 목록에 속한
  항목을 결과에서 기본 제외하도록 필터 로직 변경. `doc_type`을 명시적으로 지정하면(예:
  `?doc_type=self_service_manual`) 기존처럼 해당 값만 필터링되어 디버깅 목적의 조회는 그대로
  가능.
- 모듈 상단 docstring에 두 지식베이스가 컬렉션을 공유하되 doc_type으로만 구분된다는 사실과,
  도우미 지식 베이스는 `/api/knowledge-base/documents`,
  `/api/settings/ai-assistant/knowledge-base/inventory`로 조회해야 함을 명시.

**의도적으로 코드 변경을 하지 않은 부분**: ChromaDB 컬렉션 자체를 분리하는 것(물리적 저장소
분리)은 기존 색인·검색 경로(`RAGEngine.doc_type_allowlist`, `self_service/rag.py`)가 이미
`doc_type` 메타데이터 필터만으로 안정적으로 동작 중이므로, 이번 수정 범위(프론트 노출 문제)에
비해 리스크가 큰 리팩터링이다. 컬렉션 물리 분리는 후속 검토 대상으로 남긴다(§5 참고).

## 4. 검증

- 정적 검증: `get_errors`로 구문 오류 없음 확인.
- **잔여**: 실서버 IV — 서버 재시작 후 1001 테넌트로 `GET /api/knowledge?owner=1001` 호출해
  `self_service_manual`/`knowledge_document` doc_type 항목이 결과에서 사라졌는지, 반대로
  `?owner=1001&doc_type=self_service_manual`로는 여전히 조회되는지 확인 필요(사용자 승인 후
  서버 재시작 시 진행).

## 5. 후속 권장 사항(이번 수정 범위 밖)

1. **프론트엔드 라벨/문구 보강**: `/knowledge` 페이지 상단에 "이 화면은 고객 응대용 지식
   베이스이며, AI 도우미 매뉴얼은 [설정 > AI 도우미 > 지식베이스]에서 관리합니다" 안내 문구
   추가 권장(사용자 혼란 방지, 이번 세션 범위 밖이라 미착수).
2. **DELETE /api/knowledge/{doc_id}**: 이번 수정은 GET 목록만 필터링했다 — 삭제 API가 doc_id를
   그대로 받는 구조라 영향은 없지만, 프론트에서 도우미 문서 doc_id를 실수로 고객 KB 화면에서
   삭제 시도할 경로가 원천적으로 사라졌으므로 안전성은 오히려 개선됨.
3. **컬렉션 물리 분리 검토**: 장기적으로 두 지식베이스의 임베딩 모델/청크 전략이 달라질
   가능성을 고려하면 별도 컬렉션(`assistant_knowledge` 등)으로 분리하는 것이 더 근본적인 해법 —
   PRD/architecture 증분(FR 신설) 후 별도 Story로 진행 권장.

*최종 업데이트: 2026-08-07*
