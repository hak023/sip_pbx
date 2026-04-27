## 메타

- 작성일: 2026-04-15
- 상태: 구현 완료
- 선행 검토: `2026-04-15_1915_KNOWLEDGE_DOC_TYPE_REVIEW.md` 권장 방향

## 개요

지식 베이스 메인 화면에서 **`doc_type` 수동 선택·목록 필터를 제거**하고, 저장 시 **`doc_type`을 POST에 넣지 않아** API 기본값 `knowledge`를 쓰도록 `knowledge/add/page` 와 맞췄다. 상단 안내에 **카테고리(업무 구분) vs doc_type(서버 저장 계층)** 설명을 한 줄 추가했다.

## 변경 이력 (파일별)

| 파일 경로 | 변경 유형 | 요약 | 비고 |
|-----|-----|---|---|
| `sip-pbx/frontend/app/knowledge/page.tsx` | 수정 | `doc_type` UI·state·쿼리 파라미터 제거, POST 생략, 안내 문구 | |
| `sip-pbx/frontend/types/index.ts` | 수정 | `DOC_TYPES` 상수 제거 | 미참조 |
| `sip-pbx/docs/reports/2026-04/2026-04-15_1915_KNOWLEDGE_DOC_TYPE_REVIEW.md` | 수정 | 메타·표·권장 방향 “적용됨” 갱신 | |
| `sip-pbx/docs/reports/2026-04/2026-04-15_1945_KNOWLEDGE_DOC_TYPE_UI_REMOVED.md` | 추가 | 본 리포트 | |

## 주요 결정 사항

- 목록 테이블의 **doc_type 열**은 유지 — 관리자가 capability·HITL 등으로 적재된 행을 구분하는 데 유용.
- GET `?doc_type=` 은 백엔드에 그대로 두었고, UI에서만 필터를 뺐다.
