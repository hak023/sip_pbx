# 지식 분류 시스템 구현 완료 보고서

**작성일**: 2026-03-16  
**기반 설계**: [KNOWLEDGE_DOC_TYPE_DESIGN.md](../../design/KNOWLEDGE_DOC_TYPE_DESIGN.md)  
**핵심 규칙**: **유저 간 통화로 적재되는 모든 경우 doc_type = `knowledge`**

---

## 1. 구현 개요

지식 분류 시스템 설계(KNOWLEDGE_DOC_TYPE_DESIGN)를 기반으로 Backend와 Frontend를 모두 구현하였습니다.

### 핵심 변경사항
- **doc_type** 필드 추가: `knowledge` | `faq` (통화 유래 데이터는 `knowledge` 고정)
- **source** 필드 추가: `api` | `hitl` | `call` | `seed` (출처 구분)
- **created_at** 필드 추가: ISO 8601 형식의 생성 시각

---

## 2. Backend 구현

### 2.1 API 라우터 (`src/api/knowledge_router.py`)

**변경사항:**
1. **KnowledgeCreateRequest 모델 확장**
   ```python
   class KnowledgeCreateRequest(BaseModel):
       text: str = Field(..., description="지식 내용 (필수)", min_length=1)
       owner: str = Field(..., description="소유자 ID (필수)")
       category: str = Field(..., description="카테고리 (필수)")
       doc_type: Optional[str] = Field("knowledge", description="문서 유형 (knowledge|faq)")  # 추가
       answer: Optional[str] = Field(None, description="답변 (greeting/farewell 시 즉시 캐시용)")
       source: Optional[str] = Field("api", description="출처 (api|hitl|call|seed)")
       call_id: Optional[str] = Field(None, description="통화 ID")
   ```

2. **POST /api/knowledge 핸들러 수정**
   - `doc_type` 유효성 검증 추가 (`knowledge` | `faq` 만 허용)
   - `doc_type` 기본값: `"knowledge"`
   - `add_knowledge()` 호출 시 `doc_type` 파라미터 전달

3. **GET /api/knowledge 핸들러 확장**
   ```python
   @router.get("/knowledge")
   def get_knowledge_list(
       owner: Optional[str] = None,
       category: Optional[str] = None,
       doc_type: Optional[str] = Query(None, description="문서 유형 필터"),  # 추가
       source: Optional[str] = Query(None, description="출처 필터"),  # 추가
       limit: int = 500,
       ...
   ):
   ```

### 2.2 지식 서비스 (`src/ai_voicebot/knowledge/knowledge_service.py`)

**변경사항:**
1. **add_knowledge() 함수**
   - `doc_type` 파라미터 추가 (기본값: `"knowledge"`)
   - 메타데이터에 `doc_type`, `source`, `created_at` 포함
   ```python
   metadata = {
       "owner": owner,
       "category": category,
       "doc_type": doc_type,  # 추가
       "source": source,
       "created_at": datetime.now().isoformat(),  # 추가
   }
   ```

2. **list_knowledge() 함수**
   - `doc_type`, `source` 필터 파라미터 추가
   - where 조건 생성 로직 확장
   ```python
   def list_knowledge(
       vector_db: Any,
       owner: Optional[str] = None,
       category: Optional[str] = None,
       doc_type: Optional[str] = None,  # 추가
       source: Optional[str] = None,    # 추가
       limit: int = 500,
   ) -> Dict[str, Any]:
   ```

### 2.3 HITL 서비스 (`src/services/knowledge_service.py`)

**변경사항:**
1. **add_from_hitl() 메서드**
   - `doc_type = "knowledge"` 고정 (통화로 인한 적재)
   - `source = "hitl"` 설정
   - `owner_id` → `owner` 필드명 통일
   ```python
   doc_metadata = {
       "category": category,
       "doc_type": "knowledge",  # 통화로 인한 적재이므로 knowledge 고정
       "source": "hitl",
       "owner": owner,  # owner로 통일
       ...
   }
   ```

### 2.4 시드 데이터 (`src/services/seed_data.py`)

**변경사항:**
1. **지식 데이터 시드**
   ```python
   metadata = {
       "category": kb["category"],
       "owner": owner,
       "doc_type": "knowledge",  # 시드 지식은 knowledge
       "source": "seed",
       "created_at": datetime.now().isoformat(),
   }
   ```

2. **FAQ 데이터 시드**
   ```python
   metadata = {
       "category": "faq",
       "doc_type": "faq",  # FAQ는 doc_type=faq 유지
       "owner": owner,
       "source": "seed",
       ...
   }
   ```

---

## 3. Frontend 구현

### 3.1 타입 정의 (`frontend/types/index.ts`)

**추가된 상수 및 타입:**
```typescript
/** doc_type 타입 정의 */
export const DOC_TYPES = [
  { value: 'knowledge', label: '지식 (일반/통화·HITL)' },
  { value: 'faq', label: 'FAQ' },
] as const;
export type DocType = typeof DOC_TYPES[number]['value'];

/** source 출처 정의 */
export const KNOWLEDGE_SOURCES = [
  { value: 'api', label: '대시 입력' },
  { value: 'hitl', label: 'HITL 저장' },
  { value: 'call', label: '통화 추출' },
  { value: 'seed', label: '시드' },
] as const;

/** 지식 1건 인터페이스 확장 */
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

### 3.2 지식 페이지 (`frontend/app/knowledge/page.tsx`)

**변경사항:**

1. **상태 추가**
   ```typescript
   const [docType, setDocType] = useState<string>('knowledge');  // 폼용
   const [filterDocType, setFilterDocType] = useState('');       // 필터용
   const [filterSource, setFilterSource] = useState('');         // 필터용
   ```

2. **등록 폼 확장**
   - doc_type 선택 드롭다운 추가 (기본값: `knowledge`)
   - POST 요청 body에 `doc_type` 포함

3. **필터 영역 확장**
   ```tsx
   <select value={filterDocType} onChange={(e) => setFilterDocType(e.target.value)}>
     <option value="">전체 doc_type</option>
     {DOC_TYPES.map((t) => (
       <option key={t.value} value={t.value}>{t.label}</option>
     ))}
   </select>
   
   <select value={filterSource} onChange={(e) => setFilterSource(e.target.value)}>
     <option value="">전체 source</option>
     {KNOWLEDGE_SOURCES.map((s) => (
       <option key={s.value} value={s.value}>{s.label}</option>
     ))}
   </select>
   ```

4. **목록 테이블 컬럼 추가**
   - **doc_type** 컬럼: 한글 라벨로 표시
   - **source** 컬럼: 한글 라벨로 표시
   ```tsx
   <td>{DOC_TYPES.find(t => t.value === row.metadata?.doc_type)?.label ?? '-'}</td>
   <td>{KNOWLEDGE_SOURCES.find(s => s.value === row.metadata?.source)?.label ?? '-'}</td>
   ```

5. **API 호출 수정**
   - GET 요청 시 `doc_type`, `source` 쿼리 파라미터 포함
   - POST 요청 시 `doc_type` body 포함

---

## 4. 구현된 데이터 흐름

### 4.1 대시보드 수동 입력
```
Frontend Form
  ↓ POST /api/knowledge { text, owner, category, doc_type: "knowledge", source: "api" }
  ↓
API Router (knowledge_router.py)
  ↓ add_knowledge(..., doc_type="knowledge", source="api")
  ↓
Knowledge Service (knowledge_service.py)
  ↓ vector_db.add([metadata with doc_type, source])
  ↓
ChromaDB (metadata: { owner, category, doc_type: "knowledge", source: "api", created_at })
```

### 4.2 HITL 저장
```
Operator Response (WebSocket/API)
  ↓
KnowledgeService.add_from_hitl()
  ↓ metadata: { doc_type: "knowledge", source: "hitl", owner, call_id, operator_id }
  ↓
ChromaDB
```

### 4.3 시드 데이터
```
startup → seed_initial_data()
  ↓
지식: { doc_type: "knowledge", source: "seed", owner, category }
FAQ:  { doc_type: "faq", source: "seed", owner, category: "faq" }
  ↓
ChromaDB
```

---

## 5. 구현 완료 체크리스트

### Backend
- [x] ChromaDB 저장 시 모든 지식에 **doc_type**, **source** 필드 포함 (기본값: knowledge, api)
- [x] **POST /api/knowledge**: body에 doc_type, source 수신 및 저장
- [x] **GET /api/knowledge**: query param doc_type, source로 where 조건 추가; 응답 metadata에 doc_type, source 포함
- [x] **add_from_hitl**: doc_type="knowledge", source="hitl", 메타데이터에 owner 사용
- [x] **시드 데이터**: 지식/FAQ에 doc_type, source 추가

### Frontend
- [x] **types**: DOC_TYPES, KNOWLEDGE_SOURCES, KnowledgeItem.metadata에 doc_type, source 추가
- [x] **목록**: 필터 doc_type, source 추가; 테이블에 doc_type, source 컬럼 표시
- [x] **추가 폼**: doc_type 선택 (기본 knowledge), POST 시 doc_type, source="api" 전송

---

## 6. 테스트 가이드

### 6.1 Backend 재시작
```bash
cd c:\work\workspace_sippbx\sip-pbx
python src/main.py
```

### 6.2 Frontend 재시작
```bash
cd c:\work\workspace_sippbx\sip-pbx\frontend
npm run dev
```

### 6.3 수동 테스트 시나리오

1. **지식 추가 (doc_type=knowledge)**
   - 대시보드 → 지식 베이스 페이지
   - 카테고리: "질의·FAQ"
   - 문서 유형: "지식 (일반/통화·HITL)" (기본값)
   - 내용 입력 후 저장
   - **확인**: 목록에서 doc_type="지식 (일반/통화·HITL)", source="대시 입력" 표시

2. **필터 테스트**
   - doc_type 필터: "지식 (일반/통화·HITL)" 선택
   - source 필터: "대시 입력" 선택
   - 새로고침 → 해당 조건 데이터만 표시

3. **시드 데이터 확인**
   - owner="1003" 또는 "1004" 필터
   - source="시드" 필터
   - **확인**: 시드 데이터의 doc_type, source 확인

4. **API 직접 테스트**
   ```bash
   # GET (필터 포함)
   curl "http://localhost:8000/api/knowledge?owner=1003&doc_type=knowledge&source=api"
   
   # POST
   curl -X POST http://localhost:8000/api/knowledge \
     -H "Content-Type: application/json" \
     -d '{"text":"테스트 지식","owner":"1003","category":"question","doc_type":"knowledge","source":"api"}'
   ```

---

## 7. 향후 확장 가능성

1. **통화 추출 승인 후 적재**
   - 통화 내용 추출 → 검토 → 승인 시 ChromaDB 저장
   - `doc_type = "knowledge"`, `source = "call"`

2. **메뉴얼 업로드 (미구현)**
   - `doc_type = "manual_chunk"`, `source = "manual_upload"`

3. **RAG 검색 최적화**
   - question/unknown intent: owner만 필터 (doc_type 무관)
   - 필요 시 "doc_type in [knowledge, faq]만 검색" 옵션 추가

4. **통계 및 분석**
   - doc_type별 지식 건수
   - source별 출처 분석
   - owner별 지식 분포

---

## 8. 요약

### 핵심 달성 사항
✅ **통화로 적재되는 모든 경우 doc_type = knowledge** 규칙 적용 완료  
✅ Backend/Frontend 모두 doc_type, source 필드 지원  
✅ 대시보드에서 doc_type/source 필터 및 표시 기능 구현  
✅ HITL, 시드 데이터에 doc_type/source 자동 할당  

### 변경된 파일 목록
**Backend:**
- `src/api/knowledge_router.py`
- `src/ai_voicebot/knowledge/knowledge_service.py`
- `src/services/knowledge_service.py` (add_from_hitl)
- `src/services/seed_data.py`

**Frontend:**
- `frontend/types/index.ts`
- `frontend/app/knowledge/page.tsx`

### 다음 단계
- 서버 재시작 후 동작 확인
- 실제 통화 테스트를 통한 HITL 저장 검증
- (선택) 통화 추출 승인 워크플로 구현 시 `doc_type=knowledge, source=call` 적용

---

**구현 완료**: 2026-03-16  
**담당**: AI Assistant  
**검토**: 사용자 테스트 필요
