# 통화 이력·통화 레코딩 설계

## 1. 통화 이력 관리

### 1.1 요구사항

- **사람 간 통화**와 **AI가 응대한 통화** 내역이 **모두** 통화 이력에 남아야 한다.
- Frontend 통화 이력 목록에서 **통화 유형**(AI 응대 / 일반)을 구분해 표시할 수 있어야 한다.

### 1.2 백엔드 계약 (GET /api/call-history)

- **목록 조회** 시 해당 테넌트(callee/owner)의 **모든 통화**를 반환한다.
  - AI가 응대한 통화: `is_ai_handled: true` (또는 `type: "ai_call"`)
  - 사람 간 통화: `is_ai_handled: false` (또는 `type: "human_call"`)
- CDR/DB에 `is_ai_handled`(또는 동일 의미 필드)가 저장·조회되도록 되어 있으면, 목록 API에서 해당 필드를 포함해 반환한다.
- 선택: 녹음 존재 여부를 목록에 포함하려면 `has_recording`(boolean) 필드를 응답에 넣는다 (또는 상세 조회에서만 제공).

### 1.3 Frontend 구현 상태

- **파일**: `frontend/app/call-history/page.tsx`
- **구현 내용**:
  - `CallHistoryItem`에 `is_ai_handled?`, `has_recording?` 필드 정의.
  - 목록 테이블에 **통화 유형** 컬럼 추가: `is_ai_handled === true` → "AI 응대", 그 외 → "일반".
  - 백엔드가 `is_ai_handled`를 내려주면 그대로 표시; 미제공 시 기본 "일반"으로 표시.

### 1.4 백엔드 구현 (GET /api/call-history)

- **파일**: `src/api/routers/call_history.py`
- **목록**: `GET /api/call-history?page=&limit=&callee=&unresolved_hitl=` → `{ items, total }`, 각 항목에 `is_ai_handled`, `has_recording` 포함.
- **상세**: `GET /api/call-history/{call_id}` → `call_info`(is_ai_handled, has_recording 포함), transcripts, hitl_request.
- **저장소**: 현재 in-memory 리스트. 운영 시 DB로 교체. 이력 추가는 `append_call_history(entry)` 호출로 연동 (CDR/Orchestrator에서 사용).

### 1.5 점검 요약

| 항목 | 상태 | 비고 |
|------|------|------|
| 사람 간 + AI 응대 모두 이력에 포함 | ✅ 구현 | GET /api/call-history가 callee 기준 전체 통화 반환·is_ai_handled 포함 |
| Frontend 통화 유형 표시 | ✅ 구현 | "통화 유형" 컬럼, AI 응대/일반 배지 |

---

## 2. 통화 레코딩 Frontend 조회

### 2.1 요구사항

- Frontend에서 **통화 레코딩을 조회·재생**할 수 있어야 한다.

### 2.2 백엔드 API (구현됨)

- **파일**: `src/api/routers/recordings.py`
- **라우터 prefix**: `/api/recordings`
- **엔드포인트**:

| 메서드 | 경로 | 설명 |
|--------|------|------|
| GET | `/{call_id}/exists` | 녹음 존재 여부 (JSON: `{ "exists": true/false, "call_id": "..." }`) |
| GET | `/{call_id}/stream` | 스트리밍 재생 (Range 헤더 지원, HTML5 `<audio>` 등) |
| GET | `/{call_id}/mixed.wav` | 믹싱 녹음 파일 다운로드 |

- **저장 경로**: `RECORDINGS_DIR` 환경변수 또는 기본 `recordings` 디렉터리, 하위 `{call_id}/mixed.wav`.
- **라우터 등록**: FastAPI 메인 앱에서 등록 완료. 진입점: `src/api/main.py`.

```python
from src.api.routers import recordings, call_history
app.include_router(recordings.router)
app.include_router(call_history.router)
```

- **실행**: `uvicorn src.api.main:app --reload --host 0.0.0.0 --port 8000` (프로젝트 루트에서)

### 2.3 Frontend 구현 상태

- **파일**: `frontend/app/call-history/page.tsx`
- **구현 내용**:
  - 통화 상세 다이얼로그에 **녹음** 섹션 추가.
  - `<audio controls src="{API_URL}/api/recordings/{call_id}/stream">` 로 재생.
  - 재생 실패(404 등) 시 "녹음 파일 없음" 표시.
  - **다운로드** 링크: `GET /api/recordings/{call_id}/mixed.wav` (새 탭/다운로드).

### 2.4 설계 요약

| 항목 | 상태 | 비고 |
|------|------|------|
| 녹음 파일 제공 API | ✅ 구현 | recordings router (stream, mixed.wav, exists) |
| Frontend 녹음 재생/다운로드 | ✅ 구현 | 통화 상세 다이얼로그 내 재생·다운로드 |

---

## 3. 참고

- 아키텍처: `docs/architecture/ai-voicebot-architecture.md` §21 (Recording API 설계), §19 (HITL·통화 이력).
- CDR·is_ai_handled: 동일 문서 내 CallSession/CDR Generator 섹션.
