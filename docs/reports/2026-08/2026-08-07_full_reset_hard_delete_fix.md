# "전체 삭제해도 REST-API 실행 설정이 남는" 진짜 버그 수정 (하드 삭제로 전환)

- 작성일: 2026-08-07
- 버전: v1.0
- 관련 문서: [2026-08-07_unified_kb_view_reset_and_upload_visibility_fix.md](2026-08-07_unified_kb_view_reset_and_upload_visibility_fix.md)

## 1. 배경 — 사용자 재확인

사용자가 지난 세션의 "삭제해도 설정/화면 안내가 그대로다"에 대한 답변(카탈로그/화면 안내는
시스템 공통 정의라 삭제 대상이 아님)에는 동의하면서도, **"전체 삭제 시에도 삭제가 안 되는건
버그 맞다"**고 다시 명확히 지적했다. 이 시스템의 목적을 재확인:

> "REST-API를 이용하는 어떤 시스템이라도 이 시스템을 통해서 정보데이터만 업로드하면 REST-API
> 조작과 안내를 할 수 있음" — 테넌트마다 별개로 업로드된 데이터를 기반으로 remote에 있는
> 다른 REST-API가 실행되면서 안내해줘야 하므로, 테넌트별 REST-API 실행 설정까지 완전히
> 초기화되어야 한다.

## 2. 실제 조사(DB 직접 쿼리로 확인, 추측 없음)

`data/booking.db`를 직접 쿼리한 결과:

- `knowledge_documents` 테이블에 owner=9001로 **9개 활성 문서**(개발/QA 과정에서 쌓인
  `sample_manual_qa`/`test-md-cli-*`/`sample_openapi_demo` 등 테스트 잔재)가 남아있었다.
- ChromaDB에는 "localhost" 문자열을 포함한 청크가 없었고 owner 누락(orphan) 청크도 없었다
  (모든 청크가 정상적으로 owner 메타데이터를 갖고 있음) — 사용자가 언급한 "owner 개념 없이
  개발된 데이터"는 현재 ChromaDB 레벨에는 없었다.
- 하지만 **`reset_knowledge_base()`(어제 신설한 "전체 삭제" 기능)가 `knowledge_documents`
  테이블을 소프트 삭제(`is_active=0`)만 하고, 연결된 `knowledge_document_endpoints`(REST-API
  엔드포인트 메타: method/path/parameters/request_body)와 `tool_execution_log`(승인 이력·
  실제 실행 이력·Undo 이력)는 전혀 지우지 않는** 것을 코드로 확인했다 — 이것이 실제 버그였다.
  DB에 남아있는 `knowledge_document_endpoints` 13건이 이를 실증한다.

## 3. 근본 원인

"전체 삭제"를 소프트 삭제(비활성화)로 구현한 것은 개별 문서 삭제(`delete_document`)의 기존
관례를 그대로 따른 결과였다. 그러나 "전체 삭제"는 **QA를 위한 완전 초기화(clean slate)** 용도로
설계된 기능이라 소프트 삭제로는 부적합했다 — REST-API 실행에 필요한 `base_url`/인증/승인된
쓰기 메서드/엔드포인트 메타 정보가 DB에 그대로 남아있으면, "이 테넌트의 원격 시스템 실행 설정이
완전히 초기화됐다"고 보장할 수 없다.

## 4. 수정

### `src/common/knowledge_documents_db.py`

- 신규 `purge_all_documents(owner) -> {"deleted_documents", "deleted_endpoints",
  "deleted_execution_logs"}` — owner의 `knowledge_documents`를 **하드 삭제**하고, 연결된
  `knowledge_document_endpoints`(document_id 기준)와 `tool_execution_log`(owner 기준)도 함께
  하드 삭제한다. 이미 소프트 삭제(`is_active=0`)된 과거 문서도 완전히 지운다("전체 삭제"는
  이력 보존이 아니라 진짜 초기화이므로).
- 기존 `deactivate_all_documents()`는 더 이상 호출되지 않지만 하위 호환을 위해 남겨둠
  (docstring에 deprecated 명시).

### `src/ai_voicebot/self_service/knowledge_documents.py`

- `reset_knowledge_base()`가 `db.deactivate_all_documents()` 대신 `db.purge_all_documents()`를
  호출하도록 변경, 반환값에 `deleted_documents`/`deleted_endpoints`/`deleted_execution_logs`
  포함.

### API/프론트엔드

- `KnowledgeBaseResetResponse`(백엔드 Pydantic 모델 + 프론트 TS 인터페이스) 필드를
  `deactivated_documents` → `deleted_documents`/`deleted_endpoints`/`deleted_execution_logs`로
  갱신.

## 5. 검증

- 신규 단위테스트 3건(`TestPurgeAllDocuments`): 문서+엔드포인트+실행이력 하드 삭제, 다른
  owner 데이터 무영향, 이미 비활성화된 문서까지 완전 삭제 확인.
- `test_knowledge_documents_db.py` 전체(24건), `tests_new/unit -k "knowledge_document or
  knowledge_base or self_service or dynamic_api"` 재실행 — 기존 무관 사전 결함 1건 제외 전부
  통과.
- **실서버 확인**: 실행 중인 서버(구 코드가 이미 메모리에 로드된 상태)로 `DELETE
  /api/knowledge-base/documents?owner=9001`을 호출해, 개발 과정에서 쌓여있던 9001 테넌트의
  실제 테스트 잔재 9건(`sample_manual_qa`/`test-md-cli-*` 등)과 청크 229건을 정리 완료(구
  버전 소프트 삭제 경로로 확인, `total_chunks=0`으로 인벤토리 재확인됨). **신규 하드 삭제
  코드 자체의 실서버 검증은 프로세스 재시작이 필요** — 사용자 승인 후 재시작 시 진행.

## 6. 잔여 작업 / 다음 단계

- 서버 재시작 후: `DELETE /api/knowledge-base/documents?owner=<owner>` 호출 시 응답에
  `deleted_documents`/`deleted_endpoints`/`deleted_execution_logs`가 정확히 채워지는지,
  DB에 해당 owner의 `knowledge_documents`/`knowledge_document_endpoints`/`tool_execution_log`
  행이 실제로 0건이 되는지 재검증 필요.
- 사용자가 언급한 "REST-API가 원격(remote)에 있는 다른 시스템을 대상으로 실행되는" 멀티테넌트
  격리 자체는 `dynamic_api_tool.py::build_execution_context()`가 이미 `document_id+owner`로
  엄격히 스코프하고 있음을 코드로 재확인(Story 1.51에서 이미 owner 강제 스코프 적용) — 이번
  발견된 버그는 "실행 격리"가 아니라 "삭제 완전성"의 문제였다.

*최종 업데이트: 2026-08-07*
