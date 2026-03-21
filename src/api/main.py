"""
FastAPI 메인 앱 - REST API Gateway.

- recordings: 녹음 파일 조회/스트리밍/다운로드
- call_history: 통화 이력 목록·상세·메모·처리완료
- calls: 통화 상세 조회 및 transcript

실행: uvicorn src.api.main:app --reload --host 0.0.0.0 --port 8000
"""

import structlog
from fastapi import FastAPI, Request, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

logger = structlog.get_logger(__name__)

# 존재하는 라우터만 import (일부만 있어도 기동)
def _load_routers():
    loaded = {}
    # ⚠️ knowledge는 제외: 구버전(src/api/routers/knowledge.py) 대신
    #    신버전(src/api/knowledge_router.py)을 직접 로드
    #    이유: Pydantic v2 호환 및 tenant_id 중복 제거
    #    참고: docs/KNOWLEDGE_ROUTER_MIGRATION.md
    for name in (
        "auth",
        "tenants",
        "call_history",
        "calls",
        "metrics",
        "operator",
        "outbound",
        "recordings",
    ):
        try:
            mod = __import__(f"src.api.routers.{name}", fromlist=["router"])
            loaded[name] = getattr(mod, "router", None)
        except ImportError:
            pass
    return loaded

_ROUTERS = _load_routers()

# 🔥 신버전 knowledge_router 직접 로드 (v2_no_tenant_id)
# 구버전과 달리 owner 필수, tenant_id 없음
try:
    from src.api import knowledge_router
    _ROUTERS["knowledge"] = knowledge_router.router
    logger.info("🔥 NEW knowledge_router loaded (v2_no_tenant_id)")
except ImportError as e:
    logger.warning("Failed to load new knowledge_router", error=str(e))

ROUTERS_AVAILABLE = len(_ROUTERS) > 0
if not ROUTERS_AVAILABLE:
    print("Warning: No API routers found under src.api.routers")

app = FastAPI(
    title="AI Voicebot API",
    version="2.0.0",
    description="SmartPBX AI API - 통화 이력, 녹음, HITL 등",
)

# 422 Validation Error Handler - 상세 로깅
@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError):
    """Pydantic validation 에러 시 상세 로그"""
    errors = exc.errors()
    logger.error("api_validation_error_422",
                 method=request.method,
                 url=str(request.url),
                 path=request.url.path,
                 query_params=dict(request.query_params),
                 errors=errors,
                 body=await request.body() if request.method in ["POST", "PUT", "PATCH"] else None)
    
    return JSONResponse(
        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
        content={"detail": errors},
    )

# CORS (Frontend 연동)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000", "http://127.0.0.1:3000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 라우터 등록 (있는 것만)
if ROUTERS_AVAILABLE:
    for name, router_obj in _ROUTERS.items():
        if router_obj is not None:
            # knowledge router는 /api prefix 추가 필요
            if name == "knowledge":
                app.include_router(router_obj, prefix="/api")
                logger.info("Router registered with prefix", name=name, prefix="/api")
            else:
                app.include_router(router_obj)
                logger.info("Router registered", name=name)
    print("✅ Routers registered:", ", ".join(_ROUTERS.keys()))


@app.get("/")
async def root():
    return {
        "status": "ok",
        "message": "AI Voicebot API",
        "version": "2.0.0"
    }


@app.get("/health")
async def health():
    return {"status": "ok"}
