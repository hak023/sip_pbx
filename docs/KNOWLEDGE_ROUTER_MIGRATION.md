# Knowledge Router 변경 사항

**작성일**: 2026-03-16  
**이슈**: 422 Unprocessable Entity 에러 (tenant_id 필드 필수 오류)

---

## 파일 구조 변경

### ❌ 구버전 (더 이상 사용 안 함)
- **파일**: `src/api/routers/knowledge.py`
- **상태**: DEPRECATED (비활성화됨)
- **prefix**: `/api/knowledge_OLD_DEPRECATED`
- **문제점**:
  - `KnowledgeCreate` 모델에 `tenant_id: str` 필수
  - Pydantic v2 호환성 이슈
  - owner와 tenant_id 중복

### ✅ 신버전 (현재 사용 중)
- **파일**: `src/api/knowledge_router.py`
- **prefix**: (없음, main.py에서 `/api` prefix로 통합)
- **모델**: `KnowledgeCreateRequest`
  - `owner: str` (필수)
  - `tenant_id` 필드 **없음**
- **장점**:
  - Pydantic v2 완전 호환
  - 명확한 API 계약
  - 상세한 로깅

---

## 로드 방식

### `src/api/main.py`에서 처리:

```python
def _load_routers():
    loaded = {}
    # ⚠️ knowledge는 제외 (구버전 로드 방지)
    for name in ("auth", "tenants", "call_history", "calls", "metrics", "operator", "outbound"):
        try:
            mod = __import__(f"src.api.routers.{name}", fromlist=["router"])
            loaded[name] = getattr(mod, "router", None)
        except ImportError:
            pass
    return loaded

_ROUTERS = _load_routers()

# 🔥 신버전 knowledge_router 직접 로드
try:
    from src.api import knowledge_router
    _ROUTERS["knowledge"] = knowledge_router.router
    logger.info("🔥 NEW knowledge_router loaded (v2_no_tenant_id)")
except ImportError as e:
    logger.warning("Failed to load new knowledge_router", error=str(e))
```

---

## API 사용법

### POST `/api/knowledge`

**Request Body**:
```json
{
  "text": "안녕하세요. 기상청 AI입니다.",
  "owner": "1004",
  "category": "greeting_phase1",
  "answer": "안녕하세요.",
  "source": "api"
}
```

**주의사항**:
- ✅ `owner` 필드 사용 (필수)
- ❌ `tenant_id` 필드 사용 안 함
- ❌ Query parameter 사용 안 함

---

## 로그 확인

서버 시작 시 다음 로그가 보여야 합니다:

```
🔥 knowledge_router MODULE LOADED (version=v2_no_tenant_id)
🔥 NEW knowledge_router loaded (v2_no_tenant_id)
```

지식 추가 시:
```
🔥 HANDLER_V2_EXECUTED - NEW CODE RUNNING
knowledge_api_request (full_url=..., query_params={}, ...)
knowledge_api_added (doc_id=..., owner=1004, ...)
```

---

## 구버전 완전 제거 (선택사항)

구버전을 완전히 제거하려면:

```powershell
# 백업 후 삭제
Move-Item "c:\work\workspace_sippbx\sip-pbx\src\api\routers\knowledge.py" `
          "c:\work\workspace_sippbx\sip-pbx\src\api\routers\knowledge.py.deprecated"
```

또는 파일 내용을 비워두고 import 오류를 방지할 수 있습니다.

---

## 관련 문서

- `docs/reports/2026-03/KNOWLEDGE_API_422_ERROR_BRIEF.md` - 422 에러 상세 분석
- `FRONTEND_RESTART_GUIDE.md` - 프론트엔드 캐시 문제 해결
