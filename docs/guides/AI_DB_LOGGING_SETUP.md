# AI DB 로깅 설정 가이드

RAG 검색·LLM 처리·지식 매칭 로그를 DB에 남기려면 **DB 클라이언트를 설정**해야 합니다. 미설정 시 해당 로그는 스킵되며, 경고는 타입별 1회만 출력됩니다.

## 1. 필요한 것

- **테이블**: `migrations/002_create_ai_insights_tables.sql` 참고  
  - `rag_search_history`, `llm_process_logs`, `knowledge_match_logs`  
  - (뷰 `ai_insights_summary`는 `call_history` 등에 의존)
- **클라이언트 인터페이스**: `await client.execute(query, params_dict)` 형태의 **async** 실행 가능 객체.  
  - `params_dict`는 named 파라미터 (`:call_id`, `:timestamp` 등).  
  - config 연동 시 **asyncpg**를 쓰면, 앱이 내부에서 named → positional 변환 래퍼를 사용합니다.

## 2. 설정 방법

### 2.1 config로 자동 연동 (권장)

`config/config.yaml`의 `ai_voicebot.logging`에 `db_url`을 넣으면, AI 백그라운드 초기화 시 자동으로 DB 연결을 시도합니다.

```yaml
ai_voicebot:
  enabled: true
  logging:
    db_url: "postgresql://user:pass@localhost:5432/your_db"
```

- **의존성**: `pip install asyncpg`
- **동작**: `src/main.py`의 AI 초기화 시작 시 `await ai_logger.try_init_db_from_config(config)`가 호출됩니다.  
  `db_url`이 없거나 연결 실패 시 False 반환, 로그만 남기고 예외는 전파하지 않습니다.

### 2.2 수동 설정

앱 **시작 시 한 번** (async 컨텍스트에서) 다음을 호출합니다.

```python
from src.ai_voicebot.logging import ai_logger

# 예: asyncpg 래퍼를 쓸 경우 (실제 클라이언트는 프로젝트 DB에 맞게 구현)
# db_client = YourAsyncDbClient("postgresql://...")
# ai_logger.set_db_client(db_client)
ai_logger.set_db_client(your_async_db_client)
```

- **설정하지 않으면**: RAG/LLM/지식매칭 DB 로깅은 하지 않고, 해당 로그만 타입별 1회 경고 후 스킵됩니다.
- **설정한 경우**: `log_rag_search`, `log_llm_process`, `log_knowledge_match` 호출 시 해당 테이블에 INSERT가 시도됩니다.

## 3. 어디서 호출할지

- **config 사용**: `db_url`만 설정하면 됩니다. 호출은 `main.py`의 AI 백그라운드 초기화 블록에서 이미 수행됩니다.
- **수동**: 메인 진입점에서 DB 연결 생성 후, AI Voicebot 초기화 전이나 직후에 `set_db_client` 한 번만 호출.

## 4. 참고

- `ai_logger`는 전역 싱글톤처럼 동작하며, `set_db_client`로 주입한 객체를 사용합니다.
- 테이블이 없거나 스키마가 다르면 INSERT 시 예외가 나며, `ai_logger`는 해당 예외를 로깅한 뒤 호출부로 전파하지 않고 무시하지 않으므로, DB/테이블은 미리 준비해 두어야 합니다.
