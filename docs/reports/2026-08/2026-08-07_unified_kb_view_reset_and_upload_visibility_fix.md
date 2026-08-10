# "전체 삭제해도 지식베이스(통합)에서 그대로 보임" + 업로드 문서 미노출 + 라벨 불일치 수정

- 작성일: 2026-08-07
- 버전: v1.0
- 관련 문서: [uploaded_document_missing_from_rag_search_fix.md](2026-08-07_uploaded_document_missing_from_rag_search_fix.md)

## 1. 증상 (사용자 재보고 3건)

1. "도우미 지식 베이스 전체 삭제"를 눌렀는데 "지식베이스(통합)" 메뉴에는 아무것도 삭제되지
   않은 것처럼 보인다.
2. "도우미 지식베이스라고 frontend에 반영해달라는 게 바로 이 '지식베이스(통합)' 메뉴였는데,
   업로드된 지식이 여기서 보여야 하는데 안 보인다."
3. 메뉴의 "AI 응대 지식(페르소나)" 라벨도 지난 세션 수정(고객 지식 베이스)과 안 맞는다.

## 2. 근본 원인

### ① "전체 삭제해도 그대로 보임" — 자동 재색인이 삭제를 무효화

"지식베이스(통합)" 탭(`tab==="list"`)은 `GET /api/settings/ai-assistant/docs`(내부적으로
`loadQa()`)가 반환하는 매뉴얼 Q&A `items`를 보여준다. 이 엔드포인트는 **owner의 해당 doc_type
항목이 0개면 자동으로 기본 매뉴얼을 재색인한 뒤 반환**하도록 설계되어 있었다(신규 테넌트
온보딩을 위한 의도된 기능). 그런데 "전체 삭제" 버튼은 `kbDocuments`/`kbInventory`만 초기화하고
정작 이 화면이 쓰는 `items` 상태는 전혀 갱신하지 않았다 — 즉:

1. 백엔드 삭제 자체는 실제로 성공했다(ChromaDB 청크 삭제 확인됨).
2. 하지만 프론트는 `items`를 그대로 캐시해 보여주거나, 다시 조회하면 `GET /docs`가 "0개니까
   자동으로 다시 채워 넣자"며 즉시 기본 매뉴얼을 재색인해버려 사용자 눈에는 "삭제가 안 된
   것"처럼 보였다.

### ② 업로드 문서가 "지식베이스(통합)"에 안 보임 — 이중 필터링 누락

- `GET /docs`(`list_help_docs`)가 `doc_type == "self_service_manual"` **하나만** 필터링해
  Story 1.26 업로드 문서(`doc_type="knowledge_document"`)를 애초에 `items`에 담지 않았다
  (§1의 두 doc_type 관련 버그가 이번엔 세 번째 지점에서도 재현된 것).
- 설령 `items`에 포함되더라도, `KnowledgeClusterTable`(hop 클러스터링 컴포넌트)이 QA 항목을
  `related_domain`이 있는 경우에만 클러스터에 배정하고 **없으면 조용히 버리는 구조**였다.
  업로드 문서는 `related_domain` 메타데이터를 채우지 않으므로(Story 1.26 설계상 도메인
  비종속) 두 번째 필터에서도 사라졌다.

### ③ 라벨 불일치

`AppHeader.tsx`의 `/knowledge` nav 라벨이 여전히 "AI 응대 지식(페르소나)"였는데, 지난 세션에
`/knowledge` 페이지 본문 제목은 "고객 지식 베이스"로 바꿔서 nav와 페이지 제목이 서로 다른 표현을
쓰는 새로운 불일치가 생겼다.

## 3. 수정

### 백엔드 (`src/api/routers/settings_ai_assistant.py`)

- `_SELF_SERVICE_LIST_DOC_TYPES = ("self_service_manual", "knowledge_document")`로 `GET /docs`의
  필터를 확장 — 업로드 문서 Q&A도 `items`에 포함.
- `auto_index: bool = Query(True)` 파라미터 추가 — `false`로 호출하면 항목이 0개여도 자동
  재색인을 건너뛰고 실제 빈 상태를 그대로 반환한다.

### 프론트엔드 (`frontend/app/settings/ai-assistant/docs/page.tsx`)

- `loadQa(autoIndex: boolean = true)`로 시그니처 확장, 쿼리에 `auto_index` 전달.
- `handleResetKnowledgeBase()`가 이제 `items`도 함께 비우고 `loadQa(false)`로 재조회 —
  자동 재색인 없이 실제로 비워진 상태를 즉시 확인 가능.
- `kbDocuments` 로딩 effect에 `tab === "list"` 조건 추가(기존엔 kb/upload 탭에서만 로드).

### 프론트엔드 (`frontend/components/knowledge-base/KnowledgeClusterTable.tsx`)

- `related_domain`이 없는 QA 그룹(업로드 문서 등)을 버리지 않고, 그룹별로 독립된 "고아
  클러스터"(`unclustered:<섹션제목>`)로 만들어 화면에 그대로 노출하도록 수정. 기존 도메인
  기반 클러스터링 로직은 그대로 유지(회귀 없음).

### 라벨 정합성 (`frontend/components/AppHeader.tsx`)

- `/knowledge` nav 라벨을 "AI 응대 지식(페르소나)" → "고객 지식 베이스"로 변경, 페이지 제목과
  일치시킴.

## 4. 검증

- `python -m pytest tests_new/unit -k "settings_ai_assistant or self_service or knowledge"` —
  기존 무관 사전 결함 1건(`test_knowledge_documents_service.py`, 이번 세션 미변경 파일) 제외
  전부 통과.
- `npx tsc --noEmit`/`npx eslint`(수정한 4개 프론트 파일) 0에러.
- **잔여**: 실서버 재시작 후 ① 실제로 "전체 삭제" 클릭 시 "지식베이스(통합)" 화면이 즉시
  비워지는지 ② 새 문서 업로드 시 같은 화면에 "(도메인 미지정)" 그룹으로 나타나는지 ③ nav
  라벨이 바뀌었는지 육안 확인은 다음 세션.

## 5. 교훈

- 같은 저장소 내에서 "지식베이스 표시/집계/검색"을 다루는 지점이 최소 4곳
  (지식베이스 현황 집계 `knowledge_base_inventory.py`, 실제 RAG 검색 `rag.py`, 하이브리드 검색
  `hybrid_rag.py`, 매뉴얼 Q&A 목록 `settings_ai_assistant.py::list_help_docs`)이나 있었고, 전부
  독립적으로 `doc_type == "self_service_manual"`만 하드코딩되어 있었다 — Story 1.26이 새
  doc_type을 도입했을 때 이 4곳 전부를 갱신했어야 했는데 그러지 못한 것이 오늘 하루 동안 반복
  발견된 동일 패턴의 결함이다. 새 doc_type/데이터 소스를 추가하는 Story를 시작하기 전에,
  먼저 `grep -rn "self_service_manual"` 같은 검색으로 영향받는 모든 지점을 목록화하고 체크리스트로
  관리하는 습관이 필요하다.
- "삭제 버튼을 눌렀는데 그대로다"라는 보고를 받으면, 삭제 API 자체의 성공 여부만 보지 말고
  "그 삭제 결과를 보여주는 화면이 참조하는 모든 상태/엔드포인트"를 추적해야 한다 — 이번엔
  삭제는 100% 성공했지만, 그 결과를 반영해야 할 화면이 참조하는 별도 엔드포인트(`GET /docs`)에
  "0개면 자동 복구"라는 전혀 다른 로직이 숨어있어 사용자에게는 "삭제가 실패한 것"처럼 보였다.

## 6. 후속 — "삭제해도 설정/화면 안내는 그대로다" (버그 아님, UX 명확화)

같은 세션에서 사용자가 삭제 후 "문서 0건 / 설정 7건 / 화면 안내 6건"으로 일부만 지워진 것처럼
보인다고 재보고. 확인 결과:

- "설정"(`catalog`)/"화면 안내"(`screens`) 카운트는 `GET /api/settings/ai-assistant/catalog`,
  `GET /api/settings/ai-assistant/screen-graph`에서 오는데, **두 엔드포인트 모두 `owner` 파라미터
  자체가 없다** — 테넌트별 업로드 데이터가 아니라 Epic 2 설정 카탈로그/Screen Graph의 **시스템
  공통 구조 정의**(persona/call-control/chat-relay 등 7개 도메인, 6개 화면)다.
- 즉 "도우미 지식 베이스 전체 삭제"가 이 둘을 건드리지 않는 것은 **의도된 정상 동작**이다 —
  삭제하면 AI 도우미의 설정 조회/화면 안내 기능 자체가 깨진다. 버그가 아니라 세 가지 서로 다른
  개념(테넌트별 지식 Q&A vs 시스템 공통 설정 구조 vs 시스템 공통 화면 구조)이 한 화면에 카운트로
  같이 노출되어 사용자가 "다 지워지는 삭제"로 오해하기 쉬웠던 UX 문제였다.
- **수정**: 배지에 `title` 툴팁 추가("설정/화면 안내는 시스템 공통 정의라 삭제 대상 아님"),
  "전체 삭제" 버튼 옆 안내 문구와 확인(`window.confirm`) 다이얼로그 문구에도 동일 내용을 명시해
  삭제 범위를 클릭 전에 알 수 있도록 함.

*최종 업데이트: 2026-08-07*
