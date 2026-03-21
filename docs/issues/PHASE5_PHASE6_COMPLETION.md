# 5번, 6번 작업 완료 요약

## 5번: TTSCompleteNotifier 파이프라인 추가 ✅

### 문제
- Phase 1/2 인사말 순차 재생이 정확한 동기화가 안됨
- `TTSCompleteNotifier`가 파이프라인에 없어서 TTS 완료 이벤트가 발생하지 않음

### 해결
1. **TTSCompleteNotifier 추가** (`pipeline_builder.py`)
   ```python
   from src.ai_voicebot.pipecat.processors.tts_complete_notifier import TTSCompleteNotifier
   tts_complete_notifier = TTSCompleteNotifier(sync_context=tts_sync_context)
   
   pipeline = Pipeline([
       ...,
       tts,
       tts_complete_notifier,  # TTS 직후 배치
       ...,
   ])
   ```

2. **인사말 호출 방식 개선**
   - `pipeline.processors` 의존성 제거
   - `pipeline._rag_llm` 속성으로 직접 참조
   - `greeting_task`를 `_greeting_tasks` dict에 저장하여 cleanup 시 정리

### 효과
- Phase 1 TTS 완료 시점을 정확히 감지
- Phase 2가 정확한 타이밍에 재생 (타임아웃 fallback 불필요)
- `event.wait()`가 정상적으로 해제됨

---

## 6번: Knowledge API 및 테넌트 데이터 설정 ✅

### 1. Knowledge API 라우터 생성

**파일**: `sip-pbx/src/api/routers/knowledge.py`

**엔드포인트**:
| Method | Path | 설명 |
|--------|------|------|
| GET | `/api/knowledge/` | 지식 목록 조회 (owner, category 필터) |
| POST | `/api/knowledge/` | 새 지식 추가 |
| DELETE | `/api/knowledge/{doc_id}` | 지식 삭제 |
| GET | `/api/knowledge/capabilities` | Capabilities 조회 (Phase 2용) |
| GET | `/api/knowledge/stats` | 지식 통계 조회 |

**FastAPI 앱 등록**: `sip-pbx/src/api/main.py`
```python
from src.api.routers import ..., knowledge
app.include_router(knowledge.router, prefix="/api")
```

### 2. 테넌트 초기 데이터 스크립트

**파일**: `sip-pbx/scripts/setup_tenant_data.py`

**설정 내용** (기상청 1004):

1. **조직 정보** (tenant_config)
   - tenant_name: "기상청"
   - tenant_type: "government_agency"
   - greeting_templates: 2개 인사말 템플릿

2. **Capabilities** (7개)
   - 날씨 예보, 기상 특보, 강수량, 기온, 바람, 습도, 일기예보

3. **샘플 FAQ** (5개)
   - 오늘 날씨, 내일 비, 기상 특보, 주간 날씨, 미세먼지

4. **샘플 절차** (2개)
   - 날씨 정보 제공 절차
   - 기상 특보 안내 절차

### 3. 실행 방법

```bash
# 테넌트 데이터 초기화
cd sip-pbx
python scripts/setup_tenant_data.py
```

### 4. Frontend 연동

Frontend에서 이제 다음 API를 사용할 수 있습니다:

```typescript
// 지식 목록 조회
GET http://localhost:8000/api/knowledge/?owner=1004

// 지식 추가
POST http://localhost:8000/api/knowledge/
{
  "text": "새 지식 내용",
  "category": "faq",
  "keywords": ["키워드1", "키워드2"],
  "owner": "1004",
  "metadata": {}
}

// 지식 삭제
DELETE http://localhost:8000/api/knowledge/{doc_id}?owner=1004

// Capabilities 조회 (Phase 2용)
GET http://localhost:8000/api/knowledge/capabilities?owner=1004

// 통계
GET http://localhost:8000/api/knowledge/stats?owner=1004
```

---

## 테스트 방법

### 1. 서버 시작
```bash
cd sip-pbx
./start-all.ps1
```

### 2. 테넌트 데이터 초기화
```bash
python scripts/setup_tenant_data.py
```

### 3. API 테스트
```bash
# 지식 조회
curl "http://localhost:8000/api/knowledge/?owner=1004"

# 통계 조회
curl "http://localhost:8000/api/knowledge/stats?owner=1004"

# Capabilities 조회
curl "http://localhost:8000/api/knowledge/capabilities?owner=1004"
```

### 4. AI 통화 테스트
1. 1003에서 1004로 전화
2. 10초 대기 (AI 응대 시작)
3. **Phase 1 인사말**: "안녕하세요. 기상청 AI 통화 비서입니다. 무엇을 도와드릴까요?"
4. **Phase 2 인사말**: "저는 날씨 예보, 기상 특보, 강수량 정보, 기온 정보, 바람 정보, 습도 정보, 일기예보를 도와드릴 수 있어요. 어떤 것이 궁금하신가요?"
5. Phase 1 → Phase 2 순차 재생 확인

---

## 수정된 파일 목록

1. `sip-pbx/src/ai_voicebot/pipecat/pipeline_builder.py`
   - TTSCompleteNotifier 추가
   - 인사말 호출 방식 개선
   - greeting_tasks 관리

2. `sip-pbx/src/api/routers/knowledge.py` (신규)
   - Knowledge CRUD API

3. `sip-pbx/src/api/main.py`
   - knowledge 라우터 등록

4. `sip-pbx/scripts/setup_tenant_data.py` (신규)
   - 테넌트 초기 데이터 설정 스크립트
