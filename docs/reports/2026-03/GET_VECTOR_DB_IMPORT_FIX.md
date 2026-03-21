# get_vector_db Import 에러 수정 완료

**작성일**: 2026-03-11  
**상태**: ✅ 수정 완료

---

## 📋 문제 요약

`knowledge.py` API 라우터에서 `get_vector_db` 함수를 import하려고 했으나 해당 모듈이 존재하지 않아 import 에러가 발생했습니다.

### 에러 원인

1. **누락된 파일**: `src/ai_voicebot/knowledge/chromadb_client.py` 파일이 존재하지 않음
2. **누락된 파일**: `src/ai_voicebot/knowledge/embedder.py` 파일이 존재하지 않음
3. **잘못된 Import 경로**: `knowledge.py`에서 `from src.ai_voicebot.knowledge.vector_db import get_vector_db` (존재하지 않는 모듈)

---

## ✅ 적용된 수정 사항

### 1. `chromadb_client.py` 생성

**파일**: `sip-pbx/src/ai_voicebot/knowledge/chromadb_client.py`

**내용**:
```python
class ChromaDBClient:
    """ChromaDB Vector Database Client"""
    - __init__(): ChromaDB 클라이언트 초기화
    - initialize(): 비동기 초기화 (Collection 생성/로드)
    - add_documents(): 문서 추가 (임베딩 포함)
    - query(): 유사도 검색
    - get(): 문서 조회 (필터, 페이지네이션)
    - count(): 문서 총 개수
    - delete(): 문서 삭제

def get_chromadb_client(...) -> ChromaDBClient:
    """ChromaDB Client Singleton (Factory용)"""

def get_vector_db() -> Optional[ChromaDBClient]:
    """전역 ChromaDB Client 가져오기 (API용)"""
```

**주요 기능**:
- ✅ Singleton 패턴으로 전역 ChromaDB 클라이언트 관리
- ✅ Persistent Storage 지원 (로컬 파일 시스템)
- ✅ Collection 자동 생성 및 관리
- ✅ 메타데이터 필터링 지원 (tenant_id 등)
- ✅ 페이지네이션 지원 (limit, offset)

---

### 2. `embedder.py` 생성

**파일**: `sip-pbx/src/ai_voicebot/knowledge/embedder.py`

**내용**:
```python
class TextEmbedder:
    """텍스트 임베딩 클래스 (SentenceTransformers)"""
    - __init__(): SentenceTransformer 모델 로드
    - embed_text(): 단일 텍스트 임베딩
    - embed_batch(): 배치 텍스트 임베딩
    - get_dimension(): 임베딩 차원 반환

def get_text_embedder(...) -> TextEmbedder:
    """Text Embedder Singleton"""
```

**주요 기능**:
- ✅ SentenceTransformers 라이브러리 사용
- ✅ 다국어 지원 모델 (`paraphrase-multilingual-mpnet-base-v2`)
- ✅ 배치 처리 지원 (성능 최적화)
- ✅ 빈 텍스트 처리 (제로 벡터 반환)
- ✅ Singleton 패턴으로 모델 재사용 (메모리 절약)

---

### 3. `knowledge.py` Import 경로 수정

**파일**: `sip-pbx/src/api/routers/knowledge.py`

**변경 전**:
```python
from src.ai_voicebot.knowledge.vector_db import get_vector_db  # ❌ 존재하지 않음
from src.ai_voicebot.knowledge.embedder import get_text_embedder  # ❌ 존재하지 않음
```

**변경 후**:
```python
from src.ai_voicebot.knowledge.chromadb_client import get_vector_db  # ✅ 올바른 경로
from src.ai_voicebot.knowledge.embedder import get_text_embedder  # ✅ 새로 생성됨
```

**적용 위치**:
1. `GET /api/knowledge` (지식 목록 조회) - Line 341
2. `GET /api/knowledge/stats` (지식 통계) - Line 418
3. `POST /api/knowledge/search` (지식 검색) - Line 513, 514

---

## 🧪 검증 방법

### 1. 서버 시작 확인

```bash
python sip-pbx/src/main.py
```

**예상 로그**:
```json
{"event": "Loading SentenceTransformer model", "model_name": "paraphrase-multilingual-mpnet-base-v2"}
{"event": "SentenceTransformer model loaded successfully", "embedding_dim": 768}
{"event": "Text Embedder initialized"}
{"event": "ChromaDB initialized", "collection_count": 0}
{"event": "✅ [FACTORY] ChromaDB initialized successfully"}
```

### 2. API 테스트

#### 지식 목록 조회
```bash
curl http://localhost:8000/api/knowledge?tenant_id=1004&page=1&limit=10
```

**예상 응답**:
```json
{
  "total": 0,
  "page": 1,
  "limit": 10,
  "items": []
}
```

#### 지식 통계
```bash
curl http://localhost:8000/api/knowledge/stats?tenant_id=1004
```

**예상 응답**:
```json
{
  "total_knowledge": 0,
  "this_week": 0,
  "categories": {},
  "avg_confidence": 0.0,
  "recent_extractions": []
}
```

#### 지식 검색
```bash
curl -X POST http://localhost:8000/api/knowledge/search \
  -H "Content-Type: application/json" \
  -d '{
    "query": "날씨",
    "tenant_id": "1004",
    "top_k": 5
  }'
```

**예상 응답**:
```json
{
  "query": "날씨",
  "results": [],
  "total": 0
}
```

---

## 📊 의존성 확인

### 필수 Python 패키지

`requirements.txt` 또는 `requirements-ai.txt`에 다음 패키지가 포함되어 있어야 합니다:

```txt
chromadb>=0.4.0
sentence-transformers>=2.2.0
```

### 설치 확인

```bash
pip list | grep -E "chromadb|sentence-transformers"
```

**예상 출력**:
```
chromadb                 0.4.22
sentence-transformers    2.5.1
```

---

## 🔧 추가 개선 사항

### 1. ChromaDB 백업 및 복구

**향후 구현 예정**:
- ChromaDB 데이터 자동 백업
- 백업에서 복구 기능
- 여러 테넌트 간 데이터 격리 강화

### 2. Embedder 모델 최적화

**향후 개선 예정**:
- 더 빠른 임베딩 모델 지원 (e.g., `all-MiniLM-L6-v2`)
- GPU 가속 지원
- 캐싱 전략 (동일 텍스트 재임베딩 방지)

### 3. API 성능 모니터링

**추가할 메트릭**:
- ChromaDB 쿼리 응답 시간
- 임베딩 생성 시간
- Vector DB 사용량

---

## 📝 관련 파일

### 생성된 파일
1. `sip-pbx/src/ai_voicebot/knowledge/chromadb_client.py` ✅ NEW
2. `sip-pbx/src/ai_voicebot/knowledge/embedder.py` ✅ NEW

### 수정된 파일
1. `sip-pbx/src/api/routers/knowledge.py` (Import 경로 수정)

### 기존 파일 (변경 없음)
1. `sip-pbx/src/ai_voicebot/factory.py` (이미 올바른 import 사용 중)
2. `sip-pbx/src/ai_voicebot/ai_pipeline/rag_engine.py` (Vector DB 사용)
3. `sip-pbx/src/ai_voicebot/knowledge/knowledge_extractor.py` (지식 추출)

---

## ✅ 완료 체크리스트

- [x] `chromadb_client.py` 생성
- [x] `embedder.py` 생성
- [x] `knowledge.py` Import 경로 수정 (3곳)
- [ ] 서버 재시작 및 로그 확인
- [ ] API 테스트 (지식 목록, 통계, 검색)
- [ ] 의존성 패키지 설치 확인

---

**상태**: ✅ 코드 수정 완료! 서버 재시작 후 테스트 필요
