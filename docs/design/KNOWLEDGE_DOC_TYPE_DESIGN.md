# 지식 분류 설계 — doc_type 통일 및 Backend/Frontend 스펙

**작성일**: 2026-03-16  
**기준 문서**: [KNOWLEDGE_CLASSIFICATION_AND_INCOMING_DATA.md](./KNOWLEDGE_CLASSIFICATION_AND_INCOMING_DATA.md)  
**규칙**: **유저 간 통화로 적재되는 모든 경우 doc_type = `knowledge`** 로 통일.

---

## 1. doc_type 정의 (제한)

| doc_type | 설명 | 사용처 |
|----------|------|--------|
| **knowledge** | 일반 지식. **API 입력, 시드 지식, HITL 저장, 통화 추출 승인** 모두 이 유형으로 적재 | RAG 검색 대상 (owner만 필터) |
| **faq** | Q&A 형태 지식 (시드 FAQ만 구분용. 저장은 동일 컬렉션) | 선택적 필터용. 미사용 시 시드 FAQ도 knowledge로 저장 가능 |
| **capability** | 서비스/기능 정의 | 기존 유지. 별도 API·RAG 제외 옵션 |
| **manual_chunk** | 메뉴얼/문서 청크 (미구현) | 미구현 |
| **tenant_config** | 테넌트 설정 (기존) | RAG 검색 제외 |

**통화로 인하여 적재되는 경우** (HITL 저장, 통화 추출 검토 승인) → **반드시 doc_type = `knowledge`**.  
출처 구분은 **source** 필드로만 한다 (hitl, call 등).

---

## 2. 메타데이터 스키마 (ChromaDB)

모든 지식/FAQ 적재 시 공통으로 넣는 필드:

| 필드 | 타입 | 필수 | 설명 |
|------|------|------|------|
| owner | string | O | 테넌트(착신자) ID. RAG where 조건 |
| category | string | O | 도메인/주제 (테넌트별: weather_forecast, menu, faq 등) |
| doc_type | string | O | knowledge \| faq \| capability \| manual_chunk \| tenant_config |
| source | string | O | api \| hitl \| call \| seed \| manual_upload |
| keywords | string | - | 쉼표 구분. 검색/표시 보조 |
| created_at | string | - | ISO 8601 |

통화 연계 시 추가:

| 필드 | 타입 | 필수 | 설명 |
|------|------|------|------|
| call_id | string | - | 통화 ID (HITL/추출 시) |
| operator_id | string | - | 운영자 ID (HITL 시) |

- **owner_id** 는 사용하지 않고 **owner** 로만 통일.

---

## 3. 인입 경로별 doc_type / source

| 인입 경로 | doc_type | source | 비고 |
|-----------|----------|--------|------|
| API/대시보드 수동 입력 | knowledge | api | 기존과 동일. doc_type 명시 |
| HITL(운영자 응답) → 지식 저장 | **knowledge** | hitl | 통화로 인한 적재이므로 knowledge |
| 통화 추출 → 검토 승인 후 적재 | **knowledge** | call | 통화로 인한 적재이므로 knowledge |
| 시드 지식/FAQ | knowledge (또는 faq) | seed | capability는 doc_type=capability 유지 |
| 메뉴얼 업로드 (미구현) | manual_chunk | manual_upload | - |

---

## 4. Backend 설계

### 4.1 API 스펙

#### POST /api/knowledge (지식 추가)

**Request body:**

| 필드 | 타입 | 필수 | 기본값 | 설명 |
|------|------|------|--------|------|
| text | string | O | - | 지식 본문 |
| owner | string | O | - | 소유자(테넌트) ID |
| category | string | O | - | 카테고리 (허용 목록 내) |
| doc_type | string | - | "knowledge" | knowledge \| faq (대시 입력은 knowledge 권장) |
| source | string | - | "api" | api \| hitl \| call \| seed |
| answer | string | - | - | greeting/farewell 시 캐시용 |
| call_id | string | - | - | 통화 ID (선택) |
| keywords | string[] | - | [] | 키워드 배열 (저장 시 쉼표 문자열로) |

**Response:**  
`{ "ok": true, "doc_id": string, "cached": boolean }` 또는 4xx/5xx.

**ChromaDB 저장 시:**  
- doc_type 없으면 `"knowledge"`, source 없으면 `"api"`.  
- metadata에 owner, category, doc_type, source, keywords(문자열), created_at, (call_id 있으면 추가) 반드시 포함.

#### GET /api/knowledge (목록)

**Query:**

| 파라미터 | 타입 | 필수 | 설명 |
|----------|------|------|------|
| owner | string | - | 테넌트 필터 |
| category | string | - | 카테고리 필터 |
| doc_type | string | - | doc_type 필터 (knowledge, faq, capability 등) |
| source | string | - | source 필터 (api, hitl, call, seed) |
| limit | number | - | 기본 500 |

**Response:**  
`{ "items": KnowledgeItem[], "total"?: number }`  
- 각 항목에 metadata.doc_type, metadata.source 포함.

#### DELETE /api/knowledge/{doc_id}

- 기존과 동일. doc_type 무관 삭제.

### 4.2 서비스 레이어 규칙

- **add_knowledge (API 경로)**  
  - doc_type 기본값 `"knowledge"`, source 기본값 `"api"`.  
  - ChromaDB 메타데이터에 doc_type, source, owner 항상 저장.

- **add_from_hitl (HITL 응답 → 지식 저장)**  
  - doc_type = **"knowledge"** 고정.  
  - source = **"hitl"**.  
  - 메타데이터에 **owner** 사용 (owner_id 제거 또는 owner로 매핑).  
  - call_id, operator_id 유지.

- **통화 추출 검토 승인 후 ChromaDB 적재**  
  - doc_type = **"knowledge"** 고정.  
  - source = **"call"**.  
  - owner, category, call_id 등 기존 필드 유지.

- **시드 데이터 (seed_data.py)**  
  - 지식/FAQ: doc_type = `"knowledge"`, source = `"seed"`.  
  - capability: doc_type = `"capability"` 유지, source = `"seed"`.

### 4.3 RAG 검색

- question / unknown intent: **owner만** where 조건. doc_type/category 제한 없음 (현재와 동일).  
- greeting / farewell: **category** in [greeting_phase1, greeting_phase2] 또는 [farewell] 만 사용.  
- 필요 시 나중에 “doc_type in [knowledge, faq]만 검색” 옵션 추가 가능.

---

## 5. Frontend 설계

### 5.1 타입 정의 (types/index.ts)

- **doc_type** 상수 (목록/필터/폼에서 사용):

```ts
export const DOC_TYPES = [
  { value: 'knowledge', label: '지식 (일반/통화·HITL)' },
  { value: 'faq', label: 'FAQ' },
] as const;
export type DocType = typeof DOC_TYPES[number]['value'];
```

- **source** 표시용 (필터/목록):

```ts
export const KNOWLEDGE_SOURCES = [
  { value: 'api', label: '대시 입력' },
  { value: 'hitl', label: 'HITL 저장' },
  { value: 'call', label: '통화 추출' },
  { value: 'seed', label: '시드' },
] as const;
```

- **KnowledgeItem** 확장:

```ts
export interface KnowledgeItem {
  id: string;
  text: string;
  metadata: {
    owner?: string;
    category?: string;
    doc_type?: string;   // 추가
    source?: string;     // 추가
    call_id?: string;
    created_at?: string;
  };
}
```

- **KNOWLEDGE_CATEGORIES**  
  - 기존 유지 (question, greeting_phase1, greeting_phase2, farewell, weather_forecast 등 테넌트/도메인별).  
  - 필요 시 테넌트별 허용 목록 API 연동.

### 5.2 지식 목록 페이지 (app/knowledge/page.tsx)

- **필터**
  - 기존: owner, category.  
  - 추가: **doc_type** (드롭다운: 전체 / knowledge / faq), **source** (전체 / api / hitl / call / seed).
- **목록 테이블**
  - 컬럼 추가: **doc_type**, **source** (한글 라벨로 표시).
- **정렬**
  - 기존 카테고리별 그룹화 유지.  
  - 선택: created_at 기준 최신순.

### 5.3 지식 추가 폼

- **입력 필드**
  - 기존: text, category, answer(선택).  
  - 추가: **doc_type** (기본값 "knowledge", 선택: knowledge / faq).  
  - source는 API 호출 시 **"api"** 고정 (수동 입력이므로).
- **유효성**
  - text, owner, category 필수.  
  - doc_type은 허용 값만 허용.

### 5.4 API 호출

- **POST /api/knowledge**  
  - body: `{ text, owner, category, doc_type: "knowledge" | "faq", source: "api", answer?, call_id?, keywords? }`.
- **GET /api/knowledge**  
  - query: `owner`, `category`, `doc_type`, `source`, `limit`.  
  - 응답 items[].metadata에 doc_type, source 포함되도록 백엔드 보장.

---

## 6. 구현 체크리스트

### Backend

- [ ] ChromaDB 저장 시 모든 지식에 **doc_type**, **source** 필드 포함 (기본값: knowledge, api).
- [ ] **POST /api/knowledge**: body에 doc_type, source 수신 및 저장.
- [ ] **GET /api/knowledge**: query param doc_type, source로 where 조건 추가; 응답 metadata에 doc_type, source 포함.
- [ ] **add_from_hitl**: doc_type="knowledge", source="hitl", 메타데이터에 owner 사용 (owner_id 제거 또는 owner로 통일).
- [ ] **통화 추출 승인 후 적재**: doc_type="knowledge", source="call".
- [ ] **seed_data**: 지식/FAQ에 doc_type="knowledge", source="seed"; capability는 doc_type="capability" 유지.

### Frontend

- [ ] **types**: DOC_TYPES, KNOWLEDGE_SOURCES, KnowledgeItem.metadata에 doc_type, source 추가.
- [ ] **목록**: 필터 doc_type, source 추가; 테이블에 doc_type, source 컬럼 표시.
- [ ] **추가 폼**: doc_type 선택 (기본 knowledge), POST 시 doc_type, source="api" 전송.

---

## 7. 요약

- **통화로 적재되는 모든 경우** (HITL 저장, 통화 추출 승인) → **doc_type = knowledge**, source로 hitl/call 구분.
- **doc_type** 제한: knowledge, faq, capability, manual_chunk, tenant_config.  
- **Backend**: API·서비스·시드에서 doc_type/source 저장 및 목록 필터 지원.  
- **Frontend**: 목록 필터·컬럼, 추가 폼 doc_type, 타입 정의 반영.

이 설계에 따라 백엔드/프론트엔드 수정 시 위 체크리스트를 기준으로 적용하면 된다.
