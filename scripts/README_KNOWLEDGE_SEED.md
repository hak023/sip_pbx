# 1004 기상청 지식베이스 예제 시드

테넌트 **1004 (기상청)** 에 기상·날씨 관련 예제 지식 10건을 넣는 방법입니다.

## 데이터

- **scripts/knowledge_seed_1004_weather.json** — 예제 10건 (text, category, keywords)
- 카테고리: 소개, 일기예보, 기상특보, 미세먼지, 예보안내, 이용안내

## 방법 1: API로 시드 (권장)

**조건**: 백엔드 API 서버가 떠 있고, **ChromaDB·임베더가 사용 가능한 상태**일 때 (AI Voicebot 준비 완료 후 권장).

```bash
# sip-pbx 디렉터리에서
python scripts/seed_knowledge_1004_via_api.py
# 또는 API URL 지정
python scripts/seed_knowledge_1004_via_api.py http://localhost:8000
```

- 200/201이면 정상 추가.
- **500** 이 나오면: 서버 로그 확인.
  - `no such column: collections.topic` → ChromaDB 클라이언트와 DB 스키마 버전 불일치. **`pip install 'chromadb>=0.5.0'`** 후 재시작하거나, 지식 데이터를 비울 수 있으면 `data/chroma` 폴더 삭제 후 재시작. 자세한 내용: **docs/reports/CHROMA_COLLECTIONS_TOPIC_ERROR.md**
  - `ChromaDB or embedder not available` → 통합 서버(start-all 등)로 AI Voicebot까지 기동된 뒤 다시 실행.

## 방법 2: 직접 ChromaDB + 임베더

**조건**: 프로젝트 가상환경에 `sentence-transformers`, `chromadb` 등이 설치되어 있고, numpy 호환 이슈가 없을 때.

```bash
python scripts/seed_knowledge_1004_weather.py
```

- 임베더 로드 실패(예: numpy 호환 오류) 시에는 방법 1 사용.

## 확인

- 프론트: http://localhost:3000/knowledge → 테넌트 **1004 - 기상청** 선택 후 목록에 10건 표시되는지 확인.
- API: `GET http://localhost:8000/api/knowledge?tenant_id=sip%3A1004%40unknown&page=1&limit=20` → `total`, `items` 확인.

## 점검 및 진단 (목록이 비어 보일 때)

1. **ChromaDB 1004 데이터 점검 스크립트** (API 서버 불필요, 동일 경로 사용)
   ```bash
   python scripts/check_chromadb_1004.py
   ```
   - 출력: ChromaDB 경로, 컬렉션 전체 문서 수, **owner=1004** 문서 수, 샘플 3건.
   - 전체 0이면 시드를 아직 안 한 것. 1004만 0이면 다른 owner로 저장됐거나 tenant_id 정규화 불일치.

2. **지식 API 진단 엔드포인트** (서버 기동 후)
   ```bash
   curl -s "http://localhost:8000/api/knowledge/debug/tenant/1004"
   # 또는 tenant_id에 sip:1004@unknown 도 가능
   curl -s "http://localhost:8000/api/knowledge/debug/tenant/sip%3A1004%40unknown"
   ```
   - `vector_db_available`, `chroma_path`, `owner_filter`, `total_in_collection`, `total_for_owner` 로 원인 파악.
   - `total_for_owner` 가 0이고 `total_in_collection` > 0 이면, 저장 시 **metadata.owner** 를 `"1004"` 로 넣었는지 확인 (시드 스크립트는 owner=1004 사용).

## 지식 검색(RAG)에서의 활용

- 통화 시 **착신번호(callee)=1004** 로 걸리면, RAG 검색 시 **owner_filter=1004** 로 같은 ChromaDB 지식 컬렉션을 검색합니다.
- LangGraph 경로·레거시 경로 모두 `owner_filter` 를 넘기도록 되어 있어, 1004 테넌트 지식만 검색에 사용됩니다.
