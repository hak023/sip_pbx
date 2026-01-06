"""메트릭 관련 API"""
from fastapi import APIRouter
import structlog

from ..models import DashboardMetrics

logger = structlog.get_logger(__name__)

router = APIRouter()


@router.get("/dashboard", response_model=DashboardMetrics)
async def get_dashboard_metrics():
    """
    대시보드 메트릭 조회
    
    추후 실제 시스템 메트릭과 연동
    """
    # Mock 데이터
    return DashboardMetrics(
        active_calls=3,
        hitl_queue_size=1,
        avg_ai_confidence=85.5,
        today_calls_count=42,
        avg_response_time=0.9,
        knowledge_base_size=156
    )

