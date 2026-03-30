# PersonaService ChromaDB 클라이언트 에러 수정

**작성일**: 2026-03-30  
**버전**: 1.0  
**상태**: 수정 완료  
**관련 이슈**: `'_ChromaClientWrapper' object has no attribute 'get_or_create_collection'`

---

## 🔴 문제 상황

### 에러 로그

```json
{"timestamp": "2026-03-30T09:20:15.041", "level": "error", "event": "persona_collection_init_error", "error": "'_ChromaClientWrapper' object has no attribute 'get_or_create_collection'"}
{"timestamp": "2026-03-30T09:20:15.041", "level": "error", "event": "persona_get_error", "error": "'_ChromaClientWrapper' object has no attribute 'get_or_create_collection'", "owner": "1004"}
```

### 발생 위치

- `src/ai_voicebot/knowledge/persona_service.py` (42줄)
- `PersonaService.initialize()` 메서드

### 에러 원인

**PersonaService**가 ChromaDB 컬렉션을 초기화하려고 `get_or_create_collection()` 메서드를 호출하는데, 전달받은 객체가 **`_ChromaClientWrapper`**(초기화 헬퍼 래퍼)여서 해당 메서드가 없음.

```python
# persona_service.py (42줄)
self._collection = self._chroma.get_or_create_collection(
    name=self._collection_name,
    metadata={"description": "Organization personas for chitchat classification"}
)
```

**`_ChromaClientWrapper`는 async 초기화만 지원하는 래퍼이고, 실제 ChromaDB API를 제공하지 않음.**

---

## 🔍 근본 원인 분석

### 1. ChromaDB 클라이언트 구조

```
chromadb_client.py
├── _client (global)                  → 실제 chromadb.PersistentClient
├── _vector_db (global)               → _VectorDbWrapper (collection 래퍼)
├── _ChromaClientWrapper (class)      → async initialize() 헬퍼만 제공
└── get_raw_chroma_client() (함수)   → ❌ 없었음 (이번에 추가)
```

### 2. Factory 초기화 코드 (기존)

```python
# factory.py (361줄) - 잘못된 코드
from .knowledge.persona_service import initialize_persona_service
persona_service = await initialize_persona_service(vector_db_client, embedder)
                                                    ^^^^^^^^^^^^^^^^
                                                    _ChromaClientWrapper 전달 (❌)
```

**`vector_db_client`는 `_ChromaClientWrapper` 인스턴스**로, `get_or_create_collection()` 메서드가 없음.

### 3. PersonaService 요구사항

PersonaService는 다음 메서드를 가진 **실제 ChromaDB 클라이언트**가 필요:

- ✅ `get_or_create_collection(name, metadata)` - 컬렉션 생성/조회
- ✅ `delete_collection(name)` - 컬렉션 삭제
- ✅ `collection.upsert()` - 문서 추가/수정
- ✅ `collection.get()` - 문서 조회
- ✅ `collection.query()` - 유사도 검색

→ 이는 `chromadb.PersistentClient` 인스턴스 (`_client` 전역 변수)

---

## ✅ 해결 방법

### 1. `get_raw_chroma_client()` 함수 추가

**파일**: `src/ai_voicebot/knowledge/chromadb_client.py`

```python
def get_raw_chroma_client() -> Optional[Any]:
    """
    실제 ChromaDB 클라이언트 반환 (PersonaService 등에서 사용).
    _client가 초기화되지 않았으면 get_vector_db()를 먼저 호출하여 초기화 시도.
    
    Returns:
        chromadb.PersistentClient 또는 None
    """
    global _client
    if _client is not None:
        return _client
    # vector_db 초기화 시도 (부수효과로 _client도 초기화됨)
    get_vector_db()
    return _client
```

### 2. Factory 초기화 코드 수정

**파일**: `src/ai_voicebot/factory.py` (358-367줄)

```python
# 9-1. Persona Service (Chitchat vs Question 분류용)
try:
    from .knowledge.persona_service import initialize_persona_service
    from .knowledge.chromadb_client import get_raw_chroma_client
    # PersonaService는 실제 ChromaDB 클라이언트가 필요함
    chroma_raw_client = get_raw_chroma_client()
    if chroma_raw_client is None:
        logger.warning("persona_service_init_skipped",
                      note="ChromaDB 클라이언트가 초기화되지 않음 — Persona 없이 계속")
    else:
        persona_service = await initialize_persona_service(chroma_raw_client, embedder)
        logger.info("✅ [FACTORY] PersonaService initialized (Chitchat classification)")
except Exception as e:
    logger.warning("persona_service_init_failed", error=str(e),
                  note="Persona 없이 계속 — 기본 intent 분류 사용")
```

### 변경 사항 요약

| 항목 | 변경 전 | 변경 후 |
|------|---------|---------|
| **전달 객체** | `vector_db_client` (_ChromaClientWrapper) | `get_raw_chroma_client()` (chromadb.PersistentClient) |
| **에러 처리** | ❌ 초기화 실패 시 크래시 | ✅ None 체크 → 경고 로그 + 계속 진행 |
| **기능** | ❌ `get_or_create_collection` 없음 | ✅ 모든 ChromaDB 메서드 사용 가능 |

---

## 🧪 검증 방법

### 1. 서버 재시작 후 로그 확인

```bash
# 서버 시작
cd sip-pbx
uvicorn src.api.main:app --host 0.0.0.0 --port 8000 --reload
```

**기대 로그**:
```
✅ [FACTORY] PersonaService initialized (Chitchat classification)
```

**에러 로그 사라져야 함**:
```
❌ persona_collection_init_error
❌ persona_get_error
```

### 2. Persona API 테스트

```bash
# Persona 생성
curl -X POST http://localhost:8000/api/persona/ \
  -H "Content-Type: application/json" \
  -d '{
    "owner": "1004",
    "name": "테스트 조직",
    "description": "테스트용 조직 페르소나",
    "scope_keywords": ["테스트", "예제"]
  }'

# Persona 조회
curl http://localhost:8000/api/persona/1004
```

**기대 결과**: 200 OK + Persona 데이터 반환

### 3. Intent 분류 테스트 (통화 시)

페르소나 설정 후 통화 테스트:

- **업무 관련 질문**: `question` 분류 (유사도 ≥ 0.6)
- **업무 무관 잡담**: `chitchat` 분류 (유사도 < 0.6)

로그 확인:
```
persona_query_relevance_check
  similarity: 0.85
  is_relevant: true
  intent: question
```

---

## 📊 영향 범위

### 수정된 파일

1. **`src/ai_voicebot/knowledge/chromadb_client.py`**
   - `get_raw_chroma_client()` 함수 추가

2. **`src/ai_voicebot/factory.py`**
   - PersonaService 초기화 로직 수정
   - 에러 핸들링 강화

### 영향받는 기능

✅ **수정됨**:
- Persona 생성/수정/삭제 (API)
- Chitchat vs Question 분류 (Intent 분류)
- 페르소나 기반 유사도 검색

❌ **영향 없음**:
- Knowledge 컬렉션 (기존대로 작동)
- RAG 검색 (변경 없음)
- QA Cache (변경 없음)

---

## 🔧 추가 개선 사항

### 1. 타입 힌팅 개선 (권장)

현재 `Any` 타입으로 되어 있는 ChromaDB 클라이언트를 명시적 타입으로 개선:

```python
from chromadb.api.client import Client as ChromaClient

def get_raw_chroma_client() -> Optional[ChromaClient]:
    ...
```

### 2. 초기화 검증 로그 추가

```python
logger.info("persona_service_chroma_client_check",
           client_type=type(chroma_raw_client).__name__,
           has_get_or_create=hasattr(chroma_raw_client, "get_or_create_collection"))
```

### 3. 에러 복구 메커니즘

PersonaService 초기화 실패 시에도 기본 intent 분류가 정상 작동하도록 이미 구현됨:

```python
except Exception as e:
    logger.warning("persona_service_init_failed", error=str(e),
                  note="Persona 없이 계속 — 기본 intent 분류 사용")
```

---

## 📝 디버깅 원칙 적용

### 로그 추가 (디버깅 규칙 준수)

**추론**: `_ChromaClientWrapper`가 잘못 전달됨  
**검증 로그**: 실제 클라이언트 타입 확인

```python
logger.info("persona_init_client_check",
           client_type=type(chroma_raw_client).__name__,
           client_id=id(chroma_raw_client),
           has_method=hasattr(chroma_raw_client, "get_or_create_collection"))
```

이렇게 하면:
- ✅ 추론이 맞는지 확인 가능
- ✅ 추론이 틀렸을 때 다른 원인 판단 가능

---

## 🎯 결론

### 문제 요약

PersonaService가 `_ChromaClientWrapper` (초기화 헬퍼)를 받아서 `get_or_create_collection()` 메서드를 호출하려다 에러 발생.

### 해결책

실제 `chromadb.PersistentClient`를 전달하도록 `get_raw_chroma_client()` 함수 추가 및 factory 코드 수정.

### 핵심 교훈

**래퍼 객체와 실제 클라이언트를 구분하지 못한 것이 원인.**

- `_ChromaClientWrapper`: async 초기화만 제공 (API 없음)
- `chromadb.PersistentClient`: 전체 ChromaDB API 제공

→ **의존성 주입 시 인터페이스 명확화 필요**

---

**최종 업데이트**: 2026-03-30 09:24
