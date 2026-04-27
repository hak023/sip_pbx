## 메타

- 작성일: 2026-04-15
- 상태: 검토 완료 · 2026-04-15 권장 UI 반영됨 (`knowledge/page.tsx`, `types/index.ts`)
- 관련: `knowledge_api.py`, `knowledge_service.py`, `frontend/app/knowledge/page.tsx`, `frontend/app/knowledge/add/page.tsx`, `frontend/types/index.ts`

## 결론 요약

- **지식 추가 시 `doc_type`을 사용자가 꼭 넣을 필요는 없다.** API 모델 `KnowledgeCreateBody`에 `doc_type: str = "knowledge"` 기본값이 있어, 요청 본문에서 생략 시 서버가 `"knowledge"`로 저장한다.
- **`frontend/app/knowledge/add/page.tsx`는 이미 `doc_type`을 보내지 않는다** → 실운영에서도 생략이 정상 동작함을 의미한다.
- **시스템 전체에서 `doc_type` 메타데이터 키를 없애는 것은 권장하지 않는다.** `doc_type=capability`는 Capability CRUD·목록(`get_all_capabilities`)과 결합되어 있어, 제거 시 대체 식별자(별도 컬렉션·전용 카테고리·플래그) 설계가 필요하다.

## 코드 근거

| 구분 | 내용 |
|------|------|
| POST `/api/knowledge` | `KnowledgeCreateBody.doc_type` 기본값 `"knowledge"`; `metadata`에 `doc_type` 저장 |
| GET `/api/knowledge` | 쿼리 `doc_type` 있으면 `metadata.doc_type`으로 필터 |
| Capability | `get_all_capabilities` → `where={"doc_type": "capability"}`; `add_capability` 등이 `doc_type: "capability"` 고정 |
| HITL 적재 | `add_from_hitl`이 `doc_type: "knowledge"` 메타로 적재 |
| 지식 메인 폼 | ~~`doc_type` 명시 전송·필터~~ → **미전송·필터 제거** (목록 테이블의 `doc_type` 열 표시는 유지, API 기본값·메타 조회용) |

## 카테고리별로 `doc_type` UI 제거 가능 여부

| 카테고리(또는 흐름) | UI에서 `doc_type` 생략·고정 시 |
|---------------------|-------------------------------|
| `persona` | `/api/persona` 사용 — `doc_type` 무관 |
| `question`, `chitchat`, `complaint`, `help`, `waiting_phrase`, 인사·종료 등 | `category`가 RAG·인사 로직의 주 축; POST 시 `doc_type` 생략 시 기본 `knowledge`면 **문제 없음** |
| `contact` | 구분은 `category=contact` + `phone_number` 등 메타; `doc_type`은 보통 `knowledge`로 충분 (구 UI의 `doc_type=contact` 선택과 혼동 주의) |
| Capability 기능 | 전용 `add_capability` API 사용 시에만 `doc_type=capability`; **일반 지식 폼에서 `doc_type`을 없애도** capability 경로는 별도 유지 |

## `doc_type`을 “완전 제거”할 때 영향

- Chroma 단일 컬렉션에 일반 지식·capability가 공존하는 전제에서 **`doc_type` 없이 capability만 구분 불가**하면 `get_all_capabilities` 등 전면 수정 필요.
- 기존에 `metadata.doc_type`으로 적재된 문서 마이그레이션·하위 호환 필요.
- 목록 API의 `doc_type` 쿼리 파라미터 제거 시 관리 UI 필터 동작 변경.

## 권장 방향 (적용됨)

1. **프론트**: `knowledge/page.tsx`에서 `doc_type` 선택·목록 필터 제거, POST 본문에서 `doc_type` 생략 — `add/page`와 동일.
2. **백엔드**: 변경 없음 — `KnowledgeCreateBody.doc_type` 기본값·capability 전용 경로 유지.
3. **문서화**: 지식 페이지 상단 안내에 카테고리 vs doc_type 한 줄 추가; `types/index.ts`의 `DOC_TYPES` 상수 제거(미사용).
