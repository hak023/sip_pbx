# ChromaDB Schema Error 해결 가이드

**에러**: `no such column: collections.topic`  
**발생일**: 2026-03-17  
**상태**: 해결 방법 제시

---

## 문제 요약

### 에러 메시지
```
ChromaDB sync init failed (schema mismatch): no such column: collections.topic
```

### 로그 위치
- Line 2851: Knowledge Extractor 초기화 실패
- Line 2895: AI Voicebot 초기화 실패
- Line 2910: Seed data 적재 실패

---

## 원인 분석

### 1. ChromaDB 버전
- **설치된 버전**: 1.5.0 (requirements-ai.txt)
- **요구 버전**: >= 1.5.0, < 2.0.0 ✅

### 2. 스키마 불일치
- **기존 data/chroma**: 구버전 (0.4.x 이하) 스키마로 생성
- **현재 ChromaDB**: 1.5.0은 `collections.topic` 컬럼 필요
- **충돌**: 구버전 DB에는 해당 컬럼이 없음

### 3. 파일 현황
```powershell
C:\work\workspace_sippbx\sip-pbx\data\chroma
├── (26개 파일 존재)
└── 구버전 스키마로 생성됨
```

---

## 해결 방법

### ✅ 방법 1: data/chroma 폴더 삭제 후 재시작 (권장)

#### 단계

1. **서버 중지**
   ```bash
   # Ctrl+C로 서버 중지
   ```

2. **백업 생성 (선택사항)**
   ```powershell
   # Windows
   Move-Item "data\chroma" "data\chroma.backup_20260317"
   
   # 또는 복사
   Copy-Item "data\chroma" "data\chroma.backup_20260317" -Recurse
   ```

3. **폴더 삭제**
   ```powershell
   # Windows
   Remove-Item "data\chroma" -Recurse -Force
   
   # Linux/Mac
   rm -rf data/chroma
   ```

4. **서버 재시작**
   ```bash
   python -m src.main
   ```

5. **자동 재생성 확인**
   - ChromaDB가 신버전 스키마로 자동 생성됨
   - Seed data가 자동으로 적재됨 (1003, 1004 테넌트)
   - 로그에서 `seed_data_run_from_main` 확인

#### 장점
- 가장 안전하고 확실한 방법
- 스키마 불일치 완전 해결
- Seed data 자동 재적재

#### 단점
- 기존 수동 입력 데이터 손실 (백업 필요)

---

### 방법 2: ChromaDB 다운그레이드 (비권장)

구버전 스키마를 유지하려면:

```bash
pip install 'chromadb==0.4.24'
```

**주의**: 신기능 사용 불가, 권장하지 않음

---

### 방법 3: 수동 마이그레이션 (고급)

SQLite 직접 수정:

```sql
-- data/chroma/chroma.sqlite3
ALTER TABLE collections ADD COLUMN topic TEXT;
```

**주의**: 
- 다른 스키마 변경도 필요할 수 있음
- 데이터 손상 위험
- 권장하지 않음

---

## 삭제 후 복구되는 데이터

### 자동 재생성되는 데이터 (Seed Data)

#### 테넌트 1003 (이탈리안 비스트로)
- Knowledge: 5개 항목
- FAQ: 3개 항목
- Capability: 기본 업무 안내

#### 테넌트 1004 (기상청)
- Knowledge: 7개 항목 (인사말 포함)
- FAQ: 4개 항목
- Capability: 기상 정보 안내

### 손실되는 데이터

1. **Frontend에서 수동 입력한 지식**
   - `/knowledge` 페이지에서 추가한 항목
   - 백업 권장

2. **HITL 응답으로 저장된 지식**
   - 운영자가 답변하면서 저장한 항목
   - `source=hitl`인 항목들

3. **통화 중 자동 추출된 지식** (Knowledge Extraction)
   - `source=call`인 항목들
   - 현재는 비활성화 상태이므로 영향 없음

---

## 백업이 필요한 경우

### 백업 스크립트

```python
# scripts/backup_chromadb.py
import chromadb
from chromadb.config import Settings

# 기존 DB 연결 (구버전)
try:
    client = chromadb.PersistentClient(
        path="data/chroma",
        settings=Settings(anonymized_telemetry=False)
    )
    
    collection = client.get_collection("knowledge")
    
    # 모든 데이터 추출
    results = collection.get(include=["documents", "metadatas", "embeddings"])
    
    # JSON으로 저장
    import json
    with open("data/chromadb_backup.json", "w", encoding="utf-8") as f:
        json.dump(results, f, ensure_ascii=False, indent=2)
    
    print(f"백업 완료: {len(results['ids'])} 항목")
    
except Exception as e:
    print(f"백업 실패: {e}")
    print("구버전 스키마로는 접근 불가능할 수 있습니다.")
```

### 복원 스크립트

```python
# scripts/restore_chromadb.py
import json
from src.ai_voicebot.knowledge.knowledge_service import KnowledgeService

with open("data/chromadb_backup.json", "r", encoding="utf-8") as f:
    data = json.load(f)

knowledge_service = KnowledgeService()

for i in range(len(data["ids"])):
    doc_id = data["ids"][i]
    text = data["documents"][i]
    metadata = data["metadatas"][i]
    
    # KnowledgeService를 통해 재적재
    knowledge_service.add_knowledge(
        text=text,
        owner=metadata.get("owner", "1004"),
        category=metadata.get("category", "knowledge"),
        answer=metadata.get("answer", text),
        doc_type=metadata.get("doc_type", "knowledge"),
        source=metadata.get("source", "api"),
    )
    print(f"복원: {doc_id}")

print(f"복원 완료: {len(data['ids'])} 항목")
```

---

## 실행 명령어 요약

### 빠른 해결 (백업 없이)

```powershell
# 1. 서버 중지 (Ctrl+C)

# 2. 폴더 삭제
Remove-Item "data\chroma" -Recurse -Force

# 3. 서버 재시작
python -m src.main
```

### 안전한 해결 (백업 포함)

```powershell
# 1. 서버 중지 (Ctrl+C)

# 2. 백업
Move-Item "data\chroma" "data\chroma.backup_20260317"

# 3. 서버 재시작
python -m src.main

# 4. 문제 발생 시 복원
# Remove-Item "data\chroma" -Recurse -Force
# Move-Item "data\chroma.backup_20260317" "data\chroma"
```

---

## 확인 방법

### 1. 로그 확인
```bash
# 성공 로그
grep "ChromaDB sync init" logs/app.log
grep "seed_data_run" logs/app.log

# 에러 없어야 함
grep "no such column" logs/app.log
```

### 2. API 테스트
```bash
# Knowledge 조회
curl http://localhost:8000/api/knowledge?owner=1004

# 응답에 데이터 있어야 함
```

### 3. Frontend 테스트
- http://localhost:3000/knowledge 접속
- 테넌트 1004 선택
- 지식 목록 표시 확인

---

## 재발 방지

### 1. requirements-ai.txt 버전 고정
```txt
chromadb>=1.5.0,<2.0.0  # ✅ 이미 설정됨
```

### 2. 마이그레이션 스크립트 준비
- 향후 ChromaDB 2.x 업그레이드 시 사용
- `scripts/migrate_chromadb.py` 작성

### 3. 정기 백업
- 주요 지식 데이터는 별도 백업
- Git으로 seed_data.py 관리

---

## 관련 문서

- `requirements-ai.txt` - ChromaDB 버전 명세
- `src/services/seed_data.py` - 초기 데이터 정의
- `docs/reports/MIGRATION_COMPLETED.md` - Knowledge 분류 마이그레이션

---

## 요약

### 권장 해결 방법
1. ✅ **data/chroma 폴더 삭제**
2. ✅ **서버 재시작**
3. ✅ **Seed data 자동 적재 확인**

### 소요 시간
- 삭제: 1초
- 재시작: ~100초 (AI 모델 로딩 포함)
- 총: ~2분

### 데이터 손실
- Seed data: 자동 복구 ✅
- 수동 입력 데이터: 손실 (백업 권장) ⚠️

---

**작성자**: AI Assistant  
**최종 업데이트**: 2026-03-17
