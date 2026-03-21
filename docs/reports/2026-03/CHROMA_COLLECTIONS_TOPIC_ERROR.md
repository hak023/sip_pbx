# ChromaDB 오류: no such column: collections.topic

## 현상

다음 로그/상황에서 **동일한 원인**(스키마 불일치)으로 실패할 수 있음:

| app.log 이벤트 | 설명 |
|----------------|------|
| `AI Voicebot initialization failed` (error: no such column: collections.topic) | Factory에서 Vector DB 초기화 실패 |
| `Knowledge Extractor initialization failed` / ChromaDB sync init failed | SIP 엔드포인트 생성 시 지식 추출용 ChromaDB 실패 |
| `KnowledgeService initialization failed` / `seed_data_failed` | 시드 데이터 로드 시 ChromaDB 접근 실패 |

지식 추가(POST /api/knowledge) 또는 ChromaDB 접근 시:

```
sqlite3.OperationalError: no such column: collections.topic
  File ".../chromadb/db/mixins/sysdb.py", line 435, in get_collections
    rows = cur.execute(sql, params).fetchall()
```

## 원인

- **ChromaDB 0.4.x → 0.5.x** 에서 스키마가 바뀌었고, `collections.topic` 컬럼이 제거됨.
- 현재 **persist 디렉터리**(`data/chroma`)의 SQLite DB는 **0.5.x로 생성·마이그레이션된 상태**인데, 설치된 **chromadb 패키지는 0.4.x** 이면, 0.4.x 클라이언트가 `collections.topic` 을 참조하는 SQL을 실행해 위 오류가 발생함.
- 반대로, DB만 예전 0.4.x 스키마이고 클라이언트가 0.5.x인 경우에도 스키마 불일치로 비슷한 오류가 날 수 있음.

(참고: [chroma-core/chroma#2144](https://github.com/chroma-core/chroma/issues/2144))

## 해결 방법

### 1) ChromaDB 0.5.0 이상으로 맞추기 (권장)

DB가 이미 0.5.x 스키마라면, **클라이언트를 0.5.0 이상**으로 올리면 됨.

```bash
pip install 'chromadb>=0.5.0'
# 또는
pip install --upgrade chromadb
```

설치 후 서버 재시작하고 지식 추가를 다시 시도.

### 2) 지식 데이터를 버려도 되면 DB 초기화

기존 지식 데이터가 없거나 다시 채워도 되는 경우, **persist 디렉터리를 삭제**해 새 스키마로 다시 만들 수 있음.

1. 서버 종료.
2. ChromaDB 저장 경로 삭제:
   - 기본: `sip-pbx/data/chroma` 폴더 전체 삭제
   - 또는 `CHROMA_DB_PATH` 환경변수로 지정한 경로 삭제
3. 서버 재시작 → Chroma가 빈 DB를 현재 클라이언트 스키마로 생성.
4. 지식 시드 스크립트 등으로 1004 예제 다시 추가.

주의: 삭제하면 해당 경로의 **모든 지식 데이터**가 사라짐.

## 확인

- `pip show chromadb` 로 현재 설치된 버전 확인.
- 0.5.0 미만이면 위 1)으로 업그레이드 후 재시도.
- 이 프로젝트는 **requirements-ai.txt** 에 `chromadb>=1.5.0,<2.0.0` 이 지정되어 있음. **start-all.ps1** 이 의존성 설치 후 실행하므로, 최초 실행 또는 requirements 변경 후에는 자동으로 1.5.x가 설치됨. 그런데도 오류가 나면:
  - venv를 쓰는 경우: `.\venv\Scripts\activate` 후 `pip install -r requirements.txt` 로 재설치.
  - 이미 1.5.x인데도 `collections.topic` 오류가 나면: 과거에 다른 버전으로 만든 DB일 수 있으므로 **2) DB 초기화**(data/chroma 삭제 후 재시작)를 시도.

## 로그에서 보이는 메시지

초기화 실패 시 코드에서 다음 안내를 로그에 남김:

- `ChromaDB initialize failed (schema mismatch): ... | fix: pip install 'chromadb>=0.5.0' 또는 data/chroma 삭제 후 재시작. docs/reports/CHROMA_COLLECTIONS_TOPIC_ERROR.md`
- `ChromaDB lazy init failed (knowledge list): ... [해결: ...]`

위와 같이 나오면 이 문서의 1) 또는 2)를 적용하면 됨.
