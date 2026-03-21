# 지식베이스 메뉴 구현 점검 (입력·조회·삭제·카테고리별 분류)

**요구**: 지식 입력, 조회, 삭제가 모두 관리되고, 카테고리별 분류 처리.

---

## 1. 점검 결과 요약

| 기능 | 이전 | 현재 | 비고 |
|------|------|------|------|
| **지식 입력** | ✅ 구현됨 | ✅ 유지 | 카테고리 선택, 내용, 인사/종료 시 응답문(즉시 캐시용). POST /api/knowledge |
| **지식 조회** | ✅ 구현됨 | ✅ 유지 | owner·카테고리 필터, 목록 테이블. GET /api/knowledge |
| **지식 삭제** | ❌ 없음 | ✅ 추가됨 | 행별 삭제 버튼 + 확인 → DELETE /api/knowledge/{doc_id} |
| **카테고리별 분류** | 필터만 | ✅ 보강 | "카테고리별 분류 표시" 체크 시 목록을 카테고리별 섹션으로 그룹 표시 |

---

## 2. 구현 상세

### 2.1 지식 입력
- **위치**: 지식베이스 페이지 상단 "지식 추가" 폼.
- **필드**: 카테고리(필수, KNOWLEDGE_CATEGORIES), 내용(필수), 응답 문장(인사/종료 시 선택).
- **동작**: POST /api/knowledge → 성공 시 메시지·목록 갱신.

### 2.2 지식 조회
- **위치**: "등록된 지식" 블록.
- **필터**: owner 입력, 카테고리 셀렉트(전체/개별 카테고리).
- **동작**: GET /api/knowledge?owner=…&category=… → 테이블 또는 카테고리별 섹션으로 표시.

### 2.3 지식 삭제 (신규)
- **백엔드**
  - `chromadb_client._VectorDbWrapper`: `delete(ids=[...])` 메서드 추가.
  - `knowledge_service.delete_knowledge(vector_db, doc_id)` 추가.
  - `DELETE /api/knowledge/{doc_id}` 라우트 추가.
- **프론트**
  - 각 행에 "삭제" 버튼.
  - 클릭 시 `confirm('이 지식을 삭제할까요?')` 후 DELETE 호출.
  - 삭제 중에는 `deletingId`로 해당 행만 비활성화.

### 2.4 카테고리별 분류 (보강)
- **"카테고리별 분류 표시" 체크박스** (기본 on).
  - on: 목록을 `metadata.category` 기준으로 그룹해, 카테고리별 섹션(제목 + 건수 + 테이블)으로 표시.
  - off: 기존처럼 단일 테이블(카테고리 컬럼 포함).
- **필터**: 조회 시점에 이미 owner/category 쿼리로 필터링되며, 분류 표시는 "표시 방식"만 바꿈.

---

## 3. 파일 변경 목록

| 파일 | 변경 내용 |
|------|-----------|
| `src/ai_voicebot/knowledge/chromadb_client.py` | `_VectorDbWrapper.delete(ids=..., where=...)` 추가 |
| `src/ai_voicebot/knowledge/knowledge_service.py` | `delete_knowledge(vector_db, doc_id)` 추가 |
| `src/api/knowledge_router.py` | `DELETE /api/knowledge/{doc_id}` 추가, docstring 갱신 |
| `frontend/app/knowledge/page.tsx` | 삭제 버튼·handleDelete·확인, 카테고리별 그룹 표시·체크박스, 삭제 컬럼 추가 |

---

## 4. 정리

- **입력·조회·삭제**: 모두 지식베이스 메뉴에서 동작하도록 구현됨.
- **카테고리별 분류**: 조회 필터(카테고리) + "카테고리별 분류 표시"로 카테고리별 그룹 표시까지 반영됨.
