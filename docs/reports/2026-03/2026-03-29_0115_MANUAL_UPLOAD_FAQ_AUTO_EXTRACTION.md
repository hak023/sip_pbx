# TXT 매뉴얼 업로드 및 FAQ 자동 추출 기능 구현

**작성일**: 2026-03-29  
**기능**: 지식 베이스 매뉴얼 TXT 업로드 → LLM FAQ 자동 추출 → ChromaDB 저장  
**위치**: `sip-pbx/`, `frontend/`

---

## 개요

운영자가 **TXT 파일 형태의 매뉴얼**을 업로드하면, 시스템이 자동으로:
1. **청킹**: 매뉴얼을 4-8KB 청크로 분할 (자연스러운 구분자 기준)
2. **LLM 추출**: 각 청크에서 "사용자가 물을 법한 질문"과 "답변" 쌍 추출
3. **중복 제거**: 동일 질문 통합
4. **ChromaDB 저장**: FAQ 형태로 지식 베이스에 저장

### 목표
- **빠른 지식 확장**: 수십 페이지 매뉴얼을 수작업으로 FAQ 입력하는 대신, TXT 업로드 한 번으로 자동 처리
- **일관성**: LLM이 구어체 질문 형태로 변환하여 사용자 질의와 유사도 향상
- **효율성**: 500KB 이하 파일, 30초~2분 내 처리

---

## 아키텍처

```
Frontend (/knowledge/upload)
   ↓ TXT 파일 + Owner ID
   ↓ POST /api/knowledge/upload-manual?owner=1004
Backend API (knowledge_api.py)
   ↓ 파일 검증 (500KB, .txt)
   ↓ UTF-8/CP949 디코딩
ManualToFAQExtractor
   ↓ chunk_text() → 4-8KB 청크
   ↓ extract_faqs_from_chunk() (LLM)
   ↓ 각 청크 → JSON [Q&A 쌍]
   ↓ deduplicate_faqs()
KnowledgeService
   ↓ add_knowledge() → ChromaDB
   ↓ owner, doc_type=faq, source=manual_upload
Response
   ↓ {faqs_extracted: 15, faqs_saved: 15}
Frontend
   ↓ 결과 표시 + 대시보드 복귀
```

---

## 구현 내역

### 1. Backend - TXT → FAQ 추출 서비스

**파일**: `sip-pbx/src/ai_voicebot/knowledge/manual_to_faq_extractor.py`

**핵심 클래스**:

```python
class ManualToFAQExtractor:
    """매뉴얼 TXT → FAQ 변환 서비스"""
    
    CHUNK_MIN_SIZE = 2000  # 2KB
    CHUNK_MAX_SIZE = 8000  # 8KB
    CHUNK_OVERLAP = 100    # 100자 오버랩
    
    async def chunk_text(self, text: str) -> List[Dict[str, Any]]
    async def extract_faqs_from_chunk(self, chunk_text: str, chunk_id: int) -> List[Dict[str, str]]
    async def deduplicate_faqs(self, faqs: List[Dict[str, str]]) -> List[Dict[str, str]]
    async def extract_faqs_from_manual(self, text: str, source_filename: str) -> Dict[str, Any]
```

**청킹 전략**:
- **우선순위**: `\n\n` (단락) > `\n` (줄) > `.` (마침표) > ` ` (공백)
- **오버랩**: 청크 간 100자 오버랩으로 문맥 유지
- **크기**: 2KB~8KB (LLM context 최적화)

**LLM 프롬프트**:
```
역할: 조직 매뉴얼을 분석하여 FAQ를 추출하는 전문가

입력: 매뉴얼 텍스트
출력: JSON 형식 Q&A 쌍 리스트

규칙:
1. 질문은 자연스러운 구어체
2. 답변은 간결하고 정확하게 (2-3문장)
3. 명확한 사실 정보만 추출
4. 관련 정보는 하나의 Q&A로 통합
5. 모호한 정보는 제외

출력 예시:
[
  {
    "question": "영업 시간이 어떻게 되나요?",
    "answer": "평일은 11시 30분부터 밤 10시까지...",
    "category": "운영시간"
  }
]
```

**중복 제거**:
- 질문 정규화 (공백 제거, 소문자) 후 exact match
- 향후 개선: Embedding 유사도 기반 중복 제거

### 2. Backend - Knowledge Service

**파일**: `sip-pbx/src/services/knowledge_service.py`

**핵심 메서드**:

```python
class KnowledgeService:
    async def add_knowledge(text, category, keywords, metadata) -> Dict[str, Any]
    async def get_all_knowledge(category, limit) -> List[Dict[str, Any]]
    async def delete_knowledge(doc_id) -> bool

# 전역 접근자
async def initialize_knowledge_service(vector_db, embedder, extraction_pending_file)
def set_knowledge_service(service)
def get_knowledge_service() -> Optional[KnowledgeService]
```

**Factory 통합**: `factory.py`의 `create_ai_orchestrator`에서 초기화

### 3. Backend - API 엔드포인트

**파일**: `sip-pbx/src/api/routers/knowledge_api.py`

**신규 엔드포인트**:

```http
POST /api/knowledge/upload-manual?owner=1004
Content-Type: multipart/form-data

file: restaurant_manual.txt (최대 500KB)

Response:
{
  "success": true,
  "faqs_extracted": 15,
  "faqs_saved": 15,
  "source_file": "restaurant_manual.txt",
  "elapsed_sec": 45.2
}
```

**파일 검증**:
- **형식**: `.txt` 확장자만 허용
- **크기**: 최대 500KB
- **인코딩**: UTF-8 우선, CP949 fallback

**처리 흐름**:
1. 파일 검증 및 디코딩
2. `ManualToFAQExtractor.extract_faqs_from_manual` 호출
3. `extract_and_save_faqs_from_txt`로 ChromaDB 저장
4. 결과 반환 (추출 개수, 저장 개수, 처리 시간)

### 4. Frontend - 지식 추가 버튼

**파일**: `frontend/app/dashboard/page.tsx`

**변경**:
```tsx
<a
  href="/knowledge/upload"
  className="px-3 py-1 text-sm bg-blue-600 text-white rounded hover:bg-blue-700 transition"
>
  📚 지식 추가
</a>
```

대시보드 헤더에 "📚 지식 추가" 버튼 추가

### 5. Frontend - 매뉴얼 업로드 페이지

**파일**: `frontend/app/knowledge/upload/page.tsx`

**주요 기능**:
1. **Owner ID 입력**: 착신번호 (예: 1004)
2. **TXT 파일 선택**: 
   - 500KB 제한
   - `.txt` 형식만 허용
   - 파일 크기 표시
3. **업로드 및 처리**:
   - `POST /api/knowledge/upload-manual` 호출
   - 진행 상태 표시 ("파일 업로드 중...")
   - 에러 처리 및 표시
4. **결과 표시**:
   - 추출된 FAQ 개수
   - 저장된 FAQ 개수
   - 처리 시간
   - "대시보드로 돌아가기" 버튼

**UI/UX**:
- 깔끔한 폼 레이아웃
- 실시간 파일 검증 (크기, 형식)
- 로딩 인디케이터 (Spinner + 진행 메시지)
- 성공/실패 피드백 (색상 코딩: 녹색/빨간색)
- 안내사항 섹션 (처리 시간, 사용법 설명)

---

## 사용 예시

### 예시 1: 식당 매뉴얼

**입력 TXT** (`restaurant_manual.txt`):
```
우리 식당은 정통 이탈리아 요리 전문점입니다.

영업 시간:
- 평일: 11:30 - 22:00
- 주말: 10:00 - 23:00

주차 안내:
건물 지하 1층에 30대 규모 무료 주차장 운영 중.
발레파킹 서비스 제공.

대표 메뉴:
- 까르보나라 파스타
- 마르게리타 피자
- 안심 스테이크
```

**추출 FAQ**:
```json
[
  {
    "question": "영업 시간이 어떻게 되나요?",
    "answer": "평일은 오전 11시 30분부터 밤 10시까지, 주말은 오전 10시부터 밤 11시까지 운영합니다.",
    "category": "운영시간"
  },
  {
    "question": "주차가 가능한가요?",
    "answer": "건물 지하 1층에 30대 규모의 무료 주차장을 운영하고 있습니다. 발레파킹 서비스도 제공합니다.",
    "category": "주차"
  },
  {
    "question": "대표 메뉴는 무엇인가요?",
    "answer": "까르보나라 파스타, 마르게리타 피자, 안심 스테이크 등이 인기 메뉴입니다.",
    "category": "메뉴"
  }
]
```

### 예시 2: 기상청 특보 안내

**입력 TXT** (`weather_manual.txt`):
```
기상특보 종류:

1. 태풍 주의보: 태풍으로 인한 강풍과 호우 예상
2. 황사 경보: 미세먼지 농도 800㎍/㎥ 이상
3. 폭염 경보: 최고 기온 35도 이상, 2일 이상 지속
```

**추출 FAQ**:
```json
[
  {
    "question": "태풍 주의보는 무엇인가요?",
    "answer": "태풍으로 인한 강풍과 호우가 예상될 때 발령되는 기상특보입니다.",
    "category": "기상특보"
  },
  {
    "question": "황사 경보 기준이 어떻게 되나요?",
    "answer": "미세먼지 농도가 800㎍/㎥ 이상일 때 황사 경보가 발령됩니다.",
    "category": "기상특보"
  }
]
```

---

## 저장 구조 (ChromaDB)

```python
{
    "id": "kb_20260329_0115_456789",
    "document": "Q: 영업 시간이 어떻게 되나요?\nA: 평일은 오전 11시 30분부터...",
    "metadata": {
        "owner": "1004",
        "doc_type": "faq",
        "source": "manual_upload:restaurant_manual.txt",
        "question": "영업 시간이 어떻게 되나요?",
        "answer": "평일은 오전 11시 30분부터...",
        "category": "운영시간",
        "source_file": "restaurant_manual.txt",
        "faq_index": 0,
        "created_at": "2026-03-29T01:15:30.456789"
    },
    "embedding": [0.123, -0.456, ...],
}
```

---

## API 명세

### POST /api/knowledge/upload-manual

**Request**:
```http
POST /api/knowledge/upload-manual?owner=1004
Content-Type: multipart/form-data

file: (binary TXT file)
```

**Query Parameters**:
- `owner` (required): Owner ID (착신번호, 예: 1004)

**Response (Success)**:
```json
{
  "success": true,
  "faqs_extracted": 15,
  "faqs_saved": 15,
  "source_file": "restaurant_manual.txt",
  "elapsed_sec": 45.2
}
```

**Response (Error)**:
```json
{
  "detail": "파일 크기가 너무 큽니다. (최대 500KB, 현재: 650KB)"
}
```

**Status Codes**:
- `200`: 성공
- `400`: 잘못된 요청 (파일 형식, 크기, 디코딩 오류)
- `503`: 서비스 불가 (LLM 또는 Knowledge Service 미초기화)

---

## Frontend UI

### 1. 대시보드 - 지식 추가 버튼

**위치**: `frontend/app/dashboard/page.tsx`

**변경사항**: 헤더에 "📚 지식 추가" 버튼 추가 (`/knowledge/upload`로 이동)

### 2. 매뉴얼 업로드 페이지

**경로**: `/knowledge/upload`  
**파일**: `frontend/app/knowledge/upload/page.tsx`

**화면 구성**:

1. **헤더**:
   - 제목: "📚 지식 베이스 - 매뉴얼 업로드"
   - "← 대시보드" 버튼

2. **업로드 폼**:
   - **Owner ID 입력**: 텍스트 필드 (기본값: 1004)
   - **TXT 파일 선택**: 파일 업로드 버튼 (500KB 제한, `.txt`만)
   - **선택된 파일 정보**: 파일명, 크기 표시 (파란색 배경)

3. **진행 상태**:
   - **업로드 중**: Spinner + "파일 업로드 중..." (노란색 배경)
   - **에러**: 빨간색 박스에 에러 메시지
   - **성공**: 녹색 박스에 결과 표시
     - 파일명
     - 추출된 FAQ 개수
     - 저장된 FAQ 개수
     - 처리 시간
     - "대시보드로 돌아가기" 버튼

4. **액션 버튼**:
   - **업로드 및 FAQ 추출**: 파란색 (파일 선택 시 활성화)
   - **취소**: 회색 (대시보드로 복귀)

5. **안내사항** (회색 박스):
   - TXT 파일 내용 설명
   - AI 자동 변환 설명
   - 파일 크기 제한
   - 예상 처리 시간 (30초~2분)

---

## 처리 흐름 상세

### 1단계: TXT 청킹

```python
# 입력: "본 식당은...영업 시간...주차 안내...대표 메뉴..." (50KB)
# 출력: [
#   {"chunk_id": 0, "text": "본 식당은...영업 시간...", "size": 5200},
#   {"chunk_id": 1, "text": "...영업 시간...주차 안내...", "size": 6800},  # 100자 오버랩
#   {"chunk_id": 2, "text": "...주차 안내...대표 메뉴...", "size": 4900},
# ]
```

**로그**:
```
manual_text_chunked | total_size=50000 chunk_count=8 avg_chunk_size=6250
```

### 2단계: LLM FAQ 추출 (청크별)

```python
# 각 청크 → LLM 프롬프트 → JSON 파싱
# Chunk 0 → 3개 FAQ
# Chunk 1 → 5개 FAQ
# ...
# Total: 18개 FAQ (중복 제거 전)
```

**로그** (청크별):
```
chunk_faq_extraction_success | chunk_id=0 chunk_size=5200 faqs_extracted=3
chunk_faq_extraction_success | chunk_id=1 chunk_size=6800 faqs_extracted=5
```

### 3단계: 중복 제거

```python
# 18개 → 15개 (중복 3개 제거)
# 예: "영업 시간이 어떻게 되나요?" vs "영업 시간 알려주세요" → 정규화 후 동일
```

**로그**:
```
faq_deduplication | original_count=18 unique_count=15 removed_count=3
```

### 4단계: ChromaDB 저장

```python
# 각 FAQ → add_knowledge()
# 15개 FAQ → 15개 문서 저장
```

**로그** (FAQ별):
```
knowledge_added | doc_id=kb_20260329_0115_456789 category=운영시간 text_preview="Q: 영업 시간이 어떻게..."
```

**최종 로그**:
```
manual_upload_complete | owner=1004 source_file=restaurant_manual.txt faqs_extracted=15 faqs_saved=15
```

---

## 성능 및 제약사항

### 성능

- **500KB 파일**: 약 30초~2분 (LLM 호출 횟수에 비례)
- **청크 수**: 500KB → 약 8~10청크 (6-8KB/청크)
- **LLM 호출**: 청크당 1회 (병렬 처리 가능하나 API 쿼터 고려)
- **FAQ 개수**: 500KB → 50~100개 FAQ 예상 (매뉴얼 밀도에 따라)

### 제약사항

1. **파일 크기**: 최대 500KB
2. **파일 형식**: TXT만 지원 (PDF, DOCX 미지원)
3. **인코딩**: UTF-8, CP949만 지원
4. **LLM 정확도**: 모호한 정보나 표 형식은 추출 실패 가능
5. **중복 제거**: 단순 정규화 기반 (향후 Embedding 유사도로 개선 필요)

---

## 개선 방향

### 단기
1. **PDF/DOCX 지원**: Python `pypdf`, `python-docx` 라이브러리 추가
2. **표 형식 처리**: Markdown Table로 변환 후 LLM 프롬프트 개선
3. **진행률 표시**: WebSocket으로 실시간 진행률 전송 (청크 처리 상태)

### 중기
1. **Embedding 유사도 중복 제거**: 질문 Embedding 간 cosine similarity > 0.95면 중복 처리
2. **병렬 LLM 호출**: 청크별 FAQ 추출을 병렬로 처리 (API 쿼터 관리 필요)
3. **FAQ 검토 UI**: 추출된 FAQ를 저장 전에 운영자가 수정/삭제할 수 있는 중간 단계

### 장기
1. **다국어 지원**: 영어, 일본어 매뉴얼 자동 번역 후 FAQ 추출
2. **이미지 OCR**: 스캔된 매뉴얼 이미지에서 텍스트 추출
3. **증분 업데이트**: 동일 파일 재업로드 시 변경 부분만 추출

---

## 테스트 시나리오

### 시나리오 1: 식당 매뉴얼 업로드

1. 대시보드 → "📚 지식 추가" 클릭
2. Owner ID: `1003` 입력
3. `restaurant_manual.txt` (15KB) 업로드
4. "업로드 및 FAQ 추출" 클릭
5. **예상 결과**:
   - 30초 후 "✅ 업로드 완료"
   - 추출 FAQ: 8개
   - 저장 FAQ: 8개

**검증**:
- 전화 걸기 → "영업 시간이 어떻게 되나요?" 질문
- AI 응답: "평일은 오전 11시 30분부터..." (FAQ에서 가져옴)

### 시나리오 2: 대용량 매뉴얼 (500KB)

1. Owner ID: `1004`
2. `manual_large.txt` (480KB) 업로드
3. **예상 결과**:
   - 90초~120초 후 완료
   - 추출 FAQ: 50~60개
   - 저장 FAQ: 45~55개 (중복 제거)

### 시나리오 3: 에러 케이스

**3-1. 파일 크기 초과**:
- `manual_large.txt` (600KB) 업로드
- **에러**: "파일 크기가 너무 큽니다. (최대 500KB, 현재: 586KB)"

**3-2. 잘못된 파일 형식**:
- `manual.pdf` 업로드
- **에러**: "TXT 파일만 업로드 가능합니다."

**3-3. 빈 파일**:
- `empty.txt` (0KB) 업로드
- **에러**: "파일이 비어 있습니다."

---

## 로그 추적

### 정상 흐름 로그

```
manual_upload_received | owner=1004 filename=restaurant_manual.txt size_kb=15 text_length=15360
manual_text_chunked | total_size=15360 chunk_count=2 avg_chunk_size=7680
chunk_faq_extraction_success | chunk_id=0 chunk_size=7780 faqs_extracted=4
chunk_faq_extraction_success | chunk_id=1 chunk_size=7680 faqs_extracted=4
faq_deduplication | original_count=8 unique_count=8 removed_count=0
manual_faq_extraction_complete | source_file=restaurant_manual.txt chunks_processed=2 faqs_extracted=8 faqs_unique=8 elapsed_sec=32.5
knowledge_added | doc_id=kb_20260329_0115_001 category=운영시간 text_preview="Q: 영업 시간이..."
knowledge_added | doc_id=kb_20260329_0115_002 category=주차 text_preview="Q: 주차가 가능한..."
...
manual_upload_complete | owner=1004 source_file=restaurant_manual.txt faqs_extracted=8 faqs_saved=8
```

### 에러 로그 (JSON 파싱 실패)

```
chunk_faq_json_parse_error | chunk_id=3 error="Expecting value: line 1 column 1" response_preview="The operating hours are..."
```

**원인**: LLM이 JSON이 아닌 자연어로 응답  
**대응**: 프롬프트 개선 또는 JSON 모드 재시도

---

## 보안 및 주의사항

1. **파일 검증**: 반드시 `.txt` 확장자 검증 (스크립트 업로드 방지)
2. **크기 제한**: 500KB 엄격 제한 (DoS 방지)
3. **Owner 검증**: 향후 인증 시스템 통합 시 Owner 권한 확인 필요
4. **PII 검토**: 매뉴얼에 개인정보 포함 시 자동 마스킹 또는 경고 (향후 개선)

---

## 관련 파일

### Backend
- `sip-pbx/src/ai_voicebot/knowledge/manual_to_faq_extractor.py`: TXT → FAQ 변환 서비스
- `sip-pbx/src/services/knowledge_service.py`: Knowledge CRUD 서비스
- `sip-pbx/src/api/routers/knowledge_api.py`: API 엔드포인트
- `sip-pbx/src/ai_voicebot/factory.py`: 싱글톤 초기화

### Frontend
- `frontend/app/dashboard/page.tsx`: 지식 추가 버튼
- `frontend/app/knowledge/upload/page.tsx`: 매뉴얼 업로드 페이지

---

## 테스트 체크리스트

- [ ] 작은 TXT 파일 (10KB) 업로드 → FAQ 추출 확인
- [ ] 큰 TXT 파일 (400KB) 업로드 → 처리 시간 측정
- [ ] 파일 크기 초과 (600KB) → 에러 메시지 확인
- [ ] PDF 파일 업로드 → 형식 검증 확인
- [ ] 빈 TXT 파일 → 에러 처리 확인
- [ ] UTF-8 인코딩 파일 → 정상 디코딩
- [ ] CP949 인코딩 파일 → Fallback 디코딩
- [ ] 추출된 FAQ로 전화 응대 → RAG 검색 확인
- [ ] 중복 질문 포함 매뉴얼 → 중복 제거 확인

---

## 마이그레이션 가이드

기존 시스템에서 이 기능을 활성화하려면:

1. **서버 재시작**: Factory가 Knowledge Service 초기화
2. **Frontend 빌드**: `npm run build` (Next.js 라우트 생성)
3. **대시보드 접속**: "📚 지식 추가" 버튼 확인
4. **테스트 업로드**: 샘플 TXT 파일로 FAQ 추출 검증

---

## 요약

- **목적**: TXT 매뉴얼을 업로드하여 LLM으로 FAQ 자동 추출 → 지식 베이스 저장
- **핵심**: 청킹 → LLM 추출 → 중복 제거 → ChromaDB 저장
- **UI**: 대시보드 "지식 추가" 버튼 → 업로드 페이지 → 진행/결과 표시
- **API**: `POST /api/knowledge/upload-manual?owner=1004`
- **제약**: 500KB, TXT만, UTF-8/CP949 인코딩
- **성능**: 30초~2분 (파일 크기에 비례)

이 기능으로 운영자는 **수작업 FAQ 입력 시간을 대폭 절감**하고, **대량의 매뉴얼을 빠르게 지식 베이스화**할 수 있습니다.
