# VectorDB 연동 완료 보고서

**작성일**: 2026-01-08  
**작업**: localhost VectorDB 연동 구현

---

## ✅ 구현 완료 사항

### 1️⃣ **Knowledge Service 생성**
- **파일**: `src/services/knowledge_service.py`
- **기능**:
  - VectorDB + Embedder 통합
  - 지식 추가/검색/삭제
  - 통계 조회
  - 싱글톤 패턴

### 2️⃣ **Knowledge API → VectorDB 연동**
- **파일**: `src/api/routers/knowledge.py`
- **변경 사항**:
  - Mock DB → ChromaDB로 전환
  - GET `/api/knowledge` - VectorDB에서 조회
  - POST `/api/knowledge` - VectorDB에 저장
  - PUT `/api/knowledge/{id}` - VectorDB 업데이트
  - DELETE `/api/knowledge/{id}` - VectorDB에서 삭제

### 3️⃣ **서버 시작 시 초기화**
- **파일**: `src/api/main.py`
- **기능**: Startup 이벤트에서 VectorDB 초기화 및 샘플 데이터 로드

---

## 🔧 사용된 기술 스택

| 항목 | 기술 | 버전 |
|------|------|------|
| **VectorDB** | ChromaDB | 0.4.22 |
| **Embedder** | sentence-transformers | 2.2.2 |
| **임베딩 모델** | paraphrase-multilingual-mpnet-base-v2 | - |
| **임베딩 차원** | 768 | - |
| **유사도 측정** | Cosine Similarity | - |

---

## 📦 데이터 저장 위치

```
sip-pbx/
└── data/
    └── chromadb/           # ChromaDB 영구 저장소
        ├── chroma.sqlite3  # 메타데이터
        └── ...             # 임베딩 데이터
```

---

## 🚀 사용 방법

### 1. **Backend API 서버 재시작**

```bash
# 기존 서버 종료 (Ctrl+C)

# 서버 재시작
cd sip-pbx
python -m src.api.main
```

### 2. **VectorDB 초기화 확인**

서버 시작 로그에서 확인:
```
INFO: API Gateway starting up...
INFO: ChromaDB initialized, collection=knowledge_base, count=0
INFO: Sample knowledge data initialized in VectorDB, count=3
INFO: API Gateway startup complete
```

### 3. **Frontend에서 지식 추가 테스트**

1. `http://localhost:3000/knowledge` 접속
2. **"지식 추가"** 버튼 클릭
3. 지식 내용 입력:
   - **카테고리**: FAQ
   - **내용**: "배송은 주문 후 2-3일 소요됩니다."
   - **키워드**: 배송, 배송기간, 얼마나
4. **"저장"** 클릭
5. Knowledge 목록에서 확인

### 4. **AI가 지식 활용 확인**

```python
# Python에서 테스트
import asyncio
from src.services.knowledge_service import get_knowledge_service

async def test():
    ks = get_knowledge_service()
    await ks.initialize()
    
    # 검색 테스트
    results = await ks.search_knowledge("영업시간이 어떻게 되나요?", top_k=3)
    
    for r in results:
        print(f"Score: {r['score']:.3f}")
        print(f"Text: {r['text']}")
        print("---")

asyncio.run(test())
```

---

## 🧪 API 테스트 예시

### ✅ 지식 추가 (POST)

```bash
curl -X POST http://localhost:8000/api/knowledge \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer mock_token_operator_1" \
  -d '{
    "text": "배송은 결제 완료 후 영업일 기준 2-3일 소요됩니다.",
    "category": "faq",
    "keywords": ["배송", "배송기간", "며칠"],
    "metadata": {"source": "manual", "addedBy": "operator"}
  }'
```

**응답**:
```json
{
  "id": "kb_20260108_153022_123456",
  "text": "배송은 결제 완료 후 영업일 기준 2-3일 소요됩니다.",
  "category": "faq",
  "keywords": ["배송", "배송기간", "며칠"],
  "metadata": {"source": "manual", "addedBy": "operator", ...},
  "created_at": "2026-01-08T15:30:22.123456"
}
```

### ✅ 지식 검색 (GET)

```bash
# 검색어로 검색
curl "http://localhost:8000/api/knowledge?search=배송&limit=5" \
  -H "Authorization: Bearer mock_token_operator_1"
```

**응답**:
```json
{
  "items": [
    {
      "id": "kb_20260108_153022_123456",
      "text": "배송은 결제 완료 후 영업일 기준 2-3일 소요됩니다.",
      "category": "faq",
      "keywords": ["배송", "배송기간", "며칠"],
      ...
    }
  ],
  "total": 1,
  "page": 1,
  "limit": 5
}
```

### ✅ 지식 삭제 (DELETE)

```bash
curl -X DELETE http://localhost:8000/api/knowledge/kb_20260108_153022_123456 \
  -H "Authorization: Bearer mock_token_operator_1"
```

**응답**:
```json
{
  "success": true,
  "id": "kb_20260108_153022_123456"
}
```

---

## 📊 통계 조회

```python
from src.services.knowledge_service import get_knowledge_service

ks = get_knowledge_service()
await ks.initialize()
stats = await ks.get_stats()

print(stats)
# {
#   "total_documents": 4,
#   "vectordb": {
#     "type": "chromadb",
#     "collection_name": "knowledge_base",
#     "total_documents": 4,
#     "total_upserts": 4,
#     "total_searches": 10,
#     "total_deletes": 0
#   },
#   "embedder": {
#     "total_embeddings": 14,
#     "total_texts": 523,
#     "model_name": "paraphrase-multilingual-mpnet-base-v2",
#     "dimension": 768,
#     "avg_text_length": 37.36
#   }
# }
```

---

## 🔍 VectorDB 데이터 확인 (직접)

```python
import chromadb

client = chromadb.PersistentClient(path="./data/chromadb")
collection = client.get_collection("knowledge_base")

# 전체 문서 수
print(f"Total documents: {collection.count()}")

# 모든 문서 조회
results = collection.get(include=["documents", "metadatas"])
for i, doc_id in enumerate(results['ids']):
    print(f"\nID: {doc_id}")
    print(f"Text: {results['documents'][i]}")
    print(f"Metadata: {results['metadatas'][i]}")
```

---

## ⚠️ 주의사항

### 1. **Embedder 모델 다운로드**
첫 실행 시 `paraphrase-multilingual-mpnet-base-v2` 모델이 자동 다운로드됩니다 (약 1GB).

### 2. **VectorDB 백업**
```bash
# ChromaDB 데이터 백업
cp -r ./data/chromadb ./backup/chromadb_20260108
```

### 3. **VectorDB 초기화 (리셋)**
```bash
# 모든 데이터 삭제 후 재생성
rm -rf ./data/chromadb
# 서버 재시작하면 샘플 데이터가 자동 생성됨
```

---

## 🎯 다음 단계

### Priority 1: AI RAG 연동
- [ ] AI Orchestrator가 KnowledgeService 사용하도록 수정
- [ ] RAG Engine을 VectorDB와 연동

### Priority 2: 고급 기능
- [ ] 카테고리별 컬렉션 분리
- [ ] 임베딩 캐싱
- [ ] 검색 결과 Re-ranking

### Priority 3: 운영 기능
- [ ] VectorDB 백업/복원 스크립트
- [ ] 통계 대시보드
- [ ] 벌크 업로드 API

---

## 📚 참고 문서

- [ChromaDB Documentation](https://docs.trychroma.com/)
- [Sentence Transformers](https://www.sbert.net/)
- [Multilingual Models](https://www.sbert.net/docs/pretrained_models.html#multi-lingual-models)

---

**작성자**: AI Assistant  
**상태**: ✅ 구현 완료, 테스트 대기

