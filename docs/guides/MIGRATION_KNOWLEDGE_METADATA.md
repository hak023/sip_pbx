# ChromaDB 메타데이터 마이그레이션 가이드

**작성일**: 2026-03-16  
**목적**: 기존 ChromaDB 데이터를 KNOWLEDGE_DOC_TYPE_DESIGN 스키마에 맞게 업데이트

---

## 개요

기존 ChromaDB에 저장된 지식 데이터에 다음 필드를 추가합니다:
- `doc_type`: 문서 유형 (knowledge, faq, capability, tenant_config)
- `source`: 출처 (api, hitl, call, seed)
- `created_at`: 생성 시각 (ISO 8601)

---

## 마이그레이션 스크립트

### 위치
```
scripts/migrate_knowledge_metadata.py
```

### 기능
1. **자동 추론**: 기존 메타데이터 및 doc_id 패턴으로 `doc_type`, `source` 추론
2. **안전 모드**: `--dry-run` 옵션으로 실제 변경 전 검토 가능
3. **배치 업데이트**: 모든 문서의 메타데이터를 한 번에 업데이트

### 추론 규칙

#### doc_type 추론
| 조건 | 추론 값 | 설명 |
|------|---------|------|
| metadata에 `response_type` 또는 `display_name` 존재 | `capability` | AI 서비스 정의 |
| metadata에 `tenant_name` 또는 `tenant_type` 존재 | `tenant_config` | 테넌트 설정 |
| `category == "faq"` | `faq` | FAQ 데이터 |
| 이미 `doc_type` 필드 존재 | 기존 값 유지 | - |
| 기타 | `knowledge` | 일반 지식 (기본값) |

#### source 추론
| 조건 | 추론 값 | 설명 |
|------|---------|------|
| doc_id가 `hitl_`로 시작 | `hitl` | HITL로 저장된 지식 |
| doc_id가 `kb_seed_` 또는 `faq_seed_`로 시작 | `seed` | 시드 데이터 |
| doc_id가 `cap_`로 시작 | `seed` | Capability 시드 |
| doc_id가 `tenant_config_`로 시작 | `seed` | 테넌트 설정 시드 |
| metadata에 `call_id` 존재 | `call` | 통화 추출 데이터 |
| 이미 `source` 필드 존재 | 기존 값 유지 | - |
| 기타 | `api` | 수동 입력 (기본값) |

---

## 실행 방법

### 1. DRY-RUN (권장, 먼저 실행)
실제 변경 없이 분석 및 예상 결과만 확인:
```bash
cd c:\work\workspace_sippbx\sip-pbx
python scripts/migrate_knowledge_metadata.py --dry-run
```

**출력 예시:**
```
================================================================================
ChromaDB 지식 메타데이터 마이그레이션
================================================================================
모드: DRY-RUN (실제 변경 없음)

[1/5] ChromaDB 연결 중...
✓ 컬렉션 연결 성공: knowledge

[2/5] 기존 데이터 조회 중...
✓ 총 50건의 문서 발견

[3/5] 메타데이터 분석 중...
✓ 분석 완료:
  - 업데이트 필요: 35건
  - 이미 완료: 15건

📋 업데이트 예시 (최대 5개):

  ID: kb_20260115_abc123
    현재 category: question
    현재 owner: 1003
    추가할 doc_type: knowledge
    추가할 source: api
    추가할 created_at: (현재 시각)
  ...

[5/5] 메타데이터 업데이트 중...
  [DRY-RUN] kb_20260115_abc123: doc_type=knowledge, source=api
  ...

================================================================================
마이그레이션 완료
================================================================================
총 문서: 50건
업데이트(예정): 35건
건너뜀: 15건
오류: 0건

ℹ DRY-RUN 모드로 실행되었습니다. 실제 변경은 없습니다.
  실제 마이그레이션을 수행하려면: python scripts/migrate_knowledge_metadata.py
```

### 2. 실제 마이그레이션 실행
DRY-RUN 결과를 확인 후 실제 마이그레이션 수행:

#### 옵션 A: 확인 후 실행 (권장)
```bash
python scripts/migrate_knowledge_metadata.py
```
→ 업데이트 전 사용자 확인 요청

#### 옵션 B: 즉시 실행
```bash
python scripts/migrate_knowledge_metadata.py --force
```
→ 확인 없이 즉시 실행 (자동화 스크립트용)

### 3. 결과 확인
```bash
# 마이그레이션 후 일부 데이터 확인
python -c "
from src.ai_voicebot.knowledge.chromadb_client import get_vector_db
vdb = get_vector_db()
results = vdb.get(limit=5)
for i, doc_id in enumerate(results['ids']):
    meta = results['metadatas'][i]
    print(f'{doc_id}: doc_type={meta.get(\"doc_type\")}, source={meta.get(\"source\")}')
"
```

---

## 마이그레이션 전 체크리스트

- [ ] **백업 생성** (선택사항, 권장)
  ```bash
  # ChromaDB 데이터 디렉토리 백업
  cp -r data/chroma data/chroma_backup_20260316
  ```

- [ ] **DRY-RUN 실행 및 결과 검토**
  ```bash
  python scripts/migrate_knowledge_metadata.py --dry-run
  ```

- [ ] **추론 규칙 확인**
  - 예상치 못한 `doc_type` 또는 `source` 할당이 있는지 확인
  - 필요 시 스크립트 수정 후 재실행

- [ ] **서비스 중단** (선택사항, 안전성을 위해 권장)
  - Backend 서버 중단
  - 마이그레이션 실행
  - 서버 재시작

---

## 마이그레이션 후 확인 사항

### 1. Backend API 테스트
```bash
# 전체 목록 조회
curl "http://localhost:8000/api/knowledge?owner=1003"

# doc_type 필터 테스트
curl "http://localhost:8000/api/knowledge?owner=1003&doc_type=knowledge"

# source 필터 테스트
curl "http://localhost:8000/api/knowledge?owner=1003&source=seed"
```

### 2. Frontend 확인
1. 대시보드 로그인
2. 지식 베이스 페이지 접근
3. 목록에서 **doc_type**, **source** 컬럼 표시 확인
4. 필터 드롭다운으로 필터링 테스트

### 3. 통계 확인
```python
from src.ai_voicebot.knowledge.chromadb_client import get_vector_db

vdb = get_vector_db()
results = vdb.get(limit=10000)

# doc_type별 통계
doc_types = {}
for meta in results['metadatas']:
    dt = meta.get('doc_type', 'N/A')
    doc_types[dt] = doc_types.get(dt, 0) + 1

print("doc_type별 통계:")
for dt, count in sorted(doc_types.items()):
    print(f"  {dt}: {count}건")

# source별 통계
sources = {}
for meta in results['metadatas']:
    src = meta.get('source', 'N/A')
    sources[src] = sources.get(src, 0) + 1

print("\nsource별 통계:")
for src, count in sorted(sources.items()):
    print(f"  {src}: {count}건")
```

---

## 트러블슈팅

### 오류: "ChromaDB 연결 실패"
**원인**: ChromaDB 경로 또는 권한 문제  
**해결**:
```bash
# ChromaDB 경로 확인
python -c "from src.ai_voicebot.knowledge.chromadb_client import get_chroma_persist_path; print(get_chroma_persist_path())"

# 디렉토리 존재 및 권한 확인
ls -la data/chroma
```

### 오류: "데이터 조회 실패"
**원인**: 컬렉션이 비어있거나 손상됨  
**해결**:
```python
from src.ai_voicebot.knowledge.chromadb_client import get_vector_db
vdb = get_vector_db()
print(f"Collection: {vdb.collection.name}")
print(f"Count: {vdb.collection.count()}")
```

### 일부 문서만 업데이트하고 싶은 경우
스크립트를 수정하여 특정 조건의 문서만 필터링:
```python
# migrate_knowledge_metadata.py 수정 예시
# 특정 owner만 마이그레이션
results = collection.get(
    where={"owner": "1003"},
    limit=10000,
    include=["documents", "metadatas", "embeddings"]
)
```

---

## 롤백 방법

마이그레이션 전 백업을 생성한 경우:
```bash
# 백업 복원
rm -rf data/chroma
cp -r data/chroma_backup_20260316 data/chroma

# 서버 재시작
```

백업이 없는 경우, 수동으로 필드 제거 (권장하지 않음):
```python
from src.ai_voicebot.knowledge.chromadb_client import get_vector_db

vdb = get_vector_db()
collection = vdb.collection
results = collection.get(limit=10000, include=["documents", "metadatas", "embeddings"])

for i, doc_id in enumerate(results["ids"]):
    meta = dict(results["metadatas"][i])
    # doc_type, source, created_at 제거
    meta.pop("doc_type", None)
    meta.pop("source", None)
    # created_at은 유지 권장
    
    collection.upsert(
        ids=[doc_id],
        embeddings=[results["embeddings"][i]],
        documents=[results["documents"][i]],
        metadatas=[meta]
    )
```

---

## 요약

1. **백업 생성** (권장)
2. **DRY-RUN 실행**: `python scripts/migrate_knowledge_metadata.py --dry-run`
3. **결과 검토**: 추론된 doc_type, source 확인
4. **실제 마이그레이션**: `python scripts/migrate_knowledge_metadata.py`
5. **확인**: API 및 Frontend에서 새 필드 표시 확인

---

**작성자**: AI Assistant  
**최종 업데이트**: 2026-03-16
