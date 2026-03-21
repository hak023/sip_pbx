# Knowledge API 422 에러 분석 및 해결

**작성일**: 2026-03-16  
**문제**: 프론트엔드에서 지식 베이스 추가 시 422 Unprocessable Entity 에러 발생

---

## 1. 에러 내용

```json
[{
  "type": "missing",
  "loc": ["body", "tenant_id"],
  "msg": "Field required",
  "input": {
    "text": "안녕하세요. 기상청AI입니다.",
    "owner": "1004",
    "category": "greeting_phase1",
    "answer": "안녕하세요. 기상청AI입니다.",
    "source": "api"
  },
  "url": "https://errors.pydantic.dev/2.12/v/missing"
}]
```

**증상**: FastAPI가 request body에서 `tenant_id` 필드를 찾으려고 시도하지만, 실제로는 query parameter로 정의됨

---

## 2. 근본 원인

### 2.1 Pydantic BaseModel과 Query 파라미터의 충돌

FastAPI에서 **Pydantic BaseModel과 Query 파라미터를 동시에 사용**할 때, 특정 상황에서 FastAPI가 Query 파라미터를 body의 필드로 잘못 인식하는 버그가 있음.

**문제 있던 코드**:
```python
@router.post("/knowledge")
async def post_knowledge(
    body: KnowledgeCreateRequest,
    vector_db: Any = Depends(get_vector_db_dep),
    tenant_id: Optional[str] = Query(None, ...),  # ← 문제!
):
```

### 2.2 시도한 해결 방법들 (실패)

1. **파라미터 순서 변경**: Query를 마지막으로 이동 → 실패
2. **프론트엔드에서 query parameter 제거**: URL에서 `?tenant_id=...` 제거 → 실패 (브라우저 캐시)
3. **Pydantic 모델에서 owner를 Optional로 변경**: → 여전히 tenant_id를 body에서 찾으려 함

### 2.3 실제 원인

- **Pydantic v2의 validation 메커니즘**이 함수 시그니처를 분석할 때, `Query()`로 명시되어 있어도 특정 조건에서 body field로 취급
- 특히 `Optional[str] = Query(None)`처럼 기본값이 None인 경우 더 혼동됨

---

## 3. 해결 방법

### 3.1 Query 파라미터 완전 제거

`tenant_id`는 실제로 사용되지 않으므로 (owner가 body에 있음) 완전히 제거:

```python
class KnowledgeCreateRequest(BaseModel):
    text: str = Field(..., description="지식 내용 (필수)", min_length=1)
    owner: str = Field(..., description="소유자 ID (필수)")  # ← Required로 변경
    category: str = Field(..., description="카테고리 (필수)")
    answer: Optional[str] = Field(None, description="답변")
    source: Optional[str] = Field("api", description="출처")
    call_id: Optional[str] = Field(None, description="통화 ID")

@router.post("/knowledge")
async def post_knowledge(
    request: Request,  # ← 로깅용 추가
    body: KnowledgeCreateRequest,
    vector_db: Any = Depends(get_vector_db_dep),
):
    # tenant_id 파라미터 제거됨
```

### 3.2 상세 로깅 추가

디버깅을 위한 구조화 로그 추가:

```python
logger.info("knowledge_api_request",
            method="POST",
            path=str(request.url),
            body_text_len=len(body.text),
            body_owner=body.owner,
            body_category=body.category,
            has_answer=bool(body.answer),
            source=body.source)
```

**주요 로그 이벤트**:
- `knowledge_api_request`: 요청 수신 시
- `knowledge_api_validation_failed`: validation 실패 시
- `knowledge_api_adding`: 지식 추가 시작
- `knowledge_api_added`: 지식 추가 완료
- `knowledge_api_caching`: 즉시 캐싱 시작
- `knowledge_api_cached`: 캐싱 완료
- `knowledge_api_cache_failed`: 캐싱 실패

---

## 4. 테스트 방법

### 4.1 백엔드 재시작
```bash
# sip-pbx 디렉토리에서
python -m src.main
```

### 4.2 프론트엔드 Hard Refresh
**중요**: 브라우저 캐시를 완전히 무효화해야 함

- **Chrome/Edge**: `Ctrl + Shift + R` (Windows) / `Cmd + Shift + R` (Mac)
- **Firefox**: `Ctrl + Shift + Delete` → 캐시 삭제
- **또는**: 개발자도구(F12) → Network 탭 → "Disable cache" 체크

### 4.3 테스트 시나리오

1. 프론트엔드 지식 베이스 페이지 접속
2. 지식 추가 폼 입력:
   - **카테고리**: 인사 (시작/첫 응답)
   - **내용**: "안녕하세요. 기상청AI입니다."
   - **응답**: "안녕하세요. 기상청AI입니다."
3. **저장** 클릭
4. 예상 결과: `저장됨 (doc_id: xxx, 즉시 캐시됨)` 메시지 표시

### 4.4 로그 확인

```bash
# app.log에서 확인
tail -f logs/app.log | grep knowledge_api
```

정상 흐름:
```json
{"event": "knowledge_api_request", "body_owner": "1004", "body_category": "greeting_phase1"}
{"event": "knowledge_api_adding", "owner": "1004", "category": "greeting_phase1"}
{"event": "knowledge_api_added", "doc_id": "kb_xxx", "needs_cache": true}
{"event": "knowledge_api_caching", "owner": "1004", "category": "greeting_phase1"}
{"event": "knowledge_api_cached", "owner": "1004", "category": "greeting_phase1"}
```

---

## 5. 관련 파일

### 수정된 파일
1. `src/api/knowledge_router.py`
   - Query 파라미터 제거
   - Pydantic 모델에서 `owner`를 Required로 변경
   - 상세 로깅 추가

2. `frontend/app/knowledge/page.tsx`
   - URL에서 `?tenant_id=...` query parameter 제거
   - 422 에러 메시지를 문자열로 변환 (JSON.stringify)

### 관련 이슈
- **seed_data_failed**: `embed()` → `embed_text()` 메서드명 수정 (별도)
- **transcript.txt 분리 문제**: 화자별 발화 단위 그룹화 (별도)

---

## 6. 향후 권장사항

### 6.1 API 설계
- Pydantic BaseModel과 Query/Path 파라미터를 **혼용하지 않기**
- 모든 파라미터는 body 또는 query 중 하나로 통일
- 중복 파라미터(`owner`와 `tenant_id`) 제거

### 6.2 에러 핸들링
- FastAPI의 422 에러는 validation error로, `detail`이 객체 배열
- 프론트엔드에서 `JSON.stringify()`로 변환하여 표시

### 6.3 로깅
- 모든 API endpoint에 구조화된 로그 추가
- 요청/응답/에러 상황을 명확히 구분
- `request_id` 등 추적 ID 추가 고려

---

## 7. 결론

**422 에러의 근본 원인**: FastAPI + Pydantic v2의 파라미터 해석 메커니즘에서 Query와 Body를 혼용할 때 발생하는 충돌

**해결책**: 불필요한 Query 파라미터 제거 + owner를 Required로 명시 + 상세 로깅

이제 지식 베이스 API는 명확한 계약(contract)을 가지며, 문제 발생 시 로그를 통해 즉시 진단 가능합니다.
