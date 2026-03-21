# RAG DB 로깅

## 개요

RAG 검색 결과를 DB에 남겨 분석·디버깅에 사용할 수 있도록 `ai_logging` 모듈을 구현해 두었습니다.

- **위치**: `sip-pbx/ai_logging/`
- **API**: `set_db_client(db)`, `log_rag_search(...)`, `use_sqlite_file(path)`, `init_sqlite_schema()`

## 사용법

### 1. 앱 기동 시 DB 설정

**SQLite 파일 사용 (권장)**

```python
from ai_logging import use_sqlite_file, init_sqlite_schema, set_db_client

# 데이터 디렉터리 등에 파일 생성
use_sqlite_file("data/rag_log.db")
init_sqlite_schema()
```

**기존 DB 연결 주입**

```python
from ai_logging import set_db_client, init_sqlite_schema

set_db_client(existing_connection)  # sqlite3.Connection 또는 .execute/.commit 지원 객체
init_sqlite_schema()
```

### 2. RAG 검색 직후 호출

```python
from ai_logging import log_rag_search

# Vector 검색 완료 시점에 호출
log_rag_search(
    call_id=call_id,
    query=query,
    owner_filter=owner_filter,
    results_count=len(results),
    latency_ms=elapsed_ms,
    doc_ids=[d.id for d in results] if results else None,
    top_score=results[0].score if results else None,
    similarity_threshold=0.7,
    top_k=6,
)
```

- `set_db_client()`가 **호출되지 않았으면** `log_rag_search()`는 아무것도 쓰지 않고, 첫 스킵 시에만 로그에  
  `DB client not configured, skipping RAG logging (hint: ai_logger.set_db_client(db))` 를 남깁니다.

## 스키마

테이블 `rag_search_log`:

| 컬럼 | 타입 | 설명 |
|------|------|------|
| id | INTEGER PK | 자동 증가 |
| created_at | TEXT | ISO 시각 |
| call_id | TEXT | 통화 ID |
| query | TEXT | 검색 쿼리 |
| owner_filter | TEXT | tenant/owner |
| results_count | INTEGER | 검색 결과 건수 |
| latency_ms | REAL | 검색 소요 시간(ms) |
| doc_ids_json | TEXT | 반환된 doc id 목록(JSON) |
| top_score | REAL | 1등 유사도 |
| similarity_threshold | REAL | 유사도 임계값 |
| top_k | INTEGER | top_k |

인덱스: `call_id`, `owner_filter`, `created_at`

## 통합 위치

RAG 검색을 수행하는 코드(예: LangGraph 노드, Pipecat RAG 서비스)에서:

1. 앱/서버 기동 시 위와 같이 `use_sqlite_file` + `init_sqlite_schema` 또는 `set_db_client` + `init_sqlite_schema` 호출.
2. `rag_search_completed` 로그를 남기는 바로 다음(또는 같은 지점)에서 `log_rag_search(...)` 호출.

이렇게 하면 기존 "DB client not configured, skipping RAG logging" 메시지는 DB를 설정한 뒤에는 더 이상 나오지 않고, RAG 검색 이력이 DB에 쌓입니다.
