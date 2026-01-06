"""FastAPI Gateway for Frontend Control Center"""
import os
from fastapi import FastAPI, HTTPException, Depends, Header
from fastapi.middleware.cors import CORSMiddleware
from datetime import datetime, timedelta
from typing import List, Optional
import structlog

from .routers import auth, calls, knowledge, hitl, metrics, operator, call_history
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

