# 업로드 문서가 도우미 RAG 검색에서 누락되는 치명적 버그 수정 + 프론트 UX 보강

- 작성일: 2026-08-07
- 버전: v1.0
- 관련 문서: [2026-08-07_knowledge_base_inventory_missing_upload_and_bulk_reset.md](2026-08-07_knowledge_base_inventory_missing_upload_and_bulk_reset.md),
  [customer_vs_assistant_kb_separation_fix.md](2026-08-07_customer_vs_assistant_kb_separation_fix.md)

## 1. 증상: "업로드한 게 도우미 지식베이스에서 검색되지 않는다"

앞선 세션에서 "지식베이스 현황" 표시 버그(집계 누락)를 고쳤음에도, 실제 대화(smsdock)로 물어보면
업로드한 문서 내용이 응답에 전혀 반영되지 않는다는 보고.

## 2. 근본 원인 (표시 버그보다 훨씬 심각함)

`src/ai_voicebot/self_service/rag.py::get_self_service_rag_engine()`가 실제 대화 턴에서 사용하는
`RAGEngine` 인스턴스를 만들 때 다음과 같이 **`doc_type_allowlist=["self_service_manual"]`로
고정**하고 있었다:

```python
_self_service_rag_engine = RAGEngine(
    ...,
    doc_type_allowlist=[SELF_SERVICE_MANUAL_DOC_TYPE],  # "self_service_manual"만!
)
```

Story 1.26 업로드 문서(마크다운/PDF/OpenAPI)는 `doc_type="knowledge_document"`로 색인되므로,
ChromaDB 컬렉션에는 정상적으로 저장되어 있어도 **이 RAGEngine의 벡터 검색 `where` 절에서 항상
제외**됐다(`rag_engine.py`가 `doc_type $in [...]`을 강제 적용). 즉 지난 세션에서 고친 "현황 화면
집계 누락"은 표시상의 문제였지만, 이번 건은 **AI가 업로드 문서를 원천적으로 검색할 수 없는**
훨씬 근본적인 결함이었다. Story 1.33 하이브리드 검색(`hybrid_rag.py`, 유형 C 전용)도 동일하게
`self_service_manual`만 `where` 절에 하드코딩되어 있어 같은 문제가 있었다.

## 3. 수정

- `src/ai_voicebot/self_service/rag.py`: `doc_type_allowlist`를
  `[SELF_SERVICE_MANUAL_DOC_TYPE, KNOWLEDGE_DOCUMENT_DOC_TYPE]`(둘 다 포함)로 확장.
- `src/ai_voicebot/self_service/hybrid_rag.py::_query_domain()`: `where` 절의 `doc_type`을
  `{"$in": [SELF_SERVICE_MANUAL_DOC_TYPE, KNOWLEDGE_DOCUMENT_DOC_TYPE]}`로 확장.
- 기존 단위테스트(`test_self_service_manual_rag.py::test_builds_engine_with_doc_type_allowlist`)의
  `_doc_type_allowlist == (SELF_SERVICE_MANUAL_DOC_TYPE,)` 단언을 두 doc_type 튜플로 갱신.

## 4. 프론트엔드 보강 (같은 세션, 사용자 요청 3건)

1. **"전체 삭제" 버튼이 항상 보이지 않는 문제**: 기존엔 "지식베이스 현황" 탭에만 있었다 —
   "지식 업로드" 탭(테넌트 세그먼트, 문서 목록 위)에도 동일 버튼+확인 문구를 추가해 두 탭
   어디서든 바로 접근 가능하게 함.
2. **고객 지식 베이스 ↔ 도우미 지식 베이스 구분 명시(frontend)**: 지난 세션엔 백엔드 필터만
   고쳤을 뿐 화면에 아무 표시가 없었다 — `/knowledge`(고객 KB) 페이지 제목을 "고객 지식
   베이스"로 바꾸고 "AI 도우미 지식베이스는 설정 > AI 도우미에서 별도 관리" 안내 문구 추가.
   `/settings/ai-assistant/docs`(도우미 KB) 헤더에도 "이 화면은 AI 도우미 전용, 고객 지식
   베이스(/knowledge)와 다른 데이터" 경고 문구 추가(양방향 교차 링크).

## 5. 검증

- 신규 확인: `python -c "from src.ai_voicebot.self_service import rag; ..."`로 import 순환 없음 확인.
- `test_self_service_manual_rag.py`/`test_intellidecision_manual.py`/`hybrid_rag` 관련 테스트 전체
  통과, `tests_new/unit -k "self_service or dynamic_api or intellidecision or knowledge_document
  or knowledge_base or hybrid_rag or manual_rag"` 재실행 — 기존 무관 사전 결함 1건
  (`test_knowledge_documents_service.py::test_register_markdown_document_uses_manual_adapter`,
  이번 세션에서 건드리지 않은 파일) 제외 전부 통과.
- `npx tsc --noEmit`/`npx eslint` 0에러(수정 중 `react/no-unescaped-entities` 1건 발견해 즉시
  `&quot;`로 교체).
- **잔여**: 실서버 재시작 후 QA 픽스처 문서로 실제 대화 검색 확인(예: "재고 부족한 상품 어떻게
  봐?" → 매뉴얼 §3 내용이 실제로 RAG 매칭되는지)은 다음 세션.

## 6. 교훈

- "doc_type 화이트리스트/allowlist"처럼 여러 곳에 동일한 상수가 하드코딩되는 패턴에서는, 새
  doc_type을 추가하는 기능(Story 1.26)을 만들 때 **그 doc_type을 걸러야 하는 모든 지점**을
  찾아 갱신해야 한다 — 이번에 총 3곳(지식베이스 현황 집계, 실제 RAG 검색, 하이브리드 검색)에서
  동일한 누락이 있었다. 새 doc_type 도입 Story를 완료할 때는
  `grep -rn "self_service_manual"` 같은 명령으로 관련 상수를 참조하는 모든 위치를 점검하는
  습관이 필요하다.
- 사용자가 "표시가 안 된다"고 보고했을 때 표시 계층만 고치고 끝내지 않고, "실제로 검색/응대에
  쓰이는가"까지 코드를 따라가 봐야 한다 — 이번에 표시 버그(지난 세션)와 검색 버그(이번 세션)는
  겉보기엔 같은 증상("업로드한 게 안 보인다")처럼 보였지만 서로 다른 코드 경로의 별개 결함이었다.

*최종 업데이트: 2026-08-07*
