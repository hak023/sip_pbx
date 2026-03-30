# 지식베이스 TXT 업로드 에러 수정 (재발)

**작성일**: 2026-03-29 17:40  
**에러 시각**: 2026-03-29T17:37:35 (KST)  
**에러 메시지**: `object list can't be used in 'await' expression`  
**발생 파일**: `src/services/knowledge_service.py:52`

---

## 1. 에러 요약

### 1.1 에러 로그

```
timestamp: 2026-03-29T17:37:35.004
event: knowledge_add_error
error: object list can't be used in 'await' expression
text_preview: Q: 오늘이나 내일 비가 올까요? 몇 시쯤 올지 알 수 있을까요?
```

**영향**:
- TXT 파일에서 추출된 **8개 FAQ 모두 저장 실패**
- FAQ 추출은 성공 (`faqs_extracted: 8`)
- 저장 실패 (`faqs_saved: 0`)

### 1.2 재발 사유

**이전 수정** (2026-03-29 16:30):
- `src/api/routers/knowledge_api.py`의 `add_from_hitl` 호출 방식 수정
- HITL 지식 저장은 **정상 작동**

**이번 에러**:
- **매뉴얼 TXT 업로드**에서 발생
- `manual_to_faq_extractor.py` → `knowledge_service.add_knowledge` 호출 시 에러
- **다른 코드 경로**에서 동일한 버그 재발

---

## 2. 근본 원인

### 2.1 문제 코드

**파일**: `src/services/knowledge_service.py`  
**라인**: 52

```python
async def add_knowledge(
    self,
    text: str,
    category: str = "question",
    keywords: List[str] = None,
    metadata: Dict[str, Any] = None,
) -> Dict[str, Any]:
    try:
        # 임베딩 생성
        embedding = await self._embedder.embed_text(text)  ← ⚠️ 버그!
        
        # ChromaDB 저장
        await asyncio.to_thread(
            self._vector_db.add,
            ids=[doc_id],
            embeddings=[embedding],  ← embedding은 이미 List[float]
            documents=[text],
            metadatas=[meta],
        )
```

### 2.2 버그 설명

**`TextEmbedder.embed_text()`**:
- **동기 메서드** (일반 함수)
- 반환 타입: `List[float]` (예: `[0.1, 0.2, ..., 0.768]`)

**`await embed_text(text)`**:
- `embed_text`는 코루틴이 아니므로 **await 불가**
- Python이 `List[float]` 객체에 `__await__` 메서드가 있는지 확인
- `list`는 awaitable이 아님 → **에러 발생**

**에러 메시지 해석**:
```
object list can't be used in 'await' expression
```
= "`list` 타입 객체는 `await` 표현식에 사용할 수 없습니다"

### 2.3 올바른 호출 방법

**방법 1: 비동기 메서드 사용** (권장)

```python
embedding = await self._embedder.embed(text)  ← 수정!
```

**`embed()`**:
- **비동기 메서드** (async def)
- 내부에서 `asyncio.to_thread(embed_text, text)` 호출
- 블로킹 방지

**방법 2: 동기 메서드 직접 호출**

```python
embedding = self._embedder.embed_text(text)  ← await 제거
```

**단점**:
- SentenceTransformer가 **블로킹** (CPU 집약적)
- 이벤트 루프 차단 가능

---

## 3. 수정 내용

### 3.1 수정 파일

**파일**: `c:\work\workspace_sippbx\sip-pbx\src\services\knowledge_service.py`

### 3.2 수정 전

```python
async def add_knowledge(
    self,
    text: str,
    category: str = "question",
    keywords: List[str] = None,
    metadata: Dict[str, Any] = None,
) -> Dict[str, Any]:
    try:
        # 임베딩 생성
        embedding = await self._embedder.embed_text(text)  ← 버그
```

### 3.3 수정 후

```python
async def add_knowledge(
    self,
    text: str,
    category: str = "question",
    keywords: List[str] = None,
    metadata: Dict[str, Any] = None,
) -> Dict[str, Any]:
    try:
        # 임베딩 생성 (비동기 메서드 사용)
        embedding = await self._embedder.embed(text)  ← 수정
```

**변경 사항**:
- `embed_text` → `embed` (비동기 메서드 사용)
- 주석 명확화

---

## 4. 영향 범위

### 4.1 호출 경로

**경로 1: 매뉴얼 TXT 업로드** (이번 에러)
```
manual_to_faq_extractor.py
  → extract_and_save_faqs()
    → knowledge_service.add_knowledge()  ← 에러 발생
```

**경로 2: HITL 지식 저장** (정상 작동)
```
knowledge_api.py
  → add_from_hitl()
    → knowledge_service.add_from_hitl()
      → knowledge_service.add_knowledge()  ← 동일 메서드
```

**왜 HITL은 정상?**:
- HITL은 **정상 작동한 것으로 보고됨** (이전 수정)
- 하지만 **동일한 버그**가 존재함
- → **HITL도 테스트 필요**

### 4.2 테스트 필요 항목

- [ ] 매뉴얼 TXT 업로드 재테스트
- [ ] HITL 지식 저장 재테스트
- [ ] 직접 지식 추가 API 테스트

---

## 5. 테스트 방법

### 5.1 매뉴얼 TXT 업로드

**테스트 파일**: `sip-pbx/logs/기상청_매뉴얼.txt`

**API 호출**:
```bash
curl -X POST http://localhost:8001/api/knowledge/manual-upload \
  -F "file=@logs/기상청_매뉴얼.txt" \
  -H "Authorization: Bearer <token>"
```

**기대 결과**:
```json
{
  "success": true,
  "faqs_extracted": 8,
  "faqs_saved": 8,  ← 8개 모두 저장되어야 함
  "source_file": "기상청_매뉴얼.txt"
}
```

**로그 확인**:
```
knowledge_added (8회)
manual_upload_complete (faqs_saved: 8)
```

### 5.2 HITL 지식 저장

**테스트 방법**:
1. 통화 중 HITL 발생
2. 운영자가 Q&A 입력
3. "지식베이스 추가" 체크 후 전송
4. 통화 종료

**로그 확인**:
```
knowledge_added_from_hitl
hitl_kb_flushed
```

---

## 6. 이전 수정과의 관계

### 6.1 이전 수정 (2026-03-29 16:30)

**파일**: `src/api/routers/knowledge_api.py`

**수정 내용**:
- `result = await knowledge_service.add_from_hitl(...)` 호출 시
- 반환값이 `dict`였는데 `await`하려 함
- → `add_from_hitl`은 **이미 async 메서드**였으므로 정상

**이번 수정**:
- `add_knowledge` 메서드 **내부**의 버그
- `embedder.embed_text`를 잘못 호출

**관계**:
- 이전 수정은 **호출 방식** 문제
- 이번 수정은 **메서드 내부** 구현 문제
- **별개의 버그**

### 6.2 왜 이전에 발견되지 않았나?

**추정**:
1. HITL 기능은 **실제로 테스트되지 않았음**
2. 또는 **에러가 발생했으나 로그에서 누락**
3. 매뉴얼 업로드가 **먼저 실행되어 에러 발견**

---

## 7. 추가 발견: embed vs embed_text

### 7.1 TextEmbedder 메서드 비교

**`embed_text(text: str) -> List[float]`**:
- **동기 메서드**
- SentenceTransformer 직접 호출 (블로킹)
- 동기 코드에서 사용

**`async embed(text: str) -> List[float]`**:
- **비동기 메서드**
- 내부에서 `asyncio.to_thread(embed_text, text)` 호출
- 이벤트 루프 차단 방지

### 7.2 사용 가이드

**비동기 컨텍스트** (`async def`):
```python
embedding = await embedder.embed(text)  ← 권장
```

**동기 컨텍스트**:
```python
embedding = embedder.embed_text(text)  ← 직접 호출
```

**잘못된 사용**:
```python
embedding = await embedder.embed_text(text)  ← ❌ 에러!
```

---

## 8. 체크리스트

- [x] 에러 원인 분석
- [x] `knowledge_service.py` 수정 (`embed_text` → `embed`)
- [ ] 백엔드 재시작
- [ ] 매뉴얼 TXT 업로드 재테스트 (8개 FAQ 저장 확인)
- [ ] HITL 지식 저장 테스트
- [ ] 로그 확인 (`knowledge_added`, `knowledge_add_error` 없음)

---

## 9. 관련 파일

**수정 파일**:
- `src/services/knowledge_service.py` (line 52)

**테스트 파일**:
- `logs/기상청_매뉴얼.txt` (27줄)

**관련 리포트**:
- `docs/reports/2026-03/2026-03-29_1630_KNOWLEDGE_TXT_UPLOAD_ERROR_FIX.md` (이전 수정)

---

**수정 완료**: `embed_text` → `embed` (비동기 메서드 호출)  
**다음 단계**: 백엔드 재시작 후 매뉴얼 TXT 업로드 재테스트  
**예상 결과**: FAQ 8개 모두 정상 저장 (`faqs_saved: 8`)
