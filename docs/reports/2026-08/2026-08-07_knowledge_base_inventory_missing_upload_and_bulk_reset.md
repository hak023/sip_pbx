# 업로드한 지식이 "지식베이스 현황"에 안 보이는 버그 + 기존 데이터 전체 삭제 기능 추가

- 작성일: 2026-08-07
- 버전: v1.0
- 관련 문서: [self-service-ai-assistant-e2e-manual-driven-qa-plan.md](../../qa/self-service-ai-assistant-e2e-manual-driven-qa-plan.md)

## 1. 증상 ①: 업로드한 문서가 "지식베이스 현황"에 반영되지 않음

1001 테넌트로 QA 픽스처 매뉴얼(`clothing-store-assistant-manual.md`)을 업로드했으나 "지식 업로드"
탭의 "지식베이스 현황"에서 확인되지 않는다는 보고.

### 로그로 확인한 사실

`logs/app.log`에서 업로드 자체는 정상 처리됨을 확인:

```json
{"timestamp": "2026-08-07T11:14:00.103", "event": "knowledge_document_registered",
 "document_id": "c82fc8b304d640618bf7ba1e8912f4bd", "indexed_chunks": 12,
 "owner": "1001", "source_type": "markdown"}
```

`data/booking.db`의 `knowledge_documents` 테이블도 `is_active=1`로 정상 저장되어 있었다(직접 쿼리로
확인). 즉 업로드·색인·DB 저장까지 전부 성공했는데, 조회 화면에만 반영되지 않는 상황이었다.

### 근본 원인

`src/ai_voicebot/self_service/knowledge_base_inventory.py::summarize_inventory()`가
**`doc_type == "self_service_manual"`인 청크만 집계**하도록 구현되어 있었다. 그런데 Story 1.26
업로드 문서(마크다운/PDF/OpenAPI)는 `knowledge_documents.py::KNOWLEDGE_DOCUMENT_DOC_TYPE =
"knowledge_document"`로 색인된다 — 즉 애초에 이 집계 함수가 세는 대상 자체가 아니었다.
`GET /api/settings/ai-assistant/knowledge-base/inventory`가 `ks.get_all_knowledge()`로 owner의
모든 doc_type을 가져온 뒤 `summarize_inventory()`에 넘기지만, 이 함수 내부 필터가 `knowledge_document`
를 건너뛰어 "지식베이스 현황"의 `total_chunks`/`domain_distribution`/`last_indexed_at`(상단
요약 카드)에 전혀 반영되지 않았다. (참고: 같은 응답의 `auto_assembled` 하위 섹션은 애초부터
`knowledge_document`를 올바르게 집계하고 있었으나, 사용자가 주로 보는 상단 요약 카드는 그대로였다.)

### 수정

`knowledge_base_inventory.py`에서 필터 대상을 `_ASSISTANT_KB_DOC_TYPES =
frozenset({"self_service_manual", "knowledge_document"})`로 확장 — 매뉴얼 자동색인과 Story 1.26
업로드 문서를 모두 "도우미 지식 베이스" 집계에 포함시켰다(고객 지식 베이스 doc_type인
`knowledge`/`faq`는 여전히 제외). 응답의 `doc_type` 필드는 `"knowledge_document,self_service_manual"`
로 두 값을 함께 표기하도록 변경.

## 2. 증상 ②: 업로드 이력이 없는 기존 데이터는 삭제할 방법이 없음

사용자 지적: "업로드를 안 하고 기존에 있던 데이터라 삭제가 안 된다." `DELETE
/api/knowledge-base/documents/{document_id}`는 `knowledge_documents` 테이블에 레코드가 있는
문서(Story 1.26 업로드분)만 대상으로 하므로, Story 1.3/2.8의 매뉴얼 자동색인처럼 레코드 없이
ChromaDB에만 존재하는 청크는 개별 삭제 UI로 지울 수 없었다.

### 추가 기능

- 백엔드: `src/ai_voicebot/self_service/knowledge_documents.py::reset_knowledge_base(owner, vector_db)`
  신설 — owner의 `self_service_manual` + `knowledge_document` 청크를 ChromaDB에서 일괄 삭제하고
  (`vector_db.get(where=...)`로 대상 id 조회 후 `vector_db.delete(ids=...)`), `knowledge_documents`
  테이블의 활성 레코드도 전부 비활성화(`knowledge_documents_db.py::deactivate_all_documents()` 신설).
- API: `DELETE /api/knowledge-base/documents?owner=<owner>`(문서 단건 삭제와 경로가 겹치지 않도록
  `{document_id}` 없는 루트 경로에 신설) — `{"ok", "deleted_chunks", "deactivated_documents"}` 반환.
- 프론트엔드: "지식베이스 현황" 탭에 "도우미 지식 베이스 전체 삭제" 버튼 추가(`window.confirm`
  확인 다이얼로그 후 호출, 성공 시 목록/현황 상태와 로드 완료 표시(ref)를 초기화해 즉시 재조회).

## 3. 검증

- 신규/수정 단위테스트: `test_self_service_knowledge_base_inventory.py`에
  `test_summarize_inventory_includes_uploaded_knowledge_document_chunks` 추가, 기존
  `doc_type` 어서션 갱신 — 6건 전체 통과.
- `tests_new/unit -k "self_service or dynamic_api or intellidecision or knowledge_document or
  knowledge_base"` 재실행 — 기존 사전 결함 1건(`test_knowledge_documents_service.py::
  test_register_markdown_document_uses_manual_adapter`, 이번 세션에서 건드리지 않은 파일이며
  `git diff`로 무관함을 확인) 제외 전부 통과.
- `npx tsc --noEmit`/`npx eslint` 0에러.
- **잔여**: 실서버로 QA 픽스처 문서를 재업로드해 "지식베이스 현황" 카드에 반영되는지, "전체
  삭제" 버튼이 실제로 매뉴얼 자동색인분까지 지우는지 실물 검증은 다음 세션(서버 재시작 필요).

*최종 업데이트: 2026-08-07*
