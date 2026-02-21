"""FastAPI Gateway for Frontend Control Center"""
import os
from fastapi import FastAPI, HTTPException, Depends, Header
from fastapi.middleware.cors import CORSMiddleware
from datetime import datetime, timedelta
from typing import List, Optional
import structlog

from .routers import auth, calls, knowledge, hitl, metrics, operator, call_history, recordings, ai_insights, capabilities, extractions, transfers, outbound, tenants
from .models import User

logger = structlog.get_logger(__name__)

# FastAPI 앱 생성
app = FastAPI(
    title="AI Voicebot API Gateway",
    description="Frontend Control Center용 REST API",
    version="1.0.0"
)

# CORS 설정
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:3000",  # Frontend 개발 서버
        "http://localhost:3001",
        os.getenv("FRONTEND_URL", "http://localhost:3000")
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 라우터 등록
app.include_router(auth.router, prefix="/api/auth", tags=["Authentication"])
app.include_router(calls.router, prefix="/api/calls", tags=["Calls"])
app.include_router(knowledge.router, prefix="/api/knowledge", tags=["Knowledge"])
app.include_router(hitl.router, prefix="/api/hitl", tags=["HITL"])
app.include_router(metrics.router, prefix="/api/metrics", tags=["Metrics"])
app.include_router(operator.router, tags=["Operator"])  # 신규: 운영자 상태 관리
app.include_router(call_history.router, tags=["Call History"])  # 신규: 통화 이력
app.include_router(recordings.router, tags=["Recordings"])  # 신규: 녹음 파일 제공
app.include_router(ai_insights.router, tags=["AI Insights"])  # 신규: AI 처리 과정 조회
app.include_router(capabilities.router, prefix="/api/capabilities", tags=["Capabilities"])  # 신규: AI 서비스 관리
app.include_router(extractions.router, prefix="/api/extractions", tags=["Extractions"])  # 신규: 지식 추출 리뷰
app.include_router(transfers.router, prefix="/api/transfers", tags=["Transfers"])  # 신규: 호 전환 관리
app.include_router(outbound.router, prefix="/api/outbound", tags=["Outbound"])  # 신규: AI 아웃바운드 콜
app.include_router(tenants.router, prefix="/api/tenants", tags=["Tenants"])  # 신규: 멀티테넌트 관리


# Startup 이벤트
@app.on_event("startup")
async def startup_event():
    """서버 시작 시 초기화"""
    logger.info("API Gateway starting up...")
    
    # 멀티테넌트 시드 데이터 투입 (1003, 1004)
    from src.services.seed_data import seed_initial_data
    from src.services.knowledge_service import get_knowledge_service
    knowledge_service = get_knowledge_service()
    await seed_initial_data(knowledge_service)
    
    logger.info("API Gateway startup complete")


@app.get("/")
async def root():
    """루트 엔드포인트"""
    return {
        "message": "AI Voicebot API Gateway",
        "version": "1.0.0",
        "status": "running",
        "docs_url": "/docs"
    }


@app.get("/health")
async def health_check():
    """헬스 체크 엔드포인트"""
    return {
        "status": "healthy",
        "timestamp": datetime.now().isoformat()
    }


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000, log_level="info")

